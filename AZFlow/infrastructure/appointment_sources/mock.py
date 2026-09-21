"""Deterministic in-memory AppointmentSource adapter"""

from __future__ import annotations

from datetime import date, datetime
from typing import Dict, List, Mapping, Optional

from AZFlow.application.ports.appointment_source import ExternalAppointmentData
from AZFlow.domain.patient_identifier import PatientIdentifier

# Default appointments used when no custom data is provided
_DEFAULT_APPOINTMENTS: Dict[str, List[ExternalAppointmentData]] = {
    "RSSMRA80A01H501U": [
        ExternalAppointmentData(
            external_source_code="MOCK",
            scheduled_at=datetime(2000, 1, 1, 9, 0),
            external_agenda_reference="AGENDA-A",
            external_appointment_reference="MOCK-APPT-0001",
            external_patient_reference="MOCK-PAT-0001",
        ),
        ExternalAppointmentData(
            external_source_code="MOCK",
            scheduled_at=datetime(2000, 1, 1, 10, 30),
            external_agenda_reference="AGENDA-B",
            external_appointment_reference="MOCK-APPT-0002",
            external_patient_reference="MOCK-PAT-0001",
        ),
    ],
}


class MockAppointmentSource:
    """In-memory appointment source used for development and tests

    The same identifier always returns the same appointments. The requested
    operational day replaces the date in the sample data.
    """

    def __init__(
        self,
        appointments: Optional[Mapping[str, List[ExternalAppointmentData]]] = None,
    ) -> None:
        source = _DEFAULT_APPOINTMENTS if appointments is None else appointments
        # Copy the data to protect it from external changes
        self._appointments: Dict[str, List[ExternalAppointmentData]] = {
            key: list(value) for key, value in source.items()
        }

    def find_for_day(
        self,
        patient_identifier: PatientIdentifier,
        operational_day: date,
    ) -> List[ExternalAppointmentData]:
        """Return appointments for the identifier on the requested day"""
        stored = self._appointments.get(patient_identifier.value, [])
        return [self._on_day(appointment, operational_day) for appointment in stored]

    @staticmethod
    def _on_day(
        appointment: ExternalAppointmentData,
        operational_day: date,
    ) -> ExternalAppointmentData:
        scheduled_at = appointment.scheduled_at.replace(
            year=operational_day.year,
            month=operational_day.month,
            day=operational_day.day,
        )
        return ExternalAppointmentData(
            external_source_code=appointment.external_source_code,
            scheduled_at=scheduled_at,
            external_agenda_reference=appointment.external_agenda_reference,
            external_appointment_reference=(appointment.external_appointment_reference),
            external_patient_reference=appointment.external_patient_reference,
        )
