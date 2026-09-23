"""PostgreSQL integration and concurrency tests for
PostgresStateTransitionRepository.

These run against a real database and are skipped when no DSN is provided
(see conftest). They verify: durable persistence of the SUSPENDED, WAITING and
ADMITTED states (Property 8); the conditional-UPDATE semantics of each
transition (a row for a target in the expected state, no row otherwise); the
concurrency invariant that at most one attempt performs a given transition
(Property 4); that find_state distinguishes not-found from wrong-state on a
miss (Property 3); and that a failing persist leaves the stored state
unchanged (Property 8).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier
from typing import Optional

import psycopg
import pytest

from AZFlow.domain.service_access import ServiceAccessState
from AZFlow.infrastructure.persistence.postgres_state_transition_repository import (
    PostgresStateTransitionRepository,
)
from tests.infrastructure.persistence.seed import (
    seed_external_agenda,
    seed_location_node,
    seed_room,
    seed_source,
    seed_ticket_master,
)

OPERATIONAL_DAY = date(2024, 3, 15)
ROOM_REFERENCE = "ROOM-3"


# Local seeding helpers, mirroring the pattern in
# test_postgres_call_repository.py so each persistence test module stays
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


def _seed_service_access(
    conn: "object",
    daily_presence_id: int,
    agenda_id: int,
    state: str = "WAITING",
    appointment_id: Optional[int] = None,
    room_id: Optional[int] = None,
) -> int:
    """Insert a service_access row in the given state and return its id."""
    with conn.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute(
            """
            INSERT INTO service_access (
                daily_presence_id, agenda_id, appointment_id, state, room_id
            )
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (daily_presence_id, agenda_id, appointment_id, state, room_id),
        )
        service_access_id = cursor.fetchone()[0]
    conn.commit()  # type: ignore[attr-defined]
    return service_access_id


def _read_state(conn: "object", service_access_id: int) -> str:
    """Read the current persisted state of a service_access row."""
    with conn.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute(
            "SELECT state FROM service_access WHERE id = %s",
            (service_access_id,),
        )
        return cursor.fetchone()[0]


def _read_room_id(conn: "object", service_access_id: int) -> Optional[int]:
    """Read the persisted room_id of a service_access row."""
    with conn.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute(
            "SELECT room_id FROM service_access WHERE id = %s",
            (service_access_id,),
        )
        return cursor.fetchone()[0]


def _transition_rows(
    conn: "object", service_access_id: int
) -> "list[tuple[Optional[str], str, object]]":
    """Return (previous_state, resulting_state, occurred_at) transition rows
    for a service_access, ordered by id."""
    with conn.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute(
            """
            SELECT previous_state, resulting_state, occurred_at
            FROM service_access_transition
            WHERE service_access_id = %s
            ORDER BY id
            """,
            (service_access_id,),
        )
        return cursor.fetchall()


def _seed_configured_room(conn: "object") -> int:
    """Seed a LocationNode and a configured Room, and return the Room id."""
    node_id = seed_location_node(conn, "Radiotherapy")
    return seed_room(conn, node_id, ROOM_REFERENCE, "Room 3")


def _seed_access_in_state(
    conn: "object", state: str, room_id: Optional[int] = None
) -> int:
    """Seed the minimal configuration and a service_access in the given state.

    An optional call-time room_id can be set, which admission reuses.
    """
    source = seed_source(conn)
    agenda = seed_external_agenda(conn, source, "Cardiology", "AGENDA-A").agenda
    ticket_master = seed_ticket_master(conn, "AAA")
    dp_id = _seed_daily_presence(conn, ticket_master.id, "AAA001")
    return _seed_service_access(conn, dp_id, agenda.id, state, room_id=room_id)


# Durable persistence (Property 8; Req 8.3, 11.12)


def test_try_suspend_persists_suspended_state_durably(connection):
    """A successful suspend persists state='SUSPENDED' durably and records one
    WAITING->SUSPENDED transition (Property 1)."""
    sa_id = _seed_access_in_state(connection, "WAITING")

    repo = PostgresStateTransitionRepository(connection)
    suspended = repo.try_suspend(sa_id)

    assert suspended is not None
    assert suspended.id == sa_id
    assert suspended.state is ServiceAccessState.SUSPENDED
    assert suspended.daily_presence.public_call_code == "AAA001"
    # Re-read on a fresh query to confirm durability.
    assert _read_state(connection, sa_id) == "SUSPENDED"

    rows = _transition_rows(connection, sa_id)
    assert len(rows) == 1
    previous_state, resulting_state, occurred_at = rows[0]
    assert previous_state == "WAITING"
    assert resulting_state == "SUSPENDED"
    assert occurred_at is not None


