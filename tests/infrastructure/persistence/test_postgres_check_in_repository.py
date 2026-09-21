"""PostgreSQL integration tests for PostgresCheckInRepository.

These run against a real database and are skipped when no DSN is provided
(see conftest). They verify: agenda resolution and lowest-id ACTIVE Queue
ordering, atomic sequential code allocation, the DailyPresence unique
constraint with reload-on-conflict, Appointment recognition/reuse,
ServiceAccess non-duplication, and concurrent DailyPresence creation.
"""

from __future__ import annotations

from datetime import date, datetime

import psycopg
import pytest

from AZFlow.application.check_in import CheckInService
from AZFlow.application.errors import NoServiceAvailableError
from AZFlow.application.ports.appointment_source import ExternalAppointmentData
from AZFlow.infrastructure.appointment_sources.mock import MockAppointmentSource
from AZFlow.domain.patient_identifier import FISCAL_CODE, PatientIdentifier
from AZFlow.infrastructure.persistence.postgres_check_in_repository import (
    PostgresCheckInRepository,
)
from tests.infrastructure.persistence.seed import (
    seed_external_agenda,
    seed_queue,
    seed_source,
    seed_ticket_master,
)

OPERATIONAL_DAY = date(2024, 3, 15)
IDENTIFIER = PatientIdentifier(type=FISCAL_CODE, value="RSSMRA80A01H501U")


def _appointment_data(reference: str, hour: int = 9) -> ExternalAppointmentData:
    return ExternalAppointmentData(
        external_source_code="MOCK",
        scheduled_at=datetime(2024, 3, 15, hour, 0),
        external_agenda_reference="AGENDA-A",
        external_appointment_reference=reference,
        external_patient_reference="PAT-1",
    )


def test_resolve_agenda_returns_none_when_not_configured(connection):
    repo = PostgresCheckInRepository(connection)

    assert repo.resolve_agenda("MOCK", "AGENDA-A") is None


def test_resolve_agenda_orders_active_queues_by_lowest_id(connection):
    source = seed_source(connection)
    external_agenda = seed_external_agenda(connection, source, "Cardiology", "AGENDA-A")
    agenda_id = external_agenda.agenda.id
    tm_low = seed_ticket_master(connection, "AAA")
    tm_high = seed_ticket_master(connection, "BBB")
    # Insert the higher-prefix queue first so ids do not accidentally match.
    queue_high = seed_queue(connection, tm_high, [agenda_id])
    queue_low = seed_queue(connection, tm_low, [agenda_id])
    # An INACTIVE queue must be ignored.
    seed_queue(connection, tm_high, [agenda_id], status="INACTIVE")

    repo = PostgresCheckInRepository(connection)
    resolved = repo.resolve_agenda("MOCK", "AGENDA-A")

    assert resolved is not None
    assert resolved.has_active_queue()
    assert [q.queue_id for q in resolved.active_queues] == sorted(
        [queue_high, queue_low]
    )
    # Lowest id first.
    assert resolved.active_queues[0].queue_id == min(queue_high, queue_low)


def test_atomic_sequence_allocation_produces_sequential_unique_codes(connection):
    source = seed_source(connection)
    seed_external_agenda(connection, source, "Cardiology", "AGENDA-A")
    ticket_master = seed_ticket_master(connection, "AAA")

    repo = PostgresCheckInRepository(connection)

    codes = []
    for suffix in ("A", "B", "C"):
        identifier = PatientIdentifier(type=FISCAL_CODE, value=f"PATIENT{suffix}")
        presence = repo.create_daily_presence_with_code(
            identifier, OPERATIONAL_DAY, ticket_master
        )
        codes.append(presence.public_call_code)

    assert codes == ["AAA001", "AAA002", "AAA003"]
    assert len(set(codes)) == 3


def test_create_daily_presence_reloads_existing_on_duplicate(connection):
    source = seed_source(connection)
    seed_external_agenda(connection, source, "Cardiology", "AGENDA-A")
    ticket_master = seed_ticket_master(connection, "AAA")

    repo = PostgresCheckInRepository(connection)

    first = repo.create_daily_presence_with_code(
        IDENTIFIER, OPERATIONAL_DAY, ticket_master
    )
    # Calling again for the same (day, identifier) must return the existing
    # presence rather than raising or duplicating.
    second = repo.create_daily_presence_with_code(
        IDENTIFIER, OPERATIONAL_DAY, ticket_master
    )

    assert first.id == second.id
    assert first.public_call_code == second.public_call_code == "AAA001"

    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM daily_presence")
        assert cursor.fetchone()[0] == 1


