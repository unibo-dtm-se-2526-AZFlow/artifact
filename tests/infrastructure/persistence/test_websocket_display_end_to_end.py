"""End-to-end WebSocket + PostgreSQL tests for live call delivery.

These drive the whole stack against the real test database (gated by the
persistence conftest, skipped without AZFLOW_TEST_DATABASE_URL). A Patient
checks in and is called through the versioned calling route; display clients
subscribe over WebSocket and receive the initial snapshot and the live call.

They cover:
- Property 4 (Validates 4.1, 4.2): initial snapshot for a waiting-room monitor
  (recent calls) and a room monitor (latest call).
- Property 1 (Validates 1.2, 2.2, 5.1, 5.2): a live call reaches in-scope
  monitors and not out-of-scope monitors.
- Property 5 (Validates 3.1, 3.2, 3.3, 3.4, 4.3, 4.4): an existing monitor with
  an empty snapshot is accepted; an unknown monitor id is closed with 4004.
- Property 2 (Validates 5.1, 7.1): suspend and restore send nothing.
- Property 6 (Validates 8.2, 8.3): multiple clients on one monitor each receive.
- Property 3 (Validates 6.1, 6.2): every message carries only non-identifying
  fields.

TestClient websockets block on receive, so "no message" is checked
deterministically: a later real call to a Room the client covers must be its
first live message, which is only possible if the earlier event was never
delivered to it.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from AZFlow.api import app
from AZFlow.api.v1.calling import get_calling_service
from AZFlow.api.v1.check_in import get_check_in_service
from AZFlow.api.v1.state_management import get_state_management_service
from AZFlow.api.v1.ws_support import WebSocketDisplaySupport, set_ws_support
from AZFlow.application.calling import CallingService
from AZFlow.application.check_in import CheckInService
from AZFlow.application.state_management import StateManagementService
from AZFlow.infrastructure.appointment_sources.mock import MockAppointmentSource
from AZFlow.infrastructure.events.composite_publisher import (
    CompositeCallEventPublisher,
)
from AZFlow.infrastructure.events.in_process_publisher import (
    InProcessCallEventPublisher,
)
from AZFlow.infrastructure.events.websocket_call_hub import WebSocketCallHub
from AZFlow.infrastructure.persistence.postgres_call_repository import (
    PostgresCallRepository,
)
from AZFlow.infrastructure.persistence.postgres_check_in_repository import (
    PostgresCheckInRepository,
)
from AZFlow.infrastructure.persistence.postgres_display_read_model import (
    PostgresDisplayReadModel,
)
from AZFlow.infrastructure.persistence.postgres_queue_view_reader import (
    PostgresQueueViewReader,
)
from AZFlow.infrastructure.persistence.postgres_state_transition_repository import (
    PostgresStateTransitionRepository,
)
from tests.infrastructure.persistence.seed import (
    seed_external_agenda,
    seed_location_node,
    seed_queue,
    seed_room,
    seed_room_monitor,
    seed_source,
    seed_ticket_master,
    seed_waiting_room_monitor,
    seed_waiting_room_monitor_scope,
)

_IDENTIFIER_VALUE = "RSSMRA80A01H501U"
_IDENTIFIER_VALUE_2 = "DEV0002"  # a mock identifier with an AGENDA-A appointment
_IDENTIFIER_VALUE_3 = "DEV0003"  # a mock identifier with an AGENDA-B appointment
_ROOM_1 = "ROOM-1"
_ROOM_2 = "ROOM-2"
_ALLOWED_FIELDS = {
    "public_call_code",
    "agenda",
    "state",
    "room_reference",
    "room_label",
    "occurred_at",
}


class _Seeded:
    def __init__(self, queue_id, wrm_id, wrm_other_id, room_monitor_id):
        self.queue_id = queue_id
        self.wrm_id = wrm_id
        self.wrm_other_id = wrm_other_id
        self.room_monitor_id = room_monitor_id


def _seed_topology(connection) -> _Seeded:
    """Seed mock agendas, an ACTIVE queue, two Rooms and the monitors.

    ROOM-1 sits under Radiotherapy, covered by the Radiotherapy waiting-room
    monitor and a RoomMonitor. ROOM-2 sits under Oncology, covered by a second
    waiting-room monitor scoped to Oncology (out of scope for ROOM-1 calls).
    """
    source = seed_source(connection)
    agenda_a = seed_external_agenda(connection, source, "Cardiology", "AGENDA-A").agenda
    agenda_b = seed_external_agenda(connection, source, "Neurology", "AGENDA-B").agenda
    ticket_master = seed_ticket_master(connection, "AAA")
    queue_id = seed_queue(
        connection,
        ticket_master,
        [agenda_a.id, agenda_b.id],
        status="ACTIVE",
        policy="BY_ARRIVAL",
    )

    site = seed_location_node(connection, "Site")
    radiotherapy = seed_location_node(connection, "Radiotherapy", parent_id=site)
    oncology = seed_location_node(connection, "Oncology", parent_id=site)
    room1 = seed_room(connection, radiotherapy, _ROOM_1, "Room 1")
    seed_room(connection, oncology, _ROOM_2, "Room 2")

    wrm_id = seed_waiting_room_monitor(connection, "WRM Radiotherapy")
    seed_waiting_room_monitor_scope(connection, wrm_id, radiotherapy)
    wrm_other_id = seed_waiting_room_monitor(connection, "WRM Oncology")
    seed_waiting_room_monitor_scope(connection, wrm_other_id, oncology)
    room_monitor_id = seed_room_monitor(connection, room1)

    return _Seeded(queue_id, wrm_id, wrm_other_id, room_monitor_id)


@pytest.fixture
def wired_client(connection, dsn: str) -> Iterator[TestClient]:
    """Wire the real services over the test DB, with the composite + hub."""
    seeded = _seed_topology(connection)

    appointment_source = MockAppointmentSource()

    @contextmanager
    def open_read_model():
        with psycopg.connect(dsn) as request_connection:
            yield PostgresDisplayReadModel(request_connection, 10)

    hub = WebSocketCallHub(open_read_model)
    publisher = CompositeCallEventPublisher([InProcessCallEventPublisher(), hub])

    def provide_check_in() -> Iterator[CheckInService]:
        with psycopg.connect(dsn) as request_connection:
            repository = PostgresCheckInRepository(request_connection)
            yield CheckInService([appointment_source], repository)

    def provide_calling() -> Iterator[CallingService]:
        with psycopg.connect(dsn) as request_connection:
            reader = PostgresQueueViewReader(request_connection)
            repository = PostgresCallRepository(request_connection)
            yield CallingService(reader, repository, publisher)

    def provide_state_management() -> Iterator[StateManagementService]:
        with psycopg.connect(dsn) as request_connection:
            repository = PostgresStateTransitionRepository(request_connection)
            yield StateManagementService(repository)

    app.state.ws_call_hub = hub
    set_ws_support(app, WebSocketDisplaySupport(hub, open_read_model))
    app.dependency_overrides[get_check_in_service] = provide_check_in
    app.dependency_overrides[get_calling_service] = provide_calling
    app.dependency_overrides[get_state_management_service] = provide_state_management

    # The context manager runs the lifespan, which binds the loop to the hub.
    with TestClient(app) as client:
        client.seeded = seeded  # type: ignore[attr-defined]
        yield client

    app.dependency_overrides.clear()


def _check_in(client: TestClient, identifier_value: str = _IDENTIFIER_VALUE) -> str:
    response = client.post(
        "/api/v1/check-ins",
        json={"identifier_type": "fiscal_code", "identifier_value": identifier_value},
    )
    assert response.status_code == 200
    return response.json()["public_call_code"]


def _call_next(
    client: TestClient, queue_id: int, room_reference: str = _ROOM_1
) -> dict:
    response = client.post(
        f"/api/v1/queues/{queue_id}/calls/next",
        json={"room_reference": room_reference},
    )
    assert response.status_code == 200
    return response.json()


def _first_waiting_id(connection, exclude: int) -> int:
    """Return a WAITING service access id other than ``exclude``."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id FROM service_access "
            "WHERE state = 'WAITING' AND id <> %s ORDER BY id LIMIT 1",
            (exclude,),
        )
        row = cursor.fetchone()
    assert row is not None, "expected a remaining WAITING service access"
    return row[0]


