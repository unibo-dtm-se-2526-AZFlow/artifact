from datetime import date, datetime
from typing import List, Optional

import pytest
from fastapi.testclient import TestClient

from AZFlow.api import app
from AZFlow.api.v1.queue_view import get_queue_view_service
from AZFlow.application.ports.queue_view_reader import CandidateServiceAccess
from AZFlow.application.queue_view import QueueViewService
from AZFlow.domain.agenda import Agenda
from AZFlow.domain.queue import Queue, QueuePolicy, QueueStatus
from AZFlow.domain.service_access import ServiceAccessState
from AZFlow.domain.ticket_master import TicketMaster
from tests.application.fakes import (
    DayScopedFakeQueueViewReader,
    FakeQueueViewReader,
)

_TICKET_MASTER = TicketMaster(id=1, prefix="AAA")
_AGENDA_A = Agenda(id=1, name="Cardiology")
_AGENDA_B = Agenda(id=2, name="Radiology")


def _queue(
    queue_id: int,
    agendas: List[Agenda],
    policy: QueuePolicy = QueuePolicy.BY_ARRIVAL,
    status: QueueStatus = QueueStatus.ACTIVE,
) -> Queue:
    return Queue(
        id=queue_id,
        status=status,
        policy=policy,
        ticket_master=_TICKET_MASTER,
        agendas=list(agendas),
    )


def _candidate(
    service_access_id: int,
    daily_presence_id: int,
    agenda: Agenda,
    public_call_code: str = "AAA001",
    scheduled_at: Optional[datetime] = None,
    state: ServiceAccessState = ServiceAccessState.WAITING,
    checked_in_at: datetime = datetime(2024, 5, 20, 8, 0),
) -> CandidateServiceAccess:
    return CandidateServiceAccess(
        service_access_id=service_access_id,
        daily_presence_id=daily_presence_id,
        agenda=agenda,
        state=state,
        public_call_code=public_call_code,
        checked_in_at=checked_in_at,
        scheduled_at=scheduled_at,
    )


@pytest.fixture
def client():
    test_client = TestClient(app)
    yield test_client
    app.dependency_overrides.clear()


def _override(service: QueueViewService) -> None:
    app.dependency_overrides[get_queue_view_service] = lambda: service


def _service(
    queue: Queue, candidates: List[CandidateServiceAccess]
) -> QueueViewService:
    reader = FakeQueueViewReader({queue.id: queue}, candidates)
    return QueueViewService(reader)


class _RejectingReader:
    """QueueViewReader fake that fails if the handler ever reaches it.

    Used to check that path validation rejects a bad id before the service.
    """

    def __init__(self) -> None:
        self.load_queue_calls: List[int] = []

    def load_queue(self, queue_id: int):  # pragma: no cover - must not be called
        self.load_queue_calls.append(queue_id)
        raise AssertionError("service reached with invalid id")

    def list_service_accesses(self, agenda_ids, operational_day):
        raise AssertionError("service reached with invalid id")


def test_successful_view_returns_2xx_with_ordered_entries(client):
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_ARRIVAL)
    candidates = [
        _candidate(50, 3, _AGENDA_A, "AAA003"),
        _candidate(40, 1, _AGENDA_A, "AAA001"),
        _candidate(45, 2, _AGENDA_A, "AAA002"),
    ]
    _override(_service(queue, candidates))

    response = client.get("/api/v1/queues/1/service-accesses")

    assert 200 <= response.status_code < 300
    body = response.json()
    assert body["queue_id"] == 1
    assert body["policy"] == "BY_ARRIVAL"
    assert [entry["service_access_id"] for entry in body["entries"]] == [40, 45, 50]


def test_by_appointment_ordering_is_exposed_through_the_api(client):
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_APPOINTMENT)
    candidates = [
        _candidate(30, 1, _AGENDA_A, "AAA003", scheduled_at=None),
        _candidate(10, 2, _AGENDA_A, "AAA001", datetime(2024, 5, 20, 10, 0)),
        _candidate(5, 3, _AGENDA_A, "AAA004", datetime(2024, 5, 20, 9, 0)),
    ]
    _override(_service(queue, candidates))

    response = client.get("/api/v1/queues/1/service-accesses")

    assert response.status_code == 200
    body = response.json()
    assert body["policy"] == "BY_APPOINTMENT"
    assert [entry["service_access_id"] for entry in body["entries"]] == [5, 10, 30]


