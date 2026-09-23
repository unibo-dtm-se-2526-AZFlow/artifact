"""ServiceAccess domain concept"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Optional

from AZFlow.domain.agenda import Agenda
from AZFlow.domain.appointment import Appointment
from AZFlow.domain.daily_presence import DailyPresence
from AZFlow.domain.errors import (
    ServiceAccessNotCalledError,
    ServiceAccessNotSuspendedError,
    ServiceAccessNotWaitingError,
)


class ServiceAccessState(Enum):
    """State of a ServiceAccess

    A ServiceAccess starts ``WAITING`` and becomes ``CALLED`` when called.
    It can be ``SUSPENDED`` and restored, or ``ADMITTED`` after a call.
    """

    WAITING = "WAITING"
    CALLED = "CALLED"
    SUSPENDED = "SUSPENDED"
    ADMITTED = "ADMITTED"


@dataclass(frozen=True)
class ServiceAccess:
    """Access to one healthcare service

    It belongs to one DailyPresence and one Agenda and starts in the
    ``WAITING`` state.
    """

    id: int
    daily_presence: DailyPresence
    agenda: Agenda
    appointment: Optional[Appointment] = None
    state: ServiceAccessState = ServiceAccessState.WAITING

    def called(self) -> "ServiceAccess":
        """Return a copy in CALLED state.

        Only a WAITING ServiceAccess can be called.
        """
        if self.state is not ServiceAccessState.WAITING:
            raise ServiceAccessNotWaitingError(self.id)
        return replace(self, state=ServiceAccessState.CALLED)

    def suspended(self) -> "ServiceAccess":
        """Return a copy in SUSPENDED state.

        Only a WAITING ServiceAccess can be suspended.
        """
        if self.state is not ServiceAccessState.WAITING:
            raise ServiceAccessNotWaitingError(self.id)
        return replace(self, state=ServiceAccessState.SUSPENDED)

    def restored(self) -> "ServiceAccess":
        """Return a copy in WAITING state.

        Only a SUSPENDED ServiceAccess can be restored.
        """
        if self.state is not ServiceAccessState.SUSPENDED:
            raise ServiceAccessNotSuspendedError(self.id)
        return replace(self, state=ServiceAccessState.WAITING)

    def admitted(self) -> "ServiceAccess":
        """Return a copy in ADMITTED state.

        Only a CALLED ServiceAccess can be admitted.
        """
        if self.state is not ServiceAccessState.CALLED:
            raise ServiceAccessNotCalledError(self.id)
        return replace(self, state=ServiceAccessState.ADMITTED)
