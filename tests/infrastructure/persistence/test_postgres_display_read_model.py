"""PostgreSQL integration tests for PostgresDisplayReadModel.

These run against a real database and are skipped when no DSN is provided
(see conftest). The display views are derived from the persisted transition
history joined to the call-time Room and the topology. The tests seed
transitions with controlled ``occurred_at`` so ordering and day-filtering are
deterministic.

They cover:
- Property 3 (Validates 1.11, 7.4, 8.3, 9.2, 9.4, 12.1): authoritative call
  time drives ordering, latest-call, and current-day filtering.
- Property 7 (Validates 7.1, 7.2, 7.3, 12.1): descendant scoping and
  deduplication of overlapping scope nodes.
- Property 8 (Validates 7.4-7.7, 9.1-9.4, 12.3): recent calls bounded by the
  configured maximum, empty when none in scope.
- Property 9 (Validates 8.2-8.5, 12.2, 12.4): latest call for a Room is the
  single most recent current-day CALLED, None when none today.
- Property 10 / privacy: DisplayCall exposes only the non-identifying fields
  and never the Patient Identifier.
- Property 11 (Validates 9.5, 13.4) partial: an admission does not remove an
  earlier CALLED from recent calls.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Tuple

from AZFlow.application.ports.display_read_model import DisplayCall
from AZFlow.domain.service_access import ServiceAccessState
from AZFlow.infrastructure.persistence.postgres_display_read_model import (
    PostgresDisplayReadModel,
)
from tests.infrastructure.persistence.seed import (
    seed_external_agenda,
    seed_location_node,
    seed_room,
    seed_room_monitor,
    seed_room_workstation,
    seed_source,
    seed_ticket_master,
    seed_waiting_room_monitor,
    seed_waiting_room_monitor_scope,
)

OPERATIONAL_DAY = date(2024, 3, 15)
OTHER_DAY = date(2024, 3, 16)
PATIENT_IDENTIFIER = "RSSMRA80A01H501U"


# Local seeding helpers for rows without a shared helper, mirroring the style
# in test_postgres_call_repository.py (INSERT ... RETURNING id, conn.commit()).


def _seed_daily_presence(
    conn: "object",
    ticket_master_id: int,
    public_call_code: str,
    operational_day: date,
    identifier_value: str = PATIENT_IDENTIFIER,
) -> int:
    """Insert a daily_presence row and return its id."""
    with conn.cursor() as cursor:  # type: ignore[attr-defined]
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
                "fiscal_code",
                identifier_value,
                public_call_code,
                ticket_master_id,
            ),
        )
        daily_presence_id = cursor.fetchone()[0]
    conn.commit()  # type: ignore[attr-defined]
    return daily_presence_id


def _seed_service_access(
    conn: "object",
    daily_presence_id: int,
    agenda_id: int,
    room_id: int,
    state: str = "CALLED",
) -> int:
    """Insert a service_access row with a call-time room and return its id."""
    with conn.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute(
            """
            INSERT INTO service_access (
                daily_presence_id, agenda_id, appointment_id, state, room_id
            )
            VALUES (%s, %s, NULL, %s, %s)
            RETURNING id
            """,
            (daily_presence_id, agenda_id, state, room_id),
        )
        service_access_id = cursor.fetchone()[0]
    conn.commit()  # type: ignore[attr-defined]
    return service_access_id


def _seed_transition(
    conn: "object",
    service_access_id: int,
    resulting_state: str,
    occurred_at: datetime,
    previous_state: "str | None" = None,
) -> int:
    """Insert a transition row with an explicit occurred_at and return its id."""
    with conn.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute(
            """
            INSERT INTO service_access_transition (
                service_access_id, previous_state, resulting_state, occurred_at
            )
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (service_access_id, previous_state, resulting_state, occurred_at),
        )
        transition_id = cursor.fetchone()[0]
    conn.commit()  # type: ignore[attr-defined]
    return transition_id


