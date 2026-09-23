from typing import List, Optional, Tuple

import pytest
from fastapi.testclient import TestClient

from AZFlow.api import app
from AZFlow.api.v1.state_management import get_state_management_service
from AZFlow.application.errors import (
    ApplicationError,
    MissingRoomReferenceError,
    ServiceAccessNotAdmittableError,
    ServiceAccessNotFoundError,
    ServiceAccessNotRestorableError,
    ServiceAccessNotSuspendableError,
)
from AZFlow.application.state_management import StateChangeResult
from AZFlow.domain.agenda import Agenda
from AZFlow.domain.service_access import ServiceAccessState

_AGENDA = Agenda(id=3, name="Cardiology")


def _result(
    state: ServiceAccessState,
    room_reference: Optional[str] = None,
) -> StateChangeResult:
    """A non-identifying successful state-change result."""
    return StateChangeResult(
        public_call_code="AAA001",
        service_access_id=12,
        agenda=_AGENDA,
        state=state,
        room_reference=room_reference,
    )


class FakeStateManagementService:
    """StateManagementService substitute driven by tests.

    Each method returns a fixed StateChangeResult or raises a configured error.
    It records every call so tests can assert the arguments and that a route
    never reached the service.
    """

    def __init__(self, error: Optional[ApplicationError] = None) -> None:
        self._error = error
        self.suspend_calls: List[int] = []
        self.restore_calls: List[int] = []
        self.admission_calls: List[Tuple[int, str]] = []

    def suspend(self, service_access_id: int) -> StateChangeResult:
        self.suspend_calls.append(service_access_id)
        if self._error is not None:
            raise self._error
        return _result(ServiceAccessState.SUSPENDED)

    def restore(self, service_access_id: int) -> StateChangeResult:
        self.restore_calls.append(service_access_id)
        if self._error is not None:
            raise self._error
        return _result(ServiceAccessState.WAITING)

    def confirm_admission(
        self,
        service_access_id: int,
        room_reference: str,
    ) -> StateChangeResult:
        self.admission_calls.append((service_access_id, room_reference))
        if self._error is not None:
            raise self._error
        return _result(ServiceAccessState.ADMITTED, room_reference)


@pytest.fixture
def client():
    test_client = TestClient(app)
    yield test_client
    app.dependency_overrides.clear()


def _override(service: FakeStateManagementService) -> None:
    app.dependency_overrides[get_state_management_service] = lambda: service


_SUSPEND_PATH = "/api/v1/service-accesses/12/suspend"
_RESTORE_PATH = "/api/v1/service-accesses/12/restore"
_ADMISSION_PATH = "/api/v1/service-accesses/12/admission"


# --- Success paths ---------------------------------------------------------


def test_suspend_success_returns_2xx_and_non_identifying_shape(client):
    service = FakeStateManagementService()
    _override(service)

    response = client.post(_SUSPEND_PATH)

    assert 200 <= response.status_code < 300
    body = response.json()
    assert body["public_call_code"] == "AAA001"
    assert body["service_access_id"] == 12
    assert body["agenda"] == {"id": 3, "name": "Cardiology"}
    assert body["state"] == "SUSPENDED"
    # Suspend carries no Room reference.
    assert "room_reference" not in body
    assert service.suspend_calls == [12]


def test_restore_success_returns_2xx_and_non_identifying_shape(client):
    service = FakeStateManagementService()
    _override(service)

    response = client.post(_RESTORE_PATH)

    assert 200 <= response.status_code < 300
    body = response.json()
    assert body["public_call_code"] == "AAA001"
    assert body["service_access_id"] == 12
    assert body["agenda"] == {"id": 3, "name": "Cardiology"}
    assert body["state"] == "WAITING"
    # Restore carries no Room reference.
    assert "room_reference" not in body
    assert service.restore_calls == [12]


def test_admission_success_returns_2xx_with_state_and_room_reference(client):
    service = FakeStateManagementService()
    _override(service)

    response = client.post(_ADMISSION_PATH, json={"room_reference": "ROOM-3"})

    assert 200 <= response.status_code < 300
    body = response.json()
    assert body["public_call_code"] == "AAA001"
    assert body["service_access_id"] == 12
    assert body["agenda"] == {"id": 3, "name": "Cardiology"}
    assert body["state"] == "ADMITTED"
    # Admission carries the Room reference unchanged.
    assert body["room_reference"] == "ROOM-3"
    assert service.admission_calls == [(12, "ROOM-3")]


def test_admission_carries_room_reference_into_the_service(client):
    service = FakeStateManagementService()
    _override(service)

    response = client.post(_ADMISSION_PATH, json={"room_reference": "ROOM-7"})

    assert response.status_code == 200
    assert service.admission_calls == [(12, "ROOM-7")]
    assert response.json()["room_reference"] == "ROOM-7"


# --- Privacy ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "json_body", "expected_keys"),
    [
        (
            _SUSPEND_PATH,
            None,
            {"public_call_code", "service_access_id", "agenda", "state"},
        ),
        (
            _RESTORE_PATH,
            None,
            {"public_call_code", "service_access_id", "agenda", "state"},
        ),
        (
            _ADMISSION_PATH,
            {"room_reference": "ROOM-3"},
            {
                "public_call_code",
                "service_access_id",
                "agenda",
                "state",
                "room_reference",
            },
        ),
    ],
)
def test_success_response_exposes_only_closed_non_identifying_fields(
    client, path, json_body, expected_keys
):
    _override(FakeStateManagementService())

    response = client.post(path, json=json_body)

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == expected_keys
    assert set(body["agenda"].keys()) == {"id", "name"}
    # No identifying Patient data can reach the response.
    text = response.text
    assert "patient" not in text
    assert "identifier" not in text