def test_find_daily_presence_returns_existing(connection):
    source = seed_source(connection)
    seed_external_agenda(connection, source, "Cardiology", "AGENDA-A")
    ticket_master = seed_ticket_master(connection, "AAA")

    repo = PostgresCheckInRepository(connection)
    assert repo.find_daily_presence(OPERATIONAL_DAY, IDENTIFIER) is None

    created = repo.create_daily_presence_with_code(
        IDENTIFIER, OPERATIONAL_DAY, ticket_master
    )
    found = repo.find_daily_presence(OPERATIONAL_DAY, IDENTIFIER)

    assert found is not None
    assert found.id == created.id
    assert found.public_call_code == created.public_call_code


def test_appointment_recognition_reuses_the_same_row(connection):
    source = seed_source(connection)
    external_agenda = seed_external_agenda(connection, source, "Cardiology", "AGENDA-A")

    repo = PostgresCheckInRepository(connection)
    data = _appointment_data("MOCK-APPT-0001")

    first = repo.find_or_create_appointment(data, IDENTIFIER, external_agenda)
    second = repo.find_or_create_appointment(data, IDENTIFIER, external_agenda)

    assert first.id == second.id
    assert first.patient_identifier == IDENTIFIER

    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM appointment")
        assert cursor.fetchone()[0] == 1


def test_find_or_create_service_access_does_not_duplicate(connection):
    source = seed_source(connection)
    external_agenda = seed_external_agenda(connection, source, "Cardiology", "AGENDA-A")
    ticket_master = seed_ticket_master(connection, "AAA")

    repo = PostgresCheckInRepository(connection)
    presence = repo.create_daily_presence_with_code(
        IDENTIFIER, OPERATIONAL_DAY, ticket_master
    )
    appointment = repo.find_or_create_appointment(
        _appointment_data("MOCK-APPT-0001"), IDENTIFIER, external_agenda
    )

    first = repo.find_or_create_service_access(
        presence, external_agenda.agenda, appointment
    )
    second = repo.find_or_create_service_access(
        presence, external_agenda.agenda, appointment
    )

    assert first.id == second.id
    assert first.state.value == "WAITING"

    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM service_access")
        assert cursor.fetchone()[0] == 1


def test_concurrent_daily_presence_creation_yields_one_presence(connection, dsn):
    source = seed_source(connection)
    seed_external_agenda(connection, source, "Cardiology", "AGENDA-A")
    ticket_master = seed_ticket_master(connection, "AAA")

    # Two independent connections attempt to create the same DailyPresence.
    with psycopg.connect(dsn) as conn_a, psycopg.connect(dsn) as conn_b:
        repo_a = PostgresCheckInRepository(conn_a)
        repo_b = PostgresCheckInRepository(conn_b)

        presence_a = repo_a.create_daily_presence_with_code(
            IDENTIFIER, OPERATIONAL_DAY, ticket_master
        )
        presence_b = repo_b.create_daily_presence_with_code(
            IDENTIFIER, OPERATIONAL_DAY, ticket_master
        )

    # Exactly one DailyPresence exists and both callers observe the same code.
    assert presence_a.id == presence_b.id
    assert presence_a.public_call_code == presence_b.public_call_code

    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM daily_presence")
        assert cursor.fetchone()[0] == 1


