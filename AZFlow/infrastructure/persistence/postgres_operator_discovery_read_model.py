"""PostgreSQL operator discovery read model."""

from typing import List

import psycopg

from AZFlow.application.ports.operator_discovery_read_model import (
    OperatorQueue,
    OperatorRoom,
)
from AZFlow.domain.agenda import Agenda
from AZFlow.domain.queue import QueuePolicy, QueueStatus


class PostgresOperatorDiscoveryReadModel:
    """Read Room and Queue selector data from PostgreSQL."""

    def __init__(self, connection: "psycopg.Connection") -> None:
        self._conn = connection

    def list_rooms(self) -> List[OperatorRoom]:
        """Return Rooms ordered by label and id."""
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT r.id, r.room_reference, r.label,
                       sa.id, dp.public_call_code
                FROM room r
                LEFT JOIN LATERAL (
                    SELECT candidate.id, candidate.daily_presence_id
                    FROM service_access candidate
                    WHERE candidate.room_id = r.id
                      AND candidate.state = 'CALLED'
                    ORDER BY candidate.id DESC
                    LIMIT 1
                ) sa ON TRUE
                LEFT JOIN daily_presence dp ON dp.id = sa.daily_presence_id
                ORDER BY r.label, r.id
                """
            )
            rows = cursor.fetchall()

        return [
            OperatorRoom(
                id=room_id,
                room_reference=reference,
                label=label,
                active_service_access_id=active_service_access_id,
                active_public_call_code=active_public_call_code,
            )
            for room_id, reference, label, active_service_access_id, active_public_call_code in rows
        ]

    def list_queues(self) -> List[OperatorQueue]:
        """Return Queues and their Agendas ordered by Queue id."""
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT q.id, q.status, q.policy, a.id, a.name
                FROM queue q
                LEFT JOIN queue_agenda qa ON qa.queue_id = q.id
                LEFT JOIN agenda a ON a.id = qa.agenda_id
                ORDER BY q.id, a.id
                """
            )
            rows = cursor.fetchall()

        queues: dict[int, OperatorQueue] = {}
        for queue_id, status, policy, agenda_id, agenda_name in rows:
            queue = queues.get(queue_id)
            if queue is None:
                queue = OperatorQueue(
                    id=queue_id,
                    status=QueueStatus(status),
                    policy=QueuePolicy(policy),
                    agendas=[],
                )
                queues[queue_id] = queue
            if agenda_id is not None:
                queue.agendas.append(Agenda(id=agenda_id, name=agenda_name))

        return list(queues.values())