def _seed_call(
    conn: "object",
    room_id: int,
    agenda_id: int,
    ticket_master_id: int,
    occurred_at: datetime,
    operational_day: date,
    public_call_code: str,
    identifier_value: "str | None" = None,
) -> Tuple[int, int]:
    """Seed a full call for a Room: presence + CALLED access + CALLED transition.

    Returns the (service_access_id, transition_id) pair so a test can add
    further transitions (for example an admission) to the same access.

    Each call gets a distinct patient identifier by default, since
    daily_presence is unique per (day, identifier type, identifier value).
    """
    if identifier_value is None:
        identifier_value = f"{PATIENT_IDENTIFIER}-{public_call_code}"
    dp_id = _seed_daily_presence(
        conn,
        ticket_master_id,
        public_call_code,
        operational_day,
        identifier_value=identifier_value,
    )
    sa_id = _seed_service_access(conn, dp_id, agenda_id, room_id, state="CALLED")
    transition_id = _seed_transition(
        conn, sa_id, "CALLED", occurred_at, previous_state="WAITING"
    )
    return sa_id, transition_id


# Topology built once per test, mirroring the design/seed example:
#   Company > Site > { Radiotherapy > { Node-R1, Brachytherapy > { Node-R3 } },
#                      Oncology > { Node-R4 } }
# ROOM-1 sits under the Radiotherapy branch (Node-R1), ROOM-3 under the
# Brachytherapy sub-branch (Node-R3), ROOM-2 under the Oncology branch
# (Node-R4). A WaitingRoomMonitor scoped to Radiotherapy therefore sees ROOM-1
# and ROOM-3 but not ROOM-2.


class _Topology:
    def __init__(self, conn: "object") -> None:
        company = seed_location_node(conn, "Company")
        site = seed_location_node(conn, "Site", parent_id=company)
        self.radiotherapy = seed_location_node(conn, "Radiotherapy", parent_id=site)
        self.oncology = seed_location_node(conn, "Oncology", parent_id=site)
        node_r1 = seed_location_node(conn, "Node-R1", parent_id=self.radiotherapy)
        brachytherapy = seed_location_node(
            conn, "Brachytherapy", parent_id=self.radiotherapy
        )
        node_r3 = seed_location_node(conn, "Node-R3", parent_id=brachytherapy)
        node_r4 = seed_location_node(conn, "Node-R4", parent_id=self.oncology)

        self.room1 = seed_room(conn, node_r1, "ROOM-1", "Room 1")
        self.room3 = seed_room(conn, node_r3, "ROOM-3", "Room 3")
        self.room2 = seed_room(conn, node_r4, "ROOM-2", "Room 2")
        seed_room_workstation(conn, self.room1)
        seed_room_workstation(conn, self.room3)
        seed_room_workstation(conn, self.room2)

        # A monitor scoped to Radiotherapy sees ROOM-1 and ROOM-3, not ROOM-2.
        self.waiting_room_monitor = seed_waiting_room_monitor(conn, "WRM Radiotherapy")
        seed_waiting_room_monitor_scope(
            conn, self.waiting_room_monitor, self.radiotherapy
        )

        # A room monitor on ROOM-1.
        self.room1_monitor = seed_room_monitor(conn, self.room1)


def _agenda_id(conn: "object") -> int:
    source = seed_source(conn)
    return seed_external_agenda(conn, source, "Cardiology", "AGENDA-A").agenda.id


def _at(hour: int, minute: int = 0) -> datetime:
    """A timestamp on the operational day, for controlled ordering."""
    return datetime(2024, 3, 15, hour, minute)


# Property 3 - authoritative call time drives ordering, latest and day filter.
# Validates: Requirements 1.11, 7.4, 8.3, 9.2, 9.4, 12.1


def test_recent_calls_ordered_by_authoritative_call_time(connection):
    """recent_calls_for_monitor returns most-recent occurred_at first."""
    topology = _Topology(connection)
    agenda_id = _agenda_id(connection)
    ticket_master = seed_ticket_master(connection, "AAA")

    _seed_call(
        connection,
        topology.room1,
        agenda_id,
        ticket_master.id,
        _at(9),
        OPERATIONAL_DAY,
        "AAA001",
    )
    _seed_call(
        connection,
        topology.room1,
        agenda_id,
        ticket_master.id,
        _at(11),
        OPERATIONAL_DAY,
        "AAA003",
    )
    _seed_call(
        connection,
        topology.room3,
        agenda_id,
        ticket_master.id,
        _at(10),
        OPERATIONAL_DAY,
        "AAA002",
    )

    read_model = PostgresDisplayReadModel(connection, recent_calls_max=10)
    calls = read_model.recent_calls_for_monitor(
        topology.waiting_room_monitor, OPERATIONAL_DAY
    )

    assert [call.occurred_at for call in calls] == [_at(11), _at(10), _at(9)]
    assert [call.public_call_code for call in calls] == ["AAA003", "AAA002", "AAA001"]


