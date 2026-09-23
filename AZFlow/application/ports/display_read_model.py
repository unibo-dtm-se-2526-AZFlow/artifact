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

    def waiting_room_monitor_exists(self, waiting_room_monitor_id: int) -> bool:
        """Return whether a WaitingRoomMonitor with this id is configured.

        This is a plain configuration check, independent of whether the monitor
        currently has any calls. A configured monitor with an empty snapshot
        still exists.
        """
        ...

    def room_monitor_exists(self, room_monitor_id: int) -> bool:
        """Return whether a RoomMonitor with this id is configured.

        This is a plain configuration check, independent of whether the
        monitor's Room currently has any calls.
        """
        ...

    def waiting_room_monitor_ids_for_room(self, room_reference: str) -> List[int]:
        """Return the WaitingRoomMonitors whose scope covers a Room.

        A monitor covers the Room when one of its scope nodes is the Room's
        LocationNode or an ancestor of it. The descendant rule stays in the
        persisted topology, not in the caller.
        """
        ...

    def room_monitor_ids_for_room(self, room_reference: str) -> List[int]:
        """Return the RoomMonitors bound to a Room."""
        ...
