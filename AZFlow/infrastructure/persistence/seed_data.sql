-- Development data for Patient Check-In
-- The data matches MockAppointmentSource and uses fixed ids
-- Agenda A has two active queues to test selection by the lowest queue id

BEGIN;

-- External appointment source
INSERT INTO external_source (id, code, name, connector_type, enabled)
VALUES (1, 'MOCK', 'Mock source', 'mock', TRUE);

-- Local agendas and their external references
INSERT INTO agenda (id, name) VALUES
    (1, 'Agenda A'),
    (2, 'Agenda B');

INSERT INTO external_agenda (
    id, agenda_id, external_source_id, external_reference, source_name
) VALUES
    (1, 1, 1, 'AGENDA-A', 'Agenda A'),
    (2, 2, 1, 'AGENDA-B', 'Agenda B');

-- Public call code prefixes
INSERT INTO ticket_master (id, prefix) VALUES
    (1, 'AAA'),
    (2, 'BBB');

-- Queue View: queue 1 (BY_ARRIVAL) serves both Agenda A and Agenda B,
-- so a single queue covers more than one agenda.
-- Agenda A is shared by queue 1 and queue 2 (BY_APPOINTMENT);
-- Agenda B is shared by queue 1 and queue 3 (BY_APPOINTMENT),
-- so the same ServiceAccess is visible through queues with different policies.
-- The mock's earliest appointment is on Agenda A.
INSERT INTO queue (id, status, policy, ticket_master_id) VALUES
    (1, 'ACTIVE', 'BY_ARRIVAL', 1),
    (2, 'ACTIVE', 'BY_APPOINTMENT', 2),
    (3, 'ACTIVE', 'BY_APPOINTMENT', 2);

INSERT INTO queue_agenda (queue_id, agenda_id) VALUES
    (1, 1),
    (1, 2),
    (2, 1),
    (3, 2);

-- Daily presences and service accesses so state management can be driven
-- end to end. Two are WAITING (for suspend) and two are CALLED (for confirm
-- admission), one on each agenda. The operational day is set at load time.
INSERT INTO daily_presence (
    id, operational_day, patient_identifier_type, patient_identifier_value,
    public_call_code, ticket_master_id
) VALUES
    (1, CURRENT_DATE, 'fiscal_code', 'SEED-WAIT-A', 'AAA001', 1),
    (2, CURRENT_DATE, 'fiscal_code', 'SEED-WAIT-B', 'BBB001', 2),
    (3, CURRENT_DATE, 'fiscal_code', 'SEED-CALL-A', 'AAA002', 1),
    (4, CURRENT_DATE, 'fiscal_code', 'SEED-CALL-B', 'BBB002', 2);

INSERT INTO service_access (id, daily_presence_id, agenda_id, appointment_id, state) VALUES
    (1, 1, 1, NULL, 'WAITING'),
    (2, 2, 2, NULL, 'WAITING'),
    (3, 3, 1, NULL, 'CALLED'),
    (4, 4, 2, NULL, 'CALLED');

-- Location topology: a tree with no fixed levels. Company is the root; the
-- Radiotherapy branch has two leaf nodes and a nested Brachytherapy sub-branch,
-- while Oncology is a sibling branch. This lets descendant scoping be exercised.
--   Company > Site A > { Radiotherapy > { Node-R1, Node-R2, Brachytherapy > { Node-R3 } },
--                        Oncology > { Node-R4 } }
INSERT INTO location_node (id, parent_id, label) VALUES
    (1, NULL, 'Company'),
    (2, 1, 'Site A'),
    (3, 2, 'Radiotherapy'),
    (4, 3, 'Node-R1'),
    (5, 3, 'Node-R2'),
    (6, 3, 'Brachytherapy'),
    (7, 6, 'Node-R3'),
    (8, 2, 'Oncology'),
    (9, 8, 'Node-R4');

