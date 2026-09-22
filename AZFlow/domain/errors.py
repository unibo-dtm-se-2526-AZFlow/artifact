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
