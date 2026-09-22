"""Read-only port used to build the Operator Queue View."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Optional, Protocol

from AZFlow.domain.agenda import Agenda
from AZFlow.domain.queue import Queue
from AZFlow.domain.service_access import ServiceAccessState


@dataclass(frozen=True)
class CandidateServiceAccess:
    """A ServiceAccess the Queue View may include.

    The ``state`` is kept so the service can filter ``WAITING`` itself.
    """

    service_access_id: int
    daily_presence_id: int
    agenda: Agenda
    state: ServiceAccessState
    public_call_code: str
    scheduled_at: Optional[datetime] = None


class QueueViewReader(Protocol):
    """Read operations needed by the Operator Queue View."""

    def load_queue(self, queue_id: int) -> Optional[Queue]:
        """Return the Queue with its Agendas, or None when not found."""
        ...

    def list_service_accesses(
        self,
        agenda_ids: List[int],
        operational_day: date,
    ) -> List[CandidateServiceAccess]:
        """Return the candidate ServiceAccesses for these Agendas and day.

        The day filter is applied here, at the reader boundary.
        """
        ...
