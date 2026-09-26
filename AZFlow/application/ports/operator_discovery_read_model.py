"""Read-only port for operator client discovery."""

from dataclasses import dataclass
from typing import List, Protocol

from AZFlow.domain.agenda import Agenda
from AZFlow.domain.queue import QueuePolicy, QueueStatus


@dataclass(frozen=True)
class OperatorRoom:
    """Room available to an operator client."""

    id: int
    room_reference: str
    label: str


@dataclass(frozen=True)
class OperatorQueue:
    """Queue available to an operator client."""

    id: int
    status: QueueStatus
    policy: QueuePolicy
    agendas: List[Agenda]


class OperatorDiscoveryReadModel(Protocol):
    """Read operations used to populate operator selectors."""

    def list_rooms(self) -> List[OperatorRoom]:
        """Return Rooms ordered for display."""
        ...

    def list_queues(self) -> List[OperatorQueue]:
        """Return Queues with their served Agendas."""
        ...
