"""Unit tests for CompositeCallEventPublisher.

Property 2 (Validates: Requirements 5.1, 7.1): one event fans out to each
delegate once, in order, keeping the single publication seam.
"""

from __future__ import annotations

from typing import List, Tuple

from AZFlow.application.ports.call_event_publisher import (
    CallEvent,
    CallEventPublisher,
)
from AZFlow.domain.agenda import Agenda
from AZFlow.domain.service_access import ServiceAccessState
from AZFlow.infrastructure.events.composite_publisher import (
    CompositeCallEventPublisher,
)
from AZFlow.infrastructure.events.in_process_publisher import (
    InProcessCallEventPublisher,
)


def _event(code: str = "AAA001") -> CallEvent:
    return CallEvent(
        public_call_code=code,
        service_access_id=12,
        agenda=Agenda(id=3, name="Cardiology"),
        state=ServiceAccessState.CALLED,
        room_reference="ROOM-3",
    )


class _RecordingDelegate:
    """Delegate that records the order in which it was called."""

    def __init__(self, name: str, log: List[Tuple[str, CallEvent]]) -> None:
        self._name = name
        self._log = log

    def publish(self, event: CallEvent) -> None:
        self._log.append((self._name, event))


def test_satisfies_the_publisher_port():
    publisher: CallEventPublisher = CompositeCallEventPublisher([])

    publisher.publish(_event())


def test_fans_out_to_each_delegate_once_in_order():
    log: List[Tuple[str, CallEvent]] = []
    first = _RecordingDelegate("first", log)
    second = _RecordingDelegate("second", log)
    composite = CompositeCallEventPublisher([first, second])
    event = _event()

    composite.publish(event)

    assert log == [("first", event), ("second", event)]


def test_in_process_delegate_still_records_when_composed():
    in_process = InProcessCallEventPublisher()
    log: List[Tuple[str, CallEvent]] = []
    composite = CompositeCallEventPublisher(
        [in_process, _RecordingDelegate("other", log)]
    )
    event = _event()

    composite.publish(event)

    # The in-process delegate keeps its existing behaviour unchanged.
    assert in_process.events == [event]
    assert log == [("other", event)]


def test_empty_composite_publishes_nothing_and_does_not_raise():
    composite = CompositeCallEventPublisher([])

    composite.publish(_event())
