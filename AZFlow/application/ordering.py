"""Shared filtering and ordering for Queue candidates."""

from __future__ import annotations

from typing import Dict, List, Set

from AZFlow.application.ports.queue_view_reader import CandidateServiceAccess
from AZFlow.domain.queue import QueuePolicy
from AZFlow.domain.service_access import ServiceAccessState


def callable_ordered(
    candidates: List[CandidateServiceAccess],
    served_agenda_ids: List[int],
    policy: QueuePolicy,
) -> List[CandidateServiceAccess]:
    """Return served WAITING candidates ordered by Queue policy."""
    return _filtered_ordered(
        candidates,
        served_agenda_ids,
        policy,
        {ServiceAccessState.WAITING},
    )


def operator_list_ordered(
    candidates: List[CandidateServiceAccess],
    served_agenda_ids: List[int],
    policy: QueuePolicy,
) -> List[CandidateServiceAccess]:
    """Return WAITING and SUSPENDED entries for the operator LIST."""
    return _filtered_ordered(
        candidates,
        served_agenda_ids,
        policy,
        {ServiceAccessState.WAITING, ServiceAccessState.SUSPENDED},
    )


def _filtered_ordered(
    candidates: List[CandidateServiceAccess],
    served_agenda_ids: List[int],
    policy: QueuePolicy,
    states: Set[ServiceAccessState],
) -> List[CandidateServiceAccess]:
    """Filter served candidates by state, de-duplicate them, then order them."""
    served = set(served_agenda_ids)
    seen: Dict[int, CandidateServiceAccess] = {}
    for candidate in candidates:
        if candidate.agenda.id not in served:
            continue
        if candidate.state not in states:
            continue
        if candidate.service_access_id not in seen:
            seen[candidate.service_access_id] = candidate
    return _order(list(seen.values()), policy)


def _order(
    candidates: List[CandidateServiceAccess],
    policy: QueuePolicy,
) -> List[CandidateServiceAccess]:
    """Order candidates by Queue policy."""
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

    return sorted(
        candidates,
        key=lambda c: (c.checked_in_at, c.service_access_id),
    )
