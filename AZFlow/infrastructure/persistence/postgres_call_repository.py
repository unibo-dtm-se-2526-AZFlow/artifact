"""PostgreSQL implementation of CallRepository

The caller owns the database connection. This adapter manages transactions and
converts database rows into domain objects. Concurrency relies only on an
atomic conditional UPDATE, not on explicit row locks.
"""

from __future__ import annotations

from typing import Optional

import psycopg

from AZFlow.domain.agenda import Agenda, ExternalAgenda
from AZFlow.domain.appointment import Appointment
from AZFlow.domain.daily_presence import DailyPresence
from AZFlow.domain.external_source import ExternalSource
from AZFlow.domain.patient_identifier import PatientIdentifier
from AZFlow.domain.queue import Queue, QueuePolicy, QueueStatus
from AZFlow.domain.service_access import ServiceAccess, ServiceAccessState
from AZFlow.domain.ticket_master import TicketMaster


class PostgresCallRepository:
    """Call repository backed by PostgreSQL"""

    def __init__(self, connection: "psycopg.Connection") -> None:
        self._conn = connection
        # Each write operation manages its own transaction
        self._conn.autocommit = False

    def load_queue(self, queue_id: int) -> Optional[Queue]:
        """Return the Queue with its served Agendas, or None when not found"""
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT q.id, q.status, q.policy, tm.id, tm.prefix
                FROM queue q
                JOIN ticket_master tm ON tm.id = q.ticket_master_id
                WHERE q.id = %s
                """,
                (queue_id,),
            )
            row = cursor.fetchone()
            if row is None:
                return None

            queue_row_id, status, policy, ticket_master_id, prefix = row

            cursor.execute(
                """
                SELECT a.id, a.name
                FROM queue_agenda qa
                JOIN agenda a ON a.id = qa.agenda_id
                WHERE qa.queue_id = %s
                """,
                (queue_row_id,),
            )
            agendas = [
                Agenda(id=agenda_id, name=name)
                for (agenda_id, name) in cursor.fetchall()
            ]

        return Queue(
            id=queue_row_id,
            status=QueueStatus(status),
            policy=QueuePolicy(policy),
            ticket_master=TicketMaster(id=ticket_master_id, prefix=prefix),
            agendas=agendas,
        )

    def try_call(self, service_access_id: int) -> Optional[ServiceAccess]:
        """Try the WAITING to CALLED transition of one ServiceAccess.

        Runs a single atomic conditional UPDATE. Return the transitioned
        ServiceAccess when the row moved to CALLED, or None when it was no
        longer WAITING. No explicit row locks are used.
        """
        try:
            with self._conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE service_access
                    SET state = 'CALLED'
                    WHERE id = %s AND state = 'WAITING'
                    RETURNING id, daily_presence_id, agenda_id, appointment_id
                    """,
                    (service_access_id,),
                )
                updated = cursor.fetchone()
                if updated is None:
                    self._conn.commit()
                    return None

                access_id, daily_presence_id, agenda_id, appointment_id = updated
                daily_presence = self._load_daily_presence(cursor, daily_presence_id)
                agenda = self._load_agenda(cursor, agenda_id)
                appointment = (
                    self._load_appointment(cursor, appointment_id)
                    if appointment_id is not None
                    else None
                )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

        return ServiceAccess(
            id=access_id,
            daily_presence=daily_presence,
            agenda=agenda,
            appointment=appointment,
            state=ServiceAccessState.CALLED,
        )

    # Internal helpers

    @staticmethod
    def _load_daily_presence(
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
            raise RuntimeError("daily presence for a called service access is missing")

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

    @staticmethod
    def _load_agenda(cursor: "psycopg.Cursor", agenda_id: int) -> Agenda:
        cursor.execute(
            "SELECT id, name FROM agenda WHERE id = %s",
            (agenda_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError("agenda for a called service access is missing")
        return Agenda(id=row[0], name=row[1])

    @staticmethod
    def _load_appointment(
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
            raise RuntimeError("appointment for a called service access is missing")

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
