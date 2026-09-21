"""Persistence port used by Patient Check-In

The port works with domain objects and simple application read models. Database
rows and SQL details must not reach the application layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional, Protocol

from AZFlow.application.ports.appointment_source import ExternalAppointmentData
from AZFlow.domain.agenda import Agenda, ExternalAgenda
from AZFlow.domain.appointment import Appointment
from AZFlow.domain.daily_presence import DailyPresence
from AZFlow.domain.patient_identifier import PatientIdentifier
from AZFlow.domain.service_access import ServiceAccess
from AZFlow.domain.ticket_master import TicketMaster


# Minimum number of digits in a public call code, for example AAA001
PUBLIC_CALL_CODE_MIN_DIGITS = 3


def format_public_call_code(prefix: str, sequence: int) -> str:
    """Build a public call code from a prefix and daily sequence"""
    return f"{prefix}{sequence:0{PUBLIC_CALL_CODE_MIN_DIGITS}d}"


@dataclass(frozen=True)
class ResolvedQueue:
    """Active queue data needed during check-in"""

    queue_id: int
    ticket_master: TicketMaster


@dataclass(frozen=True)
class ResolvedAgenda:
    """Agenda data needed during check-in

    Active queues are ordered by id. The first one is used to select the
    TicketMaster.
    """

    external_agenda: ExternalAgenda
    agenda: Agenda
    active_queues: List[ResolvedQueue] = field(default_factory=list)

    def has_active_queue(self) -> bool:
        """Return whether the Agenda has at least one ACTIVE Queue"""
        return bool(self.active_queues)


class CheckInRepository(Protocol):
    """Persistence operations required by Patient Check-In"""

    def resolve_agenda(
        self,
        external_source_code: str,
        external_agenda_reference: str,
    ) -> Optional[ResolvedAgenda]:
        """Return the configured agenda and its active queues, if found"""
        ...

    def find_or_create_appointment(
        self,
        data: ExternalAppointmentData,
        patient_identifier: PatientIdentifier,
        external_agenda: ExternalAgenda,
    ) -> Appointment:
        """Import an appointment or reuse it from its external reference"""
        ...

    def find_daily_presence(
        self,
        operational_day: date,
        patient_identifier: PatientIdentifier,
    ) -> Optional[DailyPresence]:
        """Return the daily presence for the day and identifier, if found"""
        ...

    def create_daily_presence_with_code(
        self,
        patient_identifier: PatientIdentifier,
        operational_day: date,
        ticket_master: TicketMaster,
    ) -> DailyPresence:
        """Create a daily presence with the next public call code

        A concurrent request for the same patient and day returns the existing
        presence.
        """
        ...

    def find_or_create_service_access(
        self,
        daily_presence: DailyPresence,
        agenda: Agenda,
        appointment: Appointment,
    ) -> ServiceAccess:
        """Create or reuse a service access for an appointment"""
        ...
