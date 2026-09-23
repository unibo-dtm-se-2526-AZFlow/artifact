from datetime import date, datetime
from typing import Dict, List, Tuple

import pytest

from AZFlow.application.check_in import CheckInService
from AZFlow.application.errors import (
    InvalidTotemReferenceError,
    NoAppointmentAvailableError,
    UnsupportedIdentifierTypeError,
)
from AZFlow.application.ports.appointment_source import ExternalAppointmentData
from AZFlow.application.ports.check_in_repository import (
    ResolvedAgenda,
    ResolvedQueue,
)
from AZFlow.domain.agenda import Agenda, ExternalAgenda
from AZFlow.domain.external_source import ExternalSource
from AZFlow.domain.patient_identifier import FISCAL_CODE, PatientIdentifier
from AZFlow.domain.service_access import ServiceAccessState
from AZFlow.domain.ticket_master import TicketMaster
from tests.application.fakes import FakeCheckInRepository, ListAppointmentSource

_SOURCE_CODE = "MOCK"
_DAY = date(2024, 5, 20)
_IDENTIFIER = PatientIdentifier(type=FISCAL_CODE, value="RSSMRA80A01H501U")


def _external_agenda(agenda_id: int, reference: str) -> ExternalAgenda:
    agenda = Agenda(id=agenda_id, name=f"Agenda {agenda_id}")
    source = ExternalSource(id=1, code=_SOURCE_CODE, name="Mock", connector_type="mock")
    return ExternalAgenda(agenda=agenda, source=source, external_reference=reference)


def _resolution(
    agenda_id: int,
    reference: str,
    queues: List[Tuple[int, TicketMaster]],
) -> ResolvedAgenda:
    external_agenda = _external_agenda(agenda_id, reference)
    return ResolvedAgenda(
        external_agenda=external_agenda,
        agenda=external_agenda.agenda,
        active_queues=[
            ResolvedQueue(queue_id=queue_id, ticket_master=ticket_master)
            for queue_id, ticket_master in queues
        ],
    )


def _data(reference: str, appointment_ref: str, hour: int) -> ExternalAppointmentData:
    return ExternalAppointmentData(
        external_source_code=_SOURCE_CODE,
        scheduled_at=datetime(2024, 5, 20, hour, 0),
        external_agenda_reference=reference,
        external_appointment_reference=appointment_ref,
    )


def _service(
    resolutions: Dict[Tuple[str, str], ResolvedAgenda],
    appointments: List[ExternalAppointmentData],
) -> Tuple[CheckInService, FakeCheckInRepository]:
    repository = FakeCheckInRepository(resolutions)
    source = ListAppointmentSource(appointments)
    return CheckInService([source], repository), repository


def test_successful_check_in_returns_code_and_creates_service_accesses():
    ticket_master = TicketMaster(id=1, prefix="AAA")
    resolutions = {
        (_SOURCE_CODE, "AGENDA-A"): _resolution(1, "AGENDA-A", [(1, ticket_master)]),
        (_SOURCE_CODE, "AGENDA-B"): _resolution(2, "AGENDA-B", [(2, ticket_master)]),
    }
    appointments = [
        _data("AGENDA-A", "APPT-1", 9),
        _data("AGENDA-B", "APPT-2", 10),
    ]
    service, repository = _service(resolutions, appointments)

    result = service.check_in(_IDENTIFIER, operational_day=_DAY)

    assert result.public_call_code == "AAA001"
    assert repository.created_daily_presences == 1
    assert repository.created_service_accesses == 2
    accesses = repository.service_accesses()
    assert {access.agenda.id for access in accesses} == {1, 2}
    assert all(a.state is ServiceAccessState.WAITING for a in accesses)
    # The presented identifier is stored on the imported Appointment.
    assert all(
        a.appointment is not None and a.appointment.patient_identifier == _IDENTIFIER
        for a in accesses
    )


def test_no_appointments_raises_no_appointment_error_and_creates_nothing():
    service, repository = _service({}, [])

    with pytest.raises(NoAppointmentAvailableError):
        service.check_in(_IDENTIFIER, operational_day=_DAY)

    assert repository.created_daily_presences == 0
    assert repository.created_service_accesses == 0


def test_unknown_agenda_and_no_active_queue_are_filtered_out():
    # AGENDA-A is unknown (no resolution); AGENDA-B is known but has no queue.
    resolutions = {
        (_SOURCE_CODE, "AGENDA-B"): _resolution(2, "AGENDA-B", []),
    }
    appointments = [
        _data("AGENDA-A", "APPT-1", 9),
        _data("AGENDA-B", "APPT-2", 10),
    ]
    service, repository = _service(resolutions, appointments)

    with pytest.raises(NoAppointmentAvailableError):
        service.check_in(_IDENTIFIER, operational_day=_DAY)

    assert repository.created_daily_presences == 0
    assert repository.created_service_accesses == 0


