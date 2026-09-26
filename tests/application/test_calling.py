"""Application tests for CallingService.

They run the service against in-memory fakes of the ports, with no database.

The fakes share a small mutable store keyed by ServiceAccess id. The reader
reads WAITING candidates from that store; the repository performs the atomic
WAITING -> CALLED transition on it. Because a re-read no longer returns a called
ServiceAccess as WAITING, ``callable_ordered`` naturally drops a head that has
raced to CALLED, which lets the tests exercise the retry loop.
"""

from dataclasses import fields
from datetime import date, datetime
from typing import Dict, List, Optional, Set

import pytest

from AZFlow.application.calling import CallingService, CallResult
from AZFlow.application.errors import (
    MissingPublicCallCodeError,
    MissingRoomReferenceError,
    NoPatientToCallError,
    QueueInactiveError,
    QueueNotFoundError,
    RoomNotFoundError,
    ServiceAccessNotCallableError,
    ServiceAccessNotVisibleError,
)
from AZFlow.application.ports.call_event_publisher import CallEvent
from AZFlow.application.ports.queue_view_reader import CandidateServiceAccess
from AZFlow.domain.agenda import Agenda
from AZFlow.domain.appointment import Appointment
from AZFlow.domain.daily_presence import DailyPresence
from AZFlow.domain.patient_identifier import PatientIdentifier
from AZFlow.domain.queue import Queue, QueuePolicy, QueueStatus
from AZFlow.domain.service_access import ServiceAccess, ServiceAccessState
from AZFlow.domain.ticket_master import TicketMaster

_DAY = date(2024, 5, 20)
_TICKET_MASTER = TicketMaster(id=1, prefix="AAA")

_AGENDA_A = Agenda(id=1, name="Cardiology")
_AGENDA_B = Agenda(id=2, name="Radiology")

_ROOM = "ROOM-3"
_ROOM_ID = 3

# The "carried unchanged" test calls with this exact (untrimmed) reference, so
# it must resolve as a configured Room for that call to proceed.
_ROOM_WITH_SPACES = "  ROOM-with spaces and CASE 42  "
_ROOM_WITH_SPACES_ID = 42

# References the fake CallRepository resolves to a configured Room id by
# default, so existing success tests keep working with their room references.
_KNOWN_ROOMS = {
    _ROOM: _ROOM_ID,
    _ROOM_WITH_SPACES: _ROOM_WITH_SPACES_ID,
}

# A reference no configured Room has, used to exercise the rejection path.
_UNKNOWN_ROOM = "NO-SUCH-ROOM"


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


def _service_access(candidate: CandidateServiceAccess) -> ServiceAccess:
    """Build a domain ServiceAccess mirroring a candidate.

    ``try_call`` returns this on a successful transition. The identifier lives
    only on the DailyPresence and is never exposed by the service.
    """
    daily_presence = DailyPresence(
        id=candidate.daily_presence_id,
        patient_identifier=PatientIdentifier(type="fiscal_code", value="ABC123"),
        operational_day=_DAY,
        public_call_code=candidate.public_call_code,
        ticket_master=_TICKET_MASTER,
        checked_in_at=datetime(2024, 5, 20, 8, 0),
    )
    appointment: Optional[Appointment] = None
    return ServiceAccess(
        id=candidate.service_access_id,
        daily_presence=daily_presence,
        agenda=candidate.agenda,
        appointment=appointment,
        state=ServiceAccessState.WAITING,
    )


