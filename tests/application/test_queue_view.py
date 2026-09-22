from dataclasses import fields
from datetime import date, datetime
from typing import List, Optional

import pytest

from AZFlow.application.errors import (
    MissingPublicCallCodeError,
    QueueInactiveError,
    QueueNotFoundError,
)
from AZFlow.application.ports.queue_view_reader import CandidateServiceAccess
from AZFlow.application.queue_view import (
    QueueView,
    QueueViewEntry,
    QueueViewService,
)
from AZFlow.domain.agenda import Agenda
from AZFlow.domain.queue import Queue, QueuePolicy, QueueStatus
from AZFlow.domain.service_access import ServiceAccessState
from AZFlow.domain.ticket_master import TicketMaster
from tests.application.fakes import (
    DayScopedFakeQueueViewReader,
    FakeQueueViewReader,
)

_DAY = date(2024, 5, 20)
_TICKET_MASTER = TicketMaster(id=1, prefix="AAA")

_AGENDA_A = Agenda(id=1, name="Cardiology")
_AGENDA_B = Agenda(id=2, name="Radiology")
_AGENDA_C = Agenda(id=3, name="Neurology")


def _queue(
    queue_id: int,
    agendas: List[Agenda],
    policy: QueuePolicy = QueuePolicy.BY_ARRIVAL,
    status: QueueStatus = QueueStatus.ACTIVE,
) -> Queue:
    return Queue(
        id=queue_id,
        status=status,
        policy=policy,
        ticket_master=_TICKET_MASTER,
        agendas=list(agendas),
    )


def _candidate(
    service_access_id: int,
    daily_presence_id: int,
    agenda: Agenda,
    public_call_code: str = "AAA001",
    scheduled_at: Optional[datetime] = None,
    state: ServiceAccessState = ServiceAccessState.WAITING,
) -> CandidateServiceAccess:
    return CandidateServiceAccess(
        service_access_id=service_access_id,
        daily_presence_id=daily_presence_id,
        agenda=agenda,
        state=state,
        public_call_code=public_call_code,
        scheduled_at=scheduled_at,
    )


def _service(
    queue: Queue,
    candidates: List[CandidateServiceAccess],
) -> QueueViewService:
    reader = FakeQueueViewReader({queue.id: queue}, candidates)
    return QueueViewService(reader)


def _at(hour: int, minute: int = 0) -> datetime:
    return datetime(2024, 5, 20, hour, minute)


def _ids(view: QueueView) -> List[int]:
    return [entry.service_access_id for entry in view.entries]


def test_by_appointment_orders_by_scheduled_at_then_id():
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_APPOINTMENT)
    candidates = [
        _candidate(10, 1, _AGENDA_A, "AAA001", _at(10)),
        _candidate(11, 2, _AGENDA_A, "AAA002", _at(9)),
        _candidate(12, 3, _AGENDA_A, "AAA003", _at(11)),
    ]
    service = _service(queue, candidates)

    view = service.view(1, _DAY)

    assert view.policy is QueuePolicy.BY_APPOINTMENT
    assert _ids(view) == [11, 10, 12]


def test_by_appointment_ties_break_on_lower_service_access_id():
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_APPOINTMENT)
    candidates = [
        _candidate(20, 1, _AGENDA_A, "AAA002", _at(9)),
        _candidate(15, 2, _AGENDA_A, "AAA001", _at(9)),
    ]
    service = _service(queue, candidates)

    view = service.view(1, _DAY)

    assert _ids(view) == [15, 20]


def test_by_appointment_places_no_appointment_after_and_orders_by_id():
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_APPOINTMENT)
    candidates = [
        _candidate(30, 1, _AGENDA_A, "AAA003", scheduled_at=None),
        _candidate(10, 2, _AGENDA_A, "AAA001", _at(10)),
        _candidate(25, 3, _AGENDA_A, "AAA002", scheduled_at=None),
        _candidate(5, 4, _AGENDA_A, "AAA004", _at(9)),
    ]
    service = _service(queue, candidates)

    view = service.view(1, _DAY)

    # With appointment first (by scheduled_at), then no-appointment by id.
    assert _ids(view) == [5, 10, 25, 30]


