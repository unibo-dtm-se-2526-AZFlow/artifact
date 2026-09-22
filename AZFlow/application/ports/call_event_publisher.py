"""Port used to publish Patient call events."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from AZFlow.domain.agenda import Agenda
from AZFlow.domain.service_access import ServiceAccessState


@dataclass(frozen=True)
class CallEvent:
    """A published call event.

    It carries only non-identifying data and never the Patient Identifier.
    """

    public_call_code: str
    service_access_id: int
    agenda: Agenda
    state: ServiceAccessState
    room_reference: str


class CallEventPublisher(Protocol):
    """Publish call events through the publication boundary."""

    def publish(self, event: CallEvent) -> None:
        """Publish one call event."""
        ...
