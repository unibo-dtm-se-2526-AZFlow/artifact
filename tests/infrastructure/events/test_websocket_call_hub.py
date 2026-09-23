"""Unit tests for the WebSocketCallHub sync-to-async bridge.

Property 1 (Validates: Requirements 1.2, 2.2, 5.1, 5.2): a covered monitor's
connection receives the live message; a non-covered one receives nothing.
Property 3 (Validates: Requirements 6.1, 6.2): the message carries only the
non-identifying DisplayCall fields.

These are DB-free: a fake read model provides the topology and the resolved
DisplayCall (keyed on the ServiceAccess id), a fake queue records what is
enqueued, and a stub loop runs the scheduled callback immediately so publish
can be checked on one thread.
"""

from __future__ import annotations

import asyncio
import threading
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


def _event(service_access_id: int = 7, room_reference: str = "ROOM-1") -> CallEvent:
    return CallEvent(
        public_call_code="AAA001",
        service_access_id=service_access_id,
        agenda=Agenda(id=3, name="Cardiology"),
        state=ServiceAccessState.CALLED,
        room_reference=room_reference,
    )


def _display_call(
    public_call_code: str = "AAA001", room_reference: str = "ROOM-1"
) -> DisplayCall:
    return DisplayCall(
        public_call_code=public_call_code,
        agenda=Agenda(id=3, name="Cardiology"),
        state=ServiceAccessState.CALLED,
        room_reference=room_reference,
        room_label="Room 1",
        occurred_at=_OCCURRED_AT,
    )


class _FakeReadModel:
    """Fake DisplayReadModel returning fixed topology and per-access calls."""

    def __init__(
        self,
        waiting_ids: List[int],
        room_ids: List[int],
        calls_by_access: Optional[Dict[int, DisplayCall]] = None,
    ) -> None:
        self._waiting_ids = waiting_ids
        self._room_ids = room_ids
        self._calls_by_access = calls_by_access or {}

    def waiting_room_monitor_ids_for_room(self, room_reference: str) -> List[int]:
        return list(self._waiting_ids)

    def room_monitor_ids_for_room(self, room_reference: str) -> List[int]:
        return list(self._room_ids)

    def display_call_for_service_access(
        self, service_access_id: int, operational_day: Any
    ) -> Optional[DisplayCall]:
        return self._calls_by_access.get(service_access_id)


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
    read_model = _FakeReadModel([5], [], {7: _display_call()})
    loop = _ImmediateLoop()
    hub = WebSocketCallHub(_factory(read_model), loop=loop)
    queue: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()
    hub.register(waiting_room_key(5), queue)

    hub.publish(_event(service_access_id=7))

    messages = _drain(queue)
    assert len(messages) == 1
    assert messages[0]["type"] == "call"
    assert messages[0]["call"]["public_call_code"] == "AAA001"


def test_publish_enqueues_message_for_covered_room_monitor():
    read_model = _FakeReadModel([], [9], {7: _display_call()})
    loop = _ImmediateLoop()
    hub = WebSocketCallHub(_factory(read_model), loop=loop)
    queue: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()
    hub.register(room_key(9), queue)

    hub.publish(_event(service_access_id=7))

    assert len(_drain(queue)) == 1


def test_publish_does_not_enqueue_for_non_covered_monitor():
    read_model = _FakeReadModel([5], [], {7: _display_call()})
    loop = _ImmediateLoop()
    hub = WebSocketCallHub(_factory(read_model), loop=loop)
    covered: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()
    other: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()
    hub.register(waiting_room_key(5), covered)
    hub.register(waiting_room_key(6), other)

    hub.publish(_event(service_access_id=7))

    assert len(_drain(covered)) == 1
    assert _drain(other) == []


