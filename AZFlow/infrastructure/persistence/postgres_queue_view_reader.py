"""PostgreSQL implementation of QueueViewReader

The caller owns the database connection. This adapter only reads and never
creates, duplicates or modifies a ServiceAccess.
"""

from __future__ import annotations

from datetime import date
from typing import List, Optional

import psycopg

from AZFlow.application.ports.queue_view_reader import CandidateServiceAccess
from AZFlow.domain.agenda import Agenda
from AZFlow.domain.queue import Queue, QueuePolicy, QueueStatus
from AZFlow.domain.service_access import ServiceAccessState
from AZFlow.domain.ticket_master import TicketMaster


class PostgresQueueViewReader:
    """Queue View reader backed by PostgreSQL"""

    def __init__(self, connection: "psycopg.Connection") -> None:
        self._conn = connection

    def load_queue(self, queue_id: int) -> Optional[Queue]:
        """Return the Queue with its Agendas, or None when not found"""
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

    def list_service_accesses(
        self,
        agenda_ids: List[int],
        operational_day: date,
    ) -> List[CandidateServiceAccess]:
        """Return the candidate ServiceAccesses for these Agendas and day"""
        if not agenda_ids:
            return []

        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    sa.id,
                    sa.daily_presence_id,
                    a.id,
                    a.name,
                    sa.state,
                    dp.public_call_code,
                    dp.checked_in_at,
                    appt.scheduled_at
                FROM service_access sa
                JOIN daily_presence dp ON dp.id = sa.daily_presence_id
                JOIN agenda a ON a.id = sa.agenda_id
                LEFT JOIN appointment appt ON appt.id = sa.appointment_id
                WHERE sa.agenda_id = ANY(%s) AND dp.operational_day = %s
                """,
                (agenda_ids, operational_day),
            )
            rows = cursor.fetchall()

        return [
            CandidateServiceAccess(
                service_access_id=service_access_id,
                daily_presence_id=daily_presence_id,
                agenda=Agenda(id=agenda_id, name=agenda_name),
                state=ServiceAccessState(state),
                public_call_code=public_call_code,
                checked_in_at=checked_in_at,
                scheduled_at=scheduled_at,
            )
            for (
                service_access_id,
                daily_presence_id,
                agenda_id,
                agenda_name,
                state,
                public_call_code,
                checked_in_at,
                scheduled_at,
            ) in rows
        ]
