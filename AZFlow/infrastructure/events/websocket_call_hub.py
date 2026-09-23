"""WebSocket fan-out hub for live call delivery.

The hub is a CallEventPublisher that pushes each successful call to the
connected display clients whose configured monitor covers the call's Room.

Threading rule: publish() runs on the synchronous request thread and does all
its database work there. It then schedules only a non-blocking enqueue onto
each connection's asyncio.Queue via loop.call_soon_threadsafe. No synchronous
psycopg query ever runs on the event-loop thread.

The connection registry is shared between the event-loop thread (register and
unregister) and the request thread (publish). A small lock protects it. The
lock is held only for quick registry reads and writes: publish takes a snapshot
of the target queues under the lock, then releases it before any database work
or loop scheduling.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, ContextManager, Dict, List, Optional, Set

from AZFlow.application.ports.call_event_publisher import CallEvent
from AZFlow.application.ports.display_read_model import DisplayCall, DisplayReadModel

_logger = logging.getLogger(__name__)

# A factory that opens a short-lived read model as a context manager. It lets
# publish() open and close its own connection on the request thread, and lets
# tests pass a fake read model without a database.
ReadModelFactory = Callable[[], ContextManager[DisplayReadModel]]


@dataclass(frozen=True)
class MonitorKey:
    """Identity of a subscribed monitor: its kind plus configured id.

    A WaitingRoomMonitor and a RoomMonitor may share the same integer id, so
    the kind is part of the identity.
    """

    kind: str  # "waiting_room" or "room"
    monitor_id: int


def waiting_room_key(monitor_id: int) -> MonitorKey:
    """Identity key for a WaitingRoomMonitor subscription."""
    return MonitorKey(kind="waiting_room", monitor_id=monitor_id)


def room_key(monitor_id: int) -> MonitorKey:
    """Identity key for a RoomMonitor subscription."""
    return MonitorKey(kind="room", monitor_id=monitor_id)


def display_call_json(call: DisplayCall) -> Dict[str, Any]:
    """Serialise a DisplayCall to its non-identifying JSON shape."""
    return {
        "public_call_code": call.public_call_code,
        "agenda": {"id": call.agenda.id, "name": call.agenda.name},
        "state": call.state.value,
        "room_reference": call.room_reference,
        "room_label": call.room_label,
        "occurred_at": call.occurred_at.isoformat(),
    }


class WebSocketCallHub:
    """Publish live calls to subscribed WebSocket display clients.

    The read-model factory opens a short-lived read model on the request thread
    when publish() needs the persisted topology, mirroring the per-request
    connection convention used elsewhere in composition.
    """

    def __init__(
        self,
        read_model_factory: ReadModelFactory,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ) -> None:
        self._loop = loop
        self._read_model_factory = read_model_factory
        self._connections: Dict[MonitorKey, Set["asyncio.Queue[Dict[str, Any]]"]] = {}
        # Guards the registry across the event-loop thread and request thread.
        self._lock = threading.Lock()

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Bind the running event loop, called once at application startup."""
        self._loop = loop

    def register(self, key: MonitorKey, queue: "asyncio.Queue[Dict[str, Any]]") -> None:
        """Register a connection's queue under a monitor identity."""
        with self._lock:
            self._connections.setdefault(key, set()).add(queue)

    def unregister(
        self, key: MonitorKey, queue: "asyncio.Queue[Dict[str, Any]]"
    ) -> None:
        """Remove a connection's queue; drop the key when it has none left."""
        with self._lock:
            queues = self._connections.get(key)
            if queues is None:
                return
            queues.discard(queue)
            if not queues:
                self._connections.pop(key, None)

    def _has_connections(self) -> bool:
        with self._lock:
            return bool(self._connections)

    def _queues_for(
        self, keys: List[MonitorKey]
    ) -> List["asyncio.Queue[Dict[str, Any]]"]:
        """Return a snapshot of the queues registered under any of the keys.

        Taken under the lock so it is consistent with concurrent register and
        unregister, then returned as a plain list so the caller can schedule
        enqueues without holding the lock.
        """
        with self._lock:
            queues: List["asyncio.Queue[Dict[str, Any]]"] = []
            for key in keys:
                queues.extend(self._connections.get(key, set()))
            return queues

    def publish(self, event: CallEvent) -> None:
        """Deliver one successful call to every covered connection.

        Runs on the sync request thread. It resolves the covering monitors and
        the non-identifying DisplayCall from the persisted history, builds a
        plain-dict message, and schedules the enqueue on the event loop. It
        never blocks and never touches the database on the loop thread, and it
        never holds the registry lock during database work or loop scheduling.
        """
        # No connection or no bound loop means no work; skip the database read.
        if self._loop is None or not self._has_connections():
            return

        operational_day = date.today()
        with self._read_model_factory() as read_model:
            waiting_ids = read_model.waiting_room_monitor_ids_for_room(
                event.room_reference
            )
            room_ids = read_model.room_monitor_ids_for_room(event.room_reference)
            # Resolve the exact call by ServiceAccess, not by Room, so two calls
            # to the same Room close together never resolve to each other.
            display_call = read_model.display_call_for_service_access(
                event.service_access_id, operational_day
            )

        if display_call is None:
            # The event was published but no current-day CALLED transition
            # resolves for this ServiceAccess; nothing consistent to show.
            _logger.debug(
                "no display call resolved for service access %s; skipping",
                event.service_access_id,
            )
            return

        message = {"type": "call", "call": display_call_json(display_call)}

        keys: List[MonitorKey] = [waiting_room_key(i) for i in waiting_ids]
        keys += [room_key(i) for i in room_ids]

        # Snapshot the target queues under the lock, then release it before
        # scheduling the non-blocking enqueue on the event loop.
        for queue in self._queues_for(keys):
            self._loop.call_soon_threadsafe(queue.put_nowait, message)
