"""Application tests for StateManagementService.

They run the service against an in-memory fake of the StateTransitionRepository,
with no database. The fake performs the atomic conditional transition on a small
mutable store keyed by ServiceAccess id and records which methods were called, so
a test can assert both the outcome and that no repository work happened when a
precondition fails.
"""

import inspect
from dataclasses import fields
from datetime import date, datetime
from typing import Dict, List, Optional

import pytest

from AZFlow.application.errors import (
    ServiceAccessNotAdmittableError,
    ServiceAccessNotFoundError,
    ServiceAccessNotCancellableError,
    ServiceAccessNotRecallableError,
    ServiceAccessNotRestorableError,
    ServiceAccessNotSuspendableError,
)
from AZFlow.application.ports.display_state_event_publisher import DisplayStateEvent
from AZFlow.application.ports.state_transition_repository import AdmissionOutcome
from AZFlow.application.state_management import (
    StateChangeResult,
    StateManagementService,
)
from AZFlow.domain.agenda import Agenda
from AZFlow.domain.daily_presence import DailyPresence
from AZFlow.domain.patient_identifier import PatientIdentifier
from AZFlow.domain.service_access import ServiceAccess, ServiceAccessState
from AZFlow.domain.ticket_master import TicketMaster

_DAY = date(2024, 5, 20)
_TICKET_MASTER = TicketMaster(id=1, prefix="AAA")
_AGENDA = Agenda(id=1, name="Cardiology")
_ROOM_REFERENCE = "ROOM-1"
_ROOM_LABEL = "Room 1"


def _service_access(
    service_access_id: int,
    state: ServiceAccessState,
    public_call_code: str = "AAA001",
    agenda: Agenda = _AGENDA,
) -> ServiceAccess:
    """Build a ServiceAccess in a given state.

    The identifier lives only on the DailyPresence and is never exposed by the
    service.
    """
    daily_presence = DailyPresence(
        id=service_access_id,
        patient_identifier=PatientIdentifier(type="fiscal_code", value="ABC123"),
        operational_day=_DAY,
        public_call_code=public_call_code,
        ticket_master=_TICKET_MASTER,
        checked_in_at=datetime(2024, 5, 20, 8, 0),
    )
    return ServiceAccess(
        id=service_access_id,
        daily_presence=daily_presence,
        agenda=agenda,
        appointment=None,
        state=state,
    )


class FakeStateTransitionRepository:
    """StateTransitionRepository fake backed by a small mutable store.

    Each ``try_*`` performs the atomic conditional transition on the store when
    the ServiceAccess is in the expected state, and returns None otherwise. The
    store can be preset so a ServiceAccess is absent (find_state returns None) or
    present in a non-expected state (find_state returns that state), which lets a
    test tell not-found from wrong-state. Every call is recorded.
    """

    def __init__(self, accesses: Optional[List[ServiceAccess]] = None) -> None:
        self._store: Dict[int, ServiceAccess] = {
            access.id: access for access in (accesses or [])
        }
        self.try_suspend_ids: List[int] = []
        self.try_restore_ids: List[int] = []
        self.try_admit_ids: List[int] = []
        self.try_cancel_call_ids: List[int] = []
        self.try_recall_ids: List[int] = []
        self.find_state_ids: List[int] = []

    def _try_transition(
        self,
        service_access_id: int,
        expected: ServiceAccessState,
        transition,
    ) -> Optional[ServiceAccess]:
        access = self._store.get(service_access_id)
        if access is None or access.state is not expected:
            return None
        moved = transition(access)
        self._store[service_access_id] = moved
        return moved

    def try_suspend(self, service_access_id: int) -> Optional[ServiceAccess]:
        self.try_suspend_ids.append(service_access_id)
        return self._try_transition(
            service_access_id,
            ServiceAccessState.WAITING,
            lambda access: access.suspended(),
        )

    def try_restore(self, service_access_id: int) -> Optional[ServiceAccess]:
        self.try_restore_ids.append(service_access_id)
        return self._try_transition(
            service_access_id,
            ServiceAccessState.SUSPENDED,
            lambda access: access.restored(),
        )

    def try_cancel_call(self, service_access_id: int) -> Optional[AdmissionOutcome]:
        self.try_cancel_call_ids.append(service_access_id)
        cancelled = self._try_transition(
            service_access_id,
            ServiceAccessState.CALLED,
            lambda access: access.cancelled_call(),
        )
        if cancelled is None:
            return None
        return AdmissionOutcome(cancelled, _ROOM_REFERENCE, _ROOM_LABEL)

    def try_recall(self, service_access_id: int) -> Optional[AdmissionOutcome]:
        self.try_recall_ids.append(service_access_id)
        recalled = self._try_transition(
            service_access_id,
            ServiceAccessState.ADMITTED,
            lambda access: access.recalled(),
        )
        if recalled is None:
            return None
        return AdmissionOutcome(recalled, _ROOM_REFERENCE, _ROOM_LABEL)

    def try_admit(self, service_access_id: int) -> Optional[AdmissionOutcome]:
        self.try_admit_ids.append(service_access_id)
        admitted = self._try_transition(
            service_access_id,
            ServiceAccessState.CALLED,
            lambda access: access.admitted(),
        )
        if admitted is None:
            return None
        # The Room comes from the stored call-time row; the fake returns the
        # configured reference and label alongside the transitioned access.
        return AdmissionOutcome(
            service_access=admitted,
            room_reference=_ROOM_REFERENCE,
            room_label=_ROOM_LABEL,
        )

    def find_state(self, service_access_id: int) -> Optional[ServiceAccessState]:
        self.find_state_ids.append(service_access_id)
        access = self._store.get(service_access_id)
        return access.state if access is not None else None