def _assert_non_identifying(call: dict) -> None:
    assert set(call.keys()) == _ALLOWED_FIELDS
    assert _IDENTIFIER_VALUE not in str(call)
    assert _IDENTIFIER_VALUE_2 not in str(call)
    assert "patient" not in str(call).lower()


# Property 5 - existence-based acceptance.


def test_existing_monitor_with_empty_snapshot_is_accepted(wired_client):
    """A configured monitor with no calls yet is accepted with an empty
    snapshot, not treated as unknown."""
    seeded = wired_client.seeded

    with wired_client.websocket_connect(
        f"/api/v1/ws/waiting-room-monitors/{seeded.wrm_id}"
    ) as ws:
        assert ws.receive_json() == {"type": "snapshot", "calls": []}

    with wired_client.websocket_connect(
        f"/api/v1/ws/room-monitors/{seeded.room_monitor_id}"
    ) as ws:
        assert ws.receive_json() == {"type": "snapshot", "calls": []}


def test_unknown_monitor_id_is_closed_with_4004(wired_client):
    """An unknown monitor id is closed with the 4004 close code."""
    with pytest.raises(WebSocketDisconnect) as excinfo:
        with wired_client.websocket_connect(
            "/api/v1/ws/waiting-room-monitors/9999"
        ) as ws:
            ws.receive_json()
    assert excinfo.value.code == 4004

    with pytest.raises(WebSocketDisconnect) as excinfo:
        with wired_client.websocket_connect("/api/v1/ws/room-monitors/9999") as ws:
            ws.receive_json()
    assert excinfo.value.code == 4004


