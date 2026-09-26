"""Operator Queue View HTTP endpoint

This module maps a read-only queue view request to the application service and
turns application errors into HTTP responses. Responses and error messages
never include the patient identifier.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel

from AZFlow.application.errors import (
    MissingPublicCallCodeError,
    QueueInactiveError,
    QueueNotFoundError,
)
from AZFlow.application.queue_view import QueueView, QueueViewService

from AZFlow.api.v1.schemas import AgendaModel


router = APIRouter()



class QueueViewEntryModel(BaseModel):
    """One queue view entry, with no identifying Patient data"""

    service_access_id: int
    public_call_code: str
    agenda: AgendaModel
    scheduled_at: Optional[datetime] = None


class QueueViewResponse(BaseModel):
    """Ordered queue view for a Queue"""

    queue_id: int
    policy: str
    entries: List[QueueViewEntryModel]


def get_queue_view_service() -> QueueViewService:
    """Provide the QueueViewService used by the route

    The application setup and tests replace this dependency.
    """
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="queue view service is not configured",
    )


@router.get(
    "/queues/{queue_id}/service-accesses",
    response_model=QueueViewResponse,
    status_code=status.HTTP_200_OK,
)
def view_queue(
    queue_id: int = Path(..., gt=0),
    service: QueueViewService = Depends(get_queue_view_service),
) -> QueueViewResponse:
    """Return the ordered queue view for a Queue"""
    try:
        view = service.view(queue_id)
    except QueueNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="queue not found",
        ) from error
    except QueueInactiveError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="queue is not active",
        ) from error
    except MissingPublicCallCodeError as error:
        # Keep the message generic so no identifying data can leak.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="queue view entry cannot be represented",
        ) from error

    return _to_response(view)


def _to_response(view: QueueView) -> QueueViewResponse:
    """Map the application queue view to the response model."""
    return QueueViewResponse(
        queue_id=view.queue_id,
        policy=view.policy.value,
        entries=[
            QueueViewEntryModel(
                service_access_id=entry.service_access_id,
                public_call_code=entry.public_call_code,
                agenda=AgendaModel(id=entry.agenda.id, name=entry.agenda.name),
                scheduled_at=entry.scheduled_at,
            )
            for entry in view.entries
        ],
    )
