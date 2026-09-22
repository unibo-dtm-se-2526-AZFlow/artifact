"""Shared eligibility and ordering for a Queue's callable candidates.

This is the single source of truth for which candidates a Queue offers and in
what order. Both the Operator Queue View and Patient Calling use it, so "the
next Patient" is the head of the same ordered list.
"""

from __future__ import annotations

from typing import Dict, List

from AZFlow.application.ports.queue_view_reader import CandidateServiceAccess
from AZFlow.domain.queue import QueuePolicy
from AZFlow.domain.service_access import ServiceAccessState


def callable_ordered(
    candidates: List[CandidateServiceAccess],
    served_agenda_ids: List[int],
    policy: QueuePolicy,
) -> List[CandidateServiceAccess]:
    """Return the served, WAITING, de-duplicated candidates ordered by policy."""
    kept = _filter_candidates(candidates, served_agenda_ids)
    return _order(kept, policy)


def _filter_candidates(
    candidates: List[CandidateServiceAccess],
    served_agenda_ids: List[int],
) -> List[CandidateServiceAccess]:
    """Keep served, WAITING candidates, keeping the first of each id."""
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
