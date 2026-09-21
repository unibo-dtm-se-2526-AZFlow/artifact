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