def _service(accesses: Optional[List[ServiceAccess]] = None):
    repository = FakeStateTransitionRepository(accesses)
    return StateManagementService(repository), repository


# --- each operation succeeds on its expected state (Property 1) -------------
# Requirements 1.4, 2.4, 3.6


def test_suspend_transitions_waiting_to_suspended():
    access = _service_access(40, ServiceAccessState.WAITING)
    service, repository = _service([access])

    result = service.suspend(40)

    assert result.state is ServiceAccessState.SUSPENDED
    assert result.service_access_id == 40
    assert repository.try_suspend_ids == [40]
    assert repository.find_state_ids == []


def test_restore_transitions_suspended_to_waiting():
    access = _service_access(40, ServiceAccessState.SUSPENDED)
    service, repository = _service([access])

    result = service.restore(40)

    assert result.state is ServiceAccessState.WAITING
    assert result.service_access_id == 40
    assert repository.try_restore_ids == [40]
    assert repository.find_state_ids == []


def test_confirm_admission_transitions_called_to_admitted():
    access = _service_access(40, ServiceAccessState.CALLED)
    service, repository = _service([access])

    result = service.confirm_admission(40)

    assert result.state is ServiceAccessState.ADMITTED
    assert result.service_access_id == 40
    assert repository.try_admit_ids == [40]
    assert repository.find_state_ids == []


# --- not-found vs wrong-state are distinguishable (Property 3) --------------
# Requirements 1.3, 1.6, 2.3, 2.6, 3.5, 3.8, 11.3, 11.11


def test_suspend_not_found_when_no_row():
    service, repository = _service([])

    with pytest.raises(ServiceAccessNotFoundError) as info:
        service.suspend(40)

    assert info.value.service_access_id == 40
    assert repository.try_suspend_ids == [40]
    assert repository.find_state_ids == [40]


def test_suspend_wrong_state_raises_not_suspendable():
    access = _service_access(40, ServiceAccessState.CALLED)
    service, repository = _service([access])

    with pytest.raises(ServiceAccessNotSuspendableError) as info:
        service.suspend(40)

    assert info.value.service_access_id == 40
    # The store still holds the original state; nothing was transitioned.
    assert repository.find_state(40) is ServiceAccessState.CALLED


def test_restore_not_found_when_no_row():
    service, repository = _service([])

    with pytest.raises(ServiceAccessNotFoundError) as info:
        service.restore(40)

    assert info.value.service_access_id == 40
    assert repository.try_restore_ids == [40]
    assert repository.find_state_ids == [40]