def test_earliest_appointment_determines_ticket_master():
    early_master = TicketMaster(id=1, prefix="AAA")
    late_master = TicketMaster(id=2, prefix="BBB")
    resolutions = {
        (_SOURCE_CODE, "AGENDA-A"): _resolution(1, "AGENDA-A", [(1, late_master)]),
        (_SOURCE_CODE, "AGENDA-B"): _resolution(2, "AGENDA-B", [(2, early_master)]),
    }
    # AGENDA-B appointment is earlier (8:00) than AGENDA-A (9:00).
    appointments = [
        _data("AGENDA-A", "APPT-1", 9),
        _data("AGENDA-B", "APPT-2", 8),
    ]
    service, repository = _service(resolutions, appointments)

    result = service.check_in(_IDENTIFIER, operational_day=_DAY)

    # Earliest appointment (AGENDA-B, 8:00) -> early_master (prefix AAA).
    assert result.public_call_code == "AAA001"


def test_same_time_tie_broken_by_lowest_internal_appointment_id():
    first_master = TicketMaster(id=1, prefix="AAA")
    second_master = TicketMaster(id=2, prefix="BBB")
    resolutions = {
        (_SOURCE_CODE, "AGENDA-A"): _resolution(1, "AGENDA-A", [(1, first_master)]),
        (_SOURCE_CODE, "AGENDA-B"): _resolution(2, "AGENDA-B", [(2, second_master)]),
    }
    # Same scheduled_at; APPT-1 is imported first so gets the lower id.
    appointments = [
        _data("AGENDA-A", "APPT-1", 9),
        _data("AGENDA-B", "APPT-2", 9),
    ]
    service, repository = _service(resolutions, appointments)

    result = service.check_in(_IDENTIFIER, operational_day=_DAY)

    # Lowest appointment id -> AGENDA-A -> first_master (prefix AAA).
    assert result.public_call_code == "AAA001"


def test_multiple_active_queues_selects_lowest_queue_id():
    low_master = TicketMaster(id=10, prefix="AAA")
    high_master = TicketMaster(id=20, prefix="BBB")
    # active_queues ordered ascending by queue id: lowest first.
    resolutions = {
        (_SOURCE_CODE, "AGENDA-A"): _resolution(
            1, "AGENDA-A", [(1, low_master), (2, high_master)]
        ),
    }
    appointments = [_data("AGENDA-A", "APPT-1", 9)]
    service, repository = _service(resolutions, appointments)

    result = service.check_in(_IDENTIFIER, operational_day=_DAY)

    # Lowest-id queue's TicketMaster (prefix AAA) is used.
    assert result.public_call_code == "AAA001"


def test_repeated_same_day_check_in_reuses_presence_and_creates_no_duplicates():
    ticket_master = TicketMaster(id=1, prefix="AAA")
    resolutions = {
        (_SOURCE_CODE, "AGENDA-A"): _resolution(1, "AGENDA-A", [(1, ticket_master)]),
    }
    appointments = [_data("AGENDA-A", "APPT-1", 9)]
    service, repository = _service(resolutions, appointments)

    first = service.check_in(_IDENTIFIER, operational_day=_DAY)
    second = service.check_in(_IDENTIFIER, operational_day=_DAY)

    assert first.public_call_code == second.public_call_code == "AAA001"
    assert repository.created_daily_presences == 1
    assert repository.created_service_accesses == 1


def test_unsupported_identifier_type_raises():
    service, _ = _service({}, [])

    with pytest.raises(UnsupportedIdentifierTypeError) as info:
        service.check_in(PatientIdentifier(type="passport", value="X123"), _DAY)

    assert info.value.identifier_type == "passport"


def test_operational_day_defaults_to_today(monkeypatch):
    ticket_master = TicketMaster(id=1, prefix="AAA")
    resolutions = {
        (_SOURCE_CODE, "AGENDA-A"): _resolution(1, "AGENDA-A", [(1, ticket_master)]),
    }
    appointments = [_data("AGENDA-A", "APPT-1", 9)]
    repository = FakeCheckInRepository(resolutions)
    service = CheckInService([ListAppointmentSource(appointments)], repository)

    result = service.check_in(_IDENTIFIER)

    assert result.public_call_code == "AAA001"
    assert result.daily_presence.operational_day == date.today()


# Task 5.2 - optional Totem origin and initial WAITING history.
# Property 2, Validates: Requirements 1.2, 1.3, 1.12, 3.2, 3.3, 3.4, 3.5, 3.6

_TOTEM_REFERENCE = "TOTEM-1"
_TOTEM_ID = 42