def test_by_arrival_orders_by_daily_presence_then_service_access_id():
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_ARRIVAL)
    candidates = [
        _candidate(50, 3, _AGENDA_A, "AAA003"),
        _candidate(40, 1, _AGENDA_A, "AAA001"),
        _candidate(45, 2, _AGENDA_A, "AAA002"),
    ]
    service = _service(queue, candidates)

    view = service.view(1, _DAY)

    assert _ids(view) == [40, 45, 50]


def test_by_arrival_tie_breaks_same_daily_presence_by_service_access_id():
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_ARRIVAL)
    candidates = [
        _candidate(60, 1, _AGENDA_A, "AAA002"),
        _candidate(55, 1, _AGENDA_A, "AAA001"),
        _candidate(70, 2, _AGENDA_A, "AAA003"),
    ]
    service = _service(queue, candidates)

    view = service.view(1, _DAY)

    assert _ids(view) == [55, 60, 70]


@pytest.mark.parametrize(
    "order",
    [
        [0, 1, 2, 3],
        [3, 2, 1, 0],
        [2, 0, 3, 1],
        [1, 3, 0, 2],
    ],
)
def test_by_appointment_result_is_stable_regardless_of_reader_order(order):
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_APPOINTMENT)
    base = [
        _candidate(5, 4, _AGENDA_A, "AAA001", _at(9)),
        _candidate(10, 2, _AGENDA_A, "AAA002", _at(10)),
        _candidate(25, 3, _AGENDA_A, "AAA003", scheduled_at=None),
        _candidate(30, 1, _AGENDA_A, "AAA004", scheduled_at=None),
    ]
    shuffled = [base[i] for i in order]
    service = _service(queue, shuffled)

    view = service.view(1, _DAY)

    assert _ids(view) == [5, 10, 25, 30]


@pytest.mark.parametrize(
    "order",
    [
        [0, 1, 2],
        [2, 1, 0],
        [1, 2, 0],
    ],
)
def test_by_arrival_result_is_stable_regardless_of_reader_order(order):
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_ARRIVAL)
    base = [
        _candidate(40, 1, _AGENDA_A, "AAA001"),
        _candidate(45, 2, _AGENDA_A, "AAA002"),
        _candidate(50, 3, _AGENDA_A, "AAA003"),
    ]
    shuffled = [base[i] for i in order]
    service = _service(queue, shuffled)

    view = service.view(1, _DAY)

    assert _ids(view) == [40, 45, 50]


def test_membership_filtering_keeps_only_served_agendas():
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_ARRIVAL)
    # Feed a non-served agenda to check the service filters it out.
    reader = FakeQueueViewReader(
        {queue.id: queue},
        [
            _candidate(10, 1, _AGENDA_A, "AAA001"),
            _candidate(11, 2, _AGENDA_B, "AAA002"),
        ],
    )
    service = QueueViewService(reader)

    view = service.view(1, _DAY)

    assert _ids(view) == [10]


def test_all_waiting_candidates_are_kept():
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_ARRIVAL)
    candidates = [
        _candidate(10, 1, _AGENDA_A, "AAA001"),
        _candidate(11, 2, _AGENDA_A, "AAA002"),
    ]
    service = _service(queue, candidates)

    view = service.view(1, _DAY)

    assert _ids(view) == [10, 11]
    assert all(c.state is ServiceAccessState.WAITING for c in candidates)


def test_no_duplicate_service_access_id_across_multiple_agendas():
    queue = _queue(1, [_AGENDA_A, _AGENDA_B], QueuePolicy.BY_ARRIVAL)
    candidates = [
        _candidate(10, 1, _AGENDA_A, "AAA001"),
        # Same service access id returned twice (defensive dedup).
        _candidate(10, 1, _AGENDA_A, "AAA001"),
        _candidate(11, 2, _AGENDA_B, "AAA002"),
    ]
    service = _service(queue, candidates)

    view = service.view(1, _DAY)

    assert _ids(view) == [10, 11]


