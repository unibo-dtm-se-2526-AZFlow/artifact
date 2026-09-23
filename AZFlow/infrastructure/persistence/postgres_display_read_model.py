"""PostgreSQL implementation of DisplayReadModel

The caller owns the database connection. This adapter only reads and derives
display views from the persisted transition history joined to the call-time
Room and topology. It exposes only non-identifying display data.
"""

from __future__ import annotations

from datetime import date
from typing import List, Optional

import psycopg

from AZFlow.application.ports.display_read_model import DisplayCall
from AZFlow.domain.agenda import Agenda
from AZFlow.domain.service_access import ServiceAccessState


class PostgresDisplayReadModel:
    """Display read model backed by PostgreSQL

    The recent-calls bound comes from configuration, stored on the adapter,
    not from the caller.
    """

    def __init__(self, connection: "psycopg.Connection", recent_calls_max: int) -> None:
        self._conn = connection
        self._recent_calls_max = recent_calls_max

    def recent_calls_for_monitor(
        self,
        waiting_room_monitor_id: int,
        operational_day: date,
    ) -> List[DisplayCall]:
        """Return the recent calls for a configured WaitingRoomMonitor.

        A recursive CTE seeds the monitor's scope nodes and expands their
        descendants, so overlapping scopes are not counted twice. The result
        is most-recent-first for the day, bounded by the configured maximum.
        """
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                WITH RECURSIVE scope_nodes AS (
                    SELECT location_node_id AS id
                    FROM waiting_room_monitor_scope
                    WHERE waiting_room_monitor_id = %(waiting_room_monitor_id)s
                    UNION
                    SELECT ln.id
                    FROM location_node ln
                    JOIN scope_nodes s ON ln.parent_id = s.id
                )
                SELECT dp.public_call_code, a.id, a.name,
                       r.room_reference, r.label, t.occurred_at
                FROM service_access_transition t
                JOIN service_access sa ON sa.id = t.service_access_id
                JOIN daily_presence dp ON dp.id = sa.daily_presence_id
                JOIN agenda a          ON a.id = sa.agenda_id
                JOIN room r            ON r.id = sa.room_id
                WHERE t.resulting_state = 'CALLED'
                  AND dp.operational_day = %(operational_day)s
                  AND r.location_node_id IN (SELECT id FROM scope_nodes)
                ORDER BY t.occurred_at DESC, t.id DESC
                LIMIT %(max_size)s
                """,
                {
                    "waiting_room_monitor_id": waiting_room_monitor_id,
                    "operational_day": operational_day,
                    "max_size": self._recent_calls_max,
                },
            )
            rows = cursor.fetchall()

        return [self._to_display_call(row) for row in rows]

    def latest_call_for_room_monitor(
        self,
        room_monitor_id: int,
        operational_day: date,
    ) -> Optional[DisplayCall]:
        """Return the latest call for a configured RoomMonitor's Room.

        It resolves the monitor to its Room and returns the single most recent
        current-day CALLED transition, or None when there is none.
        """
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT dp.public_call_code, a.id, a.name,
                       r.room_reference, r.label, t.occurred_at
                FROM room_monitor rm
                JOIN room r            ON r.id = rm.room_id
                JOIN service_access sa ON sa.room_id = r.id
                JOIN service_access_transition t ON t.service_access_id = sa.id
                JOIN daily_presence dp ON dp.id = sa.daily_presence_id
                JOIN agenda a          ON a.id = sa.agenda_id
                WHERE rm.id = %(room_monitor_id)s
                  AND t.resulting_state = 'CALLED'
                  AND dp.operational_day = %(operational_day)s
                ORDER BY t.occurred_at DESC, t.id DESC
                LIMIT 1
                """,
                {
                    "room_monitor_id": room_monitor_id,
                    "operational_day": operational_day,
                },
            )
            row = cursor.fetchone()

        return None if row is None else self._to_display_call(row)

    def display_call_for_service_access(
        self,
        service_access_id: int,
        operational_day: date,
    ) -> Optional[DisplayCall]:
        """Return the CALLED display call for one ServiceAccess.

        It resolves the single most recent current-day CALLED transition of
        exactly this ServiceAccess, so the returned room_label and occurred_at
        are the authoritative persisted values for that specific call. None
        when there is no current-day CALLED transition for the ServiceAccess.
        """
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT dp.public_call_code, a.id, a.name,
                       r.room_reference, r.label, t.occurred_at
                FROM service_access sa
                JOIN service_access_transition t ON t.service_access_id = sa.id
                JOIN room r            ON r.id = sa.room_id
                JOIN daily_presence dp ON dp.id = sa.daily_presence_id
                JOIN agenda a          ON a.id = sa.agenda_id
                WHERE sa.id = %(service_access_id)s
                  AND t.resulting_state = 'CALLED'
                  AND dp.operational_day = %(operational_day)s
                ORDER BY t.occurred_at DESC, t.id DESC
                LIMIT 1
                """,
                {
                    "service_access_id": service_access_id,
                    "operational_day": operational_day,
                },
            )
            row = cursor.fetchone()

        return None if row is None else self._to_display_call(row)

    def waiting_room_monitor_exists(self, waiting_room_monitor_id: int) -> bool:
        """Return whether a WaitingRoomMonitor with this id is configured."""
        with self._conn.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM waiting_room_monitor WHERE id = %s",
                (waiting_room_monitor_id,),
            )
            return cursor.fetchone() is not None

    def room_monitor_exists(self, room_monitor_id: int) -> bool:
        """Return whether a RoomMonitor with this id is configured."""
        with self._conn.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM room_monitor WHERE id = %s",
                (room_monitor_id,),
            )
            return cursor.fetchone() is not None

    def waiting_room_monitor_ids_for_room(self, room_reference: str) -> List[int]:
        """Return the WaitingRoomMonitors whose scope covers a Room.

        A recursive CTE walks up from the Room's LocationNode to all its
        ancestors. A monitor covers the Room when one of its scope nodes is any
        of those nodes, so the descendant rule stays in the topology.
        """
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                WITH RECURSIVE room_node AS (
                    SELECT location_node_id AS id
                    FROM room
                    WHERE room_reference = %(room_reference)s
                ),
                ancestors AS (
                    SELECT id FROM room_node
                    UNION
                    SELECT ln.parent_id
                    FROM location_node ln
                    JOIN ancestors a ON ln.id = a.id
                    WHERE ln.parent_id IS NOT NULL
                )
                SELECT DISTINCT s.waiting_room_monitor_id
                FROM waiting_room_monitor_scope s
                WHERE s.location_node_id IN (SELECT id FROM ancestors)
                ORDER BY s.waiting_room_monitor_id
                """,
                {"room_reference": room_reference},
            )
            return [row[0] for row in cursor.fetchall()]

    def room_monitor_ids_for_room(self, room_reference: str) -> List[int]:
        """Return the RoomMonitors bound to a Room."""
        with self._conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT rm.id
                FROM room_monitor rm
                JOIN room r ON r.id = rm.room_id
                WHERE r.room_reference = %(room_reference)s
                ORDER BY rm.id
                """,
                {"room_reference": room_reference},
            )
            return [row[0] for row in cursor.fetchall()]

    @staticmethod
    def _to_display_call(row: tuple) -> DisplayCall:
        """Build a DisplayCall from a selected display row."""
        (
            public_call_code,
            agenda_id,
            agenda_name,
            room_reference,
            room_label,
            occurred_at,
        ) = row
        return DisplayCall(
            public_call_code=public_call_code,
            agenda=Agenda(id=agenda_id, name=agenda_name),
            state=ServiceAccessState.CALLED,
            room_reference=room_reference,
            room_label=room_label,
            occurred_at=occurred_at,
        )
