from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from AZFlow.api import app
from AZFlow.api.v1.check_in import get_check_in_service
from AZFlow.application.check_in import CheckInService
from AZFlow.application.ports.appointment_source import ExternalAppointmentData
from AZFlow.application.ports.check_in_repository import (
    ResolvedAgenda,
    ResolvedQueue,
)
from AZFlow.domain.agenda import Agenda, ExternalAgenda
from AZFlow.domain.external_source import ExternalSource
from AZFlow.domain.patient_identifier import FISCAL_CODE
from AZFlow.domain.ticket_master import TicketMaster
from tests.application.fakes import FakeCheckInRepository, ListAppointmentSource

_SOURCE_CODE = "MOCK"
_AGENDA_REFERENCE = "AGENDA-A"
_KNOWN_VALUE = "RSSMRA80A01H501U"


def _resolution() -> ResolvedAgenda:
    agenda = Agenda(id=1, name="Agenda 1")
    source = ExternalSource(id=1, code=_SOURCE_CODE, name="Mock", connector_type="mock")
    external_agenda = ExternalAgenda(
        agenda=agenda, source=source, external_reference=_AGENDA_REFERENCE
    )
    return ResolvedAgenda(
        external_agenda=external_agenda,
        agenda=agenda,
        active_queues=[
            ResolvedQueue(queue_id=1, ticket_master=TicketMaster(id=1, prefix="AAA"))
        ],
    )


def _service_with_appointment() -> CheckInService:
    """A CheckInService whose source always returns one relevant appointment."""
    resolutions = {(_SOURCE_CODE, _AGENDA_REFERENCE): _resolution()}
    repository = FakeCheckInRepository(resolutions)
    source = ListAppointmentSource(
        [
            ExternalAppointmentData(
                external_source_code=_SOURCE_CODE,
                scheduled_at=datetime(2024, 5, 20, 9, 0),
                external_agenda_reference=_AGENDA_REFERENCE,
                external_appointment_reference="APPT-1",
            )
        ]
    )
    return CheckInService([source], repository)


def _service_without_appointment() -> CheckInService:
    """A CheckInService whose source returns nothing relevant."""
    repository = FakeCheckInRepository({})
    source = ListAppointmentSource([])
    return CheckInService([source], repository)


_AGENDA_REFERENCE_B = "AGENDA-B"


def _resolution_for(agenda_id: int, reference: str) -> ResolvedAgenda:
    agenda = Agenda(id=agenda_id, name=f"Agenda {agenda_id}")
    source = ExternalSource(id=1, code=_SOURCE_CODE, name="Mock", connector_type="mock")
    external_agenda = ExternalAgenda(
        agenda=agenda, source=source, external_reference=reference
    )
    return ResolvedAgenda(
        external_agenda=external_agenda,
        agenda=agenda,
        active_queues=[
            ResolvedQueue(queue_id=1, ticket_master=TicketMaster(id=1, prefix="AAA"))
        ],
    )


def _service_with_two_appointments() -> FakeCheckInRepository:
    """Return a repository seeded so the API success path imports two
    appointments on two agendas, and wire it into an overridden service."""
    resolutions = {
        (_SOURCE_CODE, _AGENDA_REFERENCE): _resolution_for(1, _AGENDA_REFERENCE),
        (_SOURCE_CODE, _AGENDA_REFERENCE_B): _resolution_for(2, _AGENDA_REFERENCE_B),
    }
    repository = FakeCheckInRepository(resolutions)
    source = ListAppointmentSource(
        [
            ExternalAppointmentData(
                external_source_code=_SOURCE_CODE,
                scheduled_at=datetime(2024, 5, 20, 9, 0),
                external_agenda_reference=_AGENDA_REFERENCE,
                external_appointment_reference="APPT-1",
            ),
            ExternalAppointmentData(
                external_source_code=_SOURCE_CODE,
                scheduled_at=datetime(2024, 5, 20, 10, 0),
                external_agenda_reference=_AGENDA_REFERENCE_B,
                external_appointment_reference="APPT-2",
            ),
        ]
    )
    _override(CheckInService([source], repository))
    return repository


@pytest.fixture
def client():
    test_client = TestClient(app)
    yield test_client
    app.dependency_overrides.clear()


def _override(service: CheckInService) -> None:
    app.dependency_overrides[get_check_in_service] = lambda: service


def test_successful_check_in_returns_2xx_and_only_public_call_code(client):
    _override(_service_with_appointment())

    response = client.post(
        "/api/v1/check-ins",
        json={"identifier_type": FISCAL_CODE, "identifier_value": _KNOWN_VALUE},
    )

    assert 200 <= response.status_code < 300
    body = response.json()
    assert list(body.keys()) == ["public_call_code"]
    assert body["public_call_code"] == "AAA001"


def test_public_call_code_does_not_contain_submitted_identifier(client):
    _override(_service_with_appointment())

    response = client.post(
        "/api/v1/check-ins",
        json={"identifier_type": FISCAL_CODE, "identifier_value": _KNOWN_VALUE},
    )

    assert response.status_code == 200
    assert _KNOWN_VALUE not in response.json()["public_call_code"]


def test_unsupported_identifier_type_returns_4xx_with_description(client):
    _override(_service_with_appointment())

    response = client.post(
        "/api/v1/check-ins",
        json={"identifier_type": "passport", "identifier_value": _KNOWN_VALUE},
    )

    assert 400 <= response.status_code < 500
    detail = response.json()["detail"]
    assert "unsupported" in detail
    assert "passport" in detail
    # The submitted value must not leak into the error message.
    assert _KNOWN_VALUE not in detail


def test_empty_identifier_value_returns_4xx(client):
    _override(_service_with_appointment())

    response = client.post(
        "/api/v1/check-ins",
        json={"identifier_type": FISCAL_CODE, "identifier_value": ""},
    )

    assert 400 <= response.status_code < 500


def test_missing_identifier_value_returns_4xx(client):
    _override(_service_with_appointment())

    response = client.post(
        "/api/v1/check-ins",
        json={"identifier_type": FISCAL_CODE},
    )

    assert 400 <= response.status_code < 500


def test_no_relevant_service_returns_4xx_indicating_no_service(client):
    _override(_service_without_appointment())

    response = client.post(
        "/api/v1/check-ins",
        json={"identifier_type": FISCAL_CODE, "identifier_value": _KNOWN_VALUE},
    )

    assert 400 <= response.status_code < 500
    assert "no service" in response.json()["detail"]


def test_success_path_creates_two_service_accesses_sharing_one_code(client):
    """End-to-end through the API without PostgreSQL: two appointments on two
    agendas produce two ServiceAccesses that share one public call code."""
    repository = _service_with_two_appointments()

    response = client.post(
        "/api/v1/check-ins",
        json={"identifier_type": FISCAL_CODE, "identifier_value": _KNOWN_VALUE},
    )

    assert response.status_code == 200
    assert response.json()["public_call_code"] == "AAA001"

    accesses = repository.service_accesses()
    assert len(accesses) == 2
    assert {access.agenda.id for access in accesses} == {1, 2}
    # A single DailyPresence (one shared public call code) backs both accesses.
    assert {access.daily_presence.public_call_code for access in accesses} == {"AAA001"}
    assert repository.created_daily_presences == 1


def test_check_in_route_is_version_prefixed():
    paths = [
        route.path
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/check-ins"
    ]

    assert paths == ["/api/v1/check-ins"]
