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

-- Agenda A uses queue 1 because it has the lowest id
-- Agenda B uses queue 3
INSERT INTO queue (id, status, policy, ticket_master_id) VALUES
    (1, 'ACTIVE', 'BY_ARRIVAL', 1),
    (2, 'ACTIVE', 'BY_APPOINTMENT', 2),
    (3, 'ACTIVE', 'BY_APPOINTMENT', 2);

INSERT INTO queue_agenda (queue_id, agenda_id) VALUES
    (1, 1),
    (2, 1),
    (3, 2);

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

COMMIT;
