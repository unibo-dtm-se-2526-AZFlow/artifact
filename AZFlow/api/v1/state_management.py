"""Suspend, Restore and Admission HTTP endpoints

This module maps state-management requests to the application service and turns
application errors into HTTP responses. Responses and error messages never
include the Patient Identifier or any identifying Patient data.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel

from AZFlow.application.errors import (
    ServiceAccessNotAdmittableError,
    ServiceAccessNotFoundError,
    ServiceAccessNotRestorableError,
    ServiceAccessNotSuspendableError,
)
from AZFlow.application.state_management import (
    StateChangeResult,
    StateManagementService,
)

from AZFlow.api.v1.schemas import AgendaModel


router = APIRouter()



class StateChangeResponse(BaseModel):
    """Successful state-change response, with no identifying Patient data

    ``room_reference`` and ``room_label`` are set only for admission and
    omitted otherwise.
    """

    public_call_code: str
    service_access_id: int
    agenda: AgendaModel
    state: str
    room_reference: Optional[str] = None
    room_label: Optional[str] = None


def get_state_management_service() -> StateManagementService:
    """Provide the StateManagementService used by the routes

    The application setup and tests replace this dependency.
    """
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="state management service is not configured",
    )


@router.post(
    "/service-accesses/{service_access_id}/suspend",
    response_model=StateChangeResponse,
    response_model_exclude_none=True,
    status_code=status.HTTP_200_OK,
)
def suspend(
    service_access_id: int = Path(..., gt=0),
    service: StateManagementService = Depends(get_state_management_service),
) -> StateChangeResponse:
    """Suspend a WAITING ServiceAccess"""
    try:
        result = service.suspend(service_access_id)
    except ServiceAccessNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="service access not found",
        ) from error
    except ServiceAccessNotSuspendableError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="service access is not suspendable",
        ) from error

    return _to_response(result)


@router.post(
    "/service-accesses/{service_access_id}/restore",
    response_model=StateChangeResponse,
    response_model_exclude_none=True,
    status_code=status.HTTP_200_OK,
)
def restore(
    service_access_id: int = Path(..., gt=0),
    service: StateManagementService = Depends(get_state_management_service),
) -> StateChangeResponse:
    """Restore a SUSPENDED ServiceAccess"""
    try:
        result = service.restore(service_access_id)
    except ServiceAccessNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="service access not found",
        ) from error
    except ServiceAccessNotRestorableError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="service access is not restorable",
        ) from error

    return _to_response(result)


@router.post(
    "/service-accesses/{service_access_id}/admission",
    response_model=StateChangeResponse,
    response_model_exclude_none=True,
    status_code=status.HTTP_200_OK,
)
def confirm_admission(
    service_access_id: int = Path(..., gt=0),
    service: StateManagementService = Depends(get_state_management_service),
) -> StateChangeResponse:
    """Confirm admission of a CALLED ServiceAccess into its call-time Room"""
    try:
        result = service.confirm_admission(service_access_id)
    except ServiceAccessNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="service access not found",
        ) from error
    except ServiceAccessNotAdmittableError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="service access is not admittable",
        ) from error

    return _to_response(result)


def _to_response(result: StateChangeResult) -> StateChangeResponse:
    """Map the application state-change result to the response model."""
    return StateChangeResponse(
        public_call_code=result.public_call_code,
        service_access_id=result.service_access_id,
        agenda=AgendaModel(id=result.agenda.id, name=result.agenda.name),
        state=result.state.value,
        room_reference=result.room_reference,
        room_label=result.room_label,
    )
