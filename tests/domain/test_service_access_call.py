from datetime import date, datetime

import pytest

from AZFlow.domain.agenda import Agenda, ExternalAgenda
from AZFlow.domain.appointment import Appointment
from AZFlow.domain.daily_presence import DailyPresence
from AZFlow.domain.errors import ServiceAccessNotWaitingError
from AZFlow.domain.external_source import ExternalSource
from AZFlow.domain.patient_identifier import FISCAL_CODE, PatientIdentifier
from AZFlow.domain.service_access import ServiceAccess, ServiceAccessState
from AZFlow.domain.ticket_master import TicketMaster


def _identifier():
    return PatientIdentifier(type=FISCAL_CODE, value="RSSMRA80A01H501U")


def _presence():
    return DailyPresence(
        id=1,
        patient_identifier=_identifier(),
        operational_day=date(2024, 1, 1),
        public_call_code="AAA001",
        ticket_master=TicketMaster(id=1, prefix="AAA"),
    )


def _appointment():
    source = ExternalSource(id=1, code="SRC", name="Source", connector_type="mock")
    agenda = Agenda(id=1, name="Cardiology")
    external_agenda = ExternalAgenda(
        agenda=agenda, source=source, source_name="Cardiology"
    )
    return Appointment(
        id=1,
        scheduled_at=datetime(2024, 1, 1, 9, 0),
        patient_identifier=_identifier(),
        external_agenda=external_agenda,
    )


def _waiting_service_access():
    return ServiceAccess(
        id=7,
        daily_presence=_presence(),
        agenda=Agenda(id=1, name="Cardiology"),
        appointment=_appointment(),
    )


def test_called_transitions_waiting_to_called_copy():
    service_access = _waiting_service_access()

    called = service_access.called()

    assert called is not service_access
    assert called.state is ServiceAccessState.CALLED


def test_called_preserves_all_fields_except_state():
    service_access = _waiting_service_access()

    called = service_access.called()

    assert called.id == service_access.id
    assert called.daily_presence is service_access.daily_presence
    assert called.daily_presence.public_call_code == "AAA001"
    assert called.agenda is service_access.agenda
    assert called.appointment is service_access.appointment


def test_called_leaves_original_unchanged():
    service_access = _waiting_service_access()

    service_access.called()

    assert service_access.state is ServiceAccessState.WAITING


def test_called_on_non_waiting_raises_with_service_access_id():
    called = _waiting_service_access().called()

    with pytest.raises(ServiceAccessNotWaitingError) as excinfo:
        called.called()

    assert excinfo.value.service_access_id == 7
