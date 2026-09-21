"""DailyPresence domain concept"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from AZFlow.domain.patient_identifier import PatientIdentifier
from AZFlow.domain.ticket_master import TicketMaster


@dataclass(frozen=True)
class DailyPresence:
    """Daily check-in record for one patient identifier

    It keeps one public call code and one TicketMaster for the operational
    day. It does not mean that the patient is physically present at a site.
    The unique key is
    ``(operational_day, identifier_type, identifier_value)``.
    """

    id: int
    patient_identifier: PatientIdentifier
    operational_day: date
    public_call_code: str
    ticket_master: TicketMaster
