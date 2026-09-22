"""PostgreSQL integration and concurrency tests for PostgresCallRepository.

These run against a real database and are skipped when no DSN is provided
(see conftest). They verify: durable persistence of the CALLED state, the
conditional-UPDATE semantics of try_call, the concurrency invariant that at
most one attempt transitions the same WAITING ServiceAccess (Property 1),
the CallingService optimistic call-next and call-specific races against the
real database, and the missing-public-call-code guard (no transition, no
event).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from threading import Barrier
from typing import Optional

import psycopg
import pytest

from AZFlow.application.calling import CallingService
from AZFlow.application.errors import (
    MissingPublicCallCodeError,
    NoPatientToCallError,
    ServiceAccessNotCallableError,
)
from AZFlow.domain.service_access import ServiceAccessState
from AZFlow.infrastructure.events.in_process_publisher import (
    InProcessCallEventPublisher,
)
from AZFlow.infrastructure.persistence.postgres_call_repository import (
    PostgresCallRepository,
)
from AZFlow.infrastructure.persistence.postgres_queue_view_reader import (
    PostgresQueueViewReader,
)
from tests.infrastructure.persistence.seed import (
    seed_external_agenda,
    seed_queue,
    seed_source,
    seed_ticket_master,
)

OPERATIONAL_DAY = date(2024, 3, 15)
ROOM_REFERENCE = "ROOM-3"


# Local seeding helpers, mirroring the pattern in
# test_postgres_queue_view_reader.py so each persistence test module stays
# independent.


def _seed_daily_presence(
    conn: "object",
    ticket_master_id: int,
    public_call_code: str,
    operational_day: date = OPERATIONAL_DAY,
    identifier_value: str = "RSSMRA80A01H501U",
) -> int:
    """Insert a daily_presence row and return its id."""
    with conn.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute(
            """
            INSERT INTO daily_presence (
                operational_day,
                patient_identifier_type,
                patient_identifier_value,
                public_call_code,
                ticket_master_id
            )
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                operational_day,
                "fiscal_code",
                identifier_value,
                public_call_code,
                ticket_master_id,
            ),
        )
        daily_presence_id = cursor.fetchone()[0]
    conn.commit()  # type: ignore[attr-defined]
    return daily_presence_id