def test_same_service_access_visible_through_two_queues_is_not_mutated():
    shared_candidate = _candidate(10, 1, _AGENDA_A, "AAA001")
    queue_arrival = _queue(1, [_AGENDA_A], QueuePolicy.BY_ARRIVAL)
    queue_appointment = _queue(2, [_AGENDA_A], QueuePolicy.BY_APPOINTMENT)
    reader = FakeQueueViewReader(
        {1: queue_arrival, 2: queue_appointment},
        [shared_candidate],
    )
    service = QueueViewService(reader)

    view_one = service.view(1, _DAY)
    view_two = service.view(2, _DAY)

    assert _ids(view_one) == [10]
    assert _ids(view_two) == [10]
    # The candidate is untouched and reused, not copied or mutated.
    entry_one = view_one.entries[0]
    entry_two = view_two.entries[0]
    assert entry_one.agenda is shared_candidate.agenda
    assert entry_two.agenda is shared_candidate.agenda
    assert entry_one.public_call_code == shared_candidate.public_call_code


def test_queue_serving_no_agendas_returns_empty_without_error():
    queue = _queue(1, [], QueuePolicy.BY_ARRIVAL)
    reader = FakeQueueViewReader(
        {queue.id: queue},
        [_candidate(10, 1, _AGENDA_A, "AAA001")],
    )
    service = QueueViewService(reader)

    view = service.view(1, _DAY)

    assert view.entries == []


def test_no_candidates_for_day_returns_empty_without_error():
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_ARRIVAL)
    service = _service(queue, [])

    view = service.view(1, _DAY)

    assert view.entries == []


def test_missing_queue_raises_not_found():
    reader = FakeQueueViewReader({}, [])
    service = QueueViewService(reader)

    with pytest.raises(QueueNotFoundError) as info:
        service.view(99, _DAY)

    assert info.value.queue_id == 99


def test_inactive_queue_raises_inactive():
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_ARRIVAL, QueueStatus.INACTIVE)
    reader = FakeQueueViewReader({queue.id: queue}, [])
    service = QueueViewService(reader)

    with pytest.raises(QueueInactiveError) as info:
        service.view(1, _DAY)

    assert info.value.queue_id == 1


def test_service_passes_resolved_day_and_operates_on_returned_candidates():
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_ARRIVAL)
    other_day = date(2024, 5, 21)
    reader = DayScopedFakeQueueViewReader(
        {queue.id: queue},
        {
            _DAY: [_candidate(10, 1, _AGENDA_A, "AAA001")],
            other_day: [_candidate(20, 2, _AGENDA_A, "AAA002")],
        },
    )
    service = QueueViewService(reader)

    view_today = service.view(1, _DAY)
    view_other = service.view(1, other_day)

    assert _ids(view_today) == [10]
    assert _ids(view_other) == [20]
    assert reader.list_calls[0] == ([_AGENDA_A.id], _DAY)
    assert reader.list_calls[1] == ([_AGENDA_A.id], other_day)


def test_missing_public_call_code_raises():
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_ARRIVAL)
    service = _service(queue, [_candidate(10, 1, _AGENDA_A, public_call_code="")])

    with pytest.raises(MissingPublicCallCodeError) as info:
        service.view(1, _DAY)

    assert info.value.service_access_id == 10


def test_operational_day_defaults_to_today():
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_ARRIVAL)
    reader = FakeQueueViewReader(
        {queue.id: queue},
        [_candidate(10, 1, _AGENDA_A, "AAA001")],
    )
    service = QueueViewService(reader)

    service.view(1)

    assert reader.list_calls[0] == ([_AGENDA_A.id], date.today())


def test_entry_exposes_only_closed_non_identifying_field_set():
    field_names = {f.name for f in fields(QueueViewEntry)}

    assert field_names == {
        "service_access_id",
        "public_call_code",
        "agenda",
        "scheduled_at",
    }
    # No state or patient identifier field is exposed.
    assert "state" not in field_names
    assert not any("patient" in name or "identifier" in name for name in field_names)