class _Store:
    """Shared mutable store of candidates keyed by ServiceAccess id.

    It also lets a test preset which ids should refuse their first ``try_call``,
    simulating another caller winning the race on that head.
    """

    def __init__(self, candidates: List[CandidateServiceAccess]) -> None:
        self.candidates: Dict[int, CandidateServiceAccess] = {
            c.service_access_id: c for c in candidates
        }
        # ids that must return None on their next try_call (raced away).
        self.race_once: Set[int] = set()
        # ids already marked CALLED (so a re-read drops them).
        self.called: Set[int] = set()
        # room_id passed to each successful try_call, keyed by ServiceAccess id.
        self.called_room_ids: Dict[int, int] = {}

    def waiting_candidates(self) -> List[CandidateServiceAccess]:
        """Return current WAITING candidates, dropping called ones."""
        result: List[CandidateServiceAccess] = []
        for sa_id, candidate in self.candidates.items():
            if sa_id in self.called:
                continue
            if candidate.state is not ServiceAccessState.WAITING:
                continue
            result.append(candidate)
        return result

    def try_call(self, service_access_id: int, room_id: int) -> Optional[ServiceAccess]:
        candidate = self.candidates.get(service_access_id)
        if candidate is None:
            return None
        if service_access_id in self.race_once:
            # Simulate a concurrent caller that won this head first.
            self.race_once.discard(service_access_id)
            self.called.add(service_access_id)
            return None
        if service_access_id in self.called:
            return None
        if candidate.state is not ServiceAccessState.WAITING:
            return None
        self.called.add(service_access_id)
        self.called_room_ids[service_access_id] = room_id
        return _service_access(candidate).called()


class FakeCallingReader:
    """QueueViewReader fake backed by a shared store.

    It filters by served Agenda like the real reader and records the days it
    was called with, so a test can check the resolved operational day.
    """

    def __init__(self, queues: Dict[int, Queue], store: _Store) -> None:
        self._queues = dict(queues)
        self._store = store
        self.list_calls: List[date] = []

    def load_queue(self, queue_id: int) -> Optional[Queue]:
        return self._queues.get(queue_id)

    def list_service_accesses(
        self,
        agenda_ids: List[int],
        operational_day: date,
    ) -> List[CandidateServiceAccess]:
        self.list_calls.append(operational_day)
        served = set(agenda_ids)
        return [c for c in self._store.waiting_candidates() if c.agenda.id in served]


class FakeCallRepository:
    """CallRepository fake sharing the store with the reader.

    ``resolve_room`` returns a configured Room id for known references and None
    otherwise, so the service can reject an unknown Room before any transition.
    ``try_call`` performs the atomic WAITING -> CALLED transition on the store,
    records how many times it was invoked and with which room_id, so a test can
    assert the guard runs before the transition and the resolved room flows
    through.
    """

    def __init__(
        self,
        store: _Store,
        known_rooms: Optional[Dict[str, int]] = None,
    ) -> None:
        self._store = store
        # Map of known Room references to their configured Room id. The default
        # covers the references the existing success tests call with.
        self.known_rooms: Dict[str, int] = (
            dict(known_rooms) if known_rooms is not None else dict(_KNOWN_ROOMS)
        )
        self.resolve_room_calls: List[str] = []
        self.try_call_ids: List[int] = []
        self.try_call_room_ids: List[int] = []

    def resolve_room(self, room_reference: str) -> Optional[int]:
        self.resolve_room_calls.append(room_reference)
        return self.known_rooms.get(room_reference)

    def try_call(self, service_access_id: int, room_id: int) -> Optional[ServiceAccess]:
        self.try_call_ids.append(service_access_id)
        self.try_call_room_ids.append(room_id)
        return self._store.try_call(service_access_id, room_id)


class RecordingPublisher:
    """CallEventPublisher fake recording every published event."""

    def __init__(self) -> None:
        self.events: List[CallEvent] = []

    def publish(self, event: CallEvent) -> None:
        self.events.append(event)


def _build(
    queue: Queue,
    candidates: List[CandidateServiceAccess],
    known_rooms: Optional[Dict[str, int]] = None,
):
    """Wire the service with fakes sharing one store.

    ``known_rooms`` overrides the Room references the repository resolves; the
    default covers the references the existing success tests use.
    """
    store = _Store(candidates)
    queues = {queue.id: queue}
    reader = FakeCallingReader(queues, store)
    repository = FakeCallRepository(store, known_rooms)
    publisher = RecordingPublisher()
    service = CallingService(reader, repository, publisher)
    return service, reader, repository, publisher, store


# --- call next head selection matches Queue View semantics (Property 2) -----


