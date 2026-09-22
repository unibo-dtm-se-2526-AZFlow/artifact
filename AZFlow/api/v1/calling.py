"""Patient Calling HTTP endpoints

This module maps call requests to the application service and turns application
errors into HTTP responses. Responses and error messages never include the
patient identifier.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel

from AZFlow.application.calling import CallingService, CallResult
from AZFlow.application.errors import (
    MissingPublicCallCodeError,
    MissingRoomReferenceError,
    NoPatientToCallError,
    QueueInactiveError,
    QueueNotFoundError,
    ServiceAccessNotCallableError,
    ServiceAccessNotVisibleError,
)


router = APIRouter()


class CallRequest(BaseModel):
    """Call context received from the Operator workstation"""

    room_reference: str


class AgendaModel(BaseModel):
    """Served Agenda shown in a call response"""

    id: int
    name: str


class CallResponse(BaseModel):
    """Successful call response, with no identifying Patient data"""

    public_call_code: str
    service_access_id: int
    agenda: AgendaModel
    state: str
    room_reference: str


def get_calling_service() -> CallingService:
    """Provide the CallingService used by the routes

    The application setup and tests replace this dependency.
    """
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="calling service is not configured",
    )


@router.post(
    "/queues/{queue_id}/calls/next",
    response_model=CallResponse,
    status_code=status.HTTP_200_OK,
)
def call_next(
    request: CallRequest,
    queue_id: int = Path(..., gt=0),
    service: CallingService = Depends(get_calling_service),
) -> CallResponse:
    """Call the next callable ServiceAccess of a Queue"""
    try:
        result = service.call_next(queue_id, request.room_reference)
    except MissingRoomReferenceError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="room reference is required",
        ) from error
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
    except NoPatientToCallError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="no patient to call",
        ) from error
    except MissingPublicCallCodeError as error:
        # Keep the message generic so no identifying data can leak.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="call cannot be represented",
        ) from error

    return _to_response(result)


@router.post(
    "/queues/{queue_id}/service-accesses/{service_access_id}/call",
    response_model=CallResponse,
    status_code=status.HTTP_200_OK,
)
def call_specific(
    request: CallRequest,
    queue_id: int = Path(..., gt=0),
    service_access_id: int = Path(..., gt=0),
    service: CallingService = Depends(get_calling_service),
) -> CallResponse:
    """Call a specific ServiceAccess visible through a Queue"""
    try:
        result = service.call_specific(
            queue_id, service_access_id, request.room_reference
        )
    except MissingRoomReferenceError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="room reference is required",
        ) from error
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
    except ServiceAccessNotVisibleError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="service access not found in queue",
        ) from error
    except ServiceAccessNotCallableError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="service access is not callable",
        ) from error
    except MissingPublicCallCodeError as error:
        # Keep the message generic so no identifying data can leak.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="call cannot be represented",
        ) from error

    return _to_response(result)


def _to_response(result: CallResult) -> CallResponse:
    """Map the application call result to the response model."""
    return CallResponse(
        public_call_code=result.public_call_code,
        service_access_id=result.service_access_id,
        agenda=AgendaModel(id=result.agenda.id, name=result.agenda.name),
        state=result.state.value,
        room_reference=result.room_reference,
    )