-- Rooms reuse the demo references. ROOM-1 sits in the Radiotherapy branch and
-- ROOM-2 in the Oncology branch, so a Radiotherapy-scoped display sees only ROOM-1.
INSERT INTO room (id, room_reference, label, location_node_id) VALUES
    (1, 'ROOM-1', 'Room 1', 4),
    (2, 'ROOM-2', 'Room 2', 9);

-- Exactly one workstation per Room (the seed satisfies the product invariant).
INSERT INTO room_workstation (id, room_id) VALUES
    (1, 1),
    (2, 2);

-- Optional Room monitor: ROOM-1 has one, ROOM-2 has none (zero-or-one case).
INSERT INTO room_monitor (id, room_id) VALUES
    (1, 1);

-- Waiting-room display scoped to the Radiotherapy node, so it sees ROOM-1 and
-- its descendants but not ROOM-2 under Oncology.
INSERT INTO waiting_room_monitor (id, label) VALUES
    (1, 'Radiotherapy waiting room');

INSERT INTO waiting_room_monitor_scope (waiting_room_monitor_id, location_node_id) VALUES
    (1, 3);

-- Totem for the optional check-in origin, placed under Site A.
INSERT INTO totem (id, external_reference, location_node_id) VALUES
    (1, 'TOTEM-1', 2);

-- Give the CALLED service accesses their call-time Room so a display view is
-- non-empty for the demo: id 3 (Agenda A) in ROOM-1, id 4 (Agenda B) in ROOM-2.
UPDATE service_access SET room_id = 1 WHERE id = 3;
UPDATE service_access SET room_id = 2 WHERE id = 4;

-- WAITING->CALLED transition records for the two calls, with distinct times in
-- the current operational day so recent/latest ordering is deterministic.
INSERT INTO service_access_transition (
    id, service_access_id, previous_state, resulting_state, occurred_at
) VALUES
    (1, 3, 'WAITING', 'CALLED', CURRENT_DATE + TIME '09:00'),
    (2, 4, 'WAITING', 'CALLED', CURRENT_DATE + TIME '09:05');

-- Move identity sequences after the fixed ids
SELECT setval(pg_get_serial_sequence('external_source', 'id'),
              (SELECT MAX(id) FROM external_source));
SELECT setval(pg_get_serial_sequence('agenda', 'id'),
              (SELECT MAX(id) FROM agenda));
SELECT setval(pg_get_serial_sequence('external_agenda', 'id'),
              (SELECT MAX(id) FROM external_agenda));
SELECT setval(pg_get_serial_sequence('ticket_master', 'id'),
              (SELECT MAX(id) FROM ticket_master));
SELECT setval(pg_get_serial_sequence('queue', 'id'),
              (SELECT MAX(id) FROM queue));
SELECT setval(pg_get_serial_sequence('daily_presence', 'id'),
              (SELECT MAX(id) FROM daily_presence));
SELECT setval(pg_get_serial_sequence('service_access', 'id'),
              (SELECT MAX(id) FROM service_access));
SELECT setval(pg_get_serial_sequence('location_node', 'id'),
              (SELECT MAX(id) FROM location_node));
SELECT setval(pg_get_serial_sequence('totem', 'id'),
              (SELECT MAX(id) FROM totem));
SELECT setval(pg_get_serial_sequence('room', 'id'),
              (SELECT MAX(id) FROM room));
SELECT setval(pg_get_serial_sequence('room_workstation', 'id'),
              (SELECT MAX(id) FROM room_workstation));
SELECT setval(pg_get_serial_sequence('room_monitor', 'id'),
              (SELECT MAX(id) FROM room_monitor));
SELECT setval(pg_get_serial_sequence('waiting_room_monitor', 'id'),
              (SELECT MAX(id) FROM waiting_room_monitor));
SELECT setval(pg_get_serial_sequence('service_access_transition', 'id'),
              (SELECT MAX(id) FROM service_access_transition));

COMMIT;
