import dataclasses
from datetime import date, datetime
from typing import Optional

import pytest

from AZFlow.application.ports.call_event_publisher import (
    CallEvent,
    CallEventPublisher,
)
from AZFlow.application.ports.call_repository import CallRepository
from AZFlow.domain.agenda import Agenda
from AZFlow.domain.daily_presence import DailyPresence
from AZFlow.domain.patient_identifier import PatientIdentifier
from AZFlow.domain.service_access import ServiceAccess, ServiceAccessState
from AZFlow.domain.ticket_master import TicketMaster


def _agenda() -> Agenda:
    return Agenda(id=3, name="Cardiology")


def _service_access() -> ServiceAccess:
    ticket_master = TicketMaster(id=1, prefix="AAA")
    daily_presence = DailyPresence(
        id=7,
        patient_identifier=PatientIdentifier(type="ID", value="123"),
        operational_day=date(2024, 1, 1),
        public_call_code="AAA001",
        ticket_master=ticket_master,
        checked_in_at=datetime(2024, 5, 20, 8, 0),
    )
    return ServiceAccess(id=12, daily_presence=daily_presence, agenda=_agenda())


def test_call_event_carries_only_non_identifying_fields():
    agenda = _agenda()
    event = CallEvent(
        public_call_code="AAA001",
        service_access_id=12,
        agenda=agenda,
        state=ServiceAccessState.CALLED,
        room_reference="ROOM-3",
    )

    assert event.public_call_code == "AAA001"
    assert event.service_access_id == 12
    assert event.agenda == agenda
    assert event.state is ServiceAccessState.CALLED
    assert event.room_reference == "ROOM-3"


def test_call_event_is_immutable():
    event = CallEvent(
        public_call_code="AAA001",
        service_access_id=12,
        agenda=_agenda(),
        state=ServiceAccessState.CALLED,
        room_reference="ROOM-3",
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        event.room_reference = "ROOM-9"  # type: ignore[misc]


def test_any_object_matching_the_protocol_is_a_call_event_publisher():
    published: list[CallEvent] = []

    class InMemoryPublisher:
        def publish(self, event: CallEvent) -> None:
            published.append(event)

    publisher: CallEventPublisher = InMemoryPublisher()
    event = CallEvent(
        public_call_code="AAA001",
        service_access_id=12,
        agenda=_agenda(),
        state=ServiceAccessState.CALLED,
        room_reference="ROOM-3",
    )
    publisher.publish(event)

    assert published == [event]


def test_any_object_matching_the_protocol_is_a_call_repository():
    service_access = _service_access()

    class InMemoryCallRepository:
        def resolve_room(self, room_reference: str) -> Optional[int]:
            return 3 if room_reference == "ROOM-3" else None

        def try_call(
            self, service_access_id: int, room_id: int
        ) -> Optional[ServiceAccess]:
            if service_access_id == service_access.id:
                return service_access.called()
            return None

    repository: CallRepository = InMemoryCallRepository()

    assert repository.resolve_room("ROOM-3") == 3
    assert repository.resolve_room("NO-SUCH-ROOM") is None

    called = repository.try_call(12, 3)
    assert called is not None
    assert called.state is ServiceAccessState.CALLED
    assert repository.try_call(999, 3) is None
