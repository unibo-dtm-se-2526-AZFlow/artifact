from datetime import date, datetime
from typing import Dict, List, Tuple

import pytest

from AZFlow.application.check_in import CheckInService
from AZFlow.application.errors import (
    NoServiceAvailableError,
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

    result = service.check_in(_IDENTIFIER, _DAY)

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


def test_no_appointments_raises_no_service_and_creates_nothing():
    service, repository = _service({}, [])

    with pytest.raises(NoServiceAvailableError):
        service.check_in(_IDENTIFIER, _DAY)

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

    with pytest.raises(NoServiceAvailableError):
        service.check_in(_IDENTIFIER, _DAY)

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

    result = service.check_in(_IDENTIFIER, _DAY)

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

    result = service.check_in(_IDENTIFIER, _DAY)

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

    result = service.check_in(_IDENTIFIER, _DAY)

    # Lowest-id queue's TicketMaster (prefix AAA) is used.
    assert result.public_call_code == "AAA001"


def test_repeated_same_day_check_in_reuses_presence_and_creates_no_duplicates():
    ticket_master = TicketMaster(id=1, prefix="AAA")
    resolutions = {
        (_SOURCE_CODE, "AGENDA-A"): _resolution(1, "AGENDA-A", [(1, ticket_master)]),
    }
    appointments = [_data("AGENDA-A", "APPT-1", 9)]
    service, repository = _service(resolutions, appointments)

    first = service.check_in(_IDENTIFIER, _DAY)
    second = service.check_in(_IDENTIFIER, _DAY)

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
