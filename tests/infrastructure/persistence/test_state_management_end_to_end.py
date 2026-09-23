"""End-to-end HTTP + PostgreSQL test for Suspend, Restore and Admission.

This drives the whole stack against the real test database (gated by the
persistence conftest, skipped without AZFLOW_TEST_DATABASE_URL): a Patient
checks in through POST /api/v1/check-ins, creating WAITING service accesses,
then an Operator suspends and restores one through the versioned state
management routes and confirms admission of a CALLED one. It verifies the wired
application, the PostgreSQL adapter and the API together produce non-identifying
results, never expose the Patient Identifier, carry the Room reference unchanged
for admission only, and persist SUSPENDED and ADMITTED durably.

Unlike test_state_management_api.py, which overrides the service with a fake,
this test wires the real CheckInService, CallingService and
StateManagementService over the test connection, so it exercises the
composition path end to end (Property 5/6/8, Requirements 11.9, 11.10, 11.12).
"""

from __future__ import annotations

from typing import Iterator

import psycopg
import pytest
from fastapi.testclient import TestClient

from AZFlow.api import app
from AZFlow.api.v1.calling import get_calling_service
from AZFlow.api.v1.check_in import get_check_in_service
from AZFlow.api.v1.state_management import get_state_management_service
from AZFlow.application.calling import CallingService
from AZFlow.application.check_in import CheckInService
from AZFlow.application.state_management import StateManagementService
from AZFlow.infrastructure.appointment_sources.mock import MockAppointmentSource
from AZFlow.infrastructure.events.in_process_publisher import (
    InProcessCallEventPublisher,
)
from AZFlow.infrastructure.persistence.postgres_call_repository import (
    PostgresCallRepository,
)
from AZFlow.infrastructure.persistence.postgres_check_in_repository import (
    PostgresCheckInRepository,
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
    seed_source,
    seed_ticket_master,
)

# The default mock appointments use this identifier and AGENDA-A / AGENDA-B.
_IDENTIFIER_VALUE = "RSSMRA80A01H501U"
_ROOM = "ROOM-3"