@pytest.mark.parametrize(
    "order",
    [
        [0, 1, 2, 3],
        [3, 2, 1, 0],
        [2, 0, 3, 1],
        [1, 3, 0, 2],
    ],
)
def test_call_next_selects_by_appointment_head_regardless_of_order(order):
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_APPOINTMENT)
    base = [
        _candidate(5, 4, public_call_code="AAA004", scheduled_at=_at(9)),
        _candidate(10, 2, public_call_code="AAA002", scheduled_at=_at(10)),
        _candidate(25, 3, public_call_code="AAA003", scheduled_at=None),
        _candidate(30, 1, public_call_code="AAA001", scheduled_at=None),
    ]
    shuffled = [base[i] for i in order]
    service, _reader, _repo, _pub, _store = _build(queue, shuffled)

    result = service.call_next(1, _ROOM, _DAY)

    # The earliest scheduled_at (id 5) is the Queue View head for this policy.
    assert result.service_access_id == 5


@pytest.mark.parametrize(
    "order",
    [
        [0, 1, 2],
        [2, 1, 0],
        [1, 2, 0],
    ],
)
def test_call_next_selects_by_arrival_head_regardless_of_order(order):
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_ARRIVAL)
    base = [
        _candidate(40, 1, public_call_code="AAA001"),
        _candidate(45, 2, public_call_code="AAA002"),
        _candidate(50, 3, public_call_code="AAA003"),
    ]
    shuffled = [base[i] for i in order]
    service, _reader, _repo, _pub, _store = _build(queue, shuffled)

    result = service.call_next(1, _ROOM, _DAY)

    # Lowest daily_presence_id (id 40) is the BY_ARRIVAL head.
    assert result.service_access_id == 40


def test_call_next_transitions_head_to_called_and_publishes_one_event():
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_ARRIVAL)
    service, _reader, repo, publisher, store = _build(
        queue, [_candidate(40, 1, public_call_code="AAA001")]
    )

    result = service.call_next(1, _ROOM, _DAY)

    assert result.state is ServiceAccessState.CALLED
    assert repo.try_call_ids == [40]
    # The resolved Room id flows through to try_call.
    assert repo.try_call_room_ids == [_ROOM_ID]
    assert store.called_room_ids == {40: _ROOM_ID}
    assert store.called == {40}
    assert len(publisher.events) == 1


# --- retry loop: head raced to CALLED (Property 1/2, Req 1.11, 4.1) ---------


def test_call_next_refreshes_and_calls_next_head_when_first_raced():
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_ARRIVAL)
    service, _reader, repo, publisher, store = _build(
        queue,
        [
            _candidate(40, 1, public_call_code="AAA001"),
            _candidate(45, 2, public_call_code="AAA002"),
        ],
    )
    # The BY_ARRIVAL head (40) is taken by another caller on the first try.
    store.race_once.add(40)

    result = service.call_next(1, _ROOM, _DAY)

    # After the race, the service refreshes and calls the next current head.
    assert result.service_access_id == 45
    assert repo.try_call_ids == [40, 45]
    assert len(publisher.events) == 1


# --- empty callable set (Req 1.10, 10.6) ------------------------------------


def test_call_next_with_no_callable_raises_no_patient_to_call():
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_ARRIVAL)
    service, _reader, repo, publisher, _store = _build(queue, [])

    with pytest.raises(NoPatientToCallError) as info:
        service.call_next(1, _ROOM, _DAY)

    assert info.value.queue_id == 1
    assert repo.try_call_ids == []
    assert publisher.events == []


# --- call specific success (Req 2.8, 10.2) ----------------------------------


def test_call_specific_transitions_visible_waiting_to_called():
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_ARRIVAL)
    service, _reader, repo, publisher, store = _build(
        queue,
        [
            _candidate(40, 1, public_call_code="AAA001"),
            _candidate(45, 2, public_call_code="AAA002"),
        ],
    )

    result = service.call_specific(1, 45, _ROOM, _DAY)

    assert result.service_access_id == 45
    assert result.state is ServiceAccessState.CALLED
    assert store.called == {45}
    assert repo.try_call_ids == [45]
    assert len(publisher.events) == 1