def test_restore_wrong_state_raises_not_restorable():
    access = _service_access(40, ServiceAccessState.WAITING)
    service, repository = _service([access])

    with pytest.raises(ServiceAccessNotRestorableError) as info:
        service.restore(40)

    assert info.value.service_access_id == 40
    assert repository.find_state(40) is ServiceAccessState.WAITING


def test_confirm_admission_not_found_when_no_row():
    service, repository = _service([])

    with pytest.raises(ServiceAccessNotFoundError) as info:
        service.confirm_admission(40)

    assert info.value.service_access_id == 40
    assert repository.try_admit_ids == [40]
    assert repository.find_state_ids == [40]


def test_confirm_admission_wrong_state_raises_not_admittable():
    access = _service_access(40, ServiceAccessState.WAITING)
    service, repository = _service([access])

    with pytest.raises(ServiceAccessNotAdmittableError) as info:
        service.confirm_admission(40)

    assert info.value.service_access_id == 40
    assert repository.find_state(40) is ServiceAccessState.WAITING


def test_not_found_and_wrong_state_error_types_are_distinct():
    assert ServiceAccessNotFoundError is not ServiceAccessNotSuspendableError
    assert ServiceAccessNotFoundError is not ServiceAccessNotRestorableError
    assert ServiceAccessNotFoundError is not ServiceAccessNotAdmittableError
    assert ServiceAccessNotSuspendableError is not ServiceAccessNotRestorableError
    assert ServiceAccessNotSuspendableError is not ServiceAccessNotAdmittableError
    assert ServiceAccessNotRestorableError is not ServiceAccessNotAdmittableError


# --- admission reuses the stored call-time Room (Property 5) ----------------
# Validates: Requirements 5.4, 5.5, 5.6


def test_confirm_admission_takes_no_room_reference_argument():
    # Lock the changed Spec 4 contract: the caller no longer supplies a Room.
    parameters = inspect.signature(StateManagementService.confirm_admission).parameters
    assert "room_reference" not in parameters
    assert list(parameters) == ["self", "service_access_id"]


def test_confirm_admission_uses_stored_room_and_returns_admitted():
    # The Room comes from the stored row via the fake try_admit; the caller
    # passes only the id and the transition succeeds to ADMITTED, exposing the
    # persisted Room's reference and label.
    access = _service_access(40, ServiceAccessState.CALLED)
    service, repository = _service([access])

    result = service.confirm_admission(40)

    assert result.state is ServiceAccessState.ADMITTED
    assert result.service_access_id == 40
    assert result.room_reference == _ROOM_REFERENCE
    assert result.room_label == _ROOM_LABEL
    assert repository.try_admit_ids == [40]
    assert repository.find_state_ids == []


def test_suspend_and_restore_carry_no_room_reference():
    # suspend and restore have no Room; their results expose neither the Room
    # reference nor the label.
    waiting = _service_access(40, ServiceAccessState.WAITING)
    suspended = _service_access(41, ServiceAccessState.SUSPENDED)
    service, _repository = _service([waiting, suspended])

    suspend_result = service.suspend(40)
    restore_result = service.restore(41)

    assert suspend_result.room_reference is None
    assert suspend_result.room_label is None
    assert restore_result.room_reference is None
    assert restore_result.room_label is None


# --- results expose only non-identifying data (Property 6) ------------------
# Requirements 1.7, 2.7, 3.9, 10.1, 10.2, 10.3, 10.4, 11.9


def test_result_exposes_only_closed_non_identifying_fields():
    field_names = {f.name for f in fields(StateChangeResult)}
    expected = {
        "public_call_code",
        "service_access_id",
        "agenda",
        "state",
        "room_reference",
        "room_label",
    }

    assert field_names == expected
    assert not any("patient" in name or "identifier" in name for name in field_names)


def test_successful_results_return_only_non_identifying_values():
    waiting = _service_access(40, ServiceAccessState.WAITING, public_call_code="AAA007")
    suspended = _service_access(
        41, ServiceAccessState.SUSPENDED, public_call_code="AAA008"
    )
    called = _service_access(42, ServiceAccessState.CALLED, public_call_code="AAA009")
    service, _repository = _service([waiting, suspended, called])

    suspend_result = service.suspend(40)
    restore_result = service.restore(41)
    admit_result = service.confirm_admission(42)

    assert suspend_result.public_call_code == "AAA007"
    assert suspend_result.agenda == _AGENDA
    assert restore_result.public_call_code == "AAA008"
    assert admit_result.public_call_code == "AAA009"
    assert admit_result.state is ServiceAccessState.ADMITTED
    # Admission exposes the non-identifying Room reference and label only.
    assert admit_result.room_reference == _ROOM_REFERENCE
    assert admit_result.room_label == _ROOM_LABEL


