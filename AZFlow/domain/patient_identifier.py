"""PatientIdentifier value object"""

from __future__ import annotations

from dataclasses import dataclass

from AZFlow.domain.errors import EmptyIdentifierValueError


FISCAL_CODE = "fiscal_code"


@dataclass(frozen=True)
class PatientIdentifier:
    """Typed identifier presented at check-in.

    It is the identifier presented at check-in and is not a persistent
    Patient entity. In the current slice the only supported type is
    ``fiscal_code``, but the value object only enforces a non-empty value
    and exposes the type; the service/API layer decides type rejection.
    """

    type: str
    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise EmptyIdentifierValueError(
                "patient identifier value must not be empty"
            )