# --- call specific distinct outcomes (Req 2.9, 2.10, 10.3) ------------------


def test_call_specific_not_visible_raises_not_visible():
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_ARRIVAL)
    service, _reader, repo, publisher, _store = _build(
        queue, [_candidate(40, 1, public_call_code="AAA001")]
    )

    with pytest.raises(ServiceAccessNotVisibleError) as info:
        service.call_specific(1, 999, _ROOM, _DAY)

    assert info.value.service_access_id == 999
    assert repo.try_call_ids == []
    assert publisher.events == []


def test_call_specific_visible_but_not_waiting_raises_not_callable():
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_ARRIVAL)
    service, _reader, repo, publisher, store = _build(
        queue, [_candidate(40, 1, public_call_code="AAA001")]
    )
    # It is visible in the store but already CALLED, so try_call refuses it.
    store.race_once.add(40)

    with pytest.raises(ServiceAccessNotCallableError) as info:
        service.call_specific(1, 40, _ROOM, _DAY)

    assert info.value.service_access_id == 40
    assert repo.try_call_ids == [40]
    assert publisher.events == []


def test_call_specific_not_visible_and_not_callable_are_distinct():
    assert ServiceAccessNotVisibleError is not ServiceAccessNotCallableError


# --- queue rejections for both operations (Req 1.5, 1.6, 2.5, 2.6, 10.4) ----


def test_call_next_missing_queue_raises_not_found():
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_ARRIVAL)
    service, _reader, _repo, publisher, _store = _build(queue, [])

    with pytest.raises(QueueNotFoundError) as info:
        service.call_next(99, _ROOM, _DAY)

    assert info.value.queue_id == 99
    assert publisher.events == []


def test_call_specific_missing_queue_raises_not_found():
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_ARRIVAL)
    service, _reader, _repo, publisher, _store = _build(queue, [])

    with pytest.raises(QueueNotFoundError) as info:
        service.call_specific(99, 40, _ROOM, _DAY)

    assert info.value.queue_id == 99
    assert publisher.events == []


def test_call_next_inactive_queue_raises_inactive():
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_ARRIVAL, QueueStatus.INACTIVE)
    service, _reader, _repo, publisher, _store = _build(
        queue, [_candidate(40, 1, public_call_code="AAA001")]
    )

    with pytest.raises(QueueInactiveError) as info:
        service.call_next(1, _ROOM, _DAY)

    assert info.value.queue_id == 1
    assert publisher.events == []


def test_call_specific_inactive_queue_raises_inactive():
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_ARRIVAL, QueueStatus.INACTIVE)
    service, _reader, _repo, publisher, _store = _build(
        queue, [_candidate(40, 1, public_call_code="AAA001")]
    )

    with pytest.raises(QueueInactiveError) as info:
        service.call_specific(1, 40, _ROOM, _DAY)

    assert info.value.queue_id == 1
    assert publisher.events == []


# --- missing Room reference for both operations (Req 1.3, 2.3, 6.2, 10.5) ---


@pytest.mark.parametrize("room", ["", "   ", "\t\n"])
def test_call_next_blank_room_reference_rejected(room):
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_ARRIVAL)
    service, _reader, repo, publisher, store = _build(
        queue, [_candidate(40, 1, public_call_code="AAA001")]
    )

    with pytest.raises(MissingRoomReferenceError):
        service.call_next(1, room, _DAY)

    assert repo.try_call_ids == []
    assert store.called == set()
    assert publisher.events == []


@pytest.mark.parametrize("room", ["", "   ", "\t\n"])
def test_call_specific_blank_room_reference_rejected(room):
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_ARRIVAL)
    service, _reader, repo, publisher, store = _build(
        queue, [_candidate(40, 1, public_call_code="AAA001")]
    )

    with pytest.raises(MissingRoomReferenceError):
        service.call_specific(1, 40, room, _DAY)

    assert repo.try_call_ids == []
    assert store.called == set()
    assert publisher.events == []


# --- CALLED not offered by a subsequent call next (Req 3.6, 10.7) -----------


