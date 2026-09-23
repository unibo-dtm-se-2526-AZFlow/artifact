"""Persistence port used to call a Patient.

It works with domain objects, not SQL rows. Candidate reading, ordering and
the retry loop stay in the application.
"""

from __future__ import annotations

from typing import Optional, Protocol

from AZFlow.domain.service_access import ServiceAccess


class CallRepository(Protocol):
    """Persistence operations required to call a Patient."""

    def resolve_room(self, room_reference: str) -> Optional[int]:
        """Return the configured Room id for a room reference.

        Return None when no configured Room has that reference. This is a read
        done before the transition.
        """
        ...

    def try_call(self, service_access_id: int, room_id: int) -> Optional[ServiceAccess]:
        """Try the WAITING to CALLED transition of one ServiceAccess.

        A successful call is a single atomic conditional WAITING to CALLED
        transition. It sets the call-time room_id and records the WAITING to
        CALLED transition in the same transaction. Return the transitioned
        ServiceAccess, or None when it was no longer WAITING. No explicit row
        locks are used.
        """
        ...
