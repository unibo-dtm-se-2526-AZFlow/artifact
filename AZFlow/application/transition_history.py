"""State-transition history model.

A TransitionRecord records what happened to a ServiceAccess and when, not who
did it. It is a plain application model used to describe and assert recorded
transition effects, not a production port.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from AZFlow.domain.service_access import ServiceAccessState


@dataclass(frozen=True)
class TransitionRecord:
    """One entry in the state-transition history.

    ``previous_state`` is None for the initial WAITING creation record.
    """

    service_access_id: int
    previous_state: Optional[ServiceAccessState]
    resulting_state: ServiceAccessState
    occurred_at: datetime
