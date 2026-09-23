"""Composite CallEventPublisher adapter"""

from __future__ import annotations

from typing import List

from AZFlow.application.ports.call_event_publisher import (
    CallEvent,
    CallEventPublisher,
)


class CompositeCallEventPublisher:
    """Fan one call event out to several publishers.

    It keeps the single publication boundary: the calling service still depends
    only on the CallEventPublisher port while each delegate receives the event
    in order. It adds no scope, display or WebSocket concern of its own.
    """

    def __init__(self, delegates: List[CallEventPublisher]) -> None:
        self._delegates = list(delegates)

    def publish(self, event: CallEvent) -> None:
        """Publish the event to each delegate in order."""
        for delegate in self._delegates:
            delegate.publish(event)