def test_recent_calls_tie_break_by_transition_id_desc(connection):
    """Equal occurred_at is broken by transition id descending."""
    topology = _Topology(connection)
    agenda_id = _agenda_id(connection)
    ticket_master = seed_ticket_master(connection, "AAA")

    same_time = _at(9)
    _, first_id = _seed_call(
        connection,
        topology.room1,
        agenda_id,
        ticket_master.id,
        same_time,
        OPERATIONAL_DAY,
        "AAA001",
    )
    _, second_id = _seed_call(
        connection,
        topology.room3,
        agenda_id,
        ticket_master.id,
        same_time,
        OPERATIONAL_DAY,
        "AAA002",
    )

    assert second_id > first_id

    read_model = PostgresDisplayReadModel(connection, recent_calls_max=10)
    calls = read_model.recent_calls_for_monitor(
        topology.waiting_room_monitor, OPERATIONAL_DAY
    )

    # The later transition id comes first when the call time is equal.
    assert [call.public_call_code for call in calls] == ["AAA002", "AAA001"]


def test_recent_calls_exclude_a_different_operational_day(connection):
    """Calls from another operational day are not shown."""
    topology = _Topology(connection)
    agenda_id = _agenda_id(connection)
    ticket_master = seed_ticket_master(connection, "AAA")

    _seed_call(
        connection,
        topology.room1,
        agenda_id,
        ticket_master.id,
        datetime(2024, 3, 16, 9),
        OTHER_DAY,
        "AAA001",
        identifier_value="OTHER-DAY",
    )
    _seed_call(
        connection,
        topology.room1,
        agenda_id,
        ticket_master.id,
        _at(9),
        OPERATIONAL_DAY,
        "AAA002",
    )

    read_model = PostgresDisplayReadModel(connection, recent_calls_max=10)
    calls = read_model.recent_calls_for_monitor(
        topology.waiting_room_monitor, OPERATIONAL_DAY
    )

    assert [call.public_call_code for call in calls] == ["AAA002"]


def test_latest_call_for_room_monitor_returns_single_most_recent(connection):
    """latest_call_for_room_monitor returns the single most recent call."""
    topology = _Topology(connection)
    agenda_id = _agenda_id(connection)
    ticket_master = seed_ticket_master(connection, "AAA")

    _seed_call(
        connection,
        topology.room1,
        agenda_id,
        ticket_master.id,
        _at(9),
        OPERATIONAL_DAY,
        "AAA001",
    )
    _seed_call(
        connection,
        topology.room1,
        agenda_id,
        ticket_master.id,
        _at(12),
        OPERATIONAL_DAY,
        "AAA002",
    )

    read_model = PostgresDisplayReadModel(connection, recent_calls_max=10)
    latest = read_model.latest_call_for_room_monitor(
        topology.room1_monitor, OPERATIONAL_DAY
    )

    assert latest is not None
    assert latest.public_call_code == "AAA002"
    assert latest.occurred_at == _at(12)


def test_latest_call_for_room_monitor_excludes_other_day(connection):
    """A call from another operational day is not the latest for today."""
    topology = _Topology(connection)
    agenda_id = _agenda_id(connection)
    ticket_master = seed_ticket_master(connection, "AAA")

    _seed_call(
        connection,
        topology.room1,
        agenda_id,
        ticket_master.id,
        datetime(2024, 3, 16, 9),
        OTHER_DAY,
        "AAA001",
    )

    read_model = PostgresDisplayReadModel(connection, recent_calls_max=10)
    latest = read_model.latest_call_for_room_monitor(
        topology.room1_monitor, OPERATIONAL_DAY
    )

    assert latest is None


# Property 7 - descendant scoping and deduplication.
# Validates: Requirements 7.1, 7.2, 7.3, 12.1


