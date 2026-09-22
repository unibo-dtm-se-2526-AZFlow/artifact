"""End-to-end HTTP + PostgreSQL test for Patient Calling.

This drives the whole stack against the real test database (gated by the
persistence conftest, skipped without AZFLOW_TEST_DATABASE_URL): a Patient
checks in through POST /api/v1/check-ins, which creates WAITING service
accesses, then an Operator calls next and calls a specific ServiceAccess
through the versioned calling routes. It verifies the wired application,
the PostgreSQL adapters and the API together produce a non-identifying
CALLED result and never expose the Patient Identifier.

Unlike test_calling_api.py, which overrides the service with a fake, this
test wires the real CheckInService, QueueViewService and CallingService over
the test connection, so it exercises the composition path end to end.
"""

from __future__ import annotations

from typing import Iterator

import psycopg
import pytest
from fastapi.testclient import TestClient

from AZFlow.api import app
from AZFlow.api.v1.calling import get_calling_service
from AZFlow.api.v1.check_in import get_check_in_service
from AZFlow.application.calling import CallingService
from AZFlow.application.check_in import CheckInService
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
from tests.infrastructure.persistence.seed import (
    seed_external_agenda,
    seed_queue,
    seed_source,
    seed_ticket_master,
)

# The default mock appointments use this identifier and AGENDA-A / AGENDA-B.
_IDENTIFIER_VALUE = "RSSMRA80A01H501U"
_ROOM = "ROOM-3"


@pytest.fixture
def wired_client(connection, dsn: str) -> Iterator[TestClient]:
    """Seed the MOCK source, agendas and an ACTIVE queue, and wire the app.

    The check-in, queue-view and calling dependencies are overridden with
    providers that open their own connection to the test database, mirroring
    the per-request connection used in production composition. The queue serves
    both mock agendas and orders BY_ARRIVAL so call next is deterministic.
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

    app.dependency_overrides[get_check_in_service] = provide_check_in
    app.dependency_overrides[get_calling_service] = provide_calling

    client = TestClient(app)
    client.queue_id = queue_id  # type: ignore[attr-defined]
    client.publisher = publisher  # type: ignore[attr-defined]
    yield client

    app.dependency_overrides.clear()


def _read_state(connection, service_access_id: int) -> str:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT state FROM service_access WHERE id = %s",
            (service_access_id,),
        )
        return cursor.fetchone()[0]


def _first_waiting(connection, exclude: int):
    """Return the id of a WAITING service access other than ``exclude``."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id FROM service_access "
            "WHERE state = 'WAITING' AND id <> %s ORDER BY id LIMIT 1",
            (exclude,),
        )
        row = cursor.fetchone()
    return row[0] if row is not None else None


def test_check_in_then_call_next_then_call_specific_end_to_end(
    wired_client, connection
):
    """Req 9.2/9.3, 10.10, 10.11: check in a Patient, then call next and a
    specific ServiceAccess through /api/v1 against the real database."""
    queue_id = wired_client.queue_id
    publisher = wired_client.publisher

    # The Patient checks in; the mock returns two appointments (AGENDA-A and
    # AGENDA-B), so two WAITING service accesses are created for today.
    check_in = wired_client.post(
        "/api/v1/check-ins",
        json={"identifier_type": "fiscal_code", "identifier_value": _IDENTIFIER_VALUE},
    )
    assert check_in.status_code == 200
    public_call_code = check_in.json()["public_call_code"]
    assert public_call_code

    # Call next: the wired stack transitions the head to CALLED and returns a
    # non-identifying result carrying the Room reference unchanged.
    call_next = wired_client.post(
        f"/api/v1/queues/{queue_id}/calls/next",
        json={"room_reference": _ROOM},
    )
    assert call_next.status_code == 200
    body = call_next.json()
    assert set(body.keys()) == {
        "public_call_code",
        "service_access_id",
        "agenda",
        "state",
        "room_reference",
    }
    assert body["public_call_code"] == public_call_code
    assert body["state"] == "CALLED"
    assert body["room_reference"] == _ROOM
    first_called_id = body["service_access_id"]

    # The transition is durable in the database.
    assert _read_state(connection, first_called_id) == "CALLED"

    # No identifying Patient data leaks into the response.
    text = call_next.text
    assert "patient" not in text
    assert _IDENTIFIER_VALUE not in text

    # The second WAITING access is still callable; find it in the database and
    # call it specifically.
    target_id = _first_waiting(connection, exclude=first_called_id)
    assert target_id is not None, "a second WAITING service access should remain"

    call_specific = wired_client.post(
        f"/api/v1/queues/{queue_id}/service-accesses/{target_id}/call",
        json={"room_reference": _ROOM},
    )
    assert call_specific.status_code == 200
    specific_body = call_specific.json()
    assert specific_body["service_access_id"] == target_id
    assert specific_body["state"] == "CALLED"
    assert specific_body["room_reference"] == _ROOM
    assert _read_state(connection, target_id) == "CALLED"

    # Exactly one event per successful call reached the publication boundary,
    # and no event carries the Patient Identifier value.
    assert len(publisher.events) == 2
    for event in publisher.events:
        assert event.room_reference == _ROOM
        assert _IDENTIFIER_VALUE not in event.public_call_code


def test_call_next_when_no_patient_waiting_returns_conflict(wired_client):
    """Req 10.6: with no check-in, call next reports the no-Patient outcome."""
    queue_id = wired_client.queue_id

    response = wired_client.post(
        f"/api/v1/queues/{queue_id}/calls/next",
        json={"room_reference": _ROOM},
    )

    assert response.status_code == 409
    assert wired_client.publisher.events == []
