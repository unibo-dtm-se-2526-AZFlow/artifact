"""Regression tests for Suspend, Restore and Admission against Queue View and calling.

These tests confirm the existing WAITING-only eligibility already excludes
SUSPENDED and ADMITTED ServiceAccesses from the Queue View and from calling, that
a restored WAITING re-enters ordering like any other WAITING, and that a state
change by id is reflected through every Queue serving the Agenda with no
per-Queue state and no duplication. No production change is expected: SUSPENDED
and ADMITTED are simply non-WAITING states, filtered out like CALLED already is.

They reuse the same candidate, queue and calling fakes as the Queue View,
ordering and calling tests.
"""

from datetime import date, datetime
from typing import Dict, List, Optional

import pytest

from AZFlow.application.calling import CallingService
from AZFlow.application.errors import (
    NoPatientToCallError,
    ServiceAccessNotCallableError,
)
from AZFlow.application.ordering import callable_ordered
from AZFlow.application.ports.call_event_publisher import CallEvent
from AZFlow.application.ports.queue_view_reader import CandidateServiceAccess
from AZFlow.application.queue_view import QueueView, QueueViewService
from AZFlow.domain.agenda import Agenda
from AZFlow.domain.appointment import Appointment
from AZFlow.domain.daily_presence import DailyPresence
from AZFlow.domain.patient_identifier import PatientIdentifier
from AZFlow.domain.queue import Queue, QueuePolicy, QueueStatus
from AZFlow.domain.service_access import ServiceAccess, ServiceAccessState
from AZFlow.domain.ticket_master import TicketMaster
from tests.application.fakes import FakeQueueViewReader

_DAY = date(2024, 5, 20)
_TICKET_MASTER = TicketMaster(id=1, prefix="AAA")

_AGENDA_A = Agenda(id=1, name="Cardiology")
_AGENDA_B = Agenda(id=2, name="Radiology")

_ROOM = "ROOM-3"

# The two states introduced by this slice that must be excluded like CALLED.
_EXCLUDED_STATES = [ServiceAccessState.SUSPENDED, ServiceAccessState.ADMITTED]


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
    agenda: Agenda = _AGENDA_A,
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


def _at(hour: int, minute: int = 0) -> datetime:
    return datetime(2024, 5, 20, hour, minute)


def _ids(view: QueueView) -> List[int]:
    return [entry.service_access_id for entry in view.entries]


def _ordered_ids(
    candidates: List[CandidateServiceAccess],
    served_agenda_ids: List[int],
    policy: QueuePolicy,
) -> List[int]:
    ordered = callable_ordered(candidates, served_agenda_ids, policy)
    return [c.service_access_id for c in ordered]


# --- calling fakes, mirroring test_calling.py -------------------------------


def _service_access(candidate: CandidateServiceAccess) -> ServiceAccess:
    """Build a WAITING domain ServiceAccess mirroring a candidate."""
    daily_presence = DailyPresence(
        id=candidate.daily_presence_id,
        patient_identifier=PatientIdentifier(type="fiscal_code", value="ABC123"),
        operational_day=_DAY,
        public_call_code=candidate.public_call_code,
        ticket_master=_TICKET_MASTER,
    )
    appointment: Optional[Appointment] = None
    return ServiceAccess(
        id=candidate.service_access_id,
        daily_presence=daily_presence,
        agenda=candidate.agenda,
        appointment=appointment,
        state=ServiceAccessState.WAITING,
    )


class _CallingStore:
    """Shared store of candidates keyed by id, honouring WAITING-only calling.

    ``waiting_candidates`` returns only the WAITING ones, matching the real
    reader; ``try_call`` performs the WAITING -> CALLED transition and refuses a
    non-WAITING target, matching the atomic conditional update.
    """

    def __init__(self, candidates: List[CandidateServiceAccess]) -> None:
        self.candidates: Dict[int, CandidateServiceAccess] = {
            c.service_access_id: c for c in candidates
        }

    def waiting_candidates(self) -> List[CandidateServiceAccess]:
        return [
            c for c in self.candidates.values() if c.state is ServiceAccessState.WAITING
        ]

    def all_candidates(self) -> List[CandidateServiceAccess]:
        return list(self.candidates.values())

    def try_call(self, service_access_id: int, room_id: int) -> Optional[ServiceAccess]:
        candidate = self.candidates.get(service_access_id)
        if candidate is None:
            return None
        if candidate.state is not ServiceAccessState.WAITING:
            return None
        self.candidates[service_access_id] = _candidate(
            candidate.service_access_id,
            candidate.daily_presence_id,
            candidate.agenda,
            candidate.public_call_code,
            candidate.scheduled_at,
            ServiceAccessState.CALLED,
        )
        return _service_access(candidate).called()


