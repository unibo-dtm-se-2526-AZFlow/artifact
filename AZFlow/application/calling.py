"""Patient Calling application service.

An Operator calls a ServiceAccess visible through a selected Queue, from a
selected Room. The service reuses the Queue View eligibility and ordering to
pick the next candidate, performs an atomic WAITING to CALLED transition through
the CallRepository, and publishes one call event. It does not depend on FastAPI,
PostgreSQL or other concrete adapters.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import List, Optional

from AZFlow.application.errors import (
    MissingPublicCallCodeError,
    MissingRoomReferenceError,
    NoPatientToCallError,
    QueueInactiveError,
    QueueNotFoundError,
    ServiceAccessNotCallableError,
    ServiceAccessNotVisibleError,
)
from AZFlow.application.ordering import callable_ordered
from AZFlow.application.ports.call_event_publisher import CallEvent, CallEventPublisher
from AZFlow.application.ports.call_repository import CallRepository
from AZFlow.application.ports.queue_view_reader import (
    CandidateServiceAccess,
    QueueViewReader,
)
from AZFlow.domain.agenda import Agenda
from AZFlow.domain.queue import Queue
from AZFlow.domain.service_access import ServiceAccess, ServiceAccessState


@dataclass(frozen=True)
class CallResult:
    """Result of a successful call, with no identifying Patient data."""

    public_call_code: str
    service_access_id: int
    agenda: Agenda
    state: ServiceAccessState
    room_reference: str


class CallingService:
    """Coordinate call next and call specific through the application ports.

    Reads and ordering come from the QueueViewReader; the atomic transition
    comes from the CallRepository; success is published through the publisher.
    """

    def __init__(
        self,
        reader: QueueViewReader,
        call_repository: CallRepository,
        publisher: CallEventPublisher,
    ) -> None:
        self._reader = reader
        self._call_repository = call_repository
        self._publisher = publisher

    def call_next(
        self,
        queue_id: int,
        room_reference: str,
        operational_day: Optional[date] = None,
    ) -> CallResult:
        """Call the next callable ServiceAccess of a Queue.

        The current day is used when ``operational_day`` is not given.

        Raises:
            MissingRoomReferenceError: the Room reference is missing or blank.
            QueueNotFoundError: no Queue exists for the id.
            QueueInactiveError: the Queue is INACTIVE.
            NoPatientToCallError: no callable ServiceAccess is available.
            MissingPublicCallCodeError: the selected head has no call code.
        """
        self._require_room_reference(room_reference)
        queue = self._load_active_queue(queue_id)
        day = date.today() if operational_day is None else operational_day
        served_agenda_ids = [agenda.id for agenda in queue.agendas]

        # Optimistic loop: re-read and re-order on contention, no locking.
        # An already-CALLED head drops out on the next read, so this makes
        # progress and ends on the first success or an empty callable list.
        while True:
            candidates = self._reader.list_service_accesses(served_agenda_ids, day)
            ordered = callable_ordered(candidates, served_agenda_ids, queue.policy)
            if not ordered:
                raise NoPatientToCallError(queue_id)

            head = ordered[0]
            self._require_public_call_code(
                head.public_call_code, head.service_access_id
            )

            called = self._call_repository.try_call(head.service_access_id)
            if called is None:
                # The head raced to CALLED; try the next current head.
                continue
            return self._succeed(head.public_call_code, called, room_reference)

    def call_specific(
        self,
        queue_id: int,
        service_access_id: int,
        room_reference: str,
        operational_day: Optional[date] = None,
    ) -> CallResult:
        """Call a specific ServiceAccess visible through a Queue.

        The current day is used when ``operational_day`` is not given.

        Raises:
            MissingRoomReferenceError: the Room reference is missing or blank.
            QueueNotFoundError: no Queue exists for the id.
            QueueInactiveError: the Queue is INACTIVE.
            ServiceAccessNotVisibleError: the target is not visible in the Queue.
            ServiceAccessNotCallableError: the target is visible but not WAITING.
            MissingPublicCallCodeError: the target has no call code.
        """
        self._require_room_reference(room_reference)
        queue = self._load_active_queue(queue_id)
        day = date.today() if operational_day is None else operational_day
        served_agenda_ids = [agenda.id for agenda in queue.agendas]

        # Visibility uses the raw candidate list (any state); callability is
        # then decided by the conditional transition on the WAITING state.
        candidates = self._reader.list_service_accesses(served_agenda_ids, day)
        target = self._find_visible(candidates, service_access_id)
        if target is None:
            raise ServiceAccessNotVisibleError(service_access_id)

        self._require_public_call_code(target.public_call_code, service_access_id)

        called = self._call_repository.try_call(service_access_id)
        if called is None:
            raise ServiceAccessNotCallableError(service_access_id)
        return self._succeed(target.public_call_code, called, room_reference)

    @staticmethod
    def _require_room_reference(room_reference: str) -> None:
        """Reject a missing, empty or whitespace-only Room reference."""
        if room_reference is None or not room_reference.strip():
            raise MissingRoomReferenceError()

    def _load_active_queue(self, queue_id: int) -> Queue:
        """Load the Queue and reject a not-found or INACTIVE Queue."""
        queue = self._reader.load_queue(queue_id)
        if queue is None:
            raise QueueNotFoundError(queue_id)
        if not queue.is_active():
            raise QueueInactiveError(queue_id)
        return queue

    @staticmethod
    def _require_public_call_code(
        public_call_code: str,
        service_access_id: int,
    ) -> None:
        """Reject a call that has no public call code to represent it."""
        if not public_call_code:
            raise MissingPublicCallCodeError(service_access_id)

    @staticmethod
    def _find_visible(
        candidates: List[CandidateServiceAccess],
        service_access_id: int,
    ) -> Optional[CandidateServiceAccess]:
        """Return the candidate with this id, or None when not visible."""
        for candidate in candidates:
            if candidate.service_access_id == service_access_id:
                return candidate
        return None

    def _succeed(
        self,
        public_call_code: str,
        called: ServiceAccess,
        room_reference: str,
    ) -> CallResult:
        """Build the result and publish exactly one event after a call."""
        result = CallResult(
            public_call_code=public_call_code,
            service_access_id=called.id,
            agenda=called.agenda,
            state=called.state,
            room_reference=room_reference,
        )
        self._publisher.publish(
            CallEvent(
                public_call_code=result.public_call_code,
                service_access_id=result.service_access_id,
                agenda=result.agenda,
                state=result.state,
                room_reference=result.room_reference,
            )
        )
        return result
