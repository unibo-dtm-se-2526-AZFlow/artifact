"""Operator Queue View use case.

It reads a Queue and its candidates through the ``QueueViewReader`` port, then
filters and orders them into the view shown to the Operator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, List, Optional

from AZFlow.application.errors import (
    MissingPublicCallCodeError,
    QueueInactiveError,
    QueueNotFoundError,
)
from AZFlow.application.ports.queue_view_reader import (
    CandidateServiceAccess,
    QueueViewReader,
)
from AZFlow.domain.agenda import Agenda
from AZFlow.domain.queue import QueuePolicy
from AZFlow.domain.service_access import ServiceAccessState


@dataclass(frozen=True)
class QueueViewEntry:
    """One entry in the Queue View, with no identifying Patient data."""

    service_access_id: int
    public_call_code: str
    agenda: Agenda
    scheduled_at: Optional[datetime] = None


@dataclass(frozen=True)
class QueueView:
    """Result of the Operator Queue View use case."""

    queue_id: int
    policy: QueuePolicy
    entries: List[QueueViewEntry] = field(default_factory=list)


class QueueViewService:
    """Build the Operator Queue View through the QueueViewReader port."""

    def __init__(self, reader: QueueViewReader) -> None:
        self._reader = reader

    def view(
        self,
        queue_id: int,
        operational_day: Optional[date] = None,
    ) -> QueueView:
        """Return the ordered queue view for a Queue.

        The current day is used when ``operational_day`` is not given.

        Raises:
            QueueNotFoundError: no Queue exists for the id.
            QueueInactiveError: the Queue is INACTIVE.
            MissingPublicCallCodeError: an entry has no call code.
        """
        queue = self._reader.load_queue(queue_id)
        if queue is None:
            raise QueueNotFoundError(queue_id)
        if not queue.is_active():
            raise QueueInactiveError(queue_id)

        day = date.today() if operational_day is None else operational_day

        served_agenda_ids = [agenda.id for agenda in queue.agendas]
        candidates = self._reader.list_service_accesses(served_agenda_ids, day)

        kept = self._filter_candidates(candidates, served_agenda_ids)
        ordered = self._order(kept, queue.policy)
        entries = [self._to_entry(candidate) for candidate in ordered]

        return QueueView(queue_id=queue_id, policy=queue.policy, entries=entries)

    @staticmethod
    def _filter_candidates(
        candidates: List[CandidateServiceAccess],
        served_agenda_ids: List[int],
    ) -> List[CandidateServiceAccess]:
        """Keep served, WAITING candidates without duplicates."""
        served = set(served_agenda_ids)
        seen: Dict[int, CandidateServiceAccess] = {}
        for candidate in candidates:
            if candidate.agenda.id not in served:
                continue
            if candidate.state is not ServiceAccessState.WAITING:
                continue
            if candidate.service_access_id not in seen:
                seen[candidate.service_access_id] = candidate
        return list(seen.values())

    @staticmethod
    def _order(
        candidates: List[CandidateServiceAccess],
        policy: QueuePolicy,
    ) -> List[CandidateServiceAccess]:
        """Order the candidates by the Queue policy."""
        if policy is QueuePolicy.BY_APPOINTMENT:
            with_appointment = sorted(
                (c for c in candidates if c.scheduled_at is not None),
                key=lambda c: (c.scheduled_at, c.service_access_id),
            )
            without_appointment = sorted(
                (c for c in candidates if c.scheduled_at is None),
                key=lambda c: c.service_access_id,
            )
            return with_appointment + without_appointment

        # BY_ARRIVAL: composite arrival proxy.
        return sorted(
            candidates,
            key=lambda c: (c.daily_presence_id, c.service_access_id),
        )

    @staticmethod
    def _to_entry(candidate: CandidateServiceAccess) -> QueueViewEntry:
        """Map a candidate to a queue view entry."""
        if not candidate.public_call_code:
            raise MissingPublicCallCodeError(candidate.service_access_id)
        return QueueViewEntry(
            service_access_id=candidate.service_access_id,
            public_call_code=candidate.public_call_code,
            agenda=candidate.agenda,
            scheduled_at=candidate.scheduled_at,
        )