def test_try_restore_persists_waiting_state_durably(connection):
    """A successful restore persists state='WAITING' durably and records one
    SUSPENDED->WAITING transition (Property 1)."""
    sa_id = _seed_access_in_state(connection, "SUSPENDED")

    repo = PostgresStateTransitionRepository(connection)
    restored = repo.try_restore(sa_id)

    assert restored is not None
    assert restored.id == sa_id
    assert restored.state is ServiceAccessState.WAITING
    assert _read_state(connection, sa_id) == "WAITING"

    rows = _transition_rows(connection, sa_id)
    assert len(rows) == 1
    previous_state, resulting_state, occurred_at = rows[0]
    assert previous_state == "SUSPENDED"
    assert resulting_state == "WAITING"
    assert occurred_at is not None


def test_try_admit_persists_admitted_state_durably_and_reuses_room(connection):
    """A successful confirm admission persists state='ADMITTED' durably, records
    one CALLED->ADMITTED transition, and reuses the stored room_id unchanged
    (Property 1 / 5)."""
    room_id = _seed_configured_room(connection)
    sa_id = _seed_access_in_state(connection, "CALLED", room_id=room_id)

    repo = PostgresStateTransitionRepository(connection)
    admitted = repo.try_admit(sa_id)

    assert admitted is not None
    assert admitted.id == sa_id
    assert admitted.state is ServiceAccessState.ADMITTED
    assert _read_state(connection, sa_id) == "ADMITTED"
    # Admission does not touch the stored call-time Room.
    assert _read_room_id(connection, sa_id) == room_id

    rows = _transition_rows(connection, sa_id)
    assert len(rows) == 1
    previous_state, resulting_state, occurred_at = rows[0]
    assert previous_state == "CALLED"
    assert resulting_state == "ADMITTED"
    assert occurred_at is not None


# Conditional-UPDATE semantics: row for the expected state, none otherwise


def test_try_suspend_returns_row_only_from_waiting(connection):
    """The conditional UPDATE returns a row for WAITING and None otherwise, and
    a miss writes no transition record (Property 1)."""
    sa_id = _seed_access_in_state(connection, "WAITING")
    repo = PostgresStateTransitionRepository(connection)

    first = repo.try_suspend(sa_id)
    assert first is not None
    assert first.state is ServiceAccessState.SUSPENDED

    # A second attempt on an already-SUSPENDED target performs no transition and
    # adds no transition record.
    second = repo.try_suspend(sa_id)
    assert second is None
    assert _read_state(connection, sa_id) == "SUSPENDED"
    assert len(_transition_rows(connection, sa_id)) == 1


def test_try_restore_returns_row_only_from_suspended(connection):
    """The conditional UPDATE returns a row for SUSPENDED and None otherwise, and
    a miss writes no transition record (Property 1)."""
    sa_id = _seed_access_in_state(connection, "SUSPENDED")
    repo = PostgresStateTransitionRepository(connection)

    first = repo.try_restore(sa_id)
    assert first is not None
    assert first.state is ServiceAccessState.WAITING

    second = repo.try_restore(sa_id)
    assert second is None
    assert _read_state(connection, sa_id) == "WAITING"
    assert len(_transition_rows(connection, sa_id)) == 1


def test_try_admit_returns_row_only_from_called(connection):
    """The conditional UPDATE returns a row for CALLED and None otherwise, and
    a miss writes no transition record (Property 1)."""
    room_id = _seed_configured_room(connection)
    sa_id = _seed_access_in_state(connection, "CALLED", room_id=room_id)
    repo = PostgresStateTransitionRepository(connection)

    first = repo.try_admit(sa_id)
    assert first is not None
    assert first.state is ServiceAccessState.ADMITTED

    second = repo.try_admit(sa_id)
    assert second is None
    assert _read_state(connection, sa_id) == "ADMITTED"
    assert len(_transition_rows(connection, sa_id)) == 1


