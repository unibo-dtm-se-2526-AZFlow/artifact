"""Suspend, Restore and Admission application service.

An Operator suspends a WAITING ServiceAccess, restores a SUSPENDED one, or
confirms admission of a CALLED one. Each operation acts on a ServiceAccess by
its internal id and changes the single shared ServiceAccessState through the
StateTransitionRepository. It does not depend on FastAPI, PostgreSQL or other
concrete adapters, needs no Queue context, and publishes no event.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn, Optional

from AZFlow.application.errors import (
    MissingRoomReferenceError,
    ServiceAccessNotAdmittableError,
    ServiceAccessNotFoundError,
    ServiceAccessNotRestorableError,
    ServiceAccessNotSuspendableError,
)
from AZFlow.application.ports.state_transition_repository import (
    StateTransitionRepository,
)
from AZFlow.domain.agenda import Agenda
from AZFlow.domain.service_access import ServiceAccess, ServiceAccessState


@dataclass(frozen=True)
class StateChangeResult:
    """Result of a successful state change, with no identifying Patient data.

    ``room_reference`` is set only for confirm admission and left None for
    suspend and restore.
    """

    public_call_code: str
    service_access_id: int
    agenda: Agenda
    state: ServiceAccessState
    room_reference: Optional[str] = None


class StateManagementService:
    """Coordinate suspend, restore and confirm admission.

    Each transition is an atomic conditional change through the
    StateTransitionRepository. A miss is classified once with a read-only state
    lookup into a distinguishable not-found or not-in-expected-state outcome.
    """

    def __init__(self, repository: StateTransitionRepository) -> None:
        self._repository = repository

    def suspend(self, service_access_id: int) -> StateChangeResult:
        """Suspend a WAITING ServiceAccess.

        Raises:
            ServiceAccessNotFoundError: no ServiceAccess exists for the id.
            ServiceAccessNotSuspendableError: it exists but is not WAITING.
        """
        suspended = self._repository.try_suspend(service_access_id)
        if suspended is not None:
            return self._result(suspended)
        self._reject_miss(service_access_id, ServiceAccessNotSuspendableError)

    def restore(self, service_access_id: int) -> StateChangeResult:
        """Restore a SUSPENDED ServiceAccess.

        Raises:
            ServiceAccessNotFoundError: no ServiceAccess exists for the id.
            ServiceAccessNotRestorableError: it exists but is not SUSPENDED.
        """
        restored = self._repository.try_restore(service_access_id)
        if restored is not None:
            return self._result(restored)
        self._reject_miss(service_access_id, ServiceAccessNotRestorableError)

    def confirm_admission(
        self,
        service_access_id: int,
        room_reference: str,
    ) -> StateChangeResult:
        """Confirm admission of a CALLED ServiceAccess into the selected Room.

        The Room reference precondition is checked before any repository work.

        Raises:
            MissingRoomReferenceError: the Room reference is missing or blank.
            ServiceAccessNotFoundError: no ServiceAccess exists for the id.
            ServiceAccessNotAdmittableError: it exists but is not CALLED.
        """
        self._require_room_reference(room_reference)
        admitted = self._repository.try_admit(service_access_id)
        if admitted is not None:
            return self._result(admitted, room_reference)
        self._reject_miss(service_access_id, ServiceAccessNotAdmittableError)

    @staticmethod
    def _require_room_reference(room_reference: str) -> None:
        """Reject a missing, empty or whitespace-only Room reference."""
        if room_reference is None or not room_reference.strip():
            raise MissingRoomReferenceError()

    @staticmethod
    def _result(
        service_access: ServiceAccess,
        room_reference: Optional[str] = None,
    ) -> StateChangeResult:
        """Build the non-identifying result from the transitioned ServiceAccess."""
        return StateChangeResult(
            public_call_code=service_access.daily_presence.public_call_code,
            service_access_id=service_access.id,
            agenda=service_access.agenda,
            state=service_access.state,
            room_reference=room_reference,
        )

    def _reject_miss(
        self,
        service_access_id: int,
        wrong_state_error: type[Exception],
    ) -> NoReturn:
        """Classify a missed transition into not-found or wrong-state.

        The read-only lookup runs only on the miss path and transitions nothing.
        """
        state = self._repository.find_state(service_access_id)
        if state is None:
            raise ServiceAccessNotFoundError(service_access_id)
        raise wrong_state_error(service_access_id)
