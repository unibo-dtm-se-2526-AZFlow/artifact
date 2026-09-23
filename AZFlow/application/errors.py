"""Application errors.

They carry only the data the API needs. User-facing messages belong to the API.
"""

from __future__ import annotations


class ApplicationError(Exception):
    """Base class for application errors."""


class UnsupportedIdentifierTypeError(ApplicationError):
    """Raised when the identifier type is not supported."""

    def __init__(self, identifier_type: str) -> None:
        self.identifier_type = identifier_type
        super().__init__()


class NoAppointmentAvailableError(ApplicationError):
    """Raised when no appointment is available for check-in."""


class QueueNotFoundError(ApplicationError):
    """Raised when no Queue exists for the requested id."""

    def __init__(self, queue_id: int) -> None:
        self.queue_id = queue_id
        super().__init__()


class QueueInactiveError(ApplicationError):
    """Raised when the selected Queue is INACTIVE."""

    def __init__(self, queue_id: int) -> None:
        self.queue_id = queue_id
        super().__init__()


class MissingPublicCallCodeError(ApplicationError):
    """Raised when an included ServiceAccess has no public call code."""

    def __init__(self, service_access_id: int) -> None:
        self.service_access_id = service_access_id
        super().__init__()


class MissingRoomReferenceError(ApplicationError):
    """Raised when the required Room reference is missing, empty or blank."""


class NoPatientToCallError(ApplicationError):
    """Raised when call next finds no callable ServiceAccess for the day."""

    def __init__(self, queue_id: int) -> None:
        self.queue_id = queue_id
        super().__init__()


class ServiceAccessNotVisibleError(ApplicationError):
    """Raised when the target ServiceAccess is not visible through the Queue."""

    def __init__(self, service_access_id: int) -> None:
        self.service_access_id = service_access_id
        super().__init__()


class ServiceAccessNotCallableError(ApplicationError):
    """Raised when the target ServiceAccess is visible but not WAITING."""

    def __init__(self, service_access_id: int) -> None:
        self.service_access_id = service_access_id
        super().__init__()


class ServiceAccessNotFoundError(ApplicationError):
    """Raised when no ServiceAccess exists for the requested id."""

    def __init__(self, service_access_id: int) -> None:
        self.service_access_id = service_access_id
        super().__init__()


class ServiceAccessNotSuspendableError(ApplicationError):
    """Raised when the target ServiceAccess exists but is not WAITING."""

    def __init__(self, service_access_id: int) -> None:
        self.service_access_id = service_access_id
        super().__init__()


class ServiceAccessNotRestorableError(ApplicationError):
    """Raised when the target ServiceAccess exists but is not SUSPENDED."""

    def __init__(self, service_access_id: int) -> None:
        self.service_access_id = service_access_id
        super().__init__()


class ServiceAccessNotAdmittableError(ApplicationError):
    """Raised when the target ServiceAccess exists but is not CALLED."""

    def __init__(self, service_access_id: int) -> None:
        self.service_access_id = service_access_id
        super().__init__()