def test_called_service_access_is_not_offered_by_subsequent_call_next():
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_ARRIVAL)
    service, _reader, repo, publisher, store = _build(
        queue,
        [
            _candidate(40, 1, public_call_code="AAA001"),
            _candidate(45, 2, public_call_code="AAA002"),
        ],
    )

    first = service.call_next(1, _ROOM, _DAY)
    second = service.call_next(1, _ROOM, _DAY)

    assert first.service_access_id == 40
    # 40 is now CALLED, so the next call offers the next current head.
    assert second.service_access_id == 45
    assert store.called == {40, 45}
    assert len(publisher.events) == 2

    # A third call finds no callable candidate.
    with pytest.raises(NoPatientToCallError):
        service.call_next(1, _ROOM, _DAY)


# --- missing public call code guard runs before try_call (Req 5.5) ----------


def test_call_next_missing_public_call_code_guards_before_try_call():
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_ARRIVAL)
    service, _reader, repo, publisher, store = _build(
        queue, [_candidate(40, 1, public_call_code="")]
    )

    with pytest.raises(MissingPublicCallCodeError) as info:
        service.call_next(1, _ROOM, _DAY)

    assert info.value.service_access_id == 40
    # The code is checked before any transition is attempted.
    assert repo.try_call_ids == []
    assert store.called == set()
    assert publisher.events == []


def test_call_specific_missing_public_call_code_guards_before_try_call():
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_ARRIVAL)
    service, _reader, repo, publisher, store = _build(
        queue, [_candidate(40, 1, public_call_code="")]
    )

    with pytest.raises(MissingPublicCallCodeError) as info:
        service.call_specific(1, 40, _ROOM, _DAY)

    assert info.value.service_access_id == 40
    assert repo.try_call_ids == []
    assert store.called == set()
    assert publisher.events == []


# --- Room reference carried unchanged (Req 6.3, 10.11) ----------------------


def test_room_reference_is_carried_unchanged_into_result_and_event():
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_ARRIVAL)
    service, _reader, _repo, publisher, _store = _build(
        queue, [_candidate(40, 1, public_call_code="AAA001")]
    )
    room = "  ROOM-with spaces and CASE 42  "

    result = service.call_next(1, room, _DAY)

    assert result.room_reference == room
    assert publisher.events[0].room_reference == room


# --- only non-identifying data exposed (Property 3, Req 5.1-5.4, 10.10) -----


def test_call_result_and_event_expose_only_closed_non_identifying_fields():
    result_field_names = {f.name for f in fields(CallResult)}
    event_field_names = {f.name for f in fields(CallEvent)}
    expected = {
        "public_call_code",
        "service_access_id",
        "agenda",
        "state",
        "room_reference",
    }

    assert result_field_names == expected
    assert event_field_names == expected
    for names in (result_field_names, event_field_names):
        assert not any("patient" in name or "identifier" in name for name in names)


def test_successful_call_returns_and_publishes_only_non_identifying_values():
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_ARRIVAL)
    service, _reader, _repo, publisher, _store = _build(
        queue, [_candidate(40, 1, _AGENDA_A, public_call_code="AAA007")]
    )

    result = service.call_next(1, _ROOM, _DAY)
    event = publisher.events[0]

    assert result.public_call_code == "AAA007"
    assert result.service_access_id == 40
    assert result.agenda == _AGENDA_A
    assert result.state is ServiceAccessState.CALLED
    assert event.public_call_code == "AAA007"
    assert event.service_access_id == 40
    assert event.agenda == _AGENDA_A
    assert event.state is ServiceAccessState.CALLED


# --- operational day defaults to today --------------------------------------


def test_call_next_defaults_operational_day_to_today():
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_ARRIVAL)
    service, reader, _repo, _pub, _store = _build(
        queue, [_candidate(40, 1, public_call_code="AAA001")]
    )

    service.call_next(1, _ROOM)

    assert reader.list_calls[0] == date.today()


def test_call_specific_defaults_operational_day_to_today():
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_ARRIVAL)
    service, reader, _repo, _pub, _store = _build(
        queue, [_candidate(40, 1, public_call_code="AAA001")]
    )

    service.call_specific(1, 40, _ROOM)

    assert reader.list_calls[0] == date.today()


