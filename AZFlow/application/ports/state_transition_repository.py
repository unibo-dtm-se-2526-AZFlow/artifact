"""Persistence port used by Suspend, Restore and Admission.

It works with domain objects and the ServiceAccessState enum, not SQL rows.
Each transition is a single atomic conditional change from an expected state to
a new state. A miss is classified afterwards with a read-only state lookup.
"""

from __future__ import annotations

from typing import Optional, Protocol

from AZFlow.domain.service_access import ServiceAccess, ServiceAccessState


class StateTransitionRepository(Protocol):
    """Persistence operations required by state-management transitions."""

    def try_suspend(self, service_access_id: int) -> Optional[ServiceAccess]:
        """Try the WAITING to SUSPENDED transition of one ServiceAccess.

        Return the transitioned ServiceAccess, or None when it was no longer
        WAITING.
        """
        ...

    def try_restore(self, service_access_id: int) -> Optional[ServiceAccess]:
        """Try the SUSPENDED to WAITING transition of one ServiceAccess.

        Return the transitioned ServiceAccess, or None when it was no longer
        SUSPENDED.
        """
        ...

    def try_admit(self, service_access_id: int) -> Optional[ServiceAccess]:
        """Try the CALLED to ADMITTED transition of one ServiceAccess.

        Return the transitioned ServiceAccess, or None when it was no longer
        CALLED.
        """
        ...

    def find_state(self, service_access_id: int) -> Optional[ServiceAccessState]:
        """Return the current ServiceAccessState, or None when no ServiceAccess
        exists.

        Read-only. Used only to tell not-found from wrong-state on a miss.
        """
        ...
