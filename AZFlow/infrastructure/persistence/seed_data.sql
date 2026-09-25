-- Development/demo data for the AZFlow 1.1 mid-morning scenario
-- The matching not-yet-arrived appointments live in MockAppointmentSource.

BEGIN;

INSERT INTO external_source (id, code, name, connector_type, enabled)
VALUES (1, 'MOCK', 'Mock source', 'mock', TRUE);

INSERT INTO agenda (id, name) VALUES
    (1, 'Diagnostics'),
    (2, 'Cardiology'),
    (3, 'Oncology'),
    (4, 'Blood Tests'),
    (5, 'Radiotherapy');

INSERT INTO external_agenda (
    id, agenda_id, external_source_id, external_reference, source_name
) VALUES
    (1, 1, 1, 'AGENDA-1', 'Diagnostics'),
    (2, 2, 1, 'AGENDA-2', 'Cardiology'),
    (3, 3, 1, 'AGENDA-3', 'Oncology'),
    (4, 4, 1, 'AGENDA-4', 'Blood Tests'),
    (5, 5, 1, 'AGENDA-5', 'Radiotherapy'),
    (6, 1, 1, 'AGENDA-A', 'Diagnostics legacy alias'),
    (7, 2, 1, 'AGENDA-B', 'Cardiology legacy alias');

INSERT INTO ticket_master (id, prefix) VALUES
    (1, 'A'), (2, 'B'), (3, 'C'), (4, 'D'), (5, 'E');

-- Five primary queues plus a cross-cover queue and one inactive queue.
-- Queue 1 gives the main BY_APPOINTMENT late-arrival demonstration.
-- Queue 3 gives the main BY_ARRIVAL demonstration.
INSERT INTO queue (id, status, policy, ticket_master_id) VALUES
    (1, 'ACTIVE',   'BY_APPOINTMENT', 1),
    (2, 'ACTIVE',   'BY_APPOINTMENT', 2),
    (3, 'ACTIVE',   'BY_ARRIVAL',     3),
    (4, 'ACTIVE',   'BY_APPOINTMENT', 4),
    (5, 'ACTIVE',   'BY_ARRIVAL',     5),
    (6, 'ACTIVE',   'BY_APPOINTMENT', 2),
    (99, 'INACTIVE','BY_APPOINTMENT', 1);

INSERT INTO queue_agenda (queue_id, agenda_id) VALUES
    (1, 1),
    (2, 2),
    (3, 3),
    (4, 4),
    (5, 5),
    (6, 2),
    (6, 4),
    (99, 1);

-- Location topology used by the display demo.
-- HOSPITAL
--   Ground Floor -> Room 1, Room 2
--   First Floor  -> Room 11
INSERT INTO location_node (id, parent_id, label) VALUES
    (1, NULL, 'HOSPITAL'),
    (2, 1, 'Ground Floor'),
    (3, 1, 'First Floor'),
    (4, 2, 'Room 1 node'),
    (5, 2, 'Room 2 node'),
    (6, 3, 'Room 11 node');

-- Totem 1 belongs to the hospital root and can receive Patients for all floors.
INSERT INTO totem (id, external_reference, location_node_id)
VALUES (1, 'TOTEM-1', 1);

INSERT INTO room (id, room_reference, label, location_node_id) VALUES
    (1, 'ROOM-1',  'Room 1',  4),
    (2, 'ROOM-2',  'Room 2',  5),
    (3, 'ROOM-11', 'Room 11', 6);

INSERT INTO room_workstation (id, room_id) VALUES
    (1, 1), (2, 2), (3, 3);

INSERT INTO room_monitor (id, room_id) VALUES
    (1, 1), (2, 2), (3, 3);

INSERT INTO waiting_room_monitor (id, label) VALUES
    (1, 'Waiting Room 1'),
    (2, 'Waiting Room 2'),
    (3, 'Waiting Room 11'),
    (4, 'BAR');

-- The two Ground Floor monitors intentionally share the same floor scope.
-- BAR is scoped to HOSPITAL, so the recursive display query sees every Room.
INSERT INTO waiting_room_monitor_scope (
    waiting_room_monitor_id, location_node_id
) VALUES
    (1, 2),
    (2, 2),
    (3, 3),
    (4, 1);

-- Mid-morning context: 30 Patients have already checked in.
-- Their appointment times are deterministic and spread across all five Agendas.
INSERT INTO appointment (
    id, scheduled_at, patient_identifier_type, patient_identifier_value,
    external_agenda_id, external_patient_reference,
    external_appointment_reference
)
SELECT
    n,
    CURRENT_DATE + TIME '08:00' + n * INTERVAL '7 minutes',
    'fiscal_code',
    'SEED' || LPAD(n::text, 3, '0'),
    ((n - 1) % 5) + 1,
    'SEED-PAT-' || LPAD(n::text, 3, '0'),
    'SEED-APPT-' || LPAD(n::text, 3, '0')
FROM generate_series(1, 30) AS n;

INSERT INTO daily_presence (
    id, operational_day, patient_identifier_type, patient_identifier_value,
    public_call_code, ticket_master_id, totem_id
)
SELECT
    n,
    CURRENT_DATE,
    'fiscal_code',
    'SEED' || LPAD(n::text, 3, '0'),
    CHR(65 + ((n - 1) % 5)) || LPAD(n::text, 3, '0'),
    ((n - 1) % 5) + 1,
    1
FROM generate_series(1, 30) AS n;

-- 17 Patients are already ADMITTED, 3 are CALLED and 10 are still WAITING.
-- Only called/admitted accesses have a persisted call-time Room.
INSERT INTO service_access (
    id, daily_presence_id, agenda_id, appointment_id, state, room_id
)
SELECT
    n,
    n,
    ((n - 1) % 5) + 1,
    n,
    CASE
        WHEN n <= 17 THEN 'ADMITTED'
        WHEN n <= 20 THEN 'CALLED'
        ELSE 'WAITING'
    END,
    CASE
        WHEN n > 20 THEN NULL
        WHEN ((n - 1) % 5) + 1 = 1 THEN 1
        WHEN ((n - 1) % 5) + 1 = 2 THEN 2
        ELSE 3
    END
FROM generate_series(1, 30) AS n;

-- Every previously called Patient has a WAITING -> CALLED history record.
INSERT INTO service_access_transition (
    service_access_id, previous_state, resulting_state, occurred_at
)
SELECT
    n,
    'WAITING',
    'CALLED',
    CURRENT_DATE + TIME '08:25' + n * INTERVAL '4 minutes'
FROM generate_series(1, 20) AS n;

-- The first 17 have also entered their Room.
INSERT INTO service_access_transition (
    service_access_id, previous_state, resulting_state, occurred_at
)
SELECT
    n,
    'CALLED',
    'ADMITTED',
    CURRENT_DATE + TIME '08:35' + n * INTERVAL '4 minutes'
FROM generate_series(1, 17) AS n;

-- All ticket masters start above the seeded suffixes. Gaps are harmless in demo data.
INSERT INTO ticket_sequence (ticket_master_id, operational_day, last_number)
SELECT id, CURRENT_DATE, 30
FROM ticket_master;

-- Move identity sequences after all fixed demo ids.
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
SELECT setval(pg_get_serial_sequence('appointment', 'id'),
              (SELECT MAX(id) FROM appointment));
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
