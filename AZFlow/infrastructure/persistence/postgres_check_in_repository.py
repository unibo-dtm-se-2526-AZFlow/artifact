"""PostgreSQL implementation of CheckInRepository

The caller owns the database connection. This adapter manages transactions and
converts database rows into domain objects.
"""

from __future__ import annotations

from datetime import date
from typing import List, Optional

import psycopg

from AZFlow.application.ports.appointment_source import ExternalAppointmentData
from AZFlow.application.ports.check_in_repository import (
    ResolvedAgenda,
    ResolvedQueue,
    format_public_call_code,
)
from AZFlow.domain.agenda import Agenda, ExternalAgenda
from AZFlow.domain.appointment import Appointment
from AZFlow.domain.daily_presence import DailyPresence
from AZFlow.domain.external_source import ExternalSource
from AZFlow.domain.patient_identifier import PatientIdentifier
from AZFlow.domain.queue import QueueStatus
from AZFlow.domain.service_access import ServiceAccess, ServiceAccessState
from AZFlow.domain.ticket_master import TicketMaster


class PostgresCheckInRepository:
    """Check-in repository backed by PostgreSQL"""

    def __init__(self, connection: "psycopg.Connection") -> None:
        self._conn = connection
        # Each write operation manages its own transaction
        self._conn.autocommit = False

    def resolve_agenda(
        self,
        external_source_code: str,
        external_agenda_reference: str,
    ) -> Optional[ResolvedAgenda]:
        """Return the configured agenda and its active queues, if found"""
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    ea.id,
                    ea.external_reference,
                    ea.source_name,
                    a.id,
                    a.name,
                    es.id,
                    es.code,
                    es.name,
                    es.connector_type,
                    es.enabled
                FROM external_agenda ea
                JOIN agenda a ON a.id = ea.agenda_id
                JOIN external_source es ON es.id = ea.external_source_id
                WHERE es.code = %s
                  AND ea.external_reference = %s
                  AND es.enabled = TRUE
                """,
                (external_source_code, external_agenda_reference),
            )
            row = cursor.fetchone()
            if row is None:
                return None

            (
                external_agenda_id,
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

            agenda = Agenda(id=agenda_id, name=agenda_name)
            source = ExternalSource(
                id=source_id,
                code=source_code,
                name=source_name_col,
                connector_type=connector_type,
                enabled=enabled,
            )
            external_agenda = ExternalAgenda(
                agenda=agenda,
                source=source,
                external_reference=external_reference,
                source_name=source_name,
            )

            cursor.execute(
                """
                SELECT q.id, tm.id, tm.prefix
                FROM queue q
                JOIN queue_agenda qa ON qa.queue_id = q.id
                JOIN ticket_master tm ON tm.id = q.ticket_master_id
                WHERE qa.agenda_id = %s AND q.status = %s
                ORDER BY q.id ASC
                """,
                (agenda_id, QueueStatus.ACTIVE.value),
            )
            active_queues: List[ResolvedQueue] = [
                ResolvedQueue(
                    queue_id=queue_id,
                    ticket_master=TicketMaster(id=ticket_master_id, prefix=prefix),
                )
                for (queue_id, ticket_master_id, prefix) in cursor.fetchall()
            ]

        return ResolvedAgenda(
            external_agenda=external_agenda,
            agenda=agenda,
            active_queues=active_queues,
        )

    def find_or_create_appointment(
        self,
        data: ExternalAppointmentData,
        patient_identifier: PatientIdentifier,
        external_agenda: ExternalAgenda,
    ) -> Appointment:
        """Import an appointment or reuse it from its external reference"""
        external_agenda_id = self._require_external_agenda_id(external_agenda)
        try:
            with self._conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        id,
                        scheduled_at,
                        patient_identifier_type,
                        patient_identifier_value,
                        external_patient_reference,
                        external_appointment_reference
                    FROM appointment
                    WHERE external_agenda_id = %s
                      AND external_appointment_reference = %s
                    """,
                    (external_agenda_id, data.external_appointment_reference),
                )
                existing = cursor.fetchone()
                if existing is not None:
                    appointment = self._appointment_from_row(existing, external_agenda)
                    self._conn.commit()
                    return appointment

                cursor.execute(
                    """
                    INSERT INTO appointment (
                        scheduled_at,
                        patient_identifier_type,
                        patient_identifier_value,
                        external_agenda_id,
                        external_patient_reference,
                        external_appointment_reference
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        data.scheduled_at,
                        patient_identifier.type,
                        patient_identifier.value,
                        external_agenda_id,
                        data.external_patient_reference,
                        data.external_appointment_reference,
                    ),
                )
                appointment_id = self._require_returned_id(cursor.fetchone())
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

        return Appointment(
            id=appointment_id,
            scheduled_at=data.scheduled_at,
            patient_identifier=patient_identifier,
            external_agenda=external_agenda,
            external_patient_reference=data.external_patient_reference,
            external_appointment_reference=data.external_appointment_reference,
        )

    def find_daily_presence(
        self,
        operational_day: date,
        patient_identifier: PatientIdentifier,
    ) -> Optional[DailyPresence]:
        """Return the daily presence for the day and identifier, if found"""
        with self._conn.cursor() as cursor:
            return self._select_daily_presence(
                cursor, operational_day, patient_identifier
            )

    def create_daily_presence_with_code(
        self,
        patient_identifier: PatientIdentifier,
        operational_day: date,
        ticket_master: TicketMaster,
    ) -> DailyPresence:
        """Create a daily presence with the next public call code"""
        try:
            with self._conn.cursor() as cursor:
                # Create or increment the daily sequence in one transaction
                cursor.execute(
                    """
                    INSERT INTO ticket_sequence (
                        ticket_master_id, operational_day, last_number
                    )
                    VALUES (%s, %s, 1)
                    ON CONFLICT (ticket_master_id, operational_day)
                    DO UPDATE SET last_number = ticket_sequence.last_number + 1
                    RETURNING last_number
                    """,
                    (ticket_master.id, operational_day),
                )
                sequence = self._require_returned_id(cursor.fetchone())
                public_call_code = format_public_call_code(
                    ticket_master.prefix, sequence
                )

                cursor.execute(
                    """
                    INSERT INTO daily_presence (
                        operational_day,
                        patient_identifier_type,
                        patient_identifier_value,
                        public_call_code,
                        ticket_master_id
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        operational_day,
                        patient_identifier.type,
                        patient_identifier.value,
                        public_call_code,
                        ticket_master.id,
                    ),
                )
                daily_presence_id = self._require_returned_id(cursor.fetchone())
            self._conn.commit()
        except psycopg.errors.UniqueViolation:
            # Another request created the same presence, so return that one
            self._conn.rollback()
            existing = self.find_daily_presence(operational_day, patient_identifier)
            if existing is None:
                raise
            return existing
        except Exception:
            self._conn.rollback()
            raise

        return DailyPresence(
            id=daily_presence_id,
            patient_identifier=patient_identifier,
            operational_day=operational_day,
            public_call_code=public_call_code,
            ticket_master=ticket_master,
        )

    def find_or_create_service_access(
        self,
        daily_presence: DailyPresence,
        agenda: Agenda,
        appointment: Appointment,
    ) -> ServiceAccess:
        """Create or reuse a service access for an appointment"""
        try:
            with self._conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id
                    FROM service_access
                    WHERE daily_presence_id = %s AND appointment_id = %s
                    """,
                    (daily_presence.id, appointment.id),
                )
                existing = cursor.fetchone()
                if existing is not None:
                    service_access_id = existing[0]
                else:
                    cursor.execute(
                        """
                        INSERT INTO service_access (
                            daily_presence_id, agenda_id, appointment_id, state
                        )
                        VALUES (%s, %s, %s, %s)
                        RETURNING id
                        """,
                        (
                            daily_presence.id,
                            agenda.id,
                            appointment.id,
                            ServiceAccessState.WAITING.value,
                        ),
                    )
                    service_access_id = self._require_returned_id(cursor.fetchone())
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

        return ServiceAccess(
            id=service_access_id,
            daily_presence=daily_presence,
            agenda=agenda,
            appointment=appointment,
            state=ServiceAccessState.WAITING,
        )

    # Internal helpers

    def _select_daily_presence(
        self,
        cursor: "psycopg.Cursor",
        operational_day: date,
        patient_identifier: PatientIdentifier,
    ) -> Optional[DailyPresence]:
        cursor.execute(
            """
            SELECT
                dp.id,
                dp.public_call_code,
                tm.id,
                tm.prefix
            FROM daily_presence dp
            JOIN ticket_master tm ON tm.id = dp.ticket_master_id
            WHERE dp.operational_day = %s
              AND dp.patient_identifier_type = %s
              AND dp.patient_identifier_value = %s
            """,
            (
                operational_day,
                patient_identifier.type,
                patient_identifier.value,
            ),
        )
        row = cursor.fetchone()
        if row is None:
            return None

        daily_presence_id, public_call_code, ticket_master_id, prefix = row
        return DailyPresence(
            id=daily_presence_id,
            patient_identifier=patient_identifier,
            operational_day=operational_day,
            public_call_code=public_call_code,
            ticket_master=TicketMaster(id=ticket_master_id, prefix=prefix),
        )

    @staticmethod
    def _appointment_from_row(
        row: tuple,
        external_agenda: ExternalAgenda,
    ) -> Appointment:
        (
            appointment_id,
            scheduled_at,
            identifier_type,
            identifier_value,
            external_patient_reference,
            external_appointment_reference,
        ) = row
        return Appointment(
            id=appointment_id,
            scheduled_at=scheduled_at,
            patient_identifier=PatientIdentifier(
                type=identifier_type, value=identifier_value
            ),
            external_agenda=external_agenda,
            external_patient_reference=external_patient_reference,
            external_appointment_reference=external_appointment_reference,
        )

    def _require_external_agenda_id(self, external_agenda: ExternalAgenda) -> int:
        agenda_id = external_agenda.agenda.id
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id
                FROM external_agenda
                WHERE agenda_id = %s AND external_source_id = %s
                """,
                (agenda_id, external_agenda.source.id),
            )
            row = cursor.fetchone()
        if row is None:
            raise LookupError(
                "external agenda is not configured for the resolved agenda"
            )
        external_agenda_id: int = row[0]
        return external_agenda_id

    @staticmethod
    def _require_returned_id(row: Optional[tuple]) -> int:
        if row is None:
            raise RuntimeError("expected a RETURNING row but got none")
        value: int = row[0]
        return value