def test_publish_resolves_the_exact_call_for_the_event_not_another():
    """Two calls in the same Room: publishing the first event resolves the
    first call's DisplayCall by ServiceAccess id, never the second's."""
    # ServiceAccess 7 -> AAA001, ServiceAccess 8 -> AAA002, both in ROOM-1.
    calls = {
        7: _display_call(public_call_code="AAA001"),
        8: _display_call(public_call_code="AAA002"),
    }
    read_model = _FakeReadModel([5], [], calls)
    loop = _ImmediateLoop()
    hub = WebSocketCallHub(_factory(read_model), loop=loop)
    queue: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()
    hub.register(waiting_room_key(5), queue)

    # Publish the FIRST event; it must carry AAA001, not the other call.
    hub.publish(_event(service_access_id=7))

    message = _drain(queue)[0]
    assert message["call"]["public_call_code"] == "AAA001"

    # Publishing the second event carries AAA002.
    hub.publish(_event(service_access_id=8))
    message = _drain(queue)[0]
    assert message["call"]["public_call_code"] == "AAA002"


def test_publish_message_carries_only_non_identifying_fields():
    read_model = _FakeReadModel([5], [], {7: _display_call()})
    loop = _ImmediateLoop()
    hub = WebSocketCallHub(_factory(read_model), loop=loop)
    queue: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()
    hub.register(waiting_room_key(5), queue)

    hub.publish(_event(service_access_id=7))

    call = _drain(queue)[0]["call"]
    assert set(call.keys()) == {
        "public_call_code",
        "agenda",
        "state",
        "room_reference",
        "room_label",
        "occurred_at",
    }
    assert PATIENT_IDENTIFIER not in str(call)
    assert "patient" not in str(call).lower()


def test_publish_returns_without_scheduling_when_no_connections():
    read_model = _FakeReadModel([5], [], {7: _display_call()})
    loop = _ImmediateLoop()
    hub = WebSocketCallHub(_factory(read_model), loop=loop)

    hub.publish(_event(service_access_id=7))

    assert loop.scheduled == 0


def test_publish_sends_nothing_when_no_display_call_resolves():
    # Monitors cover the room but the ServiceAccess has no CALLED transition.
    read_model = _FakeReadModel([5], [], {})
    loop = _ImmediateLoop()
    hub = WebSocketCallHub(_factory(read_model), loop=loop)
    queue: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()
    hub.register(waiting_room_key(5), queue)

    hub.publish(_event(service_access_id=7))

    assert _drain(queue) == []


def test_publish_skips_when_loop_not_bound():
    read_model = _FakeReadModel([5], [], {7: _display_call()})
    hub = WebSocketCallHub(_factory(read_model))  # no loop bound yet
    queue: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()
    hub.register(waiting_room_key(5), queue)

    hub.publish(_event(service_access_id=7))

    assert _drain(queue) == []


def test_registry_access_is_thread_safe_under_concurrent_registration():
    """publish() run from a worker thread while the main thread registers and
    unregisters many connections must not raise and must not corrupt state.

    The hub snapshots the target queues under a lock before scheduling, so
    concurrent registry mutation cannot break iteration. A "set changed size
    during iteration" style error would surface here if the lock were missing.
    """
    read_model = _FakeReadModel([5], [], {7: _display_call()})
    loop = _ImmediateLoop()
    hub = WebSocketCallHub(_factory(read_model), loop=loop)

    stop = threading.Event()
    errors: List[BaseException] = []

    # A stable queue that stays registered for the whole run.
    stable: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()
    hub.register(waiting_room_key(5), stable)

    def churn() -> None:
        try:
            queues: List["asyncio.Queue[Dict[str, Any]]"] = [
                asyncio.Queue() for _ in range(50)
            ]
            while not stop.is_set():
                for q in queues:
                    hub.register(waiting_room_key(5), q)
                for q in queues:
                    hub.unregister(waiting_room_key(5), q)
        except BaseException as exc:  # pragma: no cover - only on failure
            errors.append(exc)

    def publish_many() -> None:
        try:
            for _ in range(500):
                hub.publish(_event(service_access_id=7))
        except BaseException as exc:  # pragma: no cover - only on failure
            errors.append(exc)

    churner = threading.Thread(target=churn)
    publisher = threading.Thread(target=publish_many)
    churner.start()
    publisher.start()
    publisher.join()
    stop.set()
    churner.join()

    assert errors == [], f"thread-safety errors: {errors}"
    # The stable connection received at least one message and the run finished.
    assert not stable.empty()
