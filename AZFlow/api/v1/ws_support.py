"""Support object shared by the WebSocket display endpoints.

It bundles the shared WebSocketCallHub with the database-backed reads the
endpoints need (monitor existence and the initial snapshot). Composition builds
one instance and stores it on ``app.state``; tests can store a fake there.

The read methods here are synchronous and open their own short-lived read
model. The endpoints call them through asyncio.to_thread, so the psycopg work
runs on a worker thread and never on the event loop.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List

from fastapi import WebSocket

from AZFlow.infrastructure.events.websocket_call_hub import (
    ReadModelFactory,
    WebSocketCallHub,
    display_call_json,
)

_STATE_KEY = "ws_display_support"


class WebSocketDisplaySupport:
    """Database-backed helpers plus the shared hub for the WS endpoints."""

    def __init__(
        self,
        hub: WebSocketCallHub,
        read_model_factory: ReadModelFactory,
    ) -> None:
        self.hub = hub
        self._read_model_factory = read_model_factory

    def waiting_room_monitor_exists(self, waiting_room_monitor_id: int) -> bool:
        """Return whether the WaitingRoomMonitor id is configured."""
        with self._read_model_factory() as read_model:
            return read_model.waiting_room_monitor_exists(waiting_room_monitor_id)

    def room_monitor_exists(self, room_monitor_id: int) -> bool:
        """Return whether the RoomMonitor id is configured."""
        with self._read_model_factory() as read_model:
            return read_model.room_monitor_exists(room_monitor_id)

    def recent_calls_snapshot(
        self, waiting_room_monitor_id: int
    ) -> List[Dict[str, Any]]:
        """Return the current recent-calls snapshot as JSON items."""
        with self._read_model_factory() as read_model:
            calls = read_model.recent_calls_for_monitor(
                waiting_room_monitor_id, date.today()
            )
        return [display_call_json(call) for call in calls]

    def latest_call_snapshot(self, room_monitor_id: int) -> List[Dict[str, Any]]:
        """Return the latest-call snapshot as zero or one JSON item."""
        with self._read_model_factory() as read_model:
            latest = read_model.latest_call_for_room_monitor(
                room_monitor_id, date.today()
            )
        return [] if latest is None else [display_call_json(latest)]


def set_ws_support(app: Any, support: WebSocketDisplaySupport) -> None:
    """Store the support object on the application state."""
    setattr(app.state, _STATE_KEY, support)


def get_ws_support(websocket: WebSocket) -> WebSocketDisplaySupport:
    """Read the support object stored on the application state."""
    return getattr(websocket.app.state, _STATE_KEY)