def test_presented_identifier_is_stored_on_appointment_and_daily_presence(connection):
    """AC 9.1: the presented identifier is stored on the imported Appointment
    and on the DailyPresence, verified against the persisted columns."""
    source = seed_source(connection)
    external_agenda = seed_external_agenda(connection, source, "Cardiology", "AGENDA-A")
    ticket_master = seed_ticket_master(connection, "AAA")

    repo = PostgresCheckInRepository(connection)
    repo.find_or_create_appointment(
        _appointment_data("MOCK-APPT-0001"), IDENTIFIER, external_agenda
    )
    repo.create_daily_presence_with_code(IDENTIFIER, OPERATIONAL_DAY, ticket_master)

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT patient_identifier_type, patient_identifier_value
            FROM appointment
            """
        )
        assert cursor.fetchall() == [(IDENTIFIER.type, IDENTIFIER.value)]

        cursor.execute(
            """
            SELECT patient_identifier_type, patient_identifier_value
            FROM daily_presence
            """
        )
        assert cursor.fetchall() == [(IDENTIFIER.type, IDENTIFIER.value)]


def test_no_persistent_patient_master_table_exists(connection):
    """AC 9.2: no separate persistent Patient aggregate/table is introduced.

    Patient information lives only as columns on appointment/daily_presence,
    never as a dedicated patient master table.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name IN ('patient', 'patients', 'patient_master')
            """
        )
        assert cursor.fetchall() == []


def test_lowest_id_active_queue_ticket_master_drives_allocated_code(connection):
    """AC 9.3: with two ACTIVE Queues on the Agenda, the lowest-id Queue's
    TicketMaster is the one whose prefix appears in the allocated code."""
    source = seed_source(connection)
    external_agenda = seed_external_agenda(connection, source, "Cardiology", "AGENDA-A")
    agenda_id = external_agenda.agenda.id
    tm_low = seed_ticket_master(connection, "AAA")
    tm_high = seed_ticket_master(connection, "BBB")
    # Insert the higher-prefix queue first so ids do not accidentally match.
    seed_queue(connection, tm_high, [agenda_id])
    seed_queue(connection, tm_low, [agenda_id])

    repo = PostgresCheckInRepository(connection)
    resolved = repo.resolve_agenda("MOCK", "AGENDA-A")

    assert resolved is not None
    assert len(resolved.active_queues) == 2
    # active_queues is ordered by ascending Queue id, so the first is the
    # lowest-id ACTIVE Queue used for TicketMaster selection.
    lowest_queue = resolved.active_queues[0]
    assert lowest_queue.queue_id == min(q.queue_id for q in resolved.active_queues)

    presence = repo.create_daily_presence_with_code(
        IDENTIFIER, OPERATIONAL_DAY, lowest_queue.ticket_master
    )

    # The lowest-id Queue's TicketMaster prefix drives the allocated code.
    assert presence.public_call_code == f"{lowest_queue.ticket_master.prefix}001"


def test_repeated_same_day_check_in_reuses_presence_code_and_service_access(
    connection,
):
    """AC 9.5: driving the repository twice reuses the DailyPresence, its
    public call code and the ServiceAccess, creating no new rows."""
    source = seed_source(connection)
    external_agenda = seed_external_agenda(connection, source, "Cardiology", "AGENDA-A")
    ticket_master = seed_ticket_master(connection, "AAA")

    repo = PostgresCheckInRepository(connection)
    data = _appointment_data("MOCK-APPT-0001")

    def drive_once() -> tuple:
        presence = repo.find_daily_presence(OPERATIONAL_DAY, IDENTIFIER)
        if presence is None:
            presence = repo.create_daily_presence_with_code(
                IDENTIFIER, OPERATIONAL_DAY, ticket_master
            )
        appointment = repo.find_or_create_appointment(data, IDENTIFIER, external_agenda)
        access = repo.find_or_create_service_access(
            presence, external_agenda.agenda, appointment
        )
        return presence, access

    first_presence, first_access = drive_once()
    second_presence, second_access = drive_once()

    assert first_presence.id == second_presence.id
    assert first_presence.public_call_code == second_presence.public_call_code
    assert first_access.id == second_access.id

    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM daily_presence")
        assert cursor.fetchone()[0] == 1
        cursor.execute("SELECT count(*) FROM appointment")
        assert cursor.fetchone()[0] == 1
        cursor.execute("SELECT count(*) FROM service_access")
        assert cursor.fetchone()[0] == 1


def test_disabled_source_appointment_is_ignored_before_operational_creation(
    connection,
):
    source = seed_source(connection)
    external_agenda = seed_external_agenda(connection, source, "Cardiology", "AGENDA-A")
    ticket_master = seed_ticket_master(connection, "AAA")
    seed_queue(connection, ticket_master, [external_agenda.agenda.id], status="ACTIVE")

    # Disable the configured source after all relevant configuration exists and
    # before the check-in performs its repository relevance lookup.
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE external_source SET enabled = FALSE WHERE id = %s",
            (source.id,),
        )
    connection.commit()

    appointment_source = MockAppointmentSource(
        {IDENTIFIER.value: [_appointment_data("MOCK-APPT-DISABLED")]}
    )
    repository = PostgresCheckInRepository(connection)
    service = CheckInService([appointment_source], repository)

    with pytest.raises(NoServiceAvailableError):
        service.check_in(IDENTIFIER, OPERATIONAL_DAY)

    assert repository.resolve_agenda("MOCK", "AGENDA-A") is None

    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM daily_presence")
        assert cursor.fetchone()[0] == 0
        cursor.execute("SELECT count(*) FROM service_access")
        assert cursor.fetchone()[0] == 0