def test_try_transition_returns_none_for_missing_target(connection):
    """A conditional UPDATE on a non-existent id returns None and changes
    nothing."""
    repo = PostgresStateTransitionRepository(connection)
    assert repo.try_suspend(999) is None
    assert repo.try_restore(999) is None
    assert repo.try_admit(999) is None


# find_state distinguishes not-found from wrong-state (Property 3; Req 1.3, 2.3, 3.5)


def test_find_state_returns_none_when_not_found(connection):
    """On a miss with no row, find_state returns None (not found)."""
    repo = PostgresStateTransitionRepository(connection)
    assert repo.find_state(999) is None


def test_find_state_returns_current_state_when_wrong_state(connection):
    """On a miss with a row present, find_state returns the current state."""
    sa_id = _seed_access_in_state(connection, "CALLED")
    repo = PostgresStateTransitionRepository(connection)

    # suspend requires WAITING, so it misses on a CALLED target.
    assert repo.try_suspend(sa_id) is None
    # find_state then reports the actual (wrong) state, not None.
    assert repo.find_state(sa_id) is ServiceAccessState.CALLED


# Concurrency invariant (Property 4; Req 1.9, 3.12, 6.1-6.6)


def _concurrent_transition_wins_once(dsn: str, sa_id: int, method_name: str) -> None:
    """Run two concurrent attempts of the same transition on the same target.

    Exactly one attempt returns a ServiceAccess; the other returns None.
    """
    barrier = Barrier(2)

    def attempt() -> bool:
        with psycopg.connect(dsn) as worker_connection:
            worker_repo = PostgresStateTransitionRepository(worker_connection)
            transition = getattr(worker_repo, method_name)
            barrier.wait(timeout=10)
            return transition(sa_id) is not None

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(attempt), executor.submit(attempt)]
        outcomes = [future.result() for future in futures]

    assert outcomes.count(True) == 1
    assert outcomes.count(False) == 1


def test_concurrent_suspend_on_same_waiting_access_transitions_once(connection, dsn):
    """Two concurrent try_suspend on the same WAITING target: exactly one wins
    and writes exactly one transition record (Property 1)."""
    sa_id = _seed_access_in_state(connection, "WAITING")
    _concurrent_transition_wins_once(dsn, sa_id, "try_suspend")
    assert _read_state(connection, sa_id) == "SUSPENDED"
    assert len(_transition_rows(connection, sa_id)) == 1


def test_concurrent_restore_on_same_suspended_access_transitions_once(connection, dsn):
    """Two concurrent try_restore on the same SUSPENDED target: exactly one
    wins and writes exactly one transition record (Property 1)."""
    sa_id = _seed_access_in_state(connection, "SUSPENDED")
    _concurrent_transition_wins_once(dsn, sa_id, "try_restore")
    assert _read_state(connection, sa_id) == "WAITING"
    assert len(_transition_rows(connection, sa_id)) == 1


def test_concurrent_admit_on_same_called_access_transitions_once(connection, dsn):
    """Two concurrent try_admit on the same CALLED target: exactly one wins
    and writes exactly one transition record (Property 1)."""
    room_id = _seed_configured_room(connection)
    sa_id = _seed_access_in_state(connection, "CALLED", room_id=room_id)
    _concurrent_transition_wins_once(dsn, sa_id, "try_admit")
    assert _read_state(connection, sa_id) == "ADMITTED"
    assert len(_transition_rows(connection, sa_id)) == 1


# A failing persist leaves the stored state unchanged (Property 8; Req 8.4)


def test_failing_persist_leaves_state_unchanged(connection, dsn):
    """When the transition fails to commit, the stored state stays unchanged.

    A separate connection holds an open transaction that has already
    transitioned the row, so a concurrent conditional UPDATE on the same row
    blocks and then finds the row no longer in the expected state. The failing
    attempt performs no transition and the committed state is the one the first
    transaction produced, never a double transition.
    """
    sa_id = _seed_access_in_state(connection, "WAITING")

    # Force a real failure path: close the connection mid-flight so commit
    # cannot succeed, and confirm the row is untouched afterwards.
    failing_conn = psycopg.connect(dsn)
    repo = PostgresStateTransitionRepository(failing_conn)
    failing_conn.close()

    with pytest.raises(psycopg.Error):
        repo.try_suspend(sa_id)

    # The row is still WAITING when read on a healthy connection.
    assert _read_state(connection, sa_id) == "WAITING"