# --- room resolution runs before any transition (Property 4) ----------------
# **Validates: Requirements 4.3, 4.4, 4.5, 4.6, 6.4**


def test_call_next_unknown_room_rejected_before_any_transition():
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_ARRIVAL)
    # A callable head exists, proving resolution happens before selection.
    service, _reader, repo, publisher, store = _build(
        queue, [_candidate(40, 1, public_call_code="AAA001")]
    )

    with pytest.raises(RoomNotFoundError) as info:
        service.call_next(1, _UNKNOWN_ROOM, _DAY)

    assert info.value.room_reference == _UNKNOWN_ROOM
    # No transition, no history, no event: try_call is never invoked.
    assert repo.try_call_ids == []
    assert store.called == set()
    assert publisher.events == []


def test_call_specific_unknown_room_rejected_before_any_transition():
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_ARRIVAL)
    # A visible, callable target exists, proving resolution runs first.
    service, _reader, repo, publisher, store = _build(
        queue, [_candidate(40, 1, public_call_code="AAA001")]
    )

    with pytest.raises(RoomNotFoundError) as info:
        service.call_specific(1, 40, _UNKNOWN_ROOM, _DAY)

    assert info.value.room_reference == _UNKNOWN_ROOM
    assert repo.try_call_ids == []
    assert store.called == set()
    assert publisher.events == []


def test_call_next_known_room_publishes_resolved_room_reference_and_id():
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_ARRIVAL)
    service, _reader, repo, publisher, store = _build(
        queue, [_candidate(40, 1, public_call_code="AAA001")]
    )

    result = service.call_next(1, _ROOM, _DAY)

    # The published event carries the resolved configured Room's reference.
    assert result.room_reference == _ROOM
    assert publisher.events[0].room_reference == _ROOM
    # try_call received the resolved Room id for that reference.
    assert repo.try_call_room_ids == [_ROOM_ID]
    assert store.called_room_ids == {40: _ROOM_ID}


def test_call_specific_known_room_publishes_resolved_room_reference_and_id():
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_ARRIVAL)
    service, _reader, repo, publisher, store = _build(
        queue, [_candidate(40, 1, public_call_code="AAA001")]
    )

    result = service.call_specific(1, 40, _ROOM, _DAY)

    assert result.room_reference == _ROOM
    assert publisher.events[0].room_reference == _ROOM
    assert repo.try_call_room_ids == [_ROOM_ID]
    assert store.called_room_ids == {40: _ROOM_ID}


# --- exactly one event per success, none on failure (Property 6) ------------
# **Validates: Requirements 6.1, 6.2, 6.3, 11.3**


def test_call_next_success_publishes_exactly_one_event():
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_ARRIVAL)
    service, _reader, _repo, publisher, _store = _build(
        queue, [_candidate(40, 1, public_call_code="AAA001")]
    )

    service.call_next(1, _ROOM, _DAY)

    assert len(publisher.events) == 1


def test_call_specific_success_publishes_exactly_one_event():
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_ARRIVAL)
    service, _reader, _repo, publisher, _store = _build(
        queue, [_candidate(40, 1, public_call_code="AAA001")]
    )

    service.call_specific(1, 40, _ROOM, _DAY)

    assert len(publisher.events) == 1


def test_call_specific_miss_publishes_no_event():
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_ARRIVAL)
    service, _reader, repo, publisher, store = _build(
        queue, [_candidate(40, 1, public_call_code="AAA001")]
    )
    # The head races to CALLED, so try_call misses and nothing is published.
    store.race_once.add(40)

    with pytest.raises(ServiceAccessNotCallableError):
        service.call_specific(1, 40, _ROOM, _DAY)

    assert repo.try_call_ids == [40]
    assert publisher.events == []


def test_call_next_no_callable_candidate_publishes_no_event():
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_ARRIVAL)
    service, _reader, _repo, publisher, _store = _build(queue, [])

    with pytest.raises(NoPatientToCallError):
        service.call_next(1, _ROOM, _DAY)

    assert publisher.events == []
