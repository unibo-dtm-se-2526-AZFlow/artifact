"""Read-only port used to build the public displays."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Optional, Protocol

from AZFlow.domain.agenda import Agenda
from AZFlow.domain.service_access import ServiceAccessState


@dataclass(frozen=True)
class DisplayCall:
    """A call shown on a public display.

    It exposes only non-identifying display data and never the Patient
    Identifier, any other identifying attribute or the LocationNode hierarchy.
    """

    public_call_code: str
    agenda: Agenda
    state: ServiceAccessState
    room_reference: str
    room_label: str
    occurred_at: datetime


class DisplayReadModel(Protocol):
    """Read operations needed by the public displays.

    The methods operate on configured monitor ids, not caller-supplied scopes.
    """

    def recent_calls_for_monitor(
        self,
        waiting_room_monitor_id: int,
        operational_day: date,
    ) -> List[DisplayCall]:
        """Return the recent calls for a configured WaitingRoomMonitor.

        The result is most-recent-first for the current operational day. The
        adapter resolves the monitor's configured scope nodes, expands their
        descendants, deduplicates and applies the configured maximum as the
        limit, so the bound comes from configuration, not the caller.
        """
        ...

    def latest_call_for_room_monitor(
        self,
        room_monitor_id: int,
        operational_day: date,
    ) -> Optional[DisplayCall]:
        """Return the latest call for a configured RoomMonitor's Room.

        It is the single latest call for the current operational day, or None
        when there is none.
        """
        ...
