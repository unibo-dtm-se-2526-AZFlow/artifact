"""Domain errors"""

from __future__ import annotations


class DomainError(Exception):
    """Base class for domain rule violations"""


class EmptyIdentifierValueError(DomainError):
    """Raised when a PatientIdentifier is built with an empty value"""


class ServiceAccessNotWaitingError(DomainError):
    """Raised when a ServiceAccess is called while not WAITING"""

    def __init__(self, service_access_id: int) -> None:
        super().__init__()
        self.service_access_id = service_access_id


class ServiceAccessNotSuspendedError(DomainError):
    """Raised when a ServiceAccess is restored while not SUSPENDED"""

    def __init__(self, service_access_id: int) -> None:
        super().__init__()
        self.service_access_id = service_access_id


class ServiceAccessNotCalledError(DomainError):
    """Raised when a ServiceAccess admission is confirmed while not CALLED"""

    def __init__(self, service_access_id: int) -> None:
        super().__init__()
        self.service_access_id = service_access_id
