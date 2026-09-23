"""PostgreSQL implementation of StateTransitionRepository

The caller owns the database connection. Each transition is one atomic
conditional UPDATE from an expected state to a target state; concurrency relies
only on that update, not on explicit row locks. A miss is classified afterwards
with a separate read-only state lookup.
"""

from __future__ import annotations

from typing import Optional

import psycopg

from AZFlow.application.ports.state_transition_repository import AdmissionOutcome
from AZFlow.domain.service_access import ServiceAccess, ServiceAccessState
from AZFlow.infrastructure.persistence.service_access_loader import (
    load_agenda,
    load_appointment,
    load_daily_presence,
)


class PostgresStateTransitionRepository:
    """State transition repository backed by PostgreSQL"""

    def __init__(self, connection: "psycopg.Connection") -> None:
        self._conn = connection
        # Each transition manages its own transaction
        self._conn.autocommit = False

    def try_suspend(self, service_access_id: int) -> Optional[ServiceAccess]:
        """Try the WAITING to SUSPENDED transition of one ServiceAccess.

        Return the transitioned ServiceAccess, or None when it was no longer
        WAITING.
        """
        return self._try_transition(
            service_access_id,
            ServiceAccessState.WAITING,
            ServiceAccessState.SUSPENDED,
        )

    def try_restore(self, service_access_id: int) -> Optional[ServiceAccess]:
        """Try the SUSPENDED to WAITING transition of one ServiceAccess.

        Return the transitioned ServiceAccess, or None when it was no longer
        SUSPENDED.
        """
        return self._try_transition(
            service_access_id,
            ServiceAccessState.SUSPENDED,
            ServiceAccessState.WAITING,
        )

    def try_admit(self, service_access_id: int) -> Optional[AdmissionOutcome]:
        """Try the CALLED to ADMITTED transition of one ServiceAccess.

        Reuses the room_id stored at call time. On a hit it also reads that
        Room's reference and label in the same transaction and returns them in
        an AdmissionOutcome. Return None when it was no longer CALLED.
        """
        try:
            with self._conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE service_access
                    SET state = %s
                    WHERE id = %s AND state = %s
                    RETURNING id, daily_presence_id, agenda_id, appointment_id,
                              room_id
                    """,
                    (
                        ServiceAccessState.ADMITTED.value,
                        service_access_id,
                        ServiceAccessState.CALLED.value,
                    ),
                )
                updated = cursor.fetchone()
                if updated is None:
                    self._conn.commit()
                    return None

                (
                    access_id,
                    daily_presence_id,
                    agenda_id,
                    appointment_id,
                    room_id,
                ) = updated
                cursor.execute(
                    """
                    INSERT INTO service_access_transition
                        (service_access_id, previous_state, resulting_state)
                    VALUES (%s, %s, %s)
                    """,
                    (
                        access_id,
                        ServiceAccessState.CALLED.value,
                        ServiceAccessState.ADMITTED.value,
                    ),
                )
                room_reference, room_label = self._read_room(cursor, room_id)
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

        service_access = ServiceAccess(
            id=access_id,
            daily_presence=daily_presence,
            agenda=agenda,
            appointment=appointment,
            state=ServiceAccessState.ADMITTED,
        )
        return AdmissionOutcome(
            service_access=service_access,
            room_reference=room_reference,
            room_label=room_label,
        )

    def find_state(self, service_access_id: int) -> Optional[ServiceAccessState]:
        """Return the current ServiceAccessState, or None when no ServiceAccess
        exists.

        Read-only. Used only to tell not-found from wrong-state on a miss.
        """
        try:
            with self._conn.cursor() as cursor:
                cursor.execute(
                    "SELECT state FROM service_access WHERE id = %s",
                    (service_access_id,),
                )
                row = cursor.fetchone()
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

        if row is None:
            return None
        return ServiceAccessState(row[0])

    # Internal helpers

    @staticmethod
    def _read_room(
        cursor: "psycopg.Cursor", room_id: Optional[int]
    ) -> "tuple[str, str]":
        """Read the reference and label of the persisted call-time Room.

        A CALLED access always has a valid persisted call-time Room. Raise when
        the room_id is missing or does not resolve to a configured Room, since
        that is an inconsistent persistence state, not a normal case.
        """
        if room_id is None:
            raise RuntimeError(
                "admitted service access has no persisted call-time room"
            )
        cursor.execute(
            "SELECT room_reference, label FROM room WHERE id = %s",
            (room_id,),
        )
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError(
                f"call-time room {room_id} for an admitted service access "
                "is not configured"
            )
        return row[0], row[1]

    def _try_transition(
        self,
        service_access_id: int,
        expected_state: ServiceAccessState,
        target_state: ServiceAccessState,
    ) -> Optional[ServiceAccess]:
        """Run one atomic conditional transition from expected to target state.

        Commits its own transaction on both the hit and the miss. On a hit it
        also records the matching transition record in the same transaction,
        then rebuilds the resulting ServiceAccess; on a miss it returns None. No
        explicit row locks are used.
        """
        try:
            with self._conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE service_access
                    SET state = %s
                    WHERE id = %s AND state = %s
                    RETURNING id, daily_presence_id, agenda_id, appointment_id
                    """,
                    (target_state.value, service_access_id, expected_state.value),
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
                    VALUES (%s, %s, %s)
                    """,
                    (access_id, expected_state.value, target_state.value),
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
            state=target_state,
        )
