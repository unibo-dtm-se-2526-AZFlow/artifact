from typing import List, Optional, Tuple

import pytest
from fastapi.testclient import TestClient

from AZFlow.api import app
from AZFlow.api.v1.calling import get_calling_service
from AZFlow.application.calling import CallResult
from AZFlow.application.errors import (
    ApplicationError,
    MissingPublicCallCodeError,
    MissingRoomReferenceError,
    NoPatientToCallError,
    QueueInactiveError,
    QueueNotFoundError,
    ServiceAccessNotCallableError,
    ServiceAccessNotVisibleError,
)
from AZFlow.domain.agenda import Agenda
from AZFlow.domain.service_access import ServiceAccessState

_AGENDA = Agenda(id=3, name="Cardiology")


def _result(room_reference: str = "ROOM-3") -> CallResult:
    """A non-identifying successful call result."""
    return CallResult(
        public_call_code="AAA001",
        service_access_id=12,
        agenda=_AGENDA,
        state=ServiceAccessState.CALLED,
        room_reference=room_reference,
    )


class FakeCallingService:
    """CallingService substitute driven by tests.

    Each method returns a fixed CallResult (built from the room reference it
    receives, so pass-through can be checked) or raises a configured error.
    It records every call so tests can assert the arguments and that a route
    never reached the service.
    """

    def __init__(
        self,
        error: Optional[ApplicationError] = None,
    ) -> None:
        self._error = error
        self.next_calls: List[Tuple[int, str]] = []
        self.specific_calls: List[Tuple[int, int, str]] = []

    def call_next(self, queue_id: int, room_reference: str) -> CallResult:
        self.next_calls.append((queue_id, room_reference))
        if self._error is not None:
            raise self._error
        return _result(room_reference)

    def call_specific(
        self,
        queue_id: int,
        service_access_id: int,
        room_reference: str,
    ) -> CallResult:
        self.specific_calls.append((queue_id, service_access_id, room_reference))
        if self._error is not None:
            raise self._error
        return _result(room_reference)


@pytest.fixture
def client():
    test_client = TestClient(app)
    yield test_client
    app.dependency_overrides.clear()


def _override(service: FakeCallingService) -> None:
    app.dependency_overrides[get_calling_service] = lambda: service


_NEXT_PATH = "/api/v1/queues/1/calls/next"
_SPECIFIC_PATH = "/api/v1/queues/1/service-accesses/12/call"


# --- Success paths ---------------------------------------------------------


def test_call_next_success_returns_2xx_and_non_identifying_shape(client):
    service = FakeCallingService()
    _override(service)

    response = client.post(_NEXT_PATH, json={"room_reference": "ROOM-3"})

    assert 200 <= response.status_code < 300
    body = response.json()
    assert body["public_call_code"] == "AAA001"
    assert body["service_access_id"] == 12
    assert body["agenda"] == {"id": 3, "name": "Cardiology"}
    assert body["state"] == "CALLED"
    assert body["room_reference"] == "ROOM-3"


def test_call_specific_success_returns_2xx_and_non_identifying_shape(client):
    service = FakeCallingService()
    _override(service)

    response = client.post(_SPECIFIC_PATH, json={"room_reference": "ROOM-3"})

    assert 200 <= response.status_code < 300
    body = response.json()
    assert body["public_call_code"] == "AAA001"
    assert body["service_access_id"] == 12
    assert body["agenda"] == {"id": 3, "name": "Cardiology"}
    assert body["state"] == "CALLED"
    assert body["room_reference"] == "ROOM-3"


def test_call_next_carries_room_reference_into_the_service(client):
    service = FakeCallingService()
    _override(service)

    response = client.post(_NEXT_PATH, json={"room_reference": "ROOM-7"})

    assert response.status_code == 200
    assert service.next_calls == [(1, "ROOM-7")]
    assert response.json()["room_reference"] == "ROOM-7"


def test_call_specific_carries_room_reference_into_the_service(client):
    service = FakeCallingService()
    _override(service)

    response = client.post(_SPECIFIC_PATH, json={"room_reference": "ROOM-7"})

    assert response.status_code == 200
    assert service.specific_calls == [(1, 12, "ROOM-7")]
    assert response.json()["room_reference"] == "ROOM-7"


# --- Privacy ---------------------------------------------------------------


def test_success_response_exposes_only_the_closed_non_identifying_fields(client):
    service = FakeCallingService()
    _override(service)

    response = client.post(_NEXT_PATH, json={"room_reference": "ROOM-3"})

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {
        "public_call_code",
        "service_access_id",
        "agenda",
        "state",
        "room_reference",
    }
    assert set(body["agenda"].keys()) == {"id", "name"}
    # No identifying Patient data can reach the response.
    text = response.text
    assert "patient" not in text
    assert "identifier" not in text


