"""Composition-root tests for the real FastAPI wiring.

These tests do not repeat endpoint behaviour. They verify that production
providers build the expected concrete adapters and that ``create_app`` installs
the complete dependency graph without opening a database connection at startup.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Callable, Iterator, cast

import psycopg
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import AZFlow.api.composition as composition
from AZFlow.api import create_app
from AZFlow.api.v1.calling import get_calling_service
from AZFlow.api.v1.check_in import get_check_in_service
from AZFlow.api.v1.displays import get_display_read_model
from AZFlow.api.v1.operator_discovery import get_operator_discovery_read_model
from AZFlow.api.v1.operator_queue_list import get_operator_queue_list_service
from AZFlow.api.v1.queue_view import get_queue_view_service
from AZFlow.api.v1.state_management import get_state_management_service
from AZFlow.application.calling import CallingService
from AZFlow.application.check_in import CheckInService
from AZFlow.application.operator_queue_list import OperatorQueueListService
from AZFlow.application.queue_view import QueueViewService
from AZFlow.application.state_management import StateManagementService
from AZFlow.infrastructure.appointment_sources.demo import DemoAppointmentSource
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
from AZFlow.infrastructure.persistence.postgres_operator_discovery_read_model import (
    PostgresOperatorDiscoveryReadModel,
)
from AZFlow.infrastructure.persistence.postgres_queue_view_reader import (
    PostgresQueueViewReader,
)
from AZFlow.infrastructure.persistence.postgres_state_transition_repository import (
    PostgresStateTransitionRepository,
)


class _Connection:
    """Minimal connection object needed while concrete adapters are constructed."""

    autocommit = True


class _ConnectionContext:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    def __enter__(self) -> _Connection:
        return self.connection

    def __exit__(self, *_args: object) -> None:
        return None


@pytest.fixture
def fake_database(monkeypatch: pytest.MonkeyPatch) -> tuple[_Connection, list[str]]:
    connection = _Connection()
    urls: list[str] = []

    def connect(url: str) -> _ConnectionContext:
        urls.append(url)
        return _ConnectionContext(connection)

    monkeypatch.setattr(psycopg, "connect", connect)
    return connection, urls


def _next_and_close(provider: Callable[[], Iterator[Any]]) -> Any:
    dependency = provider()
    value = next(dependency)
    cast(Any, dependency).close()
    return value


def test_providers_build_the_real_application_graph(fake_database) -> None:
    connection, urls = fake_database
    database_url = "postgresql://azflow:test@localhost/azflow_test"
    publisher: Any = object()
    display_publisher: Any = object()

    check_in = _next_and_close(
        composition.build_check_in_service_provider(
            database_url, [DemoAppointmentSource()]
        )
    )
    assert isinstance(check_in, CheckInService)
    assert isinstance(check_in._repository, PostgresCheckInRepository)
    assert check_in._repository._conn is connection
    assert len(check_in._appointment_sources) == 1
    assert isinstance(check_in._appointment_sources[0], DemoAppointmentSource)

    queue_view = _next_and_close(
        composition.build_queue_view_service_provider(database_url)
    )
    assert isinstance(queue_view, QueueViewService)
    assert isinstance(queue_view._reader, PostgresQueueViewReader)
    assert queue_view._reader._conn is connection

    operator_list = _next_and_close(
        composition.build_operator_queue_list_service_provider(database_url)
    )
    assert isinstance(operator_list, OperatorQueueListService)
    assert isinstance(operator_list._reader, PostgresQueueViewReader)
    assert operator_list._reader._conn is connection

    discovery = _next_and_close(
        composition.build_operator_discovery_read_model_provider(database_url)
    )
    assert isinstance(discovery, PostgresOperatorDiscoveryReadModel)
    assert discovery._conn is connection

    display = _next_and_close(
        composition.build_display_read_model_provider(database_url, 17)
    )
    assert isinstance(display, PostgresDisplayReadModel)
    assert display._conn is connection
    assert display._recent_calls_max == 17

    calling = _next_and_close(
        composition.build_calling_service_provider(database_url, publisher)
    )
    assert isinstance(calling, CallingService)
    assert isinstance(calling._reader, PostgresQueueViewReader)
    assert isinstance(calling._call_repository, PostgresCallRepository)
    assert calling._reader._conn is connection
    assert calling._call_repository._conn is connection
    assert calling._publisher is publisher

    state_management = _next_and_close(
        composition.build_state_management_service_provider(
            database_url, display_publisher
        )
    )
    assert isinstance(state_management, StateManagementService)
    assert isinstance(state_management._repository, PostgresStateTransitionRepository)
    assert state_management._repository._conn is connection
    assert state_management._display_publisher is display_publisher

    with composition.build_display_read_model_factory(database_url, 23)() as read_model:
        assert isinstance(read_model, PostgresDisplayReadModel)
        assert read_model._conn is connection
        assert read_model._recent_calls_max == 23

    assert urls == [database_url] * 8


@pytest.mark.parametrize(
    "make_dependency",
    [
        lambda: composition.build_check_in_service_provider(
            None, [DemoAppointmentSource()]
        )(),
        lambda: composition.build_queue_view_service_provider(None)(),
        lambda: composition.build_operator_queue_list_service_provider(None)(),
        lambda: composition.build_operator_discovery_read_model_provider(None)(),
        lambda: composition.build_display_read_model_provider(None, 10)(),
        lambda: composition.build_calling_service_provider(None, cast(Any, object()))(),
        lambda: composition.build_state_management_service_provider(
            None, cast(Any, object())
        )(),
    ],
)
def test_request_providers_fail_closed_without_database_url(make_dependency) -> None:
    dependency = make_dependency()
    with pytest.raises(HTTPException) as error:
        next(dependency)
    assert error.value.status_code == 503


def test_display_factory_fails_closed_without_database_url() -> None:
    factory = composition.build_display_read_model_factory(None, 10)
    with pytest.raises(HTTPException) as error, factory():
        pass
    assert error.value.status_code == 503


def test_no_appointment_sources_returns_503_without_opening_database(
    fake_database,
) -> None:
    _, urls = fake_database
    dependency = composition.build_check_in_service_provider("postgresql://unused")()
    with pytest.raises(HTTPException) as error:
        next(dependency)
    assert error.value.status_code == 503
    assert error.value.detail == "appointment source is not configured"
    assert urls == []


def test_resolve_appointment_sources() -> None:
    assert composition.resolve_appointment_sources(()) == []
    sources = composition.resolve_appointment_sources((" demo ",))
    assert len(sources) == 1
    assert isinstance(sources[0], DemoAppointmentSource)

    for value in (("unknown",), ("demo", "unknown"), ("demo", "DEMO")):
        with pytest.raises(ValueError):
            composition.resolve_appointment_sources(value)


def test_check_in_returns_503_when_source_is_not_selected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        composition,
        "load_settings",
        lambda: SimpleNamespace(
            database_url="postgresql://unused",
            appointment_sources=(),
            display_recent_calls_max=10,
        ),
    )
    application = create_app()
    with TestClient(application) as client:
        response = client.post(
            "/api/v1/check-ins",
            json={"identifier_type": "fiscal_code", "identifier_value": "DEMO031"},
        )
    assert response.status_code == 503
    assert response.json() == {"detail": "appointment source is not configured"}


def test_postgres_connection_failure_returns_503_without_startup_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        composition,
        "load_settings",
        lambda: SimpleNamespace(
            database_url="postgresql://unavailable",
            appointment_sources=("demo",),
            display_recent_calls_max=10,
        ),
    )

    def database_down(_url: str) -> None:
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr(psycopg, "connect", database_down)

    application = create_app()
    with TestClient(application) as client:
        health = client.get("/api/v1/health")
        response = client.post(
            "/api/v1/check-ins",
            json={"identifier_type": "fiscal_code", "identifier_value": "DEMO031"},
        )

    assert health.status_code == 200
    assert response.status_code == 503
    assert response.json() == {"detail": "database unavailable"}


def test_create_app_wires_all_production_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SimpleNamespace(
        database_url="postgresql://azflow:test@localhost/azflow_test",
        display_recent_calls_max=12,
        appointment_sources=("demo",),
    )
    monkeypatch.setattr(composition, "load_settings", lambda: settings)

    application = create_app()

    assert {
        get_check_in_service,
        get_queue_view_service,
        get_operator_queue_list_service,
        get_operator_discovery_read_model,
        get_calling_service,
        get_state_management_service,
        get_display_read_model,
    }.issubset(application.dependency_overrides)

    hub = application.state.ws_call_hub
    support = application.state.ws_display_support
    assert isinstance(hub, WebSocketCallHub)
    assert support.hub is hub
    assert hub._loop is None

    with TestClient(application):
        assert hub._loop is not None
