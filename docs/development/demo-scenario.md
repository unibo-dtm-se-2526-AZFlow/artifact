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

## Patient calling

Call the next Patient from Queue 1 and send the call to a Room:

~~~bash
curl -s -X POST http://localhost:8000/api/v1/queues/1/calls/next \
  -H 'Content-Type: application/json' \
  -d '{"room_reference":"ROOM-1"}'
~~~

The response should contain the public call code, the selected ServiceAccess, its Agenda, `state: "CALLED"`, and the same Room reference. It must not contain Patient-identifying data.

View Queue 1 again:

~~~bash
curl -s http://localhost:8000/api/v1/queues/1/service-accesses
~~~

The called ServiceAccess is no longer part of the WAITING Queue view. If its Agenda is shared with another Queue, it disappears there too because both Queues refer to the same ServiceAccess.

To call a specific Patient, first choose a `service_access_id` from one of the Queue responses, then run:

~~~bash
SERVICE_ACCESS_ID=<id>

curl -s -X POST \
  "http://localhost:8000/api/v1/queues/1/service-accesses/$SERVICE_ACCESS_ID/call" \
  -H 'Content-Type: application/json' \
  -d '{"room_reference":"ROOM-2"}'
~~~

The selected ServiceAccess must be visible and WAITING in Queue 1. Calling an already called ServiceAccess returns a conflict instead of calling it again.

## Suspend and restore

Choose a WAITING `service_access_id` from a Queue response and suspend it:

~~~bash
SERVICE_ACCESS_ID=<id>

curl -s -X POST \
  "http://localhost:8000/api/v1/service-accesses/$SERVICE_ACCESS_ID/suspend"
~~~

The response should report `state: "SUSPENDED"`. The ServiceAccess disappears from every Queue that contains its Agenda because Queue views contain only WAITING accesses.

Restore the same ServiceAccess:

~~~bash
curl -s -X POST \
  "http://localhost:8000/api/v1/service-accesses/$SERVICE_ACCESS_ID/restore"
~~~

The response should report `state: "WAITING"`. The ServiceAccess becomes visible again in all relevant Queues and returns to the normal Queue ordering; restoring it does not give it priority.

Trying to suspend a non-WAITING ServiceAccess or restore a non-SUSPENDED one returns a conflict.

## Confirm admission

After calling a Patient, keep the `service_access_id` returned by the call and confirm admission:

~~~bash
CALLED_SERVICE_ACCESS_ID=<id>

curl -s -X POST \
  "http://localhost:8000/api/v1/service-accesses/$CALLED_SERVICE_ACCESS_ID/admission"
~~~

The response should report `state: "ADMITTED"` together with the persisted Room reference and label selected at call time. Admission does not accept a new Room: the Room associated with the successful call is reused.

An ADMITTED ServiceAccess stays outside Queue views and cannot be called again. Confirming admission for a ServiceAccess that is not CALLED returns a conflict.

## Call notifications and displays

The development topology contains:

- `ROOM-1` ("Room 1") in the Radiotherapy branch;
- `ROOM-2` ("Room 2") in the Oncology branch;
- RoomMonitor `1`, associated with `ROOM-1`;
- WaitingRoomMonitor `1`, scoped to Radiotherapy and its descendant LocationNodes.

The waiting-room monitor therefore receives calls for `ROOM-1`, but not for `ROOM-2`.

Open a terminal and connect to WaitingRoomMonitor 1:

~~~bash
poetry run python - <<'PY'
import asyncio
import websockets

async def main():
    async with websockets.connect(
        "ws://localhost:8000/api/v1/ws/waiting-room-monitors/1"
    ) as ws:
        while True:
            print(await ws.recv())

asyncio.run(main())
PY
~~~

Open another terminal to observe the RoomMonitor:

~~~bash
poetry run python - <<'PY'
import asyncio
import websockets

async def main():
    async with websockets.connect(
        "ws://localhost:8000/api/v1/ws/room-monitors/1"
    ) as ws:
        while True:
            print(await ws.recv())

asyncio.run(main())
PY
~~~

Each connection first receives a `snapshot` built from persisted call history. The WaitingRoomMonitor snapshot contains the bounded recent calls in its configured scope; the RoomMonitor snapshot contains at most the latest call for `ROOM-1`.

Leave both clients connected and call a WAITING ServiceAccess to `ROOM-1`:

~~~bash
curl -s -X POST http://localhost:8000/api/v1/queues/1/calls/next \
  -H 'Content-Type: application/json' \
  -d '{"room_reference":"ROOM-1"}'
~~~

Both connected clients should receive a live `call` message. It contains only display-safe data: public call code, Agenda, state, Room reference and label, and the persisted call-transition timestamp. It contains no Patient identifier.

A call to `ROOM-2` is outside WaitingRoomMonitor 1's Radiotherapy scope and there is no configured RoomMonitor for `ROOM-2`, so neither of the two clients above receives that call.

An unknown monitor id is rejected by the WebSocket endpoint. Suspend, restore and admission do not produce display notifications.

If a display reconnects, its initial snapshot is rebuilt from persisted history and topology, so it does not depend on having received earlier live messages.

## Extending the scenario

Keep this dataset small and deterministic.

When a new operational feature is added, extend this document with the minimum manual steps needed to exercise it.

The demo data belongs to the development adapter. Production integrations must not depend on these identifiers or appointments.
