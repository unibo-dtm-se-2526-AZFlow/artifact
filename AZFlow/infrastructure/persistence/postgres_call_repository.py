"""PostgreSQL implementation of CallRepository

The caller owns the database connection. This adapter performs the atomic
conditional transition and builds the resulting ServiceAccess from database
rows. Concurrency relies only on an atomic conditional UPDATE, not on explicit
row locks.
"""

from __future__ import annotations

from typing import Optional

import psycopg

from AZFlow.domain.service_access import ServiceAccess, ServiceAccessState
from AZFlow.infrastructure.persistence.service_access_loader import (
    load_agenda,
    load_appointment,
    load_daily_presence,
)


class PostgresCallRepository:
    """Call repository backed by PostgreSQL"""

    def __init__(self, connection: "psycopg.Connection") -> None:
        self._conn = connection
        # Each write operation manages its own transaction
        self._conn.autocommit = False

    def resolve_room(self, room_reference: str) -> Optional[int]:
        """Return the configured Room id for a room reference, or None.

        Read-only. Done before attempting the transition.
        """
        try:
            with self._conn.cursor() as cursor:
                cursor.execute(
                    "SELECT id FROM room WHERE room_reference = %s",
                    (room_reference,),
                )
                row = cursor.fetchone()
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

        if row is None:
            return None
        return row[0]

    def try_call(self, service_access_id: int, room_id: int) -> Optional[ServiceAccess]:
        """Try the WAITING to CALLED transition of one ServiceAccess.

        Runs a single atomic conditional UPDATE that also sets the call-time
        room_id. On a hit it records the WAITING to CALLED transition in the
        same transaction. Return the transitioned ServiceAccess when the row
        moved to CALLED, or None when it was no longer WAITING. No explicit row
        locks are used.
        """
        try:
            with self._conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE service_access
                    SET state = 'CALLED', room_id = %s
                    WHERE id = %s AND state = 'WAITING'
                    RETURNING id, daily_presence_id, agenda_id, appointment_id
                    """,
                    (room_id, service_access_id),
                )
                updated = cursor.fetchone()
                if updated is None:
                    self._conn.commit()
                    return None

                access_id, daily_presence_id, agenda_id, appointment_id = updated
                cursor.execute(
                    """
                    INSERT INTO service_access_transition
                        (service_access_id, previous_state, resulting_state)
                    VALUES (%s, 'WAITING', 'CALLED')
                    """,
                    (access_id,),
                )
                daily_presence = load_daily_presence(cursor, daily_presence_id)
                agenda = load_agenda(cursor, agenda_id)
                appointment = (
                    load_appointment(cursor, appointment_id)
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
