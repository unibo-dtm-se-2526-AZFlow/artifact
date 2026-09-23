"""PostgreSQL integration tests for the existence and inverse-scope reads.

These run against a real database and are skipped without a DSN (see conftest).
They cover the read-model operations the WebSocket transport uses:

- Property 1 (Validates 1.2, 2.2, 5.1, 5.2): inverse scope returns the monitors
  covering a Room and excludes out-of-scope monitors.
- Property 5 (Validates 3.1, 3.2, 3.3, 3.4, 4.3, 4.4): existence is a plain
  configuration check, independent of whether a monitor has any calls.
"""

from __future__ import annotations

from datetime import date, datetime

from AZFlow.infrastructure.persistence.postgres_display_read_model import (
    PostgresDisplayReadModel,
)
from tests.infrastructure.persistence.seed import (
    seed_external_agenda,
    seed_location_node,
    seed_room,
    seed_room_monitor,
    seed_source,
    seed_ticket_master,
    seed_waiting_room_monitor,
    seed_waiting_room_monitor_scope,
)

OPERATIONAL_DAY = date(2024, 3, 15)


class _Topology:
    """Company > Site > { Radiotherapy > { R1, Brachytherapy > R3 }, Oncology > R4 }.

    ROOM-1 and ROOM-3 sit under the Radiotherapy branch; ROOM-2 under Oncology.
    A WaitingRoomMonitor scoped to Radiotherapy covers ROOM-1 and ROOM-3 but not
    ROOM-2. A RoomMonitor is bound to ROOM-1.
    """

    def __init__(self, conn: "object") -> None:
        company = seed_location_node(conn, "Company")
        site = seed_location_node(conn, "Site", parent_id=company)
        radiotherapy = seed_location_node(conn, "Radiotherapy", parent_id=site)
        oncology = seed_location_node(conn, "Oncology", parent_id=site)
        node_r1 = seed_location_node(conn, "Node-R1", parent_id=radiotherapy)
        brachytherapy = seed_location_node(
            conn, "Brachytherapy", parent_id=radiotherapy
        )
        node_r3 = seed_location_node(conn, "Node-R3", parent_id=brachytherapy)
        node_r4 = seed_location_node(conn, "Node-R4", parent_id=oncology)

        self.room1 = seed_room(conn, node_r1, "ROOM-1", "Room 1")
        self.room3 = seed_room(conn, node_r3, "ROOM-3", "Room 3")
        self.room2 = seed_room(conn, node_r4, "ROOM-2", "Room 2")

        self.waiting_room_monitor = seed_waiting_room_monitor(conn, "WRM Radiotherapy")
        seed_waiting_room_monitor_scope(conn, self.waiting_room_monitor, radiotherapy)

        self.room1_monitor = seed_room_monitor(conn, self.room1)


def _read_model(connection) -> PostgresDisplayReadModel:
    return PostgresDisplayReadModel(connection, recent_calls_max=10)


# Property 1 - inverse scope resolution.


def test_waiting_room_monitor_ids_cover_room_in_scope(connection):
    """A monitor scoped to an ancestor covers a Room under a descendant node."""
    topology = _Topology(connection)
    read_model = _read_model(connection)

    for room_reference in ("ROOM-1", "ROOM-3"):
        ids = read_model.waiting_room_monitor_ids_for_room(room_reference)
        assert ids == [topology.waiting_room_monitor]


def test_waiting_room_monitor_ids_exclude_out_of_scope_room(connection):
    """A Room under a sibling branch is not covered by the monitor."""
    _Topology(connection)
    read_model = _read_model(connection)

    assert read_model.waiting_room_monitor_ids_for_room("ROOM-2") == []


def test_waiting_room_monitor_ids_do_not_duplicate_on_overlapping_scope(connection):
    """A parent and a descendant both in scope must not duplicate a monitor."""
    topology = _Topology(connection)
    # Add the Brachytherapy node to the same monitor's scope, overlapping the
    # ancestor Radiotherapy that already covers ROOM-3.
    with connection.cursor() as cursor:
        cursor.execute("SELECT id FROM location_node WHERE label = 'Brachytherapy'")
        brachytherapy = cursor.fetchone()[0]
    seed_waiting_room_monitor_scope(
        connection, topology.waiting_room_monitor, brachytherapy
    )
    read_model = _read_model(connection)

    ids = read_model.waiting_room_monitor_ids_for_room("ROOM-3")
    assert ids == [topology.waiting_room_monitor]


def test_room_monitor_ids_return_only_the_bound_monitor(connection):
    """room_monitor_ids_for_room returns the monitor bound to the Room only."""
    topology = _Topology(connection)
    read_model = _read_model(connection)

    assert read_model.room_monitor_ids_for_room("ROOM-1") == [topology.room1_monitor]
    # A Room with no bound monitor returns an empty list.
    assert read_model.room_monitor_ids_for_room("ROOM-3") == []


# Property 5 - existence is a plain configuration check.


def test_waiting_room_monitor_exists_true_without_any_calls(connection):
    """A configured WaitingRoomMonitor exists even with no calls."""
    topology = _Topology(connection)
    read_model = _read_model(connection)

    assert read_model.waiting_room_monitor_exists(topology.waiting_room_monitor) is True


def test_room_monitor_exists_true_without_any_calls(connection):
    """A configured RoomMonitor exists even with no calls."""
    topology = _Topology(connection)
    read_model = _read_model(connection)

    assert read_model.room_monitor_exists(topology.room1_monitor) is True


def test_waiting_room_monitor_exists_true_with_a_call(connection):
    """Existence stays true once the monitor has a current-day call."""
    topology = _Topology(connection)
    _seed_call(connection, topology.room1, "AAA001")
    read_model = _read_model(connection)

    assert read_model.waiting_room_monitor_exists(topology.waiting_room_monitor) is True


def test_unknown_monitor_ids_do_not_exist(connection):
    """An unknown monitor id is not configured for either monitor kind."""
    _Topology(connection)
    read_model = _read_model(connection)

    assert read_model.waiting_room_monitor_exists(9999) is False
    assert read_model.room_monitor_exists(9999) is False


# Local seeding of one full call for a Room, used by the "with a call" case.


def _seed_call(conn, room_id: int, public_call_code: str) -> None:
    source = seed_source(conn)
    agenda_id = seed_external_agenda(conn, source, "Cardiology", "AGENDA-A").agenda.id
    ticket_master = seed_ticket_master(conn, "AAA")
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO daily_presence (
                operational_day, patient_identifier_type,
                patient_identifier_value, public_call_code, ticket_master_id
            )
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                OPERATIONAL_DAY,
                "fiscal_code",
                "SEED-1",
                public_call_code,
                ticket_master.id,
            ),
        )
        dp_id = cursor.fetchone()[0]
        cursor.execute(
            """
            INSERT INTO service_access (
                daily_presence_id, agenda_id, appointment_id, state, room_id
            )
            VALUES (%s, %s, NULL, 'CALLED', %s)
            RETURNING id
            """,
            (dp_id, agenda_id, room_id),
        )
        sa_id = cursor.fetchone()[0]
        cursor.execute(
            """
            INSERT INTO service_access_transition (
                service_access_id, previous_state, resulting_state, occurred_at
            )
            VALUES (%s, 'WAITING', 'CALLED', %s)
            """,
            (sa_id, datetime(2024, 3, 15, 9, 0)),
        )
    conn.commit()
