"""Queue domain concept"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List

from AZFlow.domain.agenda import Agenda
from AZFlow.domain.ticket_master import TicketMaster


class QueueStatus(Enum):
    """Operational status of a Queue"""

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class QueuePolicy(Enum):
    """Rule used to order a Queue

    This slice defines the available values but does not implement their
    behaviour.
    """

    BY_ARRIVAL = "BY_ARRIVAL"
    BY_APPOINTMENT = "BY_APPOINTMENT"


@dataclass
class Queue:
    """Queue used to manage service accesses

    It contains one or more Agendas and uses one TicketMaster and one
    QueuePolicy. It can be active or inactive.
    """

    id: int
    status: QueueStatus
    policy: QueuePolicy
    ticket_master: TicketMaster
    agendas: List[Agenda] = field(default_factory=list)

    def is_active(self) -> bool:
        """Return whether the Queue is ACTIVE"""
        return self.status is QueueStatus.ACTIVE
