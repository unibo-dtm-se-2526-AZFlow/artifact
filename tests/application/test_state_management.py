"""Application tests for StateManagementService.

They run the service against an in-memory fake of the StateTransitionRepository,
with no database. The fake performs the atomic conditional transition on a small
mutable store keyed by ServiceAccess id and records which methods were called, so
a test can assert both the outcome and that no repository work happened when a
precondition fails.
"""

from dataclasses import fields
from datetime import date
from typing import Dict, List, Optional

import pytest

from AZFlow.application.errors import (
    MissingRoomReferenceError,
    ServiceAccessNotAdmittableError,
    ServiceAccessNotFoundError,
    ServiceAccessNotRestorableError,
    ServiceAccessNotSuspendableError,
)
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
_ROOM = "ROOM-3"


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

    def try_admit(self, service_access_id: int) -> Optional[ServiceAccess]:
        self.try_admit_ids.append(service_access_id)
        return self._try_transition(
            service_access_id,
            ServiceAccessState.CALLED,
            lambda access: access.admitted(),
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

    result = service.confirm_admission(40, _ROOM)

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
        service.confirm_admission(40, _ROOM)

    assert info.value.service_access_id == 40
    assert repository.try_admit_ids == [40]
    assert repository.find_state_ids == [40]


def test_confirm_admission_wrong_state_raises_not_admittable():
    access = _service_access(40, ServiceAccessState.WAITING)
    service, repository = _service([access])

    with pytest.raises(ServiceAccessNotAdmittableError) as info:
        service.confirm_admission(40, _ROOM)

    assert info.value.service_access_id == 40
    assert repository.find_state(40) is ServiceAccessState.WAITING


def test_not_found_and_wrong_state_error_types_are_distinct():
    assert ServiceAccessNotFoundError is not ServiceAccessNotSuspendableError
    assert ServiceAccessNotFoundError is not ServiceAccessNotRestorableError
    assert ServiceAccessNotFoundError is not ServiceAccessNotAdmittableError
    assert ServiceAccessNotSuspendableError is not ServiceAccessNotRestorableError
    assert ServiceAccessNotSuspendableError is not ServiceAccessNotAdmittableError
    assert ServiceAccessNotRestorableError is not ServiceAccessNotAdmittableError


# --- Room reference precondition guards admission first (Property 5) --------
# Requirements 3.3, 3.4, 11.4, 11.10


@pytest.mark.parametrize("room", ["", "   ", "\t\n"])
def test_confirm_admission_blank_room_rejected_before_repository(room):
    access = _service_access(40, ServiceAccessState.CALLED)
    service, repository = _service([access])

    with pytest.raises(MissingRoomReferenceError):
        service.confirm_admission(40, room)

    # The precondition fails before any repository call.
    assert repository.try_admit_ids == []
    assert repository.find_state_ids == []
    assert repository.find_state(40) is ServiceAccessState.CALLED


def test_confirm_admission_missing_room_rejected_before_repository():
    access = _service_access(40, ServiceAccessState.CALLED)
    service, repository = _service([access])

    with pytest.raises(MissingRoomReferenceError):
        service.confirm_admission(40, None)  # type: ignore[arg-type]

    assert repository.try_admit_ids == []
    assert repository.find_state_ids == []


def test_suspend_and_restore_take_no_room_reference():
    # suspend and restore accept only the id; a Room reference is never required.
    waiting = _service_access(40, ServiceAccessState.WAITING)
    suspended = _service_access(41, ServiceAccessState.SUSPENDED)
    service, _repository = _service([waiting, suspended])

    assert service.suspend(40).room_reference is None
    assert service.restore(41).room_reference is None


# --- Room reference carried unchanged, admission only (Property 5) ----------
# Requirements 3.13, 10.5


def test_room_reference_is_carried_unchanged_into_admission_result():
    access = _service_access(40, ServiceAccessState.CALLED)
    service, _repository = _service([access])
    room = "  ROOM-with spaces and CASE 42  "

    result = service.confirm_admission(40, room)

    assert result.room_reference == room


def test_suspend_and_restore_results_carry_no_room_reference():
    waiting = _service_access(40, ServiceAccessState.WAITING)
    suspended = _service_access(41, ServiceAccessState.SUSPENDED)
    service, _repository = _service([waiting, suspended])

    assert service.suspend(40).room_reference is None
    assert service.restore(41).room_reference is None


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
    admit_result = service.confirm_admission(42, _ROOM)

    assert suspend_result.public_call_code == "AAA007"
    assert suspend_result.agenda == _AGENDA
    assert restore_result.public_call_code == "AAA008"
    assert admit_result.public_call_code == "AAA009"
    assert admit_result.room_reference == _ROOM


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
        service.confirm_admission(40, _ROOM)

    assert repository.try_admit_ids == [40]
    assert repository.find_state(40) is ServiceAccessState.ADMITTED