# Property 4 - initial snapshot reflects persisted state.


def test_snapshot_reflects_existing_calls(wired_client):
    """After a call, a fresh subscription snapshot shows it."""
    seeded = wired_client.seeded
    public_call_code = _check_in(wired_client)
    _call_next(wired_client, seeded.queue_id)

    with wired_client.websocket_connect(
        f"/api/v1/ws/waiting-room-monitors/{seeded.wrm_id}"
    ) as ws:
        snapshot = ws.receive_json()
    assert snapshot["type"] == "snapshot"
    assert [c["public_call_code"] for c in snapshot["calls"]] == [public_call_code]
    for call in snapshot["calls"]:
        _assert_non_identifying(call)

    with wired_client.websocket_connect(
        f"/api/v1/ws/room-monitors/{seeded.room_monitor_id}"
    ) as ws:
        snapshot = ws.receive_json()
    assert [c["public_call_code"] for c in snapshot["calls"]] == [public_call_code]


# Property 1 - live delivery to in-scope, exclusion of out-of-scope.


def test_live_call_reaches_in_scope_and_not_out_of_scope(wired_client):
    """A live ROOM-1 call reaches the covering waiting-room and room monitors.

    The Oncology monitor never sees the ROOM-1 call: a later ROOM-2 call it
    covers is its first live message, which is only possible if the earlier
    ROOM-1 call was not delivered to it.
    """
    _check_in(wired_client)
    seeded = wired_client.seeded

    with (
        wired_client.websocket_connect(
            f"/api/v1/ws/waiting-room-monitors/{seeded.wrm_id}"
        ) as covered,
        wired_client.websocket_connect(
            f"/api/v1/ws/room-monitors/{seeded.room_monitor_id}"
        ) as room,
        wired_client.websocket_connect(
            f"/api/v1/ws/waiting-room-monitors/{seeded.wrm_other_id}"
        ) as out_of_scope,
    ):
        assert covered.receive_json()["type"] == "snapshot"
        assert room.receive_json()["type"] == "snapshot"
        assert out_of_scope.receive_json()["type"] == "snapshot"

        body = _call_next(wired_client, seeded.queue_id, _ROOM_1)

        covered_msg = covered.receive_json()
        room_msg = room.receive_json()
        assert covered_msg["type"] == "call"
        assert room_msg["type"] == "call"
        assert covered_msg["call"]["public_call_code"] == body["public_call_code"]
        assert covered_msg["call"]["room_reference"] == _ROOM_1
        _assert_non_identifying(covered_msg["call"])
        _assert_non_identifying(room_msg["call"])

        # A second Patient is called into ROOM-2, which the Oncology monitor
        # covers. Its first live message must be that ROOM-2 call, proving the
        # earlier ROOM-1 call was never delivered to it.
        _check_in(wired_client, _IDENTIFIER_VALUE_2)
        oncology_body = _call_next(wired_client, seeded.queue_id, _ROOM_2)
        out_msg = out_of_scope.receive_json()
        assert out_msg["type"] == "call"
        assert out_msg["call"]["room_reference"] == _ROOM_2
        assert out_msg["call"]["public_call_code"] == oncology_body["public_call_code"]


