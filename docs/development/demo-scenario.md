# Development Demo Scenario

This scenario provides deterministic data for manual AZFlow testing.

The mock appointment source moves the sample appointment times to the current operational day automatically. Use the patients below in the suggested check-in order to make the difference between Queue policies visible.

## Demo patients

| Patient | Time | Agenda |
| --- | --- | --- |
| DEV0001 | 09:30 | Agenda A |
| DEV0002 | 08:45 | Agenda A |
| DEV0003 | 10:15 | Agenda B |
| DEV0004 | 09:00 | Agenda B |
| DEV0005 | 11:00 | Agenda A |
| DEV0006 | 09:15 | Agenda A |
| DEV0006 | 10:30 | Agenda B |

These identifiers are development-only values and are intentionally not realistic fiscal codes.

## Queues

- Queue 1: BY_ARRIVAL, Agenda A + Agenda B
- Queue 2: BY_APPOINTMENT, Agenda A
- Queue 3: BY_APPOINTMENT, Agenda B

Queue 1 can therefore be used to observe check-in order, while Queues 2 and 3 order their visible accesses by appointment time.
## Run the scenario

Start the development environment:

~~~bash
poetry run poe dev
~~~

Check in the patients in this order:

~~~bash
for patient in DEV0001 DEV0003 DEV0005 DEV0002 DEV0004 DEV0006; do
  curl -s -X POST http://localhost:8000/api/v1/check-ins \
    -H 'Content-Type: application/json' \
    -d "{\"identifier_type\":\"fiscal_code\",\"identifier_value\":\"$patient\"}"
  echo
done
~~~

View the three Queues:

~~~bash
curl -s http://localhost:8000/api/v1/queues/1/service-accesses
curl -s http://localhost:8000/api/v1/queues/2/service-accesses
curl -s http://localhost:8000/api/v1/queues/3/service-accesses
~~~

Queue 1 should reflect arrival order. Queues 2 and 3 should reflect appointment order for their respective Agendas.

DEV0006 is useful for checking that one DailyPresence can create ServiceAccesses for more than one Agenda while reusing the same public call code.
## Extending the scenario

Keep this dataset small and deterministic.

When a new operational feature is added, extend this document with the minimum manual steps needed to exercise it. Patient Calling can add Call Next and Call Specific examples here once their HTTP endpoints are implemented.

The demo data belongs to the development adapter. Production integrations must not depend on these identifiers or appointments.
