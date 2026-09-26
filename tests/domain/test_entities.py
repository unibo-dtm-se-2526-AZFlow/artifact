import dataclasses
from datetime import date, datetime

import pytest

from AZFlow.domain.agenda import Agenda, ExternalAgenda
from AZFlow.domain.appointment import Appointment
from AZFlow.domain.daily_presence import DailyPresence
from AZFlow.domain.external_source import ExternalSource
from AZFlow.domain.patient_identifier import FISCAL_CODE, PatientIdentifier
from AZFlow.domain.queue import Queue, QueuePolicy, QueueStatus
from AZFlow.domain.service_access import ServiceAccess, ServiceAccessState
from AZFlow.domain.ticket_master import TicketMaster


def _identifier():
    return PatientIdentifier(type=FISCAL_CODE, value="RSSMRA80A01H501U")


def _external_agenda():
    source = ExternalSource(id=1, code="SRC", name="Source", connector_type="mock")
    agenda = Agenda(id=1, name="Cardiology")
    return ExternalAgenda(agenda=agenda, source=source, source_name="Cardiology")


def test_agenda_name_can_change_after_creation():
    agenda = Agenda(id=1, name="Cardiology")

    agenda.name = "Renamed"

    assert agenda.name == "Renamed"


def test_external_agenda_owns_one_source_and_optional_references():
    external_agenda = _external_agenda()

    assert external_agenda.source.id == 1
    assert external_agenda.agenda.name == "Cardiology"
    assert external_agenda.external_reference is None


def test_queue_status_and_policy_enums():
    assert {status.value for status in QueueStatus} == {"ACTIVE", "INACTIVE"}
    assert {policy.value for policy in QueuePolicy} == {
        "BY_ARRIVAL",
        "BY_APPOINTMENT",
    }


def test_queue_reports_active_status():
    ticket_master = TicketMaster(id=1, prefix="AAA")
    agenda = Agenda(id=1, name="Cardiology")
    active = Queue(
        id=1,
        status=QueueStatus.ACTIVE,
        policy=QueuePolicy.BY_ARRIVAL,
        ticket_master=ticket_master,
        agendas=[agenda],
    )
    inactive = Queue(
        id=2,
        status=QueueStatus.INACTIVE,
        policy=QueuePolicy.BY_APPOINTMENT,
        ticket_master=ticket_master,
        agendas=[agenda],
    )

    assert active.is_active() is True
    assert inactive.is_active() is False


def test_appointment_stores_check_in_identifier():
    appointment = Appointment(
        id=1,
        scheduled_at=datetime(2024, 1, 1, 9, 0),
        patient_identifier=_identifier(),
        external_agenda=_external_agenda(),
        external_appointment_reference="ref-1",
    )

    assert appointment.patient_identifier == _identifier()
    assert appointment.external_appointment_reference == "ref-1"


def test_daily_presence_is_immutable():
    presence = DailyPresence(
        id=1,
        patient_identifier=_identifier(),
        operational_day=date(2024, 1, 1),
        public_call_code="AAA001",
        ticket_master=TicketMaster(id=1, prefix="AAA"),
        checked_in_at=datetime(2024, 5, 20, 8, 0),
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        presence.public_call_code = "AAA002"  # type: ignore[misc]


def test_service_access_starts_waiting():
    presence = DailyPresence(
        id=1,
        patient_identifier=_identifier(),
        operational_day=date(2024, 1, 1),
        public_call_code="AAA001",
        ticket_master=TicketMaster(id=1, prefix="AAA"),
        checked_in_at=datetime(2024, 5, 20, 8, 0),
    )
    agenda = Agenda(id=1, name="Cardiology")

    service_access = ServiceAccess(id=1, daily_presence=presence, agenda=agenda)

    assert service_access.state is ServiceAccessState.WAITING
