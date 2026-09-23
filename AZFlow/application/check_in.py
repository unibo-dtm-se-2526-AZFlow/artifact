"""Patient Check-In application service

The service uses ports to read appointments and save check-in data. It does not
depend on FastAPI, PostgreSQL or other concrete adapters.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import List, Optional, Sequence, Tuple

from AZFlow.application.errors import (
    InvalidTotemReferenceError,
    NoAppointmentAvailableError,
    UnsupportedIdentifierTypeError,
)
from AZFlow.application.ports.appointment_source import (
    AppointmentSource,
    ExternalAppointmentData,
)
from AZFlow.application.ports.check_in_repository import (
    CheckInRepository,
    ResolvedAgenda,
)
from AZFlow.domain.appointment import Appointment
from AZFlow.domain.daily_presence import DailyPresence
from AZFlow.domain.patient_identifier import FISCAL_CODE, PatientIdentifier

# Identifier types supported by the current check-in flow
_SUPPORTED_IDENTIFIER_TYPES = frozenset({FISCAL_CODE})


@dataclass(frozen=True)
class CheckInResult:
    """Result returned after a successful check-in

    The public call code never contains the patient identifier.
    """

    daily_presence: DailyPresence

    @property
    def public_call_code(self) -> str:
        """Return the public call code for ticket printing"""
        return self.daily_presence.public_call_code


class CheckInService:
    """Coordinates Patient Check-In through the application ports

    Appointment sources are queried in the order in which they are provided.
    """

    def __init__(
        self,
        appointment_sources: Sequence[AppointmentSource],
        repository: CheckInRepository,
    ) -> None:
        self._appointment_sources = list(appointment_sources)
        self._repository = repository

    def check_in(
        self,
        patient_identifier: PatientIdentifier,
        operational_day: Optional[date] = None,
        totem_reference: Optional[str] = None,
    ) -> CheckInResult:
        """Check in a patient for an operational day

        ``operational_day`` stays the second positional parameter to preserve
        the original contract, so existing positional callers are unaffected.
        The current day is used when it is not provided. When
        ``totem_reference`` is given, it records the check-in origin; the origin
        stays unknown otherwise.

        Raises:
            UnsupportedIdentifierTypeError: the identifier type is not supported
            InvalidTotemReferenceError: the Totem reference is unknown
            NoAppointmentAvailableError: no valid appointment is available
        """
        self._require_supported_type(patient_identifier)

        day = date.today() if operational_day is None else operational_day

        # Reject an unknown Totem before creating any check-in data
        totem_id = self._resolve_totem(totem_reference)

        relevant = self._collect_relevant(patient_identifier, day)
        if not relevant:
            # Stop before creating check-in data
            raise NoAppointmentAvailableError()

        # Save appointments first because their ids are used to resolve ties
        imported = [
            (
                self._repository.find_or_create_appointment(
                    data,
                    patient_identifier,
                    resolved.external_agenda,
                ),
                resolved,
            )
            for data, resolved in relevant
        ]

        daily_presence = self._find_or_create_daily_presence(
            patient_identifier, day, imported, totem_id
        )

        # Create missing service accesses without duplicates
        for appointment, resolved in imported:
            self._repository.find_or_create_service_access(
                daily_presence,
                resolved.agenda,
                appointment,
            )

        return CheckInResult(daily_presence=daily_presence)

    def _resolve_totem(self, totem_reference: Optional[str]) -> Optional[int]:
        """Resolve the optional check-in origin, rejecting an unknown Totem"""
        if totem_reference is None:
            return None
        totem_id = self._repository.resolve_totem(totem_reference)
        if totem_id is None:
            raise InvalidTotemReferenceError(totem_reference)
        return totem_id

    @staticmethod
    def _require_supported_type(patient_identifier: PatientIdentifier) -> None:
        if patient_identifier.type not in _SUPPORTED_IDENTIFIER_TYPES:
            raise UnsupportedIdentifierTypeError(patient_identifier.type)

    def _collect_relevant(
        self,
        patient_identifier: PatientIdentifier,
        operational_day: date,
    ) -> List[Tuple[ExternalAppointmentData, ResolvedAgenda]]:
        """Return appointments linked to an active queue

        Unknown agendas and agendas without an active queue are ignored.
        """
        relevant: List[Tuple[ExternalAppointmentData, ResolvedAgenda]] = []
        for source in self._appointment_sources:
            for data in source.find_for_day(patient_identifier, operational_day):
                resolved = self._repository.resolve_agenda(
                    data.external_source_code,
                    data.external_agenda_reference,
                )
                if resolved is None or not resolved.has_active_queue():
                    continue
                relevant.append((data, resolved))
        return relevant

    def _find_or_create_daily_presence(
        self,
        patient_identifier: PatientIdentifier,
        operational_day: date,
        imported: List[Tuple[Appointment, ResolvedAgenda]],
        totem_id: Optional[int] = None,
    ) -> DailyPresence:
        """Reuse a daily presence or create one with a new call code

        The earliest appointment selects the TicketMaster for a new presence.
        The Totem origin is persisted only when a new presence is created.
        """
        existing = self._repository.find_daily_presence(
            operational_day, patient_identifier
        )
        if existing is not None:
            # Reuse the same presence and public call code
            return existing

        # Use the appointment id to resolve equal schedule times
        earliest_appointment, earliest_resolved = min(
            imported,
            key=lambda pair: (pair[0].scheduled_at, pair[0].id),
        )
        # Active queues are ordered by id, so the first one is selected
        ticket_master = earliest_resolved.active_queues[0].ticket_master

        return self._repository.create_daily_presence_with_code(
            patient_identifier,
            operational_day,
            ticket_master,
            totem_id=totem_id,
        )
