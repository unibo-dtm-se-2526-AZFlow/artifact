"""Minimal seeding helpers for persistence integration tests.

These insert only the predefined ExternalSource/Agenda/ExternalAgenda/
TicketMaster/Queue configuration a test needs and return domain objects that
mirror the inserted rows, so tests can drive the repository with domain values.
"""

from __future__ import annotations

from typing import List

from AZFlow.domain.agenda import Agenda, ExternalAgenda
from AZFlow.domain.external_source import ExternalSource
from AZFlow.domain.ticket_master import TicketMaster


def seed_source(conn: "object", code: str = "MOCK") -> ExternalSource:
    with conn.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute(
            """
            INSERT INTO external_source (code, name, connector_type, enabled)
            VALUES (%s, %s, %s, TRUE)
            RETURNING id
            """,
            (code, f"{code} source", "mock"),
        )
        source_id = cursor.fetchone()[0]
    conn.commit()  # type: ignore[attr-defined]
    return ExternalSource(
        id=source_id, code=code, name=f"{code} source", connector_type="mock"
    )


def seed_ticket_master(conn: "object", prefix: str) -> TicketMaster:
    with conn.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute(
            "INSERT INTO ticket_master (prefix) VALUES (%s) RETURNING id",
            (prefix,),
        )
        ticket_master_id = cursor.fetchone()[0]
    conn.commit()  # type: ignore[attr-defined]
    return TicketMaster(id=ticket_master_id, prefix=prefix)


def seed_external_agenda(
    conn: "object",
    source: ExternalSource,
    name: str,
    external_reference: str,
) -> ExternalAgenda:
    with conn.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute(
            "INSERT INTO agenda (name) VALUES (%s) RETURNING id",
            (name,),
        )
        agenda_id = cursor.fetchone()[0]
        cursor.execute(
            """
            INSERT INTO external_agenda (
                agenda_id, external_source_id, external_reference, source_name
            )
            VALUES (%s, %s, %s, %s)
            """,
            (agenda_id, source.id, external_reference, name),
        )
    conn.commit()  # type: ignore[attr-defined]
    agenda = Agenda(id=agenda_id, name=name)
    return ExternalAgenda(
        agenda=agenda,
        source=source,
        external_reference=external_reference,
        source_name=name,
    )


def seed_queue(
    conn: "object",
    ticket_master: TicketMaster,
    agenda_ids: List[int],
    status: str = "ACTIVE",
    policy: str = "BY_ARRIVAL",
) -> int:
    with conn.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute(
            """
            INSERT INTO queue (status, policy, ticket_master_id)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (status, policy, ticket_master.id),
        )
        queue_id = cursor.fetchone()[0]
        for agenda_id in agenda_ids:
            cursor.execute(
                "INSERT INTO queue_agenda (queue_id, agenda_id) VALUES (%s, %s)",
                (queue_id, agenda_id),
            )
    conn.commit()  # type: ignore[attr-defined]
    return queue_id


def seed_location_node(
    conn: "object", label: str, parent_id: "int | None" = None
) -> int:
    with conn.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute(
            "INSERT INTO location_node (parent_id, label) VALUES (%s, %s) RETURNING id",
            (parent_id, label),
        )
        location_node_id = cursor.fetchone()[0]
    conn.commit()  # type: ignore[attr-defined]
    return location_node_id


def seed_room(
    conn: "object", location_node_id: int, room_reference: str, label: str
) -> int:
    with conn.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute(
            """
            INSERT INTO room (room_reference, label, location_node_id)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (room_reference, label, location_node_id),
        )
        room_id = cursor.fetchone()[0]
    conn.commit()  # type: ignore[attr-defined]
    return room_id


def seed_room_workstation(conn: "object", room_id: int) -> int:
    with conn.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute(
            "INSERT INTO room_workstation (room_id) VALUES (%s) RETURNING id",
            (room_id,),
        )
        workstation_id = cursor.fetchone()[0]
    conn.commit()  # type: ignore[attr-defined]
    return workstation_id


def seed_room_monitor(conn: "object", room_id: int) -> int:
    with conn.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute(
            "INSERT INTO room_monitor (room_id) VALUES (%s) RETURNING id",
            (room_id,),
        )
        monitor_id = cursor.fetchone()[0]
    conn.commit()  # type: ignore[attr-defined]
    return monitor_id


def seed_waiting_room_monitor(conn: "object", label: str) -> int:
    with conn.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute(
            "INSERT INTO waiting_room_monitor (label) VALUES (%s) RETURNING id",
            (label,),
        )
        monitor_id = cursor.fetchone()[0]
    conn.commit()  # type: ignore[attr-defined]
    return monitor_id


def seed_waiting_room_monitor_scope(
    conn: "object", waiting_room_monitor_id: int, location_node_id: int
) -> None:
    with conn.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute(
            """
            INSERT INTO waiting_room_monitor_scope (
                waiting_room_monitor_id, location_node_id
            )
            VALUES (%s, %s)
            """,
            (waiting_room_monitor_id, location_node_id),
        )
    conn.commit()  # type: ignore[attr-defined]


def seed_totem(conn: "object", location_node_id: int, external_reference: str) -> int:
    with conn.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute(
            """
            INSERT INTO totem (external_reference, location_node_id)
            VALUES (%s, %s)
            RETURNING id
            """,
            (external_reference, location_node_id),
        )
        totem_id = cursor.fetchone()[0]
    conn.commit()  # type: ignore[attr-defined]
    return totem_id
