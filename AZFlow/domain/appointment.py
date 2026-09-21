"""Appointment domain concept"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from AZFlow.domain.agenda import ExternalAgenda
from AZFlow.domain.patient_identifier import PatientIdentifier


@dataclass(frozen=True)
class Appointment:
    """Appointment imported from an external source

    It keeps the identifier used for check-in and the scheduling information.
    It does not contain AZFlow operational state.
    """

    id: int
    scheduled_at: datetime
    patient_identifier: PatientIdentifier
    external_agenda: ExternalAgenda
    external_patient_reference: Optional[str] = None
    external_appointment_reference: Optional[str] = None
