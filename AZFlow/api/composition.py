"""API dependencies

This module connects the API to the mock appointment source and PostgreSQL
adapters. A database connection is opened for each request and closed when
the request ends.
"""

from __future__ import annotations

from typing import Callable, Iterator

from fastapi import FastAPI, HTTPException, status

from AZFlow.api.v1.check_in import get_check_in_service
from AZFlow.api.v1.queue_view import get_queue_view_service
from AZFlow.application.check_in import CheckInService
from AZFlow.application.queue_view import QueueViewService
from AZFlow.infrastructure.appointment_sources.mock import MockAppointmentSource
from AZFlow.infrastructure.config import load_settings
from AZFlow.infrastructure.persistence.postgres_check_in_repository import (
    PostgresCheckInRepository,
)
from AZFlow.infrastructure.persistence.postgres_queue_view_reader import (
    PostgresQueueViewReader,
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


def wire_queue_view(application: FastAPI) -> None:
    """Connect the Operator Queue View service to the FastAPI application

    Tests can replace this dependency with a fake service.
    """
    settings = load_settings()
    application.dependency_overrides[get_queue_view_service] = (
        build_queue_view_service_provider(settings.database_url)
    )
