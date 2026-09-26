"""Port used to publish display-relevant ServiceAccess state changes."""

from dataclasses import dataclass
from typing import Protocol

from AZFlow.domain.service_access import ServiceAccessState


@dataclass(frozen=True)
class DisplayStateEvent:
    """A non-identifying state change that may update public displays."""

    public_call_code: str
    service_access_id: int
    state: ServiceAccessState
    room_reference: str


class DisplayStateEventPublisher(Protocol):
    def publish_state(self, event: DisplayStateEvent) -> None:
        """Publish one display-relevant state change."""
        ...