# --- call_next failure mapping --------------------------------------------


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (MissingRoomReferenceError(), 422),
        (QueueNotFoundError(1), 404),
        (QueueInactiveError(1), 409),
        (NoPatientToCallError(1), 409),
        (MissingPublicCallCodeError(12), 500),
    ],
)
def test_call_next_error_maps_to_distinguishable_status(client, error, expected_status):
    _override(FakeCallingService(error=error))

    response = client.post(_NEXT_PATH, json={"room_reference": "ROOM-3"})

    assert response.status_code == expected_status
    # Error responses carry only a generic detail string, no identifying data.
    detail = response.json()["detail"]
    assert isinstance(detail, str)


def test_call_next_not_found_queue_and_inactive_queue_are_distinct(client):
    _override(FakeCallingService(error=QueueNotFoundError(1)))
    not_found = client.post(_NEXT_PATH, json={"room_reference": "ROOM-3"})
    app.dependency_overrides.clear()

    _override(FakeCallingService(error=QueueInactiveError(1)))
    inactive = client.post(_NEXT_PATH, json={"room_reference": "ROOM-3"})

    assert not_found.status_code == 404
    assert inactive.status_code == 409
    assert not_found.status_code != inactive.status_code


def test_call_next_no_patient_is_distinct_from_not_found_queue(client):
    _override(FakeCallingService(error=NoPatientToCallError(1)))
    no_patient = client.post(_NEXT_PATH, json={"room_reference": "ROOM-3"})
    app.dependency_overrides.clear()

    _override(FakeCallingService(error=QueueNotFoundError(1)))
    not_found = client.post(_NEXT_PATH, json={"room_reference": "ROOM-3"})

    assert no_patient.status_code == 409
    assert not_found.status_code == 404
    assert no_patient.status_code != not_found.status_code


# --- call_specific failure mapping ----------------------------------------


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (MissingRoomReferenceError(), 422),
        (QueueNotFoundError(1), 404),
        (QueueInactiveError(1), 409),
        (ServiceAccessNotVisibleError(12), 404),
        (ServiceAccessNotCallableError(12), 409),
        (MissingPublicCallCodeError(12), 500),
    ],
)
def test_call_specific_error_maps_to_distinguishable_status(
    client, error, expected_status
):
    _override(FakeCallingService(error=error))

    response = client.post(_SPECIFIC_PATH, json={"room_reference": "ROOM-3"})

    assert response.status_code == expected_status
    detail = response.json()["detail"]
    assert isinstance(detail, str)


def test_call_specific_not_visible_is_distinct_from_not_callable(client):
    _override(FakeCallingService(error=ServiceAccessNotVisibleError(12)))
    not_visible = client.post(_SPECIFIC_PATH, json={"room_reference": "ROOM-3"})
    app.dependency_overrides.clear()

    _override(FakeCallingService(error=ServiceAccessNotCallableError(12)))
    not_callable = client.post(_SPECIFIC_PATH, json={"room_reference": "ROOM-3"})

    assert not_visible.status_code == 404
    assert not_callable.status_code == 409
    assert not_visible.status_code != not_callable.status_code


# --- Path id validation ----------------------------------------------------


@pytest.mark.parametrize("queue_id", ["0", "-1", "abc"])
def test_call_next_invalid_queue_id_is_client_error_before_service(client, queue_id):
    service = FakeCallingService()
    _override(service)

    response = client.post(
        f"/api/v1/queues/{queue_id}/calls/next",
        json={"room_reference": "ROOM-3"},
    )

    assert response.status_code == 422
    # Path validation rejects the id, so the service is never reached.
    assert service.next_calls == []


@pytest.mark.parametrize(
    ("queue_id", "service_access_id"),
    [("0", "12"), ("1", "0"), ("1", "-1"), ("abc", "12"), ("1", "abc")],
)
def test_call_specific_invalid_path_id_is_client_error_before_service(
    client, queue_id, service_access_id
):
    service = FakeCallingService()
    _override(service)

    response = client.post(
        f"/api/v1/queues/{queue_id}/service-accesses/{service_access_id}/call",
        json={"room_reference": "ROOM-3"},
    )

    assert response.status_code == 422
    assert service.specific_calls == []


# --- Versioned routes ------------------------------------------------------


def test_calling_routes_are_version_prefixed():
    paths = {getattr(route, "path", None) for route in app.routes}

    assert "/api/v1/queues/{queue_id}/calls/next" in paths
    assert (
        "/api/v1/queues/{queue_id}/service-accesses/{service_access_id}/call" in paths
    )