def _service_with_totems(
    resolutions: Dict[Tuple[str, str], ResolvedAgenda],
    appointments: List[ExternalAppointmentData],
    totems: Dict[str, int],
) -> Tuple[CheckInService, FakeCheckInRepository]:
    repository = FakeCheckInRepository(resolutions, totems)
    source = ListAppointmentSource(appointments)
    return CheckInService([source], repository), repository


def test_valid_totem_reference_persists_origin_on_new_presence():
    # Validates: Requirements 3.2, 3.4 - a known Totem origin is persisted.
    ticket_master = TicketMaster(id=1, prefix="AAA")
    resolutions = {
        (_SOURCE_CODE, "AGENDA-A"): _resolution(1, "AGENDA-A", [(1, ticket_master)]),
    }
    appointments = [_data("AGENDA-A", "APPT-1", 9)]
    service, repository = _service_with_totems(
        resolutions, appointments, {_TOTEM_REFERENCE: _TOTEM_ID}
    )

    result = service.check_in(
        _IDENTIFIER, totem_reference=_TOTEM_REFERENCE, operational_day=_DAY
    )

    assert result.public_call_code == "AAA001"
    assert repository.created_daily_presences == 1
    # The resolved totem_id reached the create path of the new presence.
    assert repository.persisted_totem_ids == [_TOTEM_ID]


def test_unknown_totem_reference_raises_and_creates_nothing():
    # Validates: Requirements 3.3 - resolution happens before any data creation.
    ticket_master = TicketMaster(id=1, prefix="AAA")
    resolutions = {
        (_SOURCE_CODE, "AGENDA-A"): _resolution(1, "AGENDA-A", [(1, ticket_master)]),
    }
    appointments = [_data("AGENDA-A", "APPT-1", 9)]
    service, repository = _service_with_totems(
        resolutions, appointments, {_TOTEM_REFERENCE: _TOTEM_ID}
    )

    with pytest.raises(InvalidTotemReferenceError) as info:
        service.check_in(_IDENTIFIER, totem_reference="UNKNOWN", operational_day=_DAY)

    assert info.value.totem_reference == "UNKNOWN"
    # No appointment, presence or service access was created.
    assert repository.created_daily_presences == 0
    assert repository.created_service_accesses == 0
    assert repository.service_accesses() == []
    assert repository.persisted_totem_ids == []


def test_no_totem_reference_leaves_origin_unknown():
    # Validates: Requirements 3.5, 3.6 - omitting the Totem behaves as before.
    ticket_master = TicketMaster(id=1, prefix="AAA")
    resolutions = {
        (_SOURCE_CODE, "AGENDA-A"): _resolution(1, "AGENDA-A", [(1, ticket_master)]),
    }
    appointments = [_data("AGENDA-A", "APPT-1", 9)]
    service, repository = _service_with_totems(resolutions, appointments, {})

    result = service.check_in(_IDENTIFIER, operational_day=_DAY)

    assert result.public_call_code == "AAA001"
    assert repository.created_daily_presences == 1
    # The origin stays unknown when no Totem reference is supplied.
    assert repository.persisted_totem_ids == [None]


def test_new_service_access_records_initial_waiting_transition_once():
    # Property 2 / Requirements 1.2, 1.12 - one initial WAITING record per new access.
    ticket_master = TicketMaster(id=1, prefix="AAA")
    resolutions = {
        (_SOURCE_CODE, "AGENDA-A"): _resolution(1, "AGENDA-A", [(1, ticket_master)]),
    }
    appointments = [_data("AGENDA-A", "APPT-1", 9)]
    service, repository = _service_with_totems(resolutions, appointments, {})

    service.check_in(_IDENTIFIER, operational_day=_DAY)

    accesses = repository.service_accesses()
    assert len(accesses) == 1
    records = repository.transition_records
    assert len(records) == 1
    record = records[0]
    assert record.service_access_id == accesses[0].id
    assert record.previous_state is None
    assert record.resulting_state is ServiceAccessState.WAITING


def test_idempotent_reuse_records_no_extra_transition():
    # Property 2 / Requirements 1.3, 1.12 - reuse appends no additional record.
    ticket_master = TicketMaster(id=1, prefix="AAA")
    resolutions = {
        (_SOURCE_CODE, "AGENDA-A"): _resolution(1, "AGENDA-A", [(1, ticket_master)]),
    }
    appointments = [_data("AGENDA-A", "APPT-1", 9)]
    service, repository = _service_with_totems(resolutions, appointments, {})

    service.check_in(_IDENTIFIER, operational_day=_DAY)
    service.check_in(_IDENTIFIER, operational_day=_DAY)

    # The second check-in reuses the presence and service access, adding no record.
    assert repository.created_service_accesses == 1
    assert len(repository.transition_records) == 1
