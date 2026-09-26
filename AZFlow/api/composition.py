"""API dependencies

This module connects the API to the mock appointment source and PostgreSQL
adapters. A database connection is opened for each request and closed when
the request ends.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Callable, ContextManager, Iterator

from fastapi import FastAPI, HTTPException, status

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
from AZFlow.application.ports.call_event_publisher import CallEventPublisher
from AZFlow.application.ports.display_read_model import DisplayReadModel
from AZFlow.application.queue_view import QueueViewService
from AZFlow.application.state_management import StateManagementService
from AZFlow.infrastructure.appointment_sources.mock import MockAppointmentSource
from AZFlow.infrastructure.config import load_settings
from AZFlow.api.v1.ws_support import WebSocketDisplaySupport, set_ws_support
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
from AZFlow.infrastructure.persistence.postgres_operator_discovery_read_model import (
    PostgresOperatorDiscoveryReadModel,
)
from AZFlow.infrastructure.persistence.postgres_queue_view_reader import (
    PostgresQueueViewReader,
)
from AZFlow.infrastructure.persistence.postgres_state_transition_repository import (
    PostgresStateTransitionRepository,
)


def build_check_in_service_provider(
    database_url: object,
) -> Callable[[], Iterator[CheckInService]]:
    """Build the CheckInService dependency used for each request

    The mock appointment source is shared. Each request gets a new PostgreSQL
    connection. A missing database URL returns HTTP 503.
    """
    appointment_source = MockAppointmentSource()

    def provide_check_in_service() -> Iterator[CheckInService]:
        if not database_url:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="check-in service is not configured",
            )

        # Import here so application startup does not open a connection
        import psycopg

        with psycopg.connect(str(database_url)) as connection:
            repository = PostgresCheckInRepository(connection)
            yield CheckInService([appointment_source], repository)

    return provide_check_in_service


def wire_check_in(application: FastAPI) -> None:
    """Connect the Patient Check-In service to the FastAPI application

    Tests can replace this dependency with a fake service.
    """
    settings = load_settings()
    application.dependency_overrides[get_check_in_service] = (
        build_check_in_service_provider(settings.database_url)
    )


def build_queue_view_service_provider(
    database_url: object,
) -> Callable[[], Iterator[QueueViewService]]:
    """Build the QueueViewService dependency used for each request

    Each request gets a new PostgreSQL connection. A missing database URL
    returns HTTP 503.
    """

    def provide_queue_view_service() -> Iterator[QueueViewService]:
        if not database_url:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="queue view service is not configured",
            )

        # Import here so application startup does not open a connection
        import psycopg

        with psycopg.connect(str(database_url)) as connection:
            reader = PostgresQueueViewReader(connection)
            yield QueueViewService(reader)

    return provide_queue_view_service


def build_operator_discovery_read_model_provider(
    database_url: object,
) -> Callable[[], Iterator[PostgresOperatorDiscoveryReadModel]]:
    """Build the operator discovery dependency for each request."""

    def provide_operator_discovery_read_model() -> Iterator[
        PostgresOperatorDiscoveryReadModel
    ]:
        if not database_url:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="operator discovery read model is not configured",
            )

        import psycopg

        with psycopg.connect(str(database_url)) as connection:
            yield PostgresOperatorDiscoveryReadModel(connection)

    return provide_operator_discovery_read_model


def wire_operator_discovery(application: FastAPI) -> None:
    """Connect operator discovery to the FastAPI application."""
    settings = load_settings()
    application.dependency_overrides[get_operator_discovery_read_model] = (
        build_operator_discovery_read_model_provider(settings.database_url)
    )


def build_operator_queue_list_service_provider(
    database_url: object,
) -> Callable[[], Iterator[OperatorQueueListService]]:
    """Build the expanded operator LIST dependency for each request."""

    def provide_operator_queue_list_service() -> Iterator[OperatorQueueListService]:
        if not database_url:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="operator queue list service is not configured",
            )

        import psycopg

        with psycopg.connect(str(database_url)) as connection:
            reader = PostgresQueueViewReader(connection)
            yield OperatorQueueListService(reader)

    return provide_operator_queue_list_service


def wire_operator_queue_list(application: FastAPI) -> None:
    """Connect the expanded operator LIST to the FastAPI application."""
    settings = load_settings()
    application.dependency_overrides[get_operator_queue_list_service] = (
        build_operator_queue_list_service_provider(settings.database_url)
    )


def wire_queue_view(application: FastAPI) -> None:
    """Connect the Operator Queue View service to the FastAPI application

    Tests can replace this dependency with a fake service.
    """
    settings = load_settings()
    application.dependency_overrides[get_queue_view_service] = (
        build_queue_view_service_provider(settings.database_url)
    )


def build_display_read_model_provider(
    database_url: object,
    recent_calls_max: int,
) -> Callable[[], Iterator[DisplayReadModel]]:
    """Build the DisplayReadModel dependency used for each request

    Each request gets a new PostgreSQL connection. The recent-calls bound comes
    from configuration. A missing database URL returns HTTP 503.
    """

    def provide_display_read_model() -> Iterator[DisplayReadModel]:
        if not database_url:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="display read model is not configured",
            )

        # Import here so application startup does not open a connection
        import psycopg

        with psycopg.connect(str(database_url)) as connection:
            yield PostgresDisplayReadModel(connection, recent_calls_max)

    return provide_display_read_model


def wire_display_read_model(application: FastAPI) -> None:
    """Connect the display read model to the FastAPI application

    Tests can replace this dependency with a fake read model.
    """
    settings = load_settings()
    application.dependency_overrides[get_display_read_model] = (
        build_display_read_model_provider(
            settings.database_url, settings.display_recent_calls_max
        )
    )


def build_calling_service_provider(
    database_url: object,
    publisher: CallEventPublisher,
) -> Callable[[], Iterator[CallingService]]:
    """Build the CallingService dependency used for each request

    Each request gets a new PostgreSQL connection. The reader and the call
    repository share that connection. The publisher is shared across requests.
    A missing database URL returns HTTP 503.
    """

    def provide_calling_service() -> Iterator[CallingService]:
        if not database_url:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="calling service is not configured",
            )

        # Import here so application startup does not open a connection
        import psycopg

        with psycopg.connect(str(database_url)) as connection:
            reader = PostgresQueueViewReader(connection)
            call_repository = PostgresCallRepository(connection)
            yield CallingService(reader, call_repository, publisher)

    return provide_calling_service


def build_display_read_model_factory(
    database_url: object,
    recent_calls_max: int,
) -> Callable[[], ContextManager[DisplayReadModel]]:
    """Build a factory that opens a short-lived display read model.

    The WebSocket hub and endpoints call this on the request thread (hub) or on
    a worker thread via asyncio.to_thread (endpoints), so the psycopg work never
    runs on the event loop. Each call opens and closes its own connection.
    """

    @contextmanager
    def open_read_model() -> Iterator[DisplayReadModel]:
        if not database_url:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="display read model is not configured",
            )

        # Import here so application startup does not open a connection
        import psycopg

        with psycopg.connect(str(database_url)) as connection:
            yield PostgresDisplayReadModel(connection, recent_calls_max)

    return open_read_model


def wire_calling(application: FastAPI) -> None:
    """Connect the Patient Calling service to the FastAPI application

    The single publication seam fans out to the in-process publisher and the
    WebSocket hub through a CompositeCallEventPublisher. The calling service
    still receives a CallEventPublisher, so the core is unaware of WebSockets.
    The shared hub is stored on the application state and bound to the running
    event loop at startup. Tests can replace this dependency with a fake.
    """
    settings = load_settings()

    read_model_factory = build_display_read_model_factory(
        settings.database_url, settings.display_recent_calls_max
    )
    hub = WebSocketCallHub(read_model_factory)
    publisher = CompositeCallEventPublisher([InProcessCallEventPublisher(), hub])

    application.state.ws_call_hub = hub
    set_ws_support(application, WebSocketDisplaySupport(hub, read_model_factory))

    application.dependency_overrides[get_calling_service] = (
        build_calling_service_provider(settings.database_url, publisher)
    )


def build_state_management_service_provider(
    database_url: object,
) -> Callable[[], Iterator[StateManagementService]]:
    """Build the StateManagementService dependency used for each request

    Each request gets a new PostgreSQL connection. Suspend, restore and confirm
    admission publish no event, so no publisher is created. A missing database
    URL returns HTTP 503.
    """

    def provide_state_management_service() -> Iterator[StateManagementService]:
        if not database_url:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="state management service is not configured",
            )

        # Import here so application startup does not open a connection
        import psycopg

        with psycopg.connect(str(database_url)) as connection:
            repository = PostgresStateTransitionRepository(connection)
            yield StateManagementService(repository)

    return provide_state_management_service


def wire_state_management(application: FastAPI) -> None:
    """Connect the state-management service to the FastAPI application

    Tests can replace this dependency with a fake service.
    """
    settings = load_settings()
    application.dependency_overrides[get_state_management_service] = (
        build_state_management_service_provider(settings.database_url)
    )
