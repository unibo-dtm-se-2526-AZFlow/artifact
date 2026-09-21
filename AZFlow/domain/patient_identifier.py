"""PatientIdentifier value object"""

from __future__ import annotations

from dataclasses import dataclass

from AZFlow.domain.errors import EmptyIdentifierValueError


FISCAL_CODE = "fiscal_code"


@dataclass(frozen=True)
class PatientIdentifier:
    """Identifier presented by the patient at check-in

    It is not a persistent Patient entity. This object only checks that the
    value is not empty. The application layer decides which types are supported.
    """

    type: str
    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise EmptyIdentifierValueError()