def test_scope_includes_descendant_rooms_and_excludes_sibling_branch(connection):
    """A monitor scoped to a parent node sees rooms under child and grandchild
    nodes, but not a room under a sibling branch."""
    topology = _Topology(connection)
    agenda_id = _agenda_id(connection)
    ticket_master = seed_ticket_master(connection, "AAA")

    # ROOM-1 (child branch) and ROOM-3 (grandchild branch) are in scope.
    _seed_call(
        connection,
        topology.room1,
        agenda_id,
        ticket_master.id,
        _at(9),
        OPERATIONAL_DAY,
        "AAA001",
    )
    _seed_call(
        connection,
        topology.room3,
        agenda_id,
        ticket_master.id,
        _at(10),
        OPERATIONAL_DAY,
        "AAA003",
    )
    # ROOM-2 sits under the Oncology sibling branch and is excluded.
    _seed_call(
        connection,
        topology.room2,
        agenda_id,
        ticket_master.id,
        _at(11),
        OPERATIONAL_DAY,
        "AAA002",
        identifier_value="ONCOLOGY",
    )

    read_model = PostgresDisplayReadModel(connection, recent_calls_max=10)
    calls = read_model.recent_calls_for_monitor(
        topology.waiting_room_monitor, OPERATIONAL_DAY
    )

    codes = {call.public_call_code for call in calls}
    assert codes == {"AAA001", "AAA003"}
    assert "AAA002" not in codes


def test_overlapping_scope_nodes_do_not_duplicate_a_call(connection):
    """A parent AND a descendant both in scope must not duplicate a call."""
    topology = _Topology(connection)
    agenda_id = _agenda_id(connection)
    ticket_master = seed_ticket_master(connection, "AAA")

    # Add the Brachytherapy grandchild node to the same monitor's scope, so
    # both Radiotherapy (ancestor) and Brachytherapy (descendant of it) cover
    # ROOM-3 through the recursive expansion.
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id FROM location_node WHERE label = 'Brachytherapy'",
        )
        brachytherapy = cursor.fetchone()[0]
    seed_waiting_room_monitor_scope(
        connection, topology.waiting_room_monitor, brachytherapy
    )

    _seed_call(
        connection,
        topology.room3,
        agenda_id,
        ticket_master.id,
        _at(10),
        OPERATIONAL_DAY,
        "AAA003",
    )

    read_model = PostgresDisplayReadModel(connection, recent_calls_max=10)
    calls = read_model.recent_calls_for_monitor(
        topology.waiting_room_monitor, OPERATIONAL_DAY
    )

    codes = [call.public_call_code for call in calls]
    assert codes.count("AAA003") == 1
    assert codes == ["AAA003"]


# Property 8 - recent calls bounded by the configured maximum.
# Validates: Requirements 7.4, 7.5, 7.6, 7.7, 9.1, 9.2, 9.3, 9.4, 12.3


def test_recent_calls_bounded_by_configured_maximum(connection):
    """Only the configured number of most-recent calls is returned; the oldest
    ages out."""
    topology = _Topology(connection)
    agenda_id = _agenda_id(connection)
    ticket_master = seed_ticket_master(connection, "AAA")

    _seed_call(
        connection,
        topology.room1,
        agenda_id,
        ticket_master.id,
        _at(9),
        OPERATIONAL_DAY,
        "AAA001",
    )
    _seed_call(
        connection,
        topology.room1,
        agenda_id,
        ticket_master.id,
        _at(10),
        OPERATIONAL_DAY,
        "AAA002",
    )
    _seed_call(
        connection,
        topology.room3,
        agenda_id,
        ticket_master.id,
        _at(11),
        OPERATIONAL_DAY,
        "AAA003",
    )

    read_model = PostgresDisplayReadModel(connection, recent_calls_max=2)
    calls = read_model.recent_calls_for_monitor(
        topology.waiting_room_monitor, OPERATIONAL_DAY
    )

    assert [call.public_call_code for call in calls] == ["AAA003", "AAA002"]
    # The oldest call has aged out beyond the configured bound.
    assert "AAA001" not in {call.public_call_code for call in calls}


def test_recent_calls_empty_when_no_current_day_call_in_scope(connection):
    """No current-day call in scope yields an empty list."""
    topology = _Topology(connection)
    agenda_id = _agenda_id(connection)
    ticket_master = seed_ticket_master(connection, "AAA")

    # A call to a room outside scope, on the current day.
    _seed_call(
        connection,
        topology.room2,
        agenda_id,
        ticket_master.id,
        _at(9),
        OPERATIONAL_DAY,
        "AAA002",
        identifier_value="ONCOLOGY",
    )

    read_model = PostgresDisplayReadModel(connection, recent_calls_max=10)
    calls = read_model.recent_calls_for_monitor(
        topology.waiting_room_monitor, OPERATIONAL_DAY
    )

    assert calls == []


