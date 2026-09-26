import pytest
from fastapi.testclient import TestClient

from AZFlow.api import app
from AZFlow.api.v1.operator_discovery import get_operator_discovery_read_model
from AZFlow.application.ports.operator_discovery_read_model import (
    OperatorQueue,
    OperatorRoom,
)
from AZFlow.domain.agenda import Agenda
from AZFlow.domain.queue import QueuePolicy, QueueStatus


class FakeOperatorDiscoveryReadModel:
    """Small fake used by operator discovery API tests."""

    def list_rooms(self):
        return [
            OperatorRoom(id=2, room_reference="ROOM-2", label="Room 2"),
            OperatorRoom(id=11, room_reference="ROOM-11", label="Room 11"),
        ]

    def list_queues(self):
        return [
            OperatorQueue(
                id=1,
                status=QueueStatus.ACTIVE,
                policy=QueuePolicy.BY_APPOINTMENT,
                agendas=[Agenda(id=1, name="Diagnostics")],
            ),
            OperatorQueue(
                id=99,
                status=QueueStatus.INACTIVE,
                policy=QueuePolicy.BY_ARRIVAL,
                agendas=[],
            ),
        ]


@pytest.fixture
def client():
    app.dependency_overrides[get_operator_discovery_read_model] = (
        lambda: FakeOperatorDiscoveryReadModel()
    )
    test_client = TestClient(app)
    yield test_client
    app.dependency_overrides.clear()


def test_list_rooms_exposes_operator_room_selector_data(client):
    response = client.get("/api/v1/rooms")

    assert response.status_code == 200
    assert response.json() == [
        {"id": 2, "room_reference": "ROOM-2", "label": "Room 2"},
        {"id": 11, "room_reference": "ROOM-11", "label": "Room 11"},
    ]


def test_list_queues_exposes_status_policy_and_agendas(client):
    response = client.get("/api/v1/queues")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": 1,
            "status": "ACTIVE",
            "policy": "BY_APPOINTMENT",
            "agendas": [{"id": 1, "name": "Diagnostics"}],
        },
        {
            "id": 99,
            "status": "INACTIVE",
            "policy": "BY_ARRIVAL",
            "agendas": [],
        },
    ]
