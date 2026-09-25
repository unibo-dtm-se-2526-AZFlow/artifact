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
            external_appointment_reference="MOCK-APPT-LEGACY-0001",
            external_patient_reference="MOCK-PAT-LEGACY-0001",
        ),
        ExternalAppointmentData(
            external_source_code="MOCK",
            scheduled_at=datetime(2000, 1, 1, 10, 30),
            external_agenda_reference="AGENDA-B",
            external_appointment_reference="MOCK-APPT-LEGACY-0002",
            external_patient_reference="MOCK-PAT-LEGACY-0001",
        ),
    ],
    "DEV0001": [
        ExternalAppointmentData(
            external_source_code="MOCK",
            scheduled_at=datetime(2000, 1, 1, 9, 30),
            external_agenda_reference="AGENDA-A",
            external_appointment_reference="MOCK-APPT-0001",
            external_patient_reference="MOCK-PAT-0001",
        ),
    ],
    "DEV0002": [
        ExternalAppointmentData(
            external_source_code="MOCK",
            scheduled_at=datetime(2000, 1, 1, 8, 45),
            external_agenda_reference="AGENDA-A",
            external_appointment_reference="MOCK-APPT-0002",
            external_patient_reference="MOCK-PAT-0002",
        ),
    ],
    "DEV0003": [
        ExternalAppointmentData(
            external_source_code="MOCK",
            scheduled_at=datetime(2000, 1, 1, 10, 15),
            external_agenda_reference="AGENDA-B",
            external_appointment_reference="MOCK-APPT-0003",
            external_patient_reference="MOCK-PAT-0003",
        ),
    ],
    "DEV0004": [
        ExternalAppointmentData(
            external_source_code="MOCK",
            scheduled_at=datetime(2000, 1, 1, 9, 0),
            external_agenda_reference="AGENDA-B",
            external_appointment_reference="MOCK-APPT-0004",
            external_patient_reference="MOCK-PAT-0004",
        ),
    ],
    "DEV0005": [
        ExternalAppointmentData(
            external_source_code="MOCK",
            scheduled_at=datetime(2000, 1, 1, 11, 0),
            external_agenda_reference="AGENDA-A",
            external_appointment_reference="MOCK-APPT-0005",
            external_patient_reference="MOCK-PAT-0005",
        ),
    ],
    "DEV0006": [
        ExternalAppointmentData(
            external_source_code="MOCK",
            scheduled_at=datetime(2000, 1, 1, 9, 15),
            external_agenda_reference="AGENDA-A",
            external_appointment_reference="MOCK-APPT-0006",
            external_patient_reference="MOCK-PAT-0006",
        ),
        ExternalAppointmentData(
            external_source_code="MOCK",
            scheduled_at=datetime(2000, 1, 1, 10, 30),
            external_agenda_reference="AGENDA-B",
            external_appointment_reference="MOCK-APPT-0007",
            external_patient_reference="MOCK-PAT-0006",
        ),
    ],
}


def _demo_appointments() -> Dict[str, List[ExternalAppointmentData]]:
    """Build the deterministic not-yet-arrived Patients used by the demo."""
    result: Dict[str, List[ExternalAppointmentData]] = {}
    multi = {
        41: (2, 4),
        52: (1, 5),
        61: (2, 3),
        67: (3, 4),
        74: (1, 5),
    }

    for number in range(31, 81):
        agenda_ids = multi.get(number, (((number - 31) % 5) + 1,))
        appointments: List[ExternalAppointmentData] = []
        for index, agenda_id in enumerate(agenda_ids):
            # DEMO031 is deliberately late at mid-morning.
            minutes = -120 if number == 31 else (number - 31) * 8 + index * 45
            hour, minute = divmod(10 * 60 + 30 + minutes, 60)
            appointments.append(
                ExternalAppointmentData(
                    external_source_code="MOCK",
                    scheduled_at=datetime(2000, 1, 1, hour, minute),
                    external_agenda_reference=f"AGENDA-{agenda_id}",
                    external_appointment_reference=f"DEMO-APPT-{number:03d}-{index + 1}",
                    external_patient_reference=f"DEMO-PAT-{number:03d}",
                )
            )
        result[f"DEMO{number:03d}"] = appointments
    return result


_DEFAULT_APPOINTMENTS.update(_demo_appointments())


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
