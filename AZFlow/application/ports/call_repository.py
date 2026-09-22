"""Persistence port used to call a Patient.

It works with domain objects, not SQL rows. Candidate reading, ordering and
the retry loop stay in the application.
"""

from __future__ import annotations

from typing import Optional, Protocol

from AZFlow.domain.service_access import ServiceAccess


class CallRepository(Protocol):
    """Persistence operations required to call a Patient."""

    def try_call(self, service_access_id: int) -> Optional[ServiceAccess]:
        """Try the WAITING to CALLED transition of one ServiceAccess.

        This is a single atomic conditional transition. Return the transitioned
        ServiceAccess when the transition happened, or None when it was no
        longer WAITING.
        """
        ...