class _CallingReader:
    """QueueViewReader fake backed by a calling store.

    ``list_service_accesses`` returns visible candidates (any state), like the
    real reader, so ``callable_ordered`` and call_next filter to WAITING while
    call_specific can see a non-WAITING target as visible.
    """

    def __init__(self, queues: Dict[int, Queue], store: _CallingStore) -> None:
        self._queues = dict(queues)
        self._store = store

    def load_queue(self, queue_id: int) -> Optional[Queue]:
        return self._queues.get(queue_id)

    def list_service_accesses(
        self,
        agenda_ids: List[int],
        operational_day: date,
    ) -> List[CandidateServiceAccess]:
        served = set(agenda_ids)
        return [c for c in self._store.all_candidates() if c.agenda.id in served]


class _CallRepository:
    """CallRepository fake sharing the store with the reader.

    ``resolve_room`` resolves the demo Room reference these tests call with; the
    resolved id flows into ``try_call`` like the real adapter.
    """

    def __init__(self, store: _CallingStore) -> None:
        self._store = store

    def resolve_room(self, room_reference: str) -> Optional[int]:
        return 3 if room_reference == _ROOM else None

    def try_call(self, service_access_id: int, room_id: int) -> Optional[ServiceAccess]:
        return self._store.try_call(service_access_id, room_id)


class _RecordingPublisher:
    def __init__(self) -> None:
        self.events: List[CallEvent] = []

    def publish(self, event: CallEvent) -> None:
        self.events.append(event)


def _build_calling(queue: Queue, candidates: List[CandidateServiceAccess]):
    store = _CallingStore(candidates)
    reader = _CallingReader({queue.id: queue}, store)
    repository = _CallRepository(store)
    publisher = _RecordingPublisher()
    service = CallingService(reader, repository, publisher)
    return service, store, publisher


# --- Property 7: SUSPENDED / ADMITTED excluded from Queue View --------------


@pytest.mark.parametrize("excluded_state", _EXCLUDED_STATES)
def test_queue_view_excludes_suspended_and_admitted(excluded_state):
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_ARRIVAL)
    candidates = [
        _candidate(10, 1, public_call_code="AAA001"),
        _candidate(11, 2, public_call_code="AAA002", state=excluded_state),
        _candidate(12, 3, public_call_code="AAA003"),
    ]
    service = QueueViewService(FakeQueueViewReader({queue.id: queue}, candidates))

    view = service.view(1, _DAY)

    # Only the WAITING ones remain; the excluded state is dropped like CALLED.
    assert _ids(view) == [10, 12]


@pytest.mark.parametrize("excluded_state", _EXCLUDED_STATES)
def test_ordering_filters_out_suspended_and_admitted(excluded_state):
    candidates = [
        _candidate(10, 1),
        _candidate(11, 2, state=excluded_state),
    ]

    kept = _ordered_ids(candidates, [_AGENDA_A.id], QueuePolicy.BY_ARRIVAL)

    assert kept == [10]


# --- Property 7: SUSPENDED / ADMITTED are not callable ----------------------


@pytest.mark.parametrize("excluded_state", _EXCLUDED_STATES)
def test_call_next_never_selects_suspended_or_admitted(excluded_state):
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_ARRIVAL)
    # The lowest arrival key belongs to the excluded one; it must be skipped.
    service, store, publisher = _build_calling(
        queue,
        [
            _candidate(10, 1, public_call_code="AAA001", state=excluded_state),
            _candidate(11, 2, public_call_code="AAA002"),
        ],
    )

    result = service.call_next(1, _ROOM, _DAY)

    assert result.service_access_id == 11
    assert store.candidates[10].state is excluded_state
    assert len(publisher.events) == 1


@pytest.mark.parametrize("excluded_state", _EXCLUDED_STATES)
def test_call_next_with_only_suspended_or_admitted_finds_no_patient(excluded_state):
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_ARRIVAL)
    service, _store, publisher = _build_calling(
        queue,
        [_candidate(10, 1, public_call_code="AAA001", state=excluded_state)],
    )

    with pytest.raises(NoPatientToCallError):
        service.call_next(1, _ROOM, _DAY)

    assert publisher.events == []


@pytest.mark.parametrize("excluded_state", _EXCLUDED_STATES)
def test_call_specific_suspended_or_admitted_is_not_callable(excluded_state):
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_ARRIVAL)
    service, store, publisher = _build_calling(
        queue,
        [_candidate(10, 1, public_call_code="AAA001", state=excluded_state)],
    )

    with pytest.raises(ServiceAccessNotCallableError) as info:
        service.call_specific(1, 10, _ROOM, _DAY)

    assert info.value.service_access_id == 10
    # The state is unchanged: the conditional transition refused it.
    assert store.candidates[10].state is excluded_state
    assert publisher.events == []