# --- concurrency miss path at the application boundary (Property 4) ---------
# Requirement 6.3


def test_suspend_concurrency_miss_reports_not_suspendable_and_no_transition():
    # The transition raced away: still present but no longer WAITING.
    access = _service_access(40, ServiceAccessState.SUSPENDED)
    service, repository = _service([access])

    with pytest.raises(ServiceAccessNotSuspendableError):
        service.suspend(40)

    assert repository.try_suspend_ids == [40]
    assert repository.find_state(40) is ServiceAccessState.SUSPENDED


def test_restore_concurrency_miss_reports_not_restorable_and_no_transition():
    access = _service_access(40, ServiceAccessState.WAITING)
    service, repository = _service([access])

    with pytest.raises(ServiceAccessNotRestorableError):
        service.restore(40)

    assert repository.try_restore_ids == [40]
    assert repository.find_state(40) is ServiceAccessState.WAITING


def test_confirm_admission_concurrency_miss_reports_not_admittable_and_no_transition():
    access = _service_access(40, ServiceAccessState.ADMITTED)
    service, repository = _service([access])

    with pytest.raises(ServiceAccessNotAdmittableError):
        service.confirm_admission(40)

    assert repository.try_admit_ids == [40]
    assert repository.find_state(40) is ServiceAccessState.ADMITTED


# --- display-relevant transitions publish notifications ----------------------


class FakeDisplayPublisher:
    def __init__(self) -> None:
        self.events: List[DisplayStateEvent] = []

    def publish_state(self, event: DisplayStateEvent) -> None:
        self.events.append(event)


def test_admission_cancel_and_recall_publish_display_state():
    publisher = FakeDisplayPublisher()
    repository = FakeStateTransitionRepository(
        [
            _service_access(40, ServiceAccessState.CALLED),
            _service_access(41, ServiceAccessState.CALLED),
            _service_access(42, ServiceAccessState.ADMITTED),
        ]
    )
    service = StateManagementService(repository, publisher)
    service.confirm_admission(40)
    service.cancel_call(41)
    service.recall(42)
    assert [event.state for event in publisher.events] == [
        ServiceAccessState.ADMITTED,
        ServiceAccessState.WAITING,
        ServiceAccessState.CALLED,
    ]
    assert all(event.room_reference == _ROOM_REFERENCE for event in publisher.events)


def test_suspend_and_restore_do_not_publish_display_state():
    publisher = FakeDisplayPublisher()
    repository = FakeStateTransitionRepository(
        [
            _service_access(40, ServiceAccessState.WAITING),
            _service_access(41, ServiceAccessState.SUSPENDED),
        ]
    )
    service = StateManagementService(repository, publisher)
    service.suspend(40)
    service.restore(41)
    assert publisher.events == []


def test_cancel_call_transitions_called_to_waiting():
    service, repository = _service([_service_access(50, ServiceAccessState.CALLED)])
    result = service.cancel_call(50)
    assert result.state is ServiceAccessState.WAITING
    assert repository.try_cancel_call_ids == [50]


def test_recall_transitions_admitted_to_called_with_room():
    service, repository = _service([_service_access(51, ServiceAccessState.ADMITTED)])
    result = service.recall(51)
    assert result.state is ServiceAccessState.CALLED
    assert result.room_reference == _ROOM_REFERENCE
    assert repository.try_recall_ids == [51]


def test_cancel_call_rejects_non_called_access():
    service, _ = _service([_service_access(50, ServiceAccessState.WAITING)])
    with pytest.raises(ServiceAccessNotCancellableError):
        service.cancel_call(50)


def test_recall_rejects_non_admitted_access():
    service, _ = _service([_service_access(51, ServiceAccessState.CALLED)])
    with pytest.raises(ServiceAccessNotRecallableError):
        service.recall(51)
