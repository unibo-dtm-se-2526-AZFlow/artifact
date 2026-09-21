import dataclasses

import pytest

from AZFlow.domain.errors import EmptyIdentifierValueError
from AZFlow.domain.patient_identifier import FISCAL_CODE, PatientIdentifier


def test_fiscal_code_identifier_is_supported():
    identifier = PatientIdentifier(type=FISCAL_CODE, value="RSSMRA80A01H501U")

    assert identifier.type == "fiscal_code"
    assert identifier.value == "RSSMRA80A01H501U"


def test_empty_value_raises_domain_error():
    with pytest.raises(EmptyIdentifierValueError):
        PatientIdentifier(type=FISCAL_CODE, value="")


def test_identifier_is_immutable():
    identifier = PatientIdentifier(type=FISCAL_CODE, value="RSSMRA80A01H501U")

    with pytest.raises(dataclasses.FrozenInstanceError):
        identifier.value = "other"  # type: ignore[misc]


def test_identifier_exposes_arbitrary_type_without_rejecting_it():
    # The value object validates only a non-empty value and exposes the
    # type; type rejection is decided by the service/API layer.
    identifier = PatientIdentifier(type="passport", value="X123")

    assert identifier.type == "passport"
