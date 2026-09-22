"""ServiceAccess domain concept"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Optional

from AZFlow.domain.agenda import Agenda
from AZFlow.domain.appointment import Appointment
from AZFlow.domain.daily_presence import DailyPresence
from AZFlow.domain.errors import ServiceAccessNotWaitingError


class ServiceAccessState(Enum):
    """State of a ServiceAccess

    A ServiceAccess starts ``WAITING`` and becomes ``CALLED`` when called.
    """

    WAITING = "WAITING"
    CALLED = "CALLED"


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
