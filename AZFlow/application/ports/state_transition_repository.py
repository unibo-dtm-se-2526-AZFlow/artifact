"""Persistence port used by Suspend, Restore and Admission.

It works with domain objects and the ServiceAccessState enum, not SQL rows.
Each transition is a single atomic conditional change from an expected state to
a new state, and it also records the matching transition record in the same
transaction. A miss is classified afterwards with a read-only state lookup.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol

from AZFlow.domain.service_access import ServiceAccess, ServiceAccessState


@dataclass(frozen=True)
class AdmissionOutcome:
    """Result of a successful admission transition.

    Carries the transitioned ServiceAccess together with the reference and
    label of the Room persisted at call time, so the caller can expose them
    without the Room being part of the domain ServiceAccess.
    """

    service_access: ServiceAccess
    room_reference: str
    room_label: str


class StateTransitionRepository(Protocol):
    """Persistence operations required by state-management transitions."""

    def try_suspend(self, service_access_id: int) -> Optional[ServiceAccess]:
        """Try the WAITING to SUSPENDED transition of one ServiceAccess.

        On success it also records the WAITING to SUSPENDED transition in the
        same transaction. Return the transitioned ServiceAccess, or None when it
        was no longer WAITING.
        """
        ...

    def try_restore(self, service_access_id: int) -> Optional[ServiceAccess]:
        """Try the SUSPENDED to WAITING transition of one ServiceAccess.

        On success it also records the SUSPENDED to WAITING transition in the
        same transaction. Return the transitioned ServiceAccess, or None when it
        was no longer SUSPENDED.
        """
        ...

    def try_admit(self, service_access_id: int) -> Optional[AdmissionOutcome]:
        """Try the CALLED to ADMITTED transition of one ServiceAccess.

        The transition uses the room_id already stored on the ServiceAccess row,
        so there is no room input. On success it also records the CALLED to
        ADMITTED transition in the same transaction. Return an AdmissionOutcome
        with the transitioned ServiceAccess and the persisted Room's reference
        and label, or None when it was no longer CALLED.
        """
        ...

    def find_state(self, service_access_id: int) -> Optional[ServiceAccessState]:
        """Return the current ServiceAccessState, or None when no ServiceAccess
        exists.

        Read-only. Used only to tell not-found from wrong-state on a miss.
        """
        ...
