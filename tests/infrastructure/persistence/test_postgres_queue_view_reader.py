"""PostgreSQL integration tests for PostgresQueueViewReader.

These run against a real database and are skipped when no DSN is provided
(see conftest). They verify Queue loading with its Agendas, candidate
selection over the served Agenda ids, operational-day filtering, data mapping
and no duplicate ServiceAccess id. They do NOT verify policy ordering, which
is the application's responsibility.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from AZFlow.domain.queue import QueuePolicy, QueueStatus
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


def test_load_queue_returns_queue_with_agendas(connection):
    source = seed_source(connection)
    agenda_a = seed_external_agenda(connection, source, "Cardiology", "AGENDA-A").agenda
    agenda_b = seed_external_agenda(connection, source, "Neurology", "AGENDA-B").agenda
    ticket_master = seed_ticket_master(connection, "AAA")
    queue_id = seed_queue(
        connection,
        ticket_master,
        [agenda_a.id, agenda_b.id],
        status="ACTIVE",
        policy="BY_APPOINTMENT",
    )

    reader = PostgresQueueViewReader(connection)
    queue = reader.load_queue(queue_id)

    assert queue is not None
    assert queue.id == queue_id
    assert queue.status is QueueStatus.ACTIVE
    assert queue.policy is QueuePolicy.BY_APPOINTMENT
    assert queue.ticket_master.id == ticket_master.id
    assert queue.ticket_master.prefix == "AAA"
    assert sorted(a.id for a in queue.agendas) == sorted([agenda_a.id, agenda_b.id])
    assert {a.name for a in queue.agendas} == {"Cardiology", "Neurology"}


def test_load_queue_returns_none_when_not_found(connection):
    reader = PostgresQueueViewReader(connection)

    assert reader.load_queue(999) is None


def test_load_queue_without_agendas_yields_empty_list(connection):
    ticket_master = seed_ticket_master(connection, "AAA")
    queue_id = seed_queue(connection, ticket_master, [])

    reader = PostgresQueueViewReader(connection)
    queue = reader.load_queue(queue_id)

    assert queue is not None
    assert queue.agendas == []


def test_load_queue_maps_inactive_and_by_arrival(connection):
    ticket_master = seed_ticket_master(connection, "AAA")
    queue_id = seed_queue(
        connection, ticket_master, [], status="INACTIVE", policy="BY_ARRIVAL"
    )

    reader = PostgresQueueViewReader(connection)
    queue = reader.load_queue(queue_id)

    assert queue is not None
    assert queue.status is QueueStatus.INACTIVE
    assert queue.policy is QueuePolicy.BY_ARRIVAL


def test_list_service_accesses_returns_candidates_with_mapped_fields(connection):
    source = seed_source(connection)
    external_agenda = seed_external_agenda(connection, source, "Cardiology", "AGENDA-A")
    agenda = external_agenda.agenda
    ticket_master = seed_ticket_master(connection, "AAA")
    ext_agenda_id = _external_agenda_id(connection, agenda.id)

    dp_id = _seed_daily_presence(connection, ticket_master.id, "AAA001")
    scheduled_at = datetime(2024, 3, 15, 9, 0)
    appointment_id = _seed_appointment(
        connection, ext_agenda_id, scheduled_at, "APPT-1"
    )
    sa_with_appt = _seed_service_access(connection, dp_id, agenda.id, appointment_id)
    sa_without_appt = _seed_service_access(connection, dp_id, agenda.id, None)

    reader = PostgresQueueViewReader(connection)
    candidates = reader.list_service_accesses([agenda.id], OPERATIONAL_DAY)

    by_id = {c.service_access_id: c for c in candidates}
    assert set(by_id) == {sa_with_appt, sa_without_appt}

    with_appt = by_id[sa_with_appt]
    assert with_appt.daily_presence_id == dp_id
    assert with_appt.agenda.id == agenda.id
    assert with_appt.agenda.name == "Cardiology"
    assert with_appt.state.value == "WAITING"
    assert with_appt.public_call_code == "AAA001"
    assert with_appt.scheduled_at == scheduled_at

    without_appt = by_id[sa_without_appt]
    assert without_appt.scheduled_at is None
    assert without_appt.public_call_code == "AAA001"


def test_list_service_accesses_selects_only_given_agendas(connection):
    source = seed_source(connection)
    agenda_a = seed_external_agenda(connection, source, "Cardiology", "AGENDA-A").agenda
    agenda_b = seed_external_agenda(connection, source, "Neurology", "AGENDA-B").agenda
    ticket_master = seed_ticket_master(connection, "AAA")

    dp_id = _seed_daily_presence(connection, ticket_master.id, "AAA001")
    sa_a = _seed_service_access(connection, dp_id, agenda_a.id, None)
    _seed_service_access(connection, dp_id, agenda_b.id, None)

    reader = PostgresQueueViewReader(connection)
    candidates = reader.list_service_accesses([agenda_a.id], OPERATIONAL_DAY)

    assert [c.service_access_id for c in candidates] == [sa_a]


def test_list_service_accesses_excludes_other_operational_days(connection):
    source = seed_source(connection)
    agenda = seed_external_agenda(connection, source, "Cardiology", "AGENDA-A").agenda
    ticket_master = seed_ticket_master(connection, "AAA")

    dp_today = _seed_daily_presence(
        connection, ticket_master.id, "AAA001", OPERATIONAL_DAY, "TODAY"
    )
    dp_past = _seed_daily_presence(
        connection, ticket_master.id, "AAA002", date(2024, 3, 14), "PAST"
    )
    dp_future = _seed_daily_presence(
        connection, ticket_master.id, "AAA003", date(2024, 3, 16), "FUTURE"
    )
    sa_today = _seed_service_access(connection, dp_today, agenda.id, None)
    _seed_service_access(connection, dp_past, agenda.id, None)
    _seed_service_access(connection, dp_future, agenda.id, None)

    reader = PostgresQueueViewReader(connection)
    candidates = reader.list_service_accesses([agenda.id], OPERATIONAL_DAY)

    assert [c.service_access_id for c in candidates] == [sa_today]


def test_list_service_accesses_has_no_duplicate_ids_across_agendas(connection):
    source = seed_source(connection)
    agenda_a = seed_external_agenda(connection, source, "Cardiology", "AGENDA-A").agenda
    agenda_b = seed_external_agenda(connection, source, "Neurology", "AGENDA-B").agenda
    ticket_master = seed_ticket_master(connection, "AAA")

    dp_id = _seed_daily_presence(connection, ticket_master.id, "AAA001")
    _seed_service_access(connection, dp_id, agenda_a.id, None)
    _seed_service_access(connection, dp_id, agenda_b.id, None)

    reader = PostgresQueueViewReader(connection)
    candidates = reader.list_service_accesses(
        [agenda_a.id, agenda_b.id], OPERATIONAL_DAY
    )

    ids = [c.service_access_id for c in candidates]
    assert len(ids) == len(set(ids))
    assert len(ids) == 2


def test_list_service_accesses_returns_empty_for_no_agendas(connection):
    reader = PostgresQueueViewReader(connection)

    assert reader.list_service_accesses([], OPERATIONAL_DAY) == []