def test_entry_exposes_only_the_closed_non_identifying_field_set(client):
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_APPOINTMENT)
    candidates = [
        _candidate(10, 1, _AGENDA_A, "AAA001", datetime(2024, 5, 20, 9, 0)),
    ]
    _override(_service(queue, candidates))

    response = client.get("/api/v1/queues/1/service-accesses")

    assert response.status_code == 200
    entry = response.json()["entries"][0]
    assert set(entry.keys()) == {
        "service_access_id",
        "public_call_code",
        "agenda",
        "scheduled_at",
    }
    assert set(entry["agenda"].keys()) == {"id", "name"}


def test_response_never_contains_patient_identifier(client):
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_ARRIVAL)
    candidates = [_candidate(10, 1, _AGENDA_A, "AAA001")]
    _override(_service(queue, candidates))

    response = client.get("/api/v1/queues/1/service-accesses")

    assert response.status_code == 200
    # CandidateServiceAccess carries no identifier, so the closed field set is
    # the guarantee: no identifier type/value can reach the response.
    body = response.text
    assert "fiscal_code" not in body
    assert "identifier" not in body
    assert "patient" not in body


def test_not_found_queue_returns_404(client):
    reader = FakeQueueViewReader({}, [])
    _override(QueueViewService(reader))

    response = client.get("/api/v1/queues/99/service-accesses")

    assert response.status_code == 404
    assert response.json()["detail"] == "queue not found"


def test_inactive_queue_returns_409_distinct_from_404(client):
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_ARRIVAL, QueueStatus.INACTIVE)
    _override(_service(queue, []))

    response = client.get("/api/v1/queues/1/service-accesses")

    assert response.status_code == 409
    assert response.status_code != 404
    assert response.json()["detail"] == "queue is not active"


@pytest.mark.parametrize("queue_id", ["0", "-1", "abc"])
def test_invalid_or_non_positive_id_returns_422_before_service(client, queue_id):
    # The reader would raise if the handler ever queried it with a bad id.
    reader = _RejectingReader()
    _override(QueueViewService(reader))

    response = client.get(f"/api/v1/queues/{queue_id}/service-accesses")

    assert response.status_code == 422
    # Path validation rejects the id, so the handler never reads the reader.
    assert reader.load_queue_calls == []


def test_missing_public_call_code_returns_500_generic_detail(client):
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_ARRIVAL)
    candidates = [_candidate(10, 1, _AGENDA_A, public_call_code="")]
    _override(_service(queue, candidates))

    response = client.get("/api/v1/queues/1/service-accesses")

    assert response.status_code == 500
    detail = response.json()["detail"]
    assert detail == "queue view entry cannot be represented"


def test_empty_view_returns_2xx_with_no_entries(client):
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_ARRIVAL)
    _override(_service(queue, []))

    response = client.get("/api/v1/queues/1/service-accesses")

    assert response.status_code == 200
    assert response.json()["entries"] == []


def test_queue_view_shows_only_current_operational_day(client):
    # The route passes no day, so the service must resolve today's day and the
    # reader must only return today's candidates end-to-end.
    queue = _queue(1, [_AGENDA_A], QueuePolicy.BY_ARRIVAL)
    other_day = date(2000, 1, 1)
    reader = DayScopedFakeQueueViewReader(
        {queue.id: queue},
        {
            date.today(): [_candidate(10, 1, _AGENDA_A, "AAA001")],
            other_day: [_candidate(20, 2, _AGENDA_A, "AAA002")],
        },
    )
    _override(QueueViewService(reader))

    response = client.get("/api/v1/queues/1/service-accesses")

    assert response.status_code == 200
    body = response.json()
    assert [entry["service_access_id"] for entry in body["entries"]] == [10]
    # The service resolved and used today's operational day.
    assert reader.list_calls[0][1] == date.today()


def test_queue_view_route_is_version_prefixed():
    paths = [
        route.path
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/queues/{queue_id}/service-accesses"
    ]

    assert paths == ["/api/v1/queues/{queue_id}/service-accesses"]
