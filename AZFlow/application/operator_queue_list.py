"""Operator LIST use case for a Queue."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List, Optional

from AZFlow.application.errors import (
    MissingPublicCallCodeError,
    QueueInactiveError,
    QueueNotFoundError,
)
from AZFlow.application.ordering import operator_list_ordered
from AZFlow.application.ports.queue_view_reader import (
    CandidateServiceAccess,
    QueueViewReader,
)
from AZFlow.domain.agenda import Agenda
from AZFlow.domain.queue import QueuePolicy
from AZFlow.domain.service_access import ServiceAccessState


@dataclass(frozen=True)
class OperatorQueueListEntry:
    """One WAITING or SUSPENDED entry visible to the operator."""

    service_access_id: int
    public_call_code: str
    agenda: Agenda
    state: ServiceAccessState
    checked_in_at: datetime
    scheduled_at: Optional[datetime] = None


@dataclass(frozen=True)
class OperatorQueueList:
    """Expanded operator LIST for one Queue."""

    queue_id: int
    policy: QueuePolicy
    entries: List[OperatorQueueListEntry] = field(default_factory=list)


class OperatorQueueListService:
    """Build the expanded operator LIST without changing callable Queue rules."""

    def __init__(self, reader: QueueViewReader) -> None:
        self._reader = reader

    def view(
        self,
        queue_id: int,
        operational_day: Optional[date] = None,
    ) -> OperatorQueueList:
        queue = self._reader.load_queue(queue_id)
        if queue is None:
            raise QueueNotFoundError(queue_id)
        if not queue.is_active():
            raise QueueInactiveError(queue_id)

        day = date.today() if operational_day is None else operational_day
        served_agenda_ids = [agenda.id for agenda in queue.agendas]
        candidates = self._reader.list_service_accesses(served_agenda_ids, day)
        ordered = operator_list_ordered(
            candidates,
            served_agenda_ids,
            queue.policy,
        )

        return OperatorQueueList(
            queue_id=queue_id,
            policy=queue.policy,
            entries=[self._to_entry(candidate) for candidate in ordered],
        )

    @staticmethod
    def _to_entry(candidate: CandidateServiceAccess) -> OperatorQueueListEntry:
        if not candidate.public_call_code:
            raise MissingPublicCallCodeError(candidate.service_access_id)
        return OperatorQueueListEntry(
            service_access_id=candidate.service_access_id,
            public_call_code=candidate.public_call_code,
            agenda=candidate.agenda,
            state=candidate.state,
            checked_in_at=candidate.checked_in_at,
            scheduled_at=candidate.scheduled_at,
        )
