"""Unit tests for the WebSocketCallHub sync-to-async bridge.

Property 1 (Validates: Requirements 1.2, 2.2, 5.1, 5.2): a covered monitor's
connection receives the live message; a non-covered one receives nothing.
Property 3 (Validates: Requirements 6.1, 6.2): the message carries only the
non-identifying DisplayCall fields.

These are DB-free: a fake read model provides the topology and the resolved
DisplayCall, a fake queue records what is enqueued, and a stub loop runs the
scheduled callback immediately so publish can be checked on one thread.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional

from AZFlow.application.ports.call_event_publisher import CallEvent
from AZFlow.application.ports.display_read_model import DisplayCall
from AZFlow.domain.agenda import Agenda
from AZFlow.domain.service_access import ServiceAccessState
from AZFlow.infrastructure.events.websocket_call_hub import (
    WebSocketCallHub,
    room_key,
    waiting_room_key,
)

PATIENT_IDENTIFIER = "RSSMRA80A01H501U"
_OCCURRED_AT = datetime(2024, 3, 15, 9, 31, tzinfo=timezone.utc)


def _event(room_reference: str = "ROOM-1") -> CallEvent:
    return CallEvent(
        public_call_code="AAA001",
        service_access_id=7,
        agenda=Agenda(id=3, name="Cardiology"),
        state=ServiceAccessState.CALLED,
        room_reference=room_reference,
    )


def _display_call(room_reference: str = "ROOM-1") -> DisplayCall:
    return DisplayCall(
        public_call_code="AAA001",
        agenda=Agenda(id=3, name="Cardiology"),
        state=ServiceAccessState.CALLED,
        room_reference=room_reference,
        room_label="Room 1",
        occurred_at=_OCCURRED_AT,
    )


class _FakeReadModel:
    """Fake DisplayReadModel returning fixed topology and a resolved call."""

    def __init__(
        self,
        waiting_ids: List[int],
        room_ids: List[int],
        display_call: Optional[DisplayCall],
    ) -> None:
        self._waiting_ids = waiting_ids
        self._room_ids = room_ids
        self._display_call = display_call

    def waiting_room_monitor_ids_for_room(self, room_reference: str) -> List[int]:
        return list(self._waiting_ids)

    def room_monitor_ids_for_room(self, room_reference: str) -> List[int]:
        return list(self._room_ids)

    def latest_call_for_room(
        self, room_reference: str, operational_day: Any
    ) -> Optional[DisplayCall]:
        return self._display_call


def _factory(read_model: _FakeReadModel):
    @contextmanager
    def open_read_model() -> Iterator[_FakeReadModel]:
        yield read_model

    return open_read_model


class _ImmediateLoop:
    """Stub loop whose call_soon_threadsafe runs the callback at once."""

    def __init__(self) -> None:
        self.scheduled = 0

    def call_soon_threadsafe(self, callback, *args) -> None:
        self.scheduled += 1
        callback(*args)


def _drain(queue: "asyncio.Queue[Dict[str, Any]]") -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    while not queue.empty():
        items.append(queue.get_nowait())
    return items


def test_publish_enqueues_message_for_covered_waiting_room_monitor():
    read_model = _FakeReadModel([5], [], _display_call())
    loop = _ImmediateLoop()
    hub = WebSocketCallHub(_factory(read_model), loop=loop)
    queue: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()
    hub.register(waiting_room_key(5), queue)

    hub.publish(_event())

    messages = _drain(queue)
    assert len(messages) == 1
    assert messages[0]["type"] == "call"
    assert messages[0]["call"]["public_call_code"] == "AAA001"


def test_publish_enqueues_message_for_covered_room_monitor():
    read_model = _FakeReadModel([], [9], _display_call())
    loop = _ImmediateLoop()
    hub = WebSocketCallHub(_factory(read_model), loop=loop)
    queue: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()
    hub.register(room_key(9), queue)

    hub.publish(_event())

    assert len(_drain(queue)) == 1


def test_publish_does_not_enqueue_for_non_covered_monitor():
    # The read model covers waiting-room monitor 5, but a client is subscribed
    # to monitor 6, which is not covered.
    read_model = _FakeReadModel([5], [], _display_call())
    loop = _ImmediateLoop()
    hub = WebSocketCallHub(_factory(read_model), loop=loop)
    covered: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()
    other: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()
    hub.register(waiting_room_key(5), covered)
    hub.register(waiting_room_key(6), other)

    hub.publish(_event())

    assert len(_drain(covered)) == 1
    assert _drain(other) == []


def test_publish_message_carries_only_non_identifying_fields():
    read_model = _FakeReadModel([5], [], _display_call())
    loop = _ImmediateLoop()
    hub = WebSocketCallHub(_factory(read_model), loop=loop)
    queue: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()
    hub.register(waiting_room_key(5), queue)

    hub.publish(_event())

    call = _drain(queue)[0]["call"]
    assert set(call.keys()) == {
        "public_call_code",
        "agenda",
        "state",
        "room_reference",
        "room_label",
        "occurred_at",
    }
    # No identifying attribute leaks anywhere in the serialised message.
    assert PATIENT_IDENTIFIER not in str(call)
    assert "patient" not in str(call).lower()


def test_publish_returns_without_scheduling_when_no_connections():
    read_model = _FakeReadModel([5], [], _display_call())
    loop = _ImmediateLoop()
    hub = WebSocketCallHub(_factory(read_model), loop=loop)

    hub.publish(_event())

    # No connection: nothing scheduled on the loop and no blocking.
    assert loop.scheduled == 0


def test_publish_sends_nothing_when_no_display_call_resolves():
    # An unusual case: monitors cover the room but no current-day call resolves.
    read_model = _FakeReadModel([5], [], None)
    loop = _ImmediateLoop()
    hub = WebSocketCallHub(_factory(read_model), loop=loop)
    queue: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()
    hub.register(waiting_room_key(5), queue)

    hub.publish(_event())

    assert _drain(queue) == []


def test_publish_skips_when_loop_not_bound():
    read_model = _FakeReadModel([5], [], _display_call())
    hub = WebSocketCallHub(_factory(read_model))  # no loop bound yet
    queue: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()
    hub.register(waiting_room_key(5), queue)

    hub.publish(_event())

    assert _drain(queue) == []