# --- Property 7: a restored WAITING re-enters ordering identically ----------


def test_restored_waiting_takes_same_by_arrival_position_as_never_suspended():
    others = [
        _candidate(40, 1, public_call_code="AAA001"),
        _candidate(50, 3, public_call_code="AAA003"),
    ]
    # A restored ServiceAccess is just WAITING again with its ordering attributes.
    restored = _candidate(45, 2, public_call_code="AAA002")
    never_suspended = _candidate(45, 2, public_call_code="AAA002")

    with_restored = _ordered_ids(
        others + [restored], [_AGENDA_A.id], QueuePolicy.BY_ARRIVAL
    )
    with_never_suspended = _ordered_ids(
        others + [never_suspended], [_AGENDA_A.id], QueuePolicy.BY_ARRIVAL
    )

    assert with_restored == with_never_suspended == [40, 45, 50]


def test_restored_waiting_takes_same_by_appointment_position_as_never_suspended():
    others = [
        _candidate(40, 1, public_call_code="AAA001", scheduled_at=_at(9)),
        _candidate(50, 3, public_call_code="AAA003", scheduled_at=_at(11)),
    ]
    restored = _candidate(45, 2, public_call_code="AAA002", scheduled_at=_at(10))
    never_suspended = _candidate(45, 2, public_call_code="AAA002", scheduled_at=_at(10))

    with_restored = _ordered_ids(
        others + [restored], [_AGENDA_A.id], QueuePolicy.BY_APPOINTMENT
    )
    with_never_suspended = _ordered_ids(
        others + [never_suspended], [_AGENDA_A.id], QueuePolicy.BY_APPOINTMENT
    )

    assert with_restored == with_never_suspended == [40, 45, 50]


def test_restored_waiting_is_visible_in_queue_view_like_any_waiting():
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_ARRIVAL)
    candidates = [
        _candidate(40, 1, public_call_code="AAA001"),
        # Back to WAITING after a restore; nothing distinguishes it.
        _candidate(45, 2, public_call_code="AAA002"),
    ]
    service = QueueViewService(FakeQueueViewReader({queue.id: queue}, candidates))

    view = service.view(1, _DAY)

    assert _ids(view) == [40, 45]


# --- Property 8: a state change by id is global across every Queue ----------


@pytest.mark.parametrize("excluded_state", _EXCLUDED_STATES)
def test_state_change_reflected_through_every_queue_serving_the_agenda(excluded_state):
    # Two Queues serve the same Agenda through the same shared candidate list.
    queue_arrival = _queue(1, [_AGENDA_A], QueuePolicy.BY_ARRIVAL)
    queue_appointment = _queue(2, [_AGENDA_A], QueuePolicy.BY_APPOINTMENT)
    shared = [
        _candidate(10, 1, public_call_code="AAA001"),
        _candidate(11, 2, public_call_code="AAA002", state=excluded_state),
    ]
    reader = FakeQueueViewReader(
        {1: queue_arrival, 2: queue_appointment},
        shared,
    )
    service = QueueViewService(reader)

    view_one = service.view(1, _DAY)
    view_two = service.view(2, _DAY)

    # The single shared state is reflected identically through both Queues:
    # the non-WAITING one is excluded everywhere, with no per-Queue state.
    assert _ids(view_one) == [10]
    assert _ids(view_two) == [10]


def test_calling_state_change_is_reflected_across_queues_without_duplication():
    # One shared store; two Queues over the same Agenda read the same state.
    queue_one = _queue(1, [_AGENDA_A], QueuePolicy.BY_ARRIVAL)
    queue_two = _queue(2, [_AGENDA_A], QueuePolicy.BY_ARRIVAL)
    store = _CallingStore(
        [
            _candidate(10, 1, public_call_code="AAA001"),
            _candidate(11, 2, public_call_code="AAA002"),
        ]
    )
    reader = _CallingReader({1: queue_one, 2: queue_two}, store)
    repository = _CallRepository(store)
    publisher = _RecordingPublisher()
    service = CallingService(reader, repository, publisher)
    view_service = QueueViewService(reader)

    # Calling through Queue 1 changes the single shared state by id.
    called = service.call_next(1, _ROOM, _DAY)
    assert called.service_access_id == 10

    # The change is visible through both Queues; no copy or duplicate appears.
    view_one = view_service.view(1, _DAY)
    view_two = view_service.view(2, _DAY)
    assert _ids(view_one) == [11]
    assert _ids(view_two) == [11]
    # The store still holds exactly the two originals, none duplicated.
    assert sorted(store.candidates.keys()) == [10, 11]
    assert store.candidates[10].state is ServiceAccessState.CALLED
