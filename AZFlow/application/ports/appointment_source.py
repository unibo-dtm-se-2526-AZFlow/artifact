"""AppointmentSource port and its application boundary data"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Optional, Protocol

from AZFlow.domain.patient_identifier import PatientIdentifier


@dataclass(frozen=True)
class ExternalAppointmentData:
    """Appointment data returned by an external source

    It contains only the information needed to create a domain Appointment.
    The external appointment reference is used to recognize the same
    appointment during repeated check-ins.
    """

    external_source_code: str
    scheduled_at: datetime
    external_agenda_reference: str
    external_appointment_reference: str
    external_patient_reference: Optional[str] = None


class AppointmentSource(Protocol):
    """Port used to find appointments in an external source"""

    def find_for_day(
        self,
        patient_identifier: PatientIdentifier,
        operational_day: date,
    ) -> List[ExternalAppointmentData]:
        """Return appointments for the identifier and day"""
        ...
