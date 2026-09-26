from datetime import datetime
from typing import List, Optional

import pytest

from AZFlow.application.ordering import callable_ordered
from AZFlow.application.ports.queue_view_reader import CandidateServiceAccess
from AZFlow.domain.agenda import Agenda
from AZFlow.domain.queue import QueuePolicy
from AZFlow.domain.service_access import ServiceAccessState

_AGENDA_A = Agenda(id=1, name="Cardiology")
_AGENDA_B = Agenda(id=2, name="Radiology")


def _candidate(
    service_access_id: int,
    daily_presence_id: int,
    agenda: Agenda = _AGENDA_A,
    public_call_code: str = "AAA001",
    scheduled_at: Optional[datetime] = None,
    state: ServiceAccessState = ServiceAccessState.WAITING,
    checked_in_at: datetime = datetime(2024, 5, 20, 8, 0),
) -> CandidateServiceAccess:
    return CandidateServiceAccess(
        service_access_id=service_access_id,
        daily_presence_id=daily_presence_id,
        agenda=agenda,
        state=state,
        public_call_code=public_call_code,
        checked_in_at=checked_in_at,
        scheduled_at=scheduled_at,
    )


def _at(hour: int, minute: int = 0) -> datetime:
    return datetime(2024, 5, 20, hour, minute)


def _ids(result: List[CandidateServiceAccess]) -> List[int]:
    return [c.service_access_id for c in result]


def test_by_appointment_orders_by_scheduled_at_then_id():
    candidates = [
        _candidate(10, 1, scheduled_at=_at(10)),
        _candidate(11, 2, scheduled_at=_at(9)),
        _candidate(12, 3, scheduled_at=_at(11)),
    ]

    result = callable_ordered(candidates, [_AGENDA_A.id], QueuePolicy.BY_APPOINTMENT)

    assert _ids(result) == [11, 10, 12]


def test_by_appointment_ties_break_on_lower_service_access_id():
    candidates = [
        _candidate(20, 1, scheduled_at=_at(9)),
        _candidate(15, 2, scheduled_at=_at(9)),
    ]

    result = callable_ordered(candidates, [_AGENDA_A.id], QueuePolicy.BY_APPOINTMENT)

    assert _ids(result) == [15, 20]


def test_by_appointment_places_no_appointment_after_and_orders_by_id():
    candidates = [
        _candidate(30, 1, scheduled_at=None),
        _candidate(10, 2, scheduled_at=_at(10)),
        _candidate(25, 3, scheduled_at=None),
        _candidate(5, 4, scheduled_at=_at(9)),
    ]

    result = callable_ordered(candidates, [_AGENDA_A.id], QueuePolicy.BY_APPOINTMENT)

    # With appointment first (by scheduled_at), then no-appointment by id.
    assert _ids(result) == [5, 10, 25, 30]


def test_by_arrival_orders_by_check_in_time_not_daily_presence_id():
    candidates = [
        _candidate(50, 1, checked_in_at=_at(10)),
        _candidate(40, 3, checked_in_at=_at(8)),
        _candidate(45, 2, checked_in_at=_at(9)),
    ]

    result = callable_ordered(candidates, [_AGENDA_A.id], QueuePolicy.BY_ARRIVAL)

    assert _ids(result) == [40, 45, 50]


def test_by_arrival_tie_breaks_same_check_in_time_by_service_access_id():
    candidates = [
        _candidate(60, 3, checked_in_at=_at(8)),
        _candidate(55, 1, checked_in_at=_at(8)),
        _candidate(70, 2, checked_in_at=_at(9)),
    ]

    result = callable_ordered(candidates, [_AGENDA_A.id], QueuePolicy.BY_ARRIVAL)

    assert _ids(result) == [55, 60, 70]


def test_membership_filtering_excludes_non_served_agenda():
    candidates = [
        _candidate(10, 1, _AGENDA_A),
        _candidate(11, 2, _AGENDA_B),
    ]

    result = callable_ordered(candidates, [_AGENDA_A.id], QueuePolicy.BY_ARRIVAL)

    assert _ids(result) == [10]


def test_state_filtering_excludes_non_waiting():
    candidates = [
        _candidate(10, 1, state=ServiceAccessState.WAITING),
        _candidate(11, 2, state=ServiceAccessState.CALLED),
    ]

    result = callable_ordered(candidates, [_AGENDA_A.id], QueuePolicy.BY_ARRIVAL)

    assert _ids(result) == [10]


def test_deduplicates_same_service_access_id_keeping_one_entry():
    candidates = [
        _candidate(10, 1),
        _candidate(10, 1),
        _candidate(11, 2),
    ]

    result = callable_ordered(candidates, [_AGENDA_A.id], QueuePolicy.BY_ARRIVAL)

    assert _ids(result) == [10, 11]


@pytest.mark.parametrize(
    "order",
    [
        [0, 1, 2, 3],
        [3, 2, 1, 0],
        [2, 0, 3, 1],
        [1, 3, 0, 2],
    ],
)
def test_by_appointment_result_is_stable_regardless_of_input_order(order):
    base = [
        _candidate(5, 4, scheduled_at=_at(9)),
        _candidate(10, 2, scheduled_at=_at(10)),
        _candidate(25, 3, scheduled_at=None),
        _candidate(30, 1, scheduled_at=None),
    ]
    shuffled = [base[i] for i in order]

    result = callable_ordered(shuffled, [_AGENDA_A.id], QueuePolicy.BY_APPOINTMENT)

    assert _ids(result) == [5, 10, 25, 30]


@pytest.mark.parametrize(
    "order",
    [
        [0, 1, 2],
        [2, 1, 0],
        [1, 2, 0],
    ],
)
def test_by_arrival_result_is_stable_regardless_of_input_order(order):
    base = [
        _candidate(40, 3, checked_in_at=_at(8)),
        _candidate(45, 1, checked_in_at=_at(9)),
        _candidate(50, 2, checked_in_at=_at(10)),
    ]
    shuffled = [base[i] for i in order]

    result = callable_ordered(shuffled, [_AGENDA_A.id], QueuePolicy.BY_ARRIVAL)

    assert _ids(result) == [40, 45, 50]


def test_empty_candidates_returns_empty():
    result = callable_ordered([], [_AGENDA_A.id], QueuePolicy.BY_ARRIVAL)

    assert result == []