def _seed_appointment(
    conn: "object",
    external_agenda_id: int,
    scheduled_at: datetime,
    reference: str,
) -> int:
    """Insert an appointment row and return its id."""
    with conn.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute(
            """
            INSERT INTO appointment (
                scheduled_at,
                patient_identifier_type,
                patient_identifier_value,
                external_agenda_id,
                external_appointment_reference
            )
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                scheduled_at,
                "fiscal_code",
                "RSSMRA80A01H501U",
                external_agenda_id,
                reference,
            ),
        )
        appointment_id = cursor.fetchone()[0]
    conn.commit()  # type: ignore[attr-defined]
    return appointment_id


def _seed_service_access(
    conn: "object",
    daily_presence_id: int,
    agenda_id: int,
    appointment_id: Optional[int] = None,
) -> int:
    """Insert a WAITING service_access row and return its id."""
    with conn.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute(
            """
            INSERT INTO service_access (
                daily_presence_id, agenda_id, appointment_id, state
            )
            VALUES (%s, %s, %s, 'WAITING')
            RETURNING id
            """,
            (daily_presence_id, agenda_id, appointment_id),
        )
        service_access_id = cursor.fetchone()[0]
    conn.commit()  # type: ignore[attr-defined]
    return service_access_id


def _external_agenda_id(conn: "object", agenda_id: int) -> int:
    with conn.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute(
            "SELECT id FROM external_agenda WHERE agenda_id = %s",
            (agenda_id,),
        )
        return cursor.fetchone()[0]


def _read_state(conn: "object", service_access_id: int) -> str:
    """Read the current persisted state of a service_access row."""
    with conn.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute(
            "SELECT state FROM service_access WHERE id = %s",
            (service_access_id,),
        )
        return cursor.fetchone()[0]


# Repository-level tests


def test_try_call_persists_called_state_durably(connection):
    """AC 8.3/8.4: a successful call persists state='CALLED' durably."""
    source = seed_source(connection)
    agenda = seed_external_agenda(connection, source, "Cardiology", "AGENDA-A").agenda
    ticket_master = seed_ticket_master(connection, "AAA")
    dp_id = _seed_daily_presence(connection, ticket_master.id, "AAA001")
    sa_id = _seed_service_access(connection, dp_id, agenda.id, None)

    repo = PostgresCallRepository(connection)
    called = repo.try_call(sa_id)

    assert called is not None
    assert called.id == sa_id
    assert called.state is ServiceAccessState.CALLED
    assert called.daily_presence.public_call_code == "AAA001"

    # Re-read the row on a fresh query to confirm durability.
    assert _read_state(connection, sa_id) == "CALLED"


def test_try_call_returns_row_for_waiting_and_none_for_called(connection):
    """The conditional UPDATE returns a row for WAITING and None for CALLED."""
    source = seed_source(connection)
    agenda = seed_external_agenda(connection, source, "Cardiology", "AGENDA-A").agenda
    ticket_master = seed_ticket_master(connection, "AAA")
    dp_id = _seed_daily_presence(connection, ticket_master.id, "AAA001")
    sa_id = _seed_service_access(connection, dp_id, agenda.id, None)

    repo = PostgresCallRepository(connection)

    first = repo.try_call(sa_id)
    assert first is not None
    assert first.state is ServiceAccessState.CALLED

    # A second attempt on an already-CALLED target performs no transition.
    second = repo.try_call(sa_id)
    assert second is None
    assert _read_state(connection, sa_id) == "CALLED"


# Concurrency tests (Property 1)


def test_concurrent_try_call_on_same_waiting_access_transitions_once(connection, dsn):
    """Property 1 / Req 4.1, 4.2, 10.8: two concurrent try_call on the same
    WAITING ServiceAccess: exactly one wins, the other gets None."""
    source = seed_source(connection)
    agenda = seed_external_agenda(connection, source, "Cardiology", "AGENDA-A").agenda
    ticket_master = seed_ticket_master(connection, "AAA")
    dp_id = _seed_daily_presence(connection, ticket_master.id, "AAA001")
    sa_id = _seed_service_access(connection, dp_id, agenda.id, None)

    barrier = Barrier(2)

    def attempt_call() -> bool:
        with psycopg.connect(dsn) as worker_connection:
            worker_repo = PostgresCallRepository(worker_connection)
            barrier.wait(timeout=10)
            called = worker_repo.try_call(sa_id)
            return called is not None

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(attempt_call),
            executor.submit(attempt_call),
        ]
        outcomes = [future.result() for future in futures]

    # Exactly one attempt performed the transition.
    assert outcomes.count(True) == 1
    assert outcomes.count(False) == 1
    assert _read_state(connection, sa_id) == "CALLED"


def _make_calling_service(connection):
    """Build a CallingService over the given connection with a real reader,
    repository and a recording in-process publisher."""
    reader = PostgresQueueViewReader(connection)
    repo = PostgresCallRepository(connection)
    publisher = InProcessCallEventPublisher()
    service = CallingService(reader, repo, publisher)
    return service, publisher


def test_concurrent_call_next_two_waiting_succeed_on_different_accesses(
    connection, dsn
):
    """Property 1 / Req 4.1, 10.8: two concurrent call-next with two waiting
    Patients each succeed on a different ServiceAccess."""
    source = seed_source(connection)
    agenda = seed_external_agenda(connection, source, "Cardiology", "AGENDA-A").agenda
    ticket_master = seed_ticket_master(connection, "AAA")
    dp_a = _seed_daily_presence(
        connection, ticket_master.id, "AAA001", identifier_value="PAT-A"
    )
    dp_b = _seed_daily_presence(
        connection, ticket_master.id, "AAA002", identifier_value="PAT-B"
    )
    sa_a = _seed_service_access(connection, dp_a, agenda.id, None)
    sa_b = _seed_service_access(connection, dp_b, agenda.id, None)
    queue_id = seed_queue(
        connection, ticket_master, [agenda.id], status="ACTIVE", policy="BY_ARRIVAL"
    )

    barrier = Barrier(2)

    def call_next() -> int:
        with psycopg.connect(dsn) as worker_connection:
            service, _ = _make_calling_service(worker_connection)
            barrier.wait(timeout=10)
            result = service.call_next(queue_id, ROOM_REFERENCE, OPERATIONAL_DAY)
            return result.service_access_id

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(call_next), executor.submit(call_next)]
        called_ids = [future.result() for future in futures]

    assert set(called_ids) == {sa_a, sa_b}
    assert _read_state(connection, sa_a) == "CALLED"
    assert _read_state(connection, sa_b) == "CALLED"


def test_concurrent_call_next_one_waiting_one_succeeds_other_no_patient(
    connection, dsn
):
    """Property 1 / Req 4.1, 10.8: with a single waiting Patient, one call-next
    succeeds and the other finds no Patient to call."""
    source = seed_source(connection)
    agenda = seed_external_agenda(connection, source, "Cardiology", "AGENDA-A").agenda
    ticket_master = seed_ticket_master(connection, "AAA")
    dp_id = _seed_daily_presence(connection, ticket_master.id, "AAA001")
    sa_id = _seed_service_access(connection, dp_id, agenda.id, None)
    queue_id = seed_queue(
        connection, ticket_master, [agenda.id], status="ACTIVE", policy="BY_ARRIVAL"
    )

    barrier = Barrier(2)

    def call_next() -> Optional[int]:
        with psycopg.connect(dsn) as worker_connection:
            service, _ = _make_calling_service(worker_connection)
            barrier.wait(timeout=10)
            try:
                result = service.call_next(queue_id, ROOM_REFERENCE, OPERATIONAL_DAY)
                return result.service_access_id
            except NoPatientToCallError:
                return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(call_next), executor.submit(call_next)]
        outcomes = [future.result() for future in futures]

    assert sorted(outcomes, key=lambda value: value is None) == [sa_id, None]
    assert _read_state(connection, sa_id) == "CALLED"


def test_concurrent_call_specific_same_target_one_succeeds_other_not_callable(
    connection, dsn
):
    """Property 1 / Req 4.1, 4.2, 10.8: two concurrent call-specific on the
    same target: one transitions, the other observes not-callable."""
    source = seed_source(connection)
    agenda = seed_external_agenda(connection, source, "Cardiology", "AGENDA-A").agenda
    ticket_master = seed_ticket_master(connection, "AAA")
    dp_id = _seed_daily_presence(connection, ticket_master.id, "AAA001")
    sa_id = _seed_service_access(connection, dp_id, agenda.id, None)
    queue_id = seed_queue(
        connection, ticket_master, [agenda.id], status="ACTIVE", policy="BY_ARRIVAL"
    )

    barrier = Barrier(2)

    def call_specific() -> bool:
        with psycopg.connect(dsn) as worker_connection:
            service, _ = _make_calling_service(worker_connection)
            barrier.wait(timeout=10)
            try:
                service.call_specific(queue_id, sa_id, ROOM_REFERENCE, OPERATIONAL_DAY)
                return True
            except ServiceAccessNotCallableError:
                return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(call_specific), executor.submit(call_specific)]
        outcomes = [future.result() for future in futures]

    assert outcomes.count(True) == 1
    assert outcomes.count(False) == 1
    assert _read_state(connection, sa_id) == "CALLED"


# Missing public call code guard (CallingService level, against the real DB)


def test_missing_public_call_code_leaves_row_waiting_and_publishes_no_event(
    connection,
):
    """Req 5.5: an empty public call code guards call_next and call_specific,
    leaving the row WAITING and publishing no event."""
    source = seed_source(connection)
    agenda = seed_external_agenda(connection, source, "Cardiology", "AGENDA-A").agenda
    ticket_master = seed_ticket_master(connection, "AAA")
    # public_call_code is NOT NULL, so an empty string models a missing code.
    dp_id = _seed_daily_presence(connection, ticket_master.id, "")
    sa_id = _seed_service_access(connection, dp_id, agenda.id, None)
    queue_id = seed_queue(
        connection, ticket_master, [agenda.id], status="ACTIVE", policy="BY_ARRIVAL"
    )

    reader = PostgresQueueViewReader(connection)
    repo = PostgresCallRepository(connection)
    publisher = InProcessCallEventPublisher()
    service = CallingService(reader, repo, publisher)

    with pytest.raises(MissingPublicCallCodeError):
        service.call_next(queue_id, ROOM_REFERENCE, OPERATIONAL_DAY)
    with pytest.raises(MissingPublicCallCodeError):
        service.call_specific(queue_id, sa_id, ROOM_REFERENCE, OPERATIONAL_DAY)

    assert _read_state(connection, sa_id) == "WAITING"
    assert publisher.events == []
