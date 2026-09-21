"""Patient Check-In HTTP endpoint

This module converts API requests into domain objects and maps application
errors to HTTP responses. Error messages never include the patient identifier.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from AZFlow.application.check_in import CheckInService
from AZFlow.application.errors import (
    NoAppointmentAvailableError,
    UnsupportedIdentifierTypeError,
)
from AZFlow.domain.errors import EmptyIdentifierValueError
from AZFlow.domain.patient_identifier import PatientIdentifier


router = APIRouter()


class CheckInRequest(BaseModel):
    """Check-in data received from the kiosk"""

    identifier_type: str = Field(min_length=1)
    identifier_value: str = Field(min_length=1)


class CheckInResponse(BaseModel):
    """Successful check-in response with the public call code"""

    public_call_code: str


def get_check_in_service() -> CheckInService:
    """Provide the CheckInService used by the route

    The application setup and tests replace this dependency.
    """
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="check-in service is not configured",
    )


@router.post(
    "/check-ins",
    response_model=CheckInResponse,
    status_code=status.HTTP_200_OK,
)
def check_in(
    request: CheckInRequest,
    service: CheckInService = Depends(get_check_in_service),
) -> CheckInResponse:
    """Check in a patient and return the public call code"""
    try:
        patient_identifier = PatientIdentifier(
            type=request.identifier_type,
            value=request.identifier_value,
        )
    except EmptyIdentifierValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error),
        ) from error

    try:
        result = service.check_in(patient_identifier)
    except UnsupportedIdentifierTypeError as error:
        # Return the unsupported type but never the identifier value
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(f"unsupported patient identifier type: {error.identifier_type!r}"),
        ) from error
    except NoAppointmentAvailableError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no appointments found for check-in",
        ) from error

    return CheckInResponse(public_call_code=result.public_call_code)
