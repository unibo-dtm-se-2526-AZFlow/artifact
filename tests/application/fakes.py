"""In-memory fakes honouring the check-in ports.

These fakes let the application service be exercised without PostgreSQL while
respecting the port contracts:

- ``resolve_agenda`` returns configured Agenda/Queue mappings or ``None``;
- ``find_or_create_appointment`` recognizes an already imported Appointment by
  its stable ``(external_agenda_reference, external_appointment_reference)``
  and assigns incrementing ids otherwise;
- ``create_daily_presence_with_code`` allocates an atomic-ish daily sequence
  per ``(ticket_master, operational_day)`` and reloads an existing
  DailyPresence on a duplicate ``(operational_day, identifier)``;
- ``find_or_create_service_access`` does not duplicate for the same
  ``(daily_presence, appointment)`` and starts in ``WAITING``.

They are placed here so other application/API tests can reuse them.
"""

from __future__ import annotations

from datetime import date
from typing import Dict, List, Mapping, Optional, Tuple

from AZFlow.application.ports.appointment_source import ExternalAppointmentData
from AZFlow.application.ports.check_in_repository import (
    ResolvedAgenda,
    format_public_call_code,
)
from AZFlow.domain.agenda import Agenda, ExternalAgenda
from AZFlow.domain.appointment import Appointment
from AZFlow.domain.daily_presence import DailyPresence
from AZFlow.domain.patient_identifier import PatientIdentifier
from AZFlow.domain.service_access import ServiceAccess, ServiceAccessState
from AZFlow.domain.ticket_master import TicketMaster


class ListAppointmentSource:
    """A trivial AppointmentSource returning a fixed list of data."""

    def __init__(self, appointments: List[ExternalAppointmentData]) -> None:
        self._appointments = list(appointments)

    def find_for_day(
        self,
        patient_identifier: PatientIdentifier,
        operational_day: date,
    ) -> List[ExternalAppointmentData]:
        return list(self._appointments)


def _identifier_key(
    identifier: PatientIdentifier,
) -> Tuple[str, str]:
    return (identifier.type, identifier.value)


class FakeCheckInRepository:
    """In-memory CheckInRepository honouring the port contract.

    Agenda resolution is driven by a mapping keyed on
    ``(external_source_code, external_agenda_reference)``.
    """

    def __init__(
        self,
        resolutions: Mapping[Tuple[str, str], ResolvedAgenda],
    ) -> None:
        self._resolutions: Dict[Tuple[str, str], ResolvedAgenda] = dict(resolutions)

        self._next_appointment_id = 1
        # Recognize appointments by stable source-specific reference.
        self._appointments: Dict[Tuple[Optional[str], str], Appointment] = {}

        self._next_daily_presence_id = 1
        self._daily_presences: Dict[Tuple[str, str, str], DailyPresence] = {}
        # (ticket_master id, operational_day) -> last allocated sequence.
        self._sequences: Dict[Tuple[int, date], int] = {}

        self._next_service_access_id = 1
        self._service_accesses: Dict[Tuple[int, int], ServiceAccess] = {}

        # Observability for tests.
        self.created_daily_presences = 0
        self.created_service_accesses = 0

    def resolve_agenda(
        self,
        external_source_code: str,
        external_agenda_reference: str,
    ) -> Optional[ResolvedAgenda]:
        return self._resolutions.get((external_source_code, external_agenda_reference))

    def find_or_create_appointment(
        self,
        data: ExternalAppointmentData,
        patient_identifier: PatientIdentifier,
        external_agenda: ExternalAgenda,
    ) -> Appointment:
        key = (data.external_agenda_reference, data.external_appointment_reference)
        existing = self._appointments.get(key)
        if existing is not None:
            return existing

        appointment = Appointment(
            id=self._next_appointment_id,
            scheduled_at=data.scheduled_at,
            patient_identifier=patient_identifier,
            external_agenda=external_agenda,
            external_patient_reference=data.external_patient_reference,
            external_appointment_reference=data.external_appointment_reference,
        )
        self._next_appointment_id += 1
        self._appointments[key] = appointment
        return appointment

    def find_daily_presence(
        self,
        operational_day: date,
        patient_identifier: PatientIdentifier,
    ) -> Optional[DailyPresence]:
        return self._daily_presences.get(
            self._daily_presence_key(operational_day, patient_identifier)
        )

    def create_daily_presence_with_code(
        self,
        patient_identifier: PatientIdentifier,
        operational_day: date,
        ticket_master: TicketMaster,
    ) -> DailyPresence:
        key = self._daily_presence_key(operational_day, patient_identifier)
        existing = self._daily_presences.get(key)
        if existing is not None:
            # Reload on duplicate instead of surfacing a conflict.
            return existing

        sequence_key = (ticket_master.id, operational_day)
        sequence = self._sequences.get(sequence_key, 0) + 1
        self._sequences[sequence_key] = sequence

        daily_presence = DailyPresence(
            id=self._next_daily_presence_id,
            patient_identifier=patient_identifier,
            operational_day=operational_day,
            public_call_code=format_public_call_code(ticket_master.prefix, sequence),
            ticket_master=ticket_master,
        )
        self._next_daily_presence_id += 1
        self._daily_presences[key] = daily_presence
        self.created_daily_presences += 1
        return daily_presence

    def find_or_create_service_access(
        self,
        daily_presence: DailyPresence,
        agenda: Agenda,
        appointment: Appointment,
    ) -> ServiceAccess:
        key = (daily_presence.id, appointment.id)
        existing = self._service_accesses.get(key)
        if existing is not None:
            return existing

        service_access = ServiceAccess(
            id=self._next_service_access_id,
            daily_presence=daily_presence,
            agenda=agenda,
            appointment=appointment,
            state=ServiceAccessState.WAITING,
        )
        self._next_service_access_id += 1
        self._service_accesses[key] = service_access
        self.created_service_accesses += 1
        return service_access

    def service_accesses(self) -> List[ServiceAccess]:
        """Return all created ServiceAccesses (test helper)."""
        return list(self._service_accesses.values())

    @staticmethod
    def _daily_presence_key(
        operational_day: date,
        patient_identifier: PatientIdentifier,
    ) -> Tuple[str, str, str]:
        identifier_type, identifier_value = _identifier_key(patient_identifier)
        return (operational_day.isoformat(), identifier_type, identifier_value)