# Property 9 - latest call for a Room monitor.
# Validates: Requirements 8.2, 8.3, 8.4, 8.5, 12.2, 12.4


def test_latest_call_none_when_no_call_today(connection):
    """latest_call_for_room_monitor is None when the Room has no call today."""
    topology = _Topology(connection)

    read_model = PostgresDisplayReadModel(connection, recent_calls_max=10)
    latest = read_model.latest_call_for_room_monitor(
        topology.room1_monitor, OPERATIONAL_DAY
    )

    assert latest is None


def test_latest_call_tie_break_by_transition_id_desc(connection):
    """Equal occurred_at for the same Room is broken by transition id desc."""
    topology = _Topology(connection)
    agenda_id = _agenda_id(connection)
    ticket_master = seed_ticket_master(connection, "AAA")

    same_time = _at(9)
    _seed_call(
        connection,
        topology.room1,
        agenda_id,
        ticket_master.id,
        same_time,
        OPERATIONAL_DAY,
        "AAA001",
    )
    _seed_call(
        connection,
        topology.room1,
        agenda_id,
        ticket_master.id,
        same_time,
        OPERATIONAL_DAY,
        "AAA002",
    )

    read_model = PostgresDisplayReadModel(connection, recent_calls_max=10)
    latest = read_model.latest_call_for_room_monitor(
        topology.room1_monitor, OPERATIONAL_DAY
    )

    assert latest is not None
    assert latest.public_call_code == "AAA002"


# Property 10 / privacy - the DisplayCall exposes only non-identifying fields.


def test_display_call_exposes_only_non_identifying_fields(connection):
    """A DisplayCall never exposes the Patient Identifier."""
    topology = _Topology(connection)
    agenda_id = _agenda_id(connection)
    ticket_master = seed_ticket_master(connection, "AAA")

    _seed_call(
        connection,
        topology.room1,
        agenda_id,
        ticket_master.id,
        _at(9),
        OPERATIONAL_DAY,
        "AAA001",
        identifier_value=PATIENT_IDENTIFIER,
    )

    read_model = PostgresDisplayReadModel(connection, recent_calls_max=10)
    calls = read_model.recent_calls_for_monitor(
        topology.waiting_room_monitor, OPERATIONAL_DAY
    )

    assert len(calls) == 1
    call = calls[0]

    # Exactly the non-identifying field set is present.
    expected_fields = {
        "public_call_code",
        "agenda",
        "state",
        "room_reference",
        "room_label",
        "occurred_at",
    }
    assert set(vars(call).keys()) == expected_fields

    # No patient identifier attribute of any kind.
    assert not hasattr(call, "patient_identifier_value")
    assert not hasattr(call, "patient_identifier_type")

    # The seeded identifier value never leaks into any display field.
    assert PATIENT_IDENTIFIER not in call.public_call_code
    assert PATIENT_IDENTIFIER not in call.room_reference
    assert PATIENT_IDENTIFIER not in call.room_label
    assert PATIENT_IDENTIFIER not in call.agenda.name

    assert call.state is ServiceAccessState.CALLED
    assert isinstance(call, DisplayCall)


# Property 11 (partial) - an admission does not remove an earlier CALLED.
# Validates: Requirements 9.5, 13.4


def test_admission_does_not_remove_earlier_call_from_recent_calls(connection):
    """Adding a CALLED->ADMITTED transition does not drop the earlier CALLED."""
    topology = _Topology(connection)
    agenda_id = _agenda_id(connection)
    ticket_master = seed_ticket_master(connection, "AAA")

    sa_id, _ = _seed_call(
        connection,
        topology.room1,
        agenda_id,
        ticket_master.id,
        _at(9),
        OPERATIONAL_DAY,
        "AAA001",
    )
    # The Patient later enters the Room: a new ADMITTED record is appended.
    _seed_transition(connection, sa_id, "ADMITTED", _at(9, 30), previous_state="CALLED")

    read_model = PostgresDisplayReadModel(connection, recent_calls_max=10)
    calls = read_model.recent_calls_for_monitor(
        topology.waiting_room_monitor, OPERATIONAL_DAY
    )

    # The earlier CALLED still shows; admission only adds a record.
    codes = [call.public_call_code for call in calls]
    assert codes == ["AAA001"]
    assert all(call.state is ServiceAccessState.CALLED for call in calls)
