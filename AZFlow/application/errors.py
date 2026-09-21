"""Application-level errors for the Patient Check-In use case.

These are use-case errors raised by the application layer. They are kept
small and explicit, and they must not depend on FastAPI, psycopg or any
delivery/infrastructure framework. The API adapter maps them to HTTP 4xx
responses; the domain does not depend on them.

Patient identifiers must not be included in these messages, so they can be
surfaced in public error output and routine logs without leaking identity.
"""

from __future__ import annotations


class ApplicationError(Exception):
    """Base class for Patient Check-In application errors"""


class UnsupportedIdentifierTypeError(ApplicationError):
    """Raised when the presented PatientIdentifier type is not supported.

    The current slice supports only ``fiscal_code``. The message names the
    unsupported type but never the identifier value.
    """

    def __init__(self, identifier_type: str) -> None:
        self.identifier_type = identifier_type
        super().__init__(f"unsupported patient identifier type: {identifier_type!r}")


class NoAppointmentAvailableError(ApplicationError):
    """Raised when no relevant appointment is available for check-in"""
