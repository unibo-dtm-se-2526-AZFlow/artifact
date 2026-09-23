"""WebSocket display endpoints for live call delivery.

Two endpoints let a waiting-room or Room display subscribe by its configured
monitor id and receive an initial snapshot plus live calls. The core stays
WebSocket-independent: these adapters only deliver what the DisplayReadModel
and the WebSocketCallHub already provide.

Threading rule: every database read here (the existence check and the initial
snapshot) runs off the event loop with asyncio.to_thread, so no synchronous
psycopg query runs on the event-loop thread.

Ordering rule: the queue is registered with the hub BEFORE the initial snapshot
is read, so a call published during snapshot setup lands in the queue and is
delivered right after the snapshot rather than being lost in a gap. A call may
therefore appear both in the snapshot and as a live message around subscription
time; a duplicate call is harmless for a display and is preferred over a missed
call in this single-process design.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict, List

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

# A callable that reads the current snapshot items off the event loop.
SnapshotReader = Callable[[], Awaitable[List[Dict[str, Any]]]]


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

    async def read_snapshot() -> List[Dict[str, Any]]:
        return await asyncio.to_thread(
            support.recent_calls_snapshot, waiting_room_monitor_id
        )

    await _subscribe(
        websocket,
        support.hub,
        waiting_room_key(waiting_room_monitor_id),
        read_snapshot,
    )


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

    async def read_snapshot() -> List[Dict[str, Any]]:
        return await asyncio.to_thread(support.latest_call_snapshot, room_monitor_id)

    await _subscribe(websocket, support.hub, room_key(room_monitor_id), read_snapshot)


async def _subscribe(
    websocket: WebSocket,
    hub: WebSocketCallHub,
    key: MonitorKey,
    read_snapshot: SnapshotReader,
) -> None:
    """Register, send the snapshot, then stream live calls, cleaning up on exit.

    The queue is registered before the snapshot is read, so a call arriving
    during snapshot setup is buffered in the queue and delivered after the
    snapshot instead of being lost.
    """
    queue: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()
    hub.register(key, queue)
    try:
        snapshot = await read_snapshot()
        await websocket.send_json({"type": "snapshot", "calls": snapshot})
        while True:
            message = await queue.get()
            await websocket.send_json(message)
    except WebSocketDisconnect:
        pass
    finally:
        hub.unregister(key, queue)
