"""Application errors for Patient Check-In

These errors describe problems found while running the use case. They do not
depend on FastAPI, the database or other external tools.

They only keep the data needed by the API. User-facing messages belong to the
API layer.
"""

from __future__ import annotations


class ApplicationError(Exception):
    """Base class for Patient Check-In application errors"""


class UnsupportedIdentifierTypeError(ApplicationError):
    """Raised when the identifier type is not supported"""

    def __init__(self, identifier_type: str) -> None:
        self.identifier_type = identifier_type
        super().__init__()


class NoAppointmentAvailableError(ApplicationError):
    """Raised when no appointment is available for check-in"""
