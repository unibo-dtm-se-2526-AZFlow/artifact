from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from AZFlow.api import app
from AZFlow.api.v1.operator_queue_list import get_operator_queue_list_service
from AZFlow.application.operator_queue_list import OperatorQueueListService
from AZFlow.application.ports.queue_view_reader import CandidateServiceAccess
from AZFlow.domain.agenda import Agenda
from AZFlow.domain.queue import Queue, QueuePolicy, QueueStatus
from AZFlow.domain.service_access import ServiceAccessState
from AZFlow.domain.ticket_master import TicketMaster
from tests.application.fakes import FakeQueueViewReader

_AGENDA = Agenda(id=1, name="Cardiology")


@pytest.fixture
def client():
    test_client = TestClient(app)
    yield test_client
    app.dependency_overrides.clear()


def test_operator_list_exposes_waiting_and_suspended_state(client):
    queue = Queue(
        id=1,
        status=QueueStatus.ACTIVE,
        policy=QueuePolicy.BY_APPOINTMENT,
        ticket_master=TicketMaster(id=1, prefix="AAA"),
        agendas=[_AGENDA],
    )
    candidates = [
        CandidateServiceAccess(
            service_access_id=1,
            daily_presence_id=1,
            agenda=_AGENDA,
            state=ServiceAccessState.WAITING,
            public_call_code="AAA001",
            checked_in_at=datetime(2024, 5, 20, 8, 0),
            scheduled_at=datetime(2024, 5, 20, 9),
        ),
        CandidateServiceAccess(
            service_access_id=2,
            daily_presence_id=2,
            agenda=_AGENDA,
            state=ServiceAccessState.SUSPENDED,
            public_call_code="AAA002",
            checked_in_at=datetime(2024, 5, 20, 8, 0),
            scheduled_at=datetime(2024, 5, 20, 10),
        ),
    ]
    service = OperatorQueueListService(
        FakeQueueViewReader({queue.id: queue}, candidates)
    )
    app.dependency_overrides[get_operator_queue_list_service] = lambda: service

    response = client.get("/api/v1/queues/1/operator-list")

    assert response.status_code == 200
    assert [
        (entry["service_access_id"], entry["state"])
        for entry in response.json()["entries"]
    ] == [(1, "WAITING"), (2, "SUSPENDED")]
    assert response.json()["entries"][0]["checked_in_at"] == "2024-05-20T08:00:00"
    assert "patient" not in response.text.lower()


def test_existing_queue_view_contract_is_unchanged(client):
    paths = [route.path for route in app.routes]

    assert "/api/v1/queues/{queue_id}/service-accesses" in paths
    assert "/api/v1/queues/{queue_id}/operator-list" in paths