# Property 6 - multiple clients on one monitor each receive.


def test_multiple_clients_on_one_monitor_each_receive(wired_client):
    """Two clients on the same monitor both get the snapshot and the live call."""
    _check_in(wired_client)
    seeded = wired_client.seeded

    with (
        wired_client.websocket_connect(
            f"/api/v1/ws/waiting-room-monitors/{seeded.wrm_id}"
        ) as first,
        wired_client.websocket_connect(
            f"/api/v1/ws/waiting-room-monitors/{seeded.wrm_id}"
        ) as second,
    ):
        assert first.receive_json()["type"] == "snapshot"
        assert second.receive_json()["type"] == "snapshot"

        _call_next(wired_client, seeded.queue_id, _ROOM_1)

        assert first.receive_json()["type"] == "call"
        assert second.receive_json()["type"] == "call"


# Property 2 - suspend and restore send nothing.


def test_suspend_restore_send_no_message(wired_client, connection):
    """Suspend and restore produce no WS message.

    The first Patient has two accesses; one is called into ROOM-1 and the other
    stays WAITING. That WAITING access is suspended then restored (neither
    publishes). A later real call into ROOM-1 is the room monitor's first live
    message, proving suspend and restore sent nothing in between.
    """
    _check_in(wired_client)
    seeded = wired_client.seeded
    body = _call_next(wired_client, seeded.queue_id, _ROOM_1)
    called_id = body["service_access_id"]
    waiting_id = _first_waiting_id(connection, exclude=called_id)

    with wired_client.websocket_connect(
        f"/api/v1/ws/room-monitors/{seeded.room_monitor_id}"
    ) as room:
        assert room.receive_json()["type"] == "snapshot"

        suspend = wired_client.post(f"/api/v1/service-accesses/{waiting_id}/suspend")
        assert suspend.status_code == 200
        restore = wired_client.post(f"/api/v1/service-accesses/{waiting_id}/restore")
        assert restore.status_code == 200

        # The restored access is called into ROOM-1; its call is the room
        # monitor's first live message, proving suspend and restore sent nothing.
        second = _call_next(wired_client, seeded.queue_id, _ROOM_1)
        message = room.receive_json()
        assert message["type"] == "call"
        assert message["call"]["public_call_code"] == second["public_call_code"]


# Property 1 (regression) - the live call is resolved for the exact event.


def test_two_calls_same_room_resolve_to_their_own_events(wired_client):
    """Two Patients called into ROOM-1 close together each deliver their own
    call.

    Two distinct Patients (so two distinct public call codes) are called into
    ROOM-1 in sequence. The room monitor must receive the first event's code
    first and the second event's code second: the hub resolves each event by
    its ServiceAccess, so the first event never picks up the second (latest)
    call's data. The codes differ, so a mix-up would be visible.
    """
    # Two Patients with exactly one appointment each, so the two call_next
    # calls necessarily hit two distinct Patients with distinct call codes.
    _check_in(wired_client, _IDENTIFIER_VALUE_2)
    _check_in(wired_client, _IDENTIFIER_VALUE_3)
    seeded = wired_client.seeded

    with wired_client.websocket_connect(
        f"/api/v1/ws/room-monitors/{seeded.room_monitor_id}"
    ) as room:
        assert room.receive_json()["type"] == "snapshot"

        first = _call_next(wired_client, seeded.queue_id, _ROOM_1)
        second = _call_next(wired_client, seeded.queue_id, _ROOM_1)
        assert first["service_access_id"] != second["service_access_id"]
        assert first["public_call_code"] != second["public_call_code"]

        first_msg = room.receive_json()
        second_msg = room.receive_json()

        assert first_msg["type"] == "call"
        assert second_msg["type"] == "call"
        # Each live message carries its own event's call code, in order; the
        # first event is not overwritten by the second (latest) call's data.
        assert first_msg["call"]["public_call_code"] == first["public_call_code"]
        assert second_msg["call"]["public_call_code"] == second["public_call_code"]
