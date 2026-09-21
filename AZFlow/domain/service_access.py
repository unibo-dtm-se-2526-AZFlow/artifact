"""ServiceAccess domain concept"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from AZFlow.domain.agenda import Agenda
from AZFlow.domain.appointment import Appointment
from AZFlow.domain.daily_presence import DailyPresence


class ServiceAccessState(Enum):
    """State of a ServiceAccess

    This slice only needs the ``WAITING`` state.
    """

    WAITING = "WAITING"


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
