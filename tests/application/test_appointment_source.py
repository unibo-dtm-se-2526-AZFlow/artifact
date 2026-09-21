import dataclasses
from datetime import date, datetime
from typing import List

import pytest

from AZFlow.application.ports.appointment_source import (
    AppointmentSource,
    ExternalAppointmentData,
)
from AZFlow.domain.patient_identifier import FISCAL_CODE, PatientIdentifier


def test_external_appointment_data_is_immutable():
    data = ExternalAppointmentData(
        external_source_code="MOCK",
        scheduled_at=datetime(2024, 1, 1, 9, 0),
        external_agenda_reference="AGENDA-A",
        external_appointment_reference="APPT-1",
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        data.scheduled_at = datetime(2024, 1, 1, 10, 0)  # type: ignore[misc]


def test_external_patient_reference_is_optional():
    data = ExternalAppointmentData(
        external_source_code="MOCK",
        scheduled_at=datetime(2024, 1, 1, 9, 0),
        external_agenda_reference="AGENDA-A",
        external_appointment_reference="APPT-1",
    )

    assert data.external_patient_reference is None


def test_any_object_matching_the_protocol_is_an_appointment_source():
    class InMemorySource:
        def find_for_day(
            self,
            patient_identifier: PatientIdentifier,
            operational_day: date,
        ) -> List[ExternalAppointmentData]:
            return []

    source: AppointmentSource = InMemorySource()

    identifier = PatientIdentifier(type=FISCAL_CODE, value="RSSMRA80A01H501U")
    assert source.find_for_day(identifier, date(2024, 1, 1)) == []
