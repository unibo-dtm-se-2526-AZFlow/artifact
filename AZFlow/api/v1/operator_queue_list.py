"""HTTP endpoint for the expanded operator Queue LIST."""

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
from AZFlow.application.operator_queue_list import (
    OperatorQueueListService,
)

router = APIRouter()


class OperatorAgendaModel(BaseModel):
    id: int
    name: str


class OperatorQueueListEntryModel(BaseModel):
    service_access_id: int
    public_call_code: str
    agenda: OperatorAgendaModel
    state: str
    checked_in_at: datetime
    scheduled_at: Optional[datetime] = None


class OperatorQueueListResponse(BaseModel):
    queue_id: int
    policy: str
    entries: List[OperatorQueueListEntryModel]


def get_operator_queue_list_service() -> OperatorQueueListService:
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="operator queue list service is not configured",
    )


@router.get(
    "/queues/{queue_id}/operator-list",
    response_model=OperatorQueueListResponse,
    status_code=status.HTTP_200_OK,
)
def view_operator_queue_list(
    queue_id: int = Path(..., gt=0),
    service: OperatorQueueListService = Depends(get_operator_queue_list_service),
) -> OperatorQueueListResponse:
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
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="operator queue list entry cannot be represented",
        ) from error

    return OperatorQueueListResponse(
        queue_id=view.queue_id,
        policy=view.policy.value,
        entries=[
            OperatorQueueListEntryModel(
                service_access_id=entry.service_access_id,
                public_call_code=entry.public_call_code,
                agenda=OperatorAgendaModel(
                    id=entry.agenda.id,
                    name=entry.agenda.name,
                ),
                state=entry.state.value,
                checked_in_at=entry.checked_in_at,
                scheduled_at=entry.scheduled_at,
            )
            for entry in view.entries
        ],
    )
