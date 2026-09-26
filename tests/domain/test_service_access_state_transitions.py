from datetime import date, datetime

import pytest

from AZFlow.domain.agenda import Agenda, ExternalAgenda
from AZFlow.domain.appointment import Appointment
from AZFlow.domain.daily_presence import DailyPresence
from AZFlow.domain.errors import (
    ServiceAccessNotCalledError,
    ServiceAccessNotSuspendedError,
    ServiceAccessNotWaitingError,
)
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
        checked_in_at=datetime(2024, 5, 20, 8, 0),
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


def _assert_fields_preserved(original: ServiceAccess, transitioned: ServiceAccess):
    assert transitioned is not original
    assert transitioned.id == original.id
    assert transitioned.daily_presence is original.daily_presence
    assert transitioned.daily_presence.public_call_code == "AAA001"
    assert transitioned.agenda is original.agenda
    assert transitioned.appointment is original.appointment


# suspended()


def test_suspended_transitions_waiting_to_suspended_copy():
    service_access = _waiting_service_access()

    suspended = service_access.suspended()

    assert suspended.state is ServiceAccessState.SUSPENDED
    _assert_fields_preserved(service_access, suspended)


def test_suspended_leaves_original_unchanged():
    service_access = _waiting_service_access()

    service_access.suspended()

    assert service_access.state is ServiceAccessState.WAITING


def test_suspended_on_non_waiting_raises_with_service_access_id():
    called = _waiting_service_access().called()

    with pytest.raises(ServiceAccessNotWaitingError) as excinfo:
        called.suspended()

    assert excinfo.value.service_access_id == 7


# restored()


def test_restored_transitions_suspended_to_waiting_copy():
    suspended = _waiting_service_access().suspended()

    restored = suspended.restored()

    assert restored.state is ServiceAccessState.WAITING
    _assert_fields_preserved(suspended, restored)


def test_restored_leaves_original_unchanged():
    suspended = _waiting_service_access().suspended()

    suspended.restored()

    assert suspended.state is ServiceAccessState.SUSPENDED


def test_restored_on_non_suspended_raises_with_service_access_id():
    service_access = _waiting_service_access()

    with pytest.raises(ServiceAccessNotSuspendedError) as excinfo:
        service_access.restored()

    assert excinfo.value.service_access_id == 7


# admitted()


def test_admitted_transitions_called_to_admitted_copy():
    called = _waiting_service_access().called()

    admitted = called.admitted()

    assert admitted.state is ServiceAccessState.ADMITTED
    _assert_fields_preserved(called, admitted)


def test_admitted_leaves_original_unchanged():
    called = _waiting_service_access().called()

    called.admitted()

    assert called.state is ServiceAccessState.CALLED


def test_admitted_on_non_called_raises_with_service_access_id():
    service_access = _waiting_service_access()

    with pytest.raises(ServiceAccessNotCalledError) as excinfo:
        service_access.admitted()

    assert excinfo.value.service_access_id == 7


# ADMITTED is terminal


def test_admitted_has_no_outbound_transition():
    admitted = _waiting_service_access().called().admitted()

    with pytest.raises(ServiceAccessNotCalledError):
        admitted.admitted()
    with pytest.raises(ServiceAccessNotWaitingError):
        admitted.suspended()
    with pytest.raises(ServiceAccessNotSuspendedError):
        admitted.restored()
