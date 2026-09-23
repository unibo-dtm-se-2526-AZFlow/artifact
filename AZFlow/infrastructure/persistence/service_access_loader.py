"""Load ServiceAccess parts from PostgreSQL rows.

Shared helpers used by adapters that rebuild a ServiceAccess after an atomic
conditional transition. They read the DailyPresence, Agenda and Appointment for
a row already selected by the caller and build domain objects, so SQL rows never
leak to the application.
"""

from __future__ import annotations

import psycopg

from AZFlow.domain.agenda import Agenda, ExternalAgenda
from AZFlow.domain.appointment import Appointment
from AZFlow.domain.daily_presence import DailyPresence
from AZFlow.domain.external_source import ExternalSource
from AZFlow.domain.patient_identifier import PatientIdentifier
from AZFlow.domain.ticket_master import TicketMaster


def load_daily_presence(
    cursor: "psycopg.Cursor",
    daily_presence_id: int,
) -> DailyPresence:
    cursor.execute(
        """
        SELECT
            dp.id,
            dp.operational_day,
            dp.patient_identifier_type,
            dp.patient_identifier_value,
            dp.public_call_code,
            tm.id,
            tm.prefix
        FROM daily_presence dp
        JOIN ticket_master tm ON tm.id = dp.ticket_master_id
        WHERE dp.id = %s
        """,
        (daily_presence_id,),
    )
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError("daily presence for a service access is missing")

    (
        presence_id,
        operational_day,
        identifier_type,
        identifier_value,
        public_call_code,
        ticket_master_id,
        prefix,
    ) = row
    return DailyPresence(
        id=presence_id,
        patient_identifier=PatientIdentifier(
            type=identifier_type, value=identifier_value
        ),
        operational_day=operational_day,
        public_call_code=public_call_code,
        ticket_master=TicketMaster(id=ticket_master_id, prefix=prefix),
    )


def load_agenda(cursor: "psycopg.Cursor", agenda_id: int) -> Agenda:
    cursor.execute(
        "SELECT id, name FROM agenda WHERE id = %s",
        (agenda_id,),
    )
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError("agenda for a service access is missing")
    return Agenda(id=row[0], name=row[1])


def load_appointment(
    cursor: "psycopg.Cursor",
    appointment_id: int,
) -> Appointment:
    cursor.execute(
        """
        SELECT
            appt.id,
            appt.scheduled_at,
            appt.patient_identifier_type,
            appt.patient_identifier_value,
            appt.external_patient_reference,
            appt.external_appointment_reference,
            ea.external_reference,
            ea.source_name,
            a.id,
            a.name,
            es.id,
            es.code,
            es.name,
            es.connector_type,
            es.enabled
        FROM appointment appt
        JOIN external_agenda ea ON ea.id = appt.external_agenda_id
        JOIN agenda a ON a.id = ea.agenda_id
        JOIN external_source es ON es.id = ea.external_source_id
        WHERE appt.id = %s
        """,
        (appointment_id,),
    )
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError("appointment for a service access is missing")

    (
        appt_id,
        scheduled_at,
        identifier_type,
        identifier_value,
        external_patient_reference,
        external_appointment_reference,
        external_reference,
        source_name,
        agenda_id,
        agenda_name,
        source_id,
        source_code,
        source_name_col,
        connector_type,
        enabled,
    ) = row

    external_agenda = ExternalAgenda(
        agenda=Agenda(id=agenda_id, name=agenda_name),
        source=ExternalSource(
            id=source_id,
            code=source_code,
            name=source_name_col,
            connector_type=connector_type,
            enabled=enabled,
        ),
        external_reference=external_reference,
        source_name=source_name,
    )
    return Appointment(
        id=appt_id,
        scheduled_at=scheduled_at,
        patient_identifier=PatientIdentifier(
            type=identifier_type, value=identifier_value
        ),
        external_agenda=external_agenda,
        external_patient_reference=external_patient_reference,
        external_appointment_reference=external_appointment_reference,
    )