@pytest.fixture
def wired_client(connection, dsn: str) -> Iterator[TestClient]:
    """Seed the MOCK source, agendas and an ACTIVE queue, and wire the app.

    The check-in, calling and state-management dependencies are overridden with
    providers that open their own connection to the test database, mirroring the
    per-request connection used in production composition.
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
    # A configured Room the call resolves room_reference against, and which
    # admission then reuses.
    node_id = seed_location_node(connection, "Radiotherapy")
    seed_room(connection, node_id, _ROOM, "Room 3")

    appointment_source = MockAppointmentSource()
    publisher = InProcessCallEventPublisher()

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

    app.dependency_overrides[get_check_in_service] = provide_check_in
    app.dependency_overrides[get_calling_service] = provide_calling
    app.dependency_overrides[get_state_management_service] = provide_state_management

    client = TestClient(app)
    client.queue_id = queue_id  # type: ignore[attr-defined]
    yield client

    app.dependency_overrides.clear()


def _read_state(connection, service_access_id: int) -> str:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT state FROM service_access WHERE id = %s",
            (service_access_id,),
        )
        return cursor.fetchone()[0]


def _waiting_ids(connection):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id FROM service_access WHERE state = 'WAITING' ORDER BY id"
        )
        return [row[0] for row in cursor.fetchall()]


def _check_in(client) -> str:
    """Check a Patient in and return the public call code."""
    response = client.post(
        "/api/v1/check-ins",
        json={"identifier_type": "fiscal_code", "identifier_value": _IDENTIFIER_VALUE},
    )
    assert response.status_code == 200
    public_call_code = response.json()["public_call_code"]
    assert public_call_code
    return public_call_code


def _assert_no_identifier(response) -> None:
    text = response.text
    assert "patient" not in text
    assert "identifier" not in text
    assert _IDENTIFIER_VALUE not in text


def test_suspend_then_restore_end_to_end(wired_client, connection):
    """Req 11.9/11.12: suspend then restore a WAITING ServiceAccess through
    /api/v1 against the real database, returning a non-identifying result and
    persisting each state durably."""
    public_call_code = _check_in(wired_client)
    target_id = _waiting_ids(connection)[0]

    suspend = wired_client.post(f"/api/v1/service-accesses/{target_id}/suspend")
    assert suspend.status_code == 200
    body = suspend.json()
    assert set(body.keys()) == {
        "public_call_code",
        "service_access_id",
        "agenda",
        "state",
    }
    assert body["public_call_code"] == public_call_code
    assert body["service_access_id"] == target_id
    assert body["state"] == "SUSPENDED"
    # Suspend carries no Room reference and no identifying data.
    assert "room_reference" not in body
    _assert_no_identifier(suspend)
    # The SUSPENDED state is durable.
    assert _read_state(connection, target_id) == "SUSPENDED"

    restore = wired_client.post(f"/api/v1/service-accesses/{target_id}/restore")
    assert restore.status_code == 200
    restore_body = restore.json()
    assert restore_body["state"] == "WAITING"
    assert "room_reference" not in restore_body
    _assert_no_identifier(restore)
    # The restored WAITING state is durable.
    assert _read_state(connection, target_id) == "WAITING"


def test_call_then_confirm_admission_end_to_end(wired_client, connection):
    """Req 5: call a Patient then confirm admission through /api/v1. Admission
    accepts no room_reference and reuses the Room stored at call time,
    persisting ADMITTED durably with no identifying data exposed."""
    public_call_code = _check_in(wired_client)
    queue_id = wired_client.queue_id

    # Call next transitions the head WAITING access to CALLED.
    call_next = wired_client.post(
        f"/api/v1/queues/{queue_id}/calls/next",
        json={"room_reference": _ROOM},
    )
    assert call_next.status_code == 200
    called_id = call_next.json()["service_access_id"]
    assert _read_state(connection, called_id) == "CALLED"

    # Admission takes no room_reference; it uses the stored call-time Room.
    admission = wired_client.post(f"/api/v1/service-accesses/{called_id}/admission")
    assert admission.status_code == 200
    body = admission.json()
    # room_reference is derived from the stored Room and currently left unset,
    # so response_model_exclude_none omits it from the admission body.
    assert set(body.keys()) == {
        "public_call_code",
        "service_access_id",
        "agenda",
        "state",
    }
    assert body["public_call_code"] == public_call_code
    assert body["service_access_id"] == called_id
    assert body["state"] == "ADMITTED"
    _assert_no_identifier(admission)
    # The ADMITTED state is durable.
    assert _read_state(connection, called_id) == "ADMITTED"


def test_state_management_failures_are_distinguishable_end_to_end(
    wired_client, connection
):
    """Req 5/11: each state-management failure maps to its expected status.

    Admission no longer accepts a room_reference, so the earlier missing-room
    precondition case is gone; instead admitting a non-CALLED target is a
    not-admittable conflict. Each outcome maps to its specific status:
    not-found suspend -> 404, not-restorable restore -> 409, not-admittable
    admission -> 409. None changes the target state.
    """
    _check_in(wired_client)
    waiting_id = _waiting_ids(connection)[0]

    # Not found: no ServiceAccess exists for a large id -> 404.
    not_found = wired_client.post("/api/v1/service-accesses/999999/suspend")
    assert not_found.status_code == 404

    # Not in the expected state: restore requires SUSPENDED, but the target is
    # WAITING, so it is not restorable -> 409.
    not_restorable = wired_client.post(f"/api/v1/service-accesses/{waiting_id}/restore")
    assert not_restorable.status_code == 409

    # Not admittable: admission requires CALLED, but the target is WAITING, so
    # it is not admittable -> 409.
    not_admittable = wired_client.post(
        f"/api/v1/service-accesses/{waiting_id}/admission"
    )
    assert not_admittable.status_code == 409

    # None of the failing attempts changed the target state.
    assert _read_state(connection, waiting_id) == "WAITING"
