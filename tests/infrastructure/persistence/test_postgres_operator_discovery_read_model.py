"""PostgreSQL integration tests for operator discovery."""

from AZFlow.infrastructure.persistence.postgres_operator_discovery_read_model import (
    PostgresOperatorDiscoveryReadModel,
)
from tests.infrastructure.persistence.seed import (
    seed_external_agenda,
    seed_queue,
    seed_source,
    seed_ticket_master,
)


def _seed_room(connection, reference: str, label: str) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO location_node (label) VALUES (%s) RETURNING id",
            (f"{label} node",),
        )
        location_node_id = cursor.fetchone()[0]
        cursor.execute(
            """
            INSERT INTO room (room_reference, label, location_node_id)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (reference, label, location_node_id),
        )
        room_id = cursor.fetchone()[0]
    connection.commit()
    return room_id


def test_list_rooms_returns_selector_data_in_display_order(connection):
    room_b = _seed_room(connection, "ROOM-B", "Room B")
    room_a = _seed_room(connection, "ROOM-A", "Room A")

    read_model = PostgresOperatorDiscoveryReadModel(connection)
    rooms = read_model.list_rooms()

    assert [(room.id, room.room_reference, room.label) for room in rooms] == [
        (room_a, "ROOM-A", "Room A"),
        (room_b, "ROOM-B", "Room B"),
    ]


def test_list_queues_returns_all_queues_with_agendas(connection):
    source = seed_source(connection)
    agenda_a = seed_external_agenda(connection, source, "Cardiology", "AGENDA-A").agenda
    agenda_b = seed_external_agenda(
        connection, source, "Diagnostics", "AGENDA-B"
    ).agenda
    ticket_master = seed_ticket_master(connection, "AAA")
    active_id = seed_queue(
        connection,
        ticket_master,
        [agenda_b.id, agenda_a.id],
        status="ACTIVE",
        policy="BY_APPOINTMENT",
    )
    inactive_id = seed_queue(
        connection,
        ticket_master,
        [],
        status="INACTIVE",
        policy="BY_ARRIVAL",
    )

    read_model = PostgresOperatorDiscoveryReadModel(connection)
    queues = read_model.list_queues()

    assert [queue.id for queue in queues] == sorted([active_id, inactive_id])
    by_id = {queue.id: queue for queue in queues}

    active = by_id[active_id]
    assert active.status.value == "ACTIVE"
    assert active.policy.value == "BY_APPOINTMENT"
    assert [agenda.id for agenda in active.agendas] == sorted(
        [agenda_a.id, agenda_b.id]
    )

    inactive = by_id[inactive_id]
    assert inactive.status.value == "INACTIVE"
    assert inactive.policy.value == "BY_ARRIVAL"
    assert inactive.agendas == []
