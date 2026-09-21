"""Domain errors for the check-in slice"""

from __future__ import annotations


class DomainError(Exception):
    """Base class for domain rule violations"""


class EmptyIdentifierValueError(DomainError):
    """Raised when a PatientIdentifier is built with an empty value"""
