"""In-process CallEventPublisher adapter"""

from __future__ import annotations

import logging
from typing import List

from AZFlow.application.ports.call_event_publisher import CallEvent

_logger = logging.getLogger(__name__)


class InProcessCallEventPublisher:
    """Publish call events inside the running process.

    It intentionally keeps the published events in memory so tests and a future
    consumer can read them. When one instance is shared, that event list is
    shared across requests. There is no broker, outbox or retry.
    """

    def __init__(self) -> None:
        self._events: List[CallEvent] = []

    def publish(self, event: CallEvent) -> None:
        """Record one call event and log it at debug level."""
        self._events.append(event)
        _logger.debug(
            "published call event for service access %s", event.service_access_id
        )

    @property
    def events(self) -> List[CallEvent]:
        """Return the events published so far, most recent last."""
        return list(self._events)