# --- suspend failure mapping ----------------------------------------------


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (ServiceAccessNotFoundError(12), 404),
        (ServiceAccessNotSuspendableError(12), 409),
    ],
)
def test_suspend_error_maps_to_distinguishable_status(client, error, expected_status):
    _override(FakeStateManagementService(error=error))

    response = client.post(_SUSPEND_PATH)

    assert response.status_code == expected_status
    # Error responses carry only a generic detail string, no identifying data.
    detail = response.json()["detail"]
    assert isinstance(detail, str)


def test_suspend_not_found_is_distinct_from_not_suspendable(client):
    _override(FakeStateManagementService(error=ServiceAccessNotFoundError(12)))
    not_found = client.post(_SUSPEND_PATH)
    app.dependency_overrides.clear()

    _override(FakeStateManagementService(error=ServiceAccessNotSuspendableError(12)))
    not_suspendable = client.post(_SUSPEND_PATH)

    assert not_found.status_code == 404
    assert not_suspendable.status_code == 409
    assert not_found.status_code != not_suspendable.status_code


# --- restore failure mapping ----------------------------------------------


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (ServiceAccessNotFoundError(12), 404),
        (ServiceAccessNotRestorableError(12), 409),
    ],
)
def test_restore_error_maps_to_distinguishable_status(client, error, expected_status):
    _override(FakeStateManagementService(error=error))

    response = client.post(_RESTORE_PATH)

    assert response.status_code == expected_status
    detail = response.json()["detail"]
    assert isinstance(detail, str)


def test_restore_not_found_is_distinct_from_not_restorable(client):
    _override(FakeStateManagementService(error=ServiceAccessNotFoundError(12)))
    not_found = client.post(_RESTORE_PATH)
    app.dependency_overrides.clear()

    _override(FakeStateManagementService(error=ServiceAccessNotRestorableError(12)))
    not_restorable = client.post(_RESTORE_PATH)

    assert not_found.status_code == 404
    assert not_restorable.status_code == 409
    assert not_found.status_code != not_restorable.status_code


# --- admission failure mapping --------------------------------------------


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (MissingRoomReferenceError(), 422),
        (ServiceAccessNotFoundError(12), 404),
        (ServiceAccessNotAdmittableError(12), 409),
    ],
)
def test_admission_error_maps_to_distinguishable_status(client, error, expected_status):
    _override(FakeStateManagementService(error=error))

    response = client.post(_ADMISSION_PATH, json={"room_reference": "ROOM-3"})

    assert response.status_code == expected_status
    detail = response.json()["detail"]
    assert isinstance(detail, str)


def test_admission_missing_room_not_found_and_not_admittable_are_distinct(client):
    _override(FakeStateManagementService(error=MissingRoomReferenceError()))
    missing_room = client.post(_ADMISSION_PATH, json={"room_reference": "   "})
    app.dependency_overrides.clear()

    _override(FakeStateManagementService(error=ServiceAccessNotFoundError(12)))
    not_found = client.post(_ADMISSION_PATH, json={"room_reference": "ROOM-3"})
    app.dependency_overrides.clear()

    _override(FakeStateManagementService(error=ServiceAccessNotAdmittableError(12)))
    not_admittable = client.post(_ADMISSION_PATH, json={"room_reference": "ROOM-3"})

    assert missing_room.status_code == 422
    assert not_found.status_code == 404
    assert not_admittable.status_code == 409
    assert (
        len(
            {
                missing_room.status_code,
                not_found.status_code,
                not_admittable.status_code,
            }
        )
        == 3
    )


def test_admission_missing_body_is_client_error_before_service(client):
    service = FakeStateManagementService()
    _override(service)

    response = client.post(_ADMISSION_PATH)

    # A missing request body fails Pydantic validation, before the service.
    assert response.status_code == 422
    assert service.admission_calls == []


# --- Path id validation ----------------------------------------------------


@pytest.mark.parametrize("service_access_id", ["0", "-1", "abc"])
def test_suspend_invalid_path_id_is_client_error_before_service(
    client, service_access_id
):
    service = FakeStateManagementService()
    _override(service)

    response = client.post(f"/api/v1/service-accesses/{service_access_id}/suspend")

    assert response.status_code == 422
    # Path validation rejects the id, so the service is never reached.
    assert service.suspend_calls == []


@pytest.mark.parametrize("service_access_id", ["0", "-1", "abc"])
def test_restore_invalid_path_id_is_client_error_before_service(
    client, service_access_id
):
    service = FakeStateManagementService()
    _override(service)

    response = client.post(f"/api/v1/service-accesses/{service_access_id}/restore")

    assert response.status_code == 422
    assert service.restore_calls == []


@pytest.mark.parametrize("service_access_id", ["0", "-1", "abc"])
def test_admission_invalid_path_id_is_client_error_before_service(
    client, service_access_id
):
    service = FakeStateManagementService()
    _override(service)

    response = client.post(
        f"/api/v1/service-accesses/{service_access_id}/admission",
        json={"room_reference": "ROOM-3"},
    )

    assert response.status_code == 422
    assert service.admission_calls == []


# --- Versioned routes ------------------------------------------------------


def test_state_management_routes_are_version_prefixed():
    paths = {getattr(route, "path", None) for route in app.routes}

    assert "/api/v1/service-accesses/{service_access_id}/suspend" in paths
    assert "/api/v1/service-accesses/{service_access_id}/restore" in paths
    assert "/api/v1/service-accesses/{service_access_id}/admission" in paths
