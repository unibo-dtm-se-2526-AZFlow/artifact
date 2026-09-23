"""WebSocket display endpoints for live call delivery.

Two endpoints let a waiting-room or Room display subscribe by its configured
monitor id and receive an initial snapshot plus live calls. The core stays
WebSocket-independent: these adapters only deliver what the DisplayReadModel
and the WebSocketCallHub already provide.

Threading rule: every database read here (the existence check and the initial
snapshot) runs off the event loop with asyncio.to_thread, so no synchronous
psycopg query runs on the event-loop thread.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from AZFlow.api.v1.ws_support import get_ws_support
from AZFlow.infrastructure.events.websocket_call_hub import (
    MonitorKey,
    WebSocketCallHub,
    room_key,
    waiting_room_key,
)

_logger = logging.getLogger(__name__)

router = APIRouter()

# Application close code for a monitor id that is not configured.
_UNKNOWN_MONITOR_CODE = 4004
_UNKNOWN_MONITOR_REASON = "unknown monitor"


@router.websocket("/ws/waiting-room-monitors/{waiting_room_monitor_id}")
async def waiting_room_monitor_socket(
    websocket: WebSocket,
    waiting_room_monitor_id: int,
) -> None:
    """Subscribe a waiting-room display and stream its live calls."""
    support = get_ws_support(websocket)
    await websocket.accept()

    exists = await asyncio.to_thread(
        support.waiting_room_monitor_exists, waiting_room_monitor_id
    )
    if not exists:
        await websocket.close(
            code=_UNKNOWN_MONITOR_CODE, reason=_UNKNOWN_MONITOR_REASON
        )
        return

    snapshot = await asyncio.to_thread(
        support.recent_calls_snapshot, waiting_room_monitor_id
    )
    await websocket.send_json({"type": "snapshot", "calls": snapshot})

    await _stream(websocket, support.hub, waiting_room_key(waiting_room_monitor_id))


@router.websocket("/ws/room-monitors/{room_monitor_id}")
async def room_monitor_socket(
    websocket: WebSocket,
    room_monitor_id: int,
) -> None:
    """Subscribe a Room display and stream its live calls."""
    support = get_ws_support(websocket)
    await websocket.accept()

    exists = await asyncio.to_thread(support.room_monitor_exists, room_monitor_id)
    if not exists:
        await websocket.close(
            code=_UNKNOWN_MONITOR_CODE, reason=_UNKNOWN_MONITOR_REASON
        )
        return

    snapshot = await asyncio.to_thread(support.latest_call_snapshot, room_monitor_id)
    await websocket.send_json({"type": "snapshot", "calls": snapshot})

    await _stream(websocket, support.hub, room_key(room_monitor_id))


async def _stream(websocket: WebSocket, hub: WebSocketCallHub, key: MonitorKey) -> None:
    """Register the connection, forward queued messages, clean up on exit."""
    queue: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()
    hub.register(key, queue)
    try:
        while True:
            message = await queue.get()
            await websocket.send_json(message)
    except WebSocketDisconnect:
        pass
    finally:
        hub.unregister(key, queue)
