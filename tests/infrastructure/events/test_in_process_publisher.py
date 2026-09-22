from AZFlow.application.ports.call_event_publisher import (
    CallEvent,
    CallEventPublisher,
)
from AZFlow.domain.agenda import Agenda
from AZFlow.domain.service_access import ServiceAccessState
from AZFlow.infrastructure.events.in_process_publisher import (
    InProcessCallEventPublisher,
)


def _event() -> CallEvent:
    return CallEvent(
        public_call_code="AAA001",
        service_access_id=12,
        agenda=Agenda(id=3, name="Cardiology"),
        state=ServiceAccessState.CALLED,
        room_reference="ROOM-3",
    )


def test_satisfies_the_publisher_port():
    publisher: CallEventPublisher = InProcessCallEventPublisher()

    publisher.publish(_event())


def test_records_the_published_event():
    publisher = InProcessCallEventPublisher()
    event = _event()

    publisher.publish(event)

    assert publisher.events == [event]


def test_records_events_in_order():
    publisher = InProcessCallEventPublisher()
    first = _event()
    second = CallEvent(
        public_call_code="BBB002",
        service_access_id=13,
        agenda=Agenda(id=4, name="Radiology"),
        state=ServiceAccessState.CALLED,
        room_reference="ROOM-4",
    )

    publisher.publish(first)
    publisher.publish(second)

    assert publisher.events == [first, second]


def test_event_carries_only_non_identifying_fields():
    event = _event()

    assert set(vars(event)) == {
        "public_call_code",
        "service_access_id",
        "agenda",
        "state",
        "room_reference",
    }
