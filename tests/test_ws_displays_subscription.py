"""Subscription-ordering regression for the WebSocket display endpoint.

Property 6 (Validates: Requirements 8.2, 8.3) and the snapshot-to-live gap:
the endpoint registers its queue with the hub BEFORE reading the initial
snapshot, so a call published during snapshot setup is buffered and delivered
right after the snapshot instead of being lost.

DB-free: a fake WebSocket captures sent JSON and a slow snapshot reader lets a
call be published into the real hub while the snapshot is being read. Driven
with asyncio.run so no async test plugin is needed.
"""

from __future__ import annotations

import asyncio
from typing import cast
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional

from fastapi import WebSocket

from AZFlow.api.v1.ws_displays import _subscribe
from AZFlow.application.ports.call_event_publisher import CallEvent
from AZFlow.application.ports.display_read_model import DisplayCall
from AZFlow.domain.agenda import Agenda
from AZFlow.domain.service_access import ServiceAccessState
from AZFlow.infrastructure.events.websocket_call_hub import (
    WebSocketCallHub,
    waiting_room_key,
)


class _FakeWebSocket:
    """Captures messages sent through send_json."""

    def __init__(self) -> None:
        self.sent: List[Dict[str, Any]] = []

    async def send_json(self, message: Dict[str, Any]) -> None:
        self.sent.append(message)


class _FakeReadModel:
    def __init__(self, call: DisplayCall) -> None:
        self._call = call

    def waiting_room_monitor_ids_for_room(self, room_reference: str) -> List[int]:
        return [5]

    def room_monitor_ids_for_room(self, room_reference: str) -> List[int]:
        return []

    def display_call_for_service_access(
        self, service_access_id: int, operational_day: Any
    ) -> Optional[DisplayCall]:
        return self._call


def _display_call() -> DisplayCall:
    return DisplayCall(
        public_call_code="AAA001",
        agenda=Agenda(id=3, name="Cardiology"),
        state=ServiceAccessState.CALLED,
        room_reference="ROOM-1",
        room_label="Room 1",
        occurred_at=datetime(2024, 3, 15, 9, 31, tzinfo=timezone.utc),
    )


def _factory(read_model: _FakeReadModel):
    @contextmanager
    def open_read_model() -> Iterator[_FakeReadModel]:
        yield read_model

    return open_read_model


def test_call_during_snapshot_setup_is_not_lost():
    async def scenario() -> _FakeWebSocket:
        loop = asyncio.get_running_loop()
        read_model = _FakeReadModel(_display_call())
        hub = WebSocketCallHub(_factory(read_model), loop=loop)
        websocket = _FakeWebSocket()
        key = waiting_room_key(5)

        snapshot_started = asyncio.Event()

        async def slow_snapshot() -> List[Dict[str, Any]]:
            # Signal that the queue is already registered, then publish a call
            # "during" the snapshot read before returning the empty snapshot.
            snapshot_started.set()
            await asyncio.sleep(0.02)
            return []

        # Run the endpoint subscription; it registers before reading snapshot.
        subscription = asyncio.create_task(
            _subscribe(cast(WebSocket, websocket), hub, key, slow_snapshot)
        )

        # Wait until the snapshot read has begun (queue is registered by now),
        # then publish a call from a worker thread as the real request path does.
        await snapshot_started.wait()
        await asyncio.to_thread(
            hub.publish,
            CallEvent(
                public_call_code="AAA001",
                service_access_id=7,
                agenda=Agenda(id=3, name="Cardiology"),
                state=ServiceAccessState.CALLED,
                room_reference="ROOM-1",
            ),
        )

        # Give the subscription time to send the snapshot then the live call.
        await asyncio.sleep(0.05)
        subscription.cancel()
        try:
            await subscription
        except asyncio.CancelledError:
            pass
        return websocket

    websocket = asyncio.run(scenario())

    # The snapshot is first and the call published during setup follows it; the
    # call is not lost in the gap.
    assert websocket.sent[0] == {"type": "snapshot", "calls": []}
    assert any(
        m.get("type") == "call" and m["call"]["public_call_code"] == "AAA001"
        for m in websocket.sent[1:]
    ), f"live call was lost; sent={websocket.sent}"
