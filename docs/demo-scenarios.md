# AZFlow demo walkthrough

This document is a short, repeatable walkthrough for demonstrating the current
AZFlow vertical slice. It is not an acceptance-test report: the automated test
suite remains the validation evidence for the project.

The walkthrough is intentionally small. A fresh demo can cover the important
behaviours in a few minutes instead of executing a catalogue of isolated cases.

## Prepare the demo

Reset the deterministic dataset, then start AZFlow:

```bash
poetry run poe dev-reset
poetry run poe dev
```

Useful browser clients are documented in the project README. The main ones are:

- Totem: `http://localhost/demo/totem/?id=1`
- Operator: `http://localhost/demo/operator/?room=1&queue=1`
- Waiting Room 1: `http://localhost/demo/waiting_room/?id=1`
- Waiting Room 2: `http://localhost/demo/waiting_room/?id=2`
- Waiting Room 11: `http://localhost/demo/waiting_room/?id=3`
- BAR: `http://localhost/demo/waiting_room/?id=4`
- Room 1 display: `http://localhost/demo/room_display/?id=1`

There is no login in the current slice. Room and Queue selection belong to the
operator client; URL parameters can preselect them, but AZFlow does not persist
an operator workstation selection.

The seed represents an in-progress working day: 30 Patients have already
checked in, including historical and active calls, while `DEMO031` to `DEMO080`
have appointments but have not yet arrived. `DEMO041`, `DEMO052`, `DEMO061`,
`DEMO067` and `DEMO074` each have two appointments.

The display topology is:

```text
HOSPITAL
├── Totem 1
├── BAR                         [WaitingRoomMonitor 4: whole hospital]
├── Ground Floor
│   ├── Waiting Room 1          [WaitingRoomMonitor 1]
│   ├── Waiting Room 2          [WaitingRoomMonitor 2]
│   ├── Room 1                  [RoomMonitor 1]
│   └── Room 2                  [RoomMonitor 2]
└── First Floor
    ├── Waiting Room 11         [WaitingRoomMonitor 3]
    └── Room 11                 [RoomMonitor 3]
```

## 1. Open an in-progress day

Open the Operator and a few display tabs immediately after the reset.

Expected:

- existing calls are reconstructed from persisted state;
- WAITING, CALLED and ADMITTED entries are already visible in the operational
  data;
- Patients that have appointments but have not checked in do not appear in an
  operational Queue;
- each Room already has one active seeded call, demonstrating recovery after a
  client reconnect rather than relying on a live WebSocket event.

Before making a new call from Room 1, admit its current seeded call so the Room
is free. The UI deliberately allows only one active call per Room.

## 2. Check-in, idempotency and multiple appointments

At Totem 1, check in `DEMO032`.

Expected: one DailyPresence, one ServiceAccess and one public call code are
created. Check in `DEMO032` again and the same operational objects and code are
reused rather than duplicated.

Then check in `DEMO041`, which has two appointments on different Agendas.

Expected: one DailyPresence and one public call code are shared by two
ServiceAccesses. In the Operator UI, switch between the relevant Queues and
observe that the same public code identifies both accesses. Queue selection
changes the operational view; it does not create a new check-in.

## 3. Compare Queue policies

Queue 1 is `BY_APPOINTMENT`. `DEMO031` is deliberately configured as an early
appointment arriving late. Check in `DEMO031`, select Queue 1 and use NEXT from
a free Room.

Expected: `DEMO031` is selected before later appointments even though it has
just arrived.

Queue 3 is `BY_ARRIVAL`. After freeing the Room if necessary, select Queue 3 and
use NEXT.

Expected: the earliest checked-in eligible access is selected independently of
appointment time.

This demonstrates that the same calling operation is driven by the Queue policy
rather than by a fixed global ordering rule.

## 4. Exercise the operator state lifecycle

Use LIST on a Queue containing WAITING entries and choose one access for the
following short sequence:

1. SUSPEND it: the state becomes SUSPENDED and it is excluded from NEXT.
2. RESTORE it: the state returns to WAITING without creating another access.
3. SUSPEND it again, then CALL it directly: the current implementation performs
   the direct `SUSPENDED -> CALLED` transition and associates the selected Room.
4. ADMIT it: the state becomes ADMITTED and the Room becomes available again.
5. RECALL it: the access becomes CALLED again in the same persisted Room.
6. CANCEL the recalled call: the access returns to WAITING.

A WAITING entry that is not first in the Queue can also be called directly from
LIST, showing the explicit operator override of NEXT ordering.

For a `BY_APPOINTMENT` Queue, observe that the appointment timing after a call
uses the persisted first-call time; a later recall does not reset that reference.

## 5. Show live displays, topology and reconnect

Keep Waiting Room 1, Waiting Room 2, Waiting Room 11, BAR and the Room 1 display
open. Make a new call into Room 1.

Expected:

- Waiting Room 1 and Waiting Room 2 receive the call because both cover the
  Ground Floor;
- BAR receives the call because its scope is the HOSPITAL root;
- Waiting Room 11 does not receive it because it belongs to the First Floor;
- Room 1 display shows the call, while other Room displays do not.

The update should arrive live through WebSocket. Close one relevant display,
change the state if useful, then reopen it.

Expected: the initial view is rebuilt from persisted operational history. The
WebSocket is a notification channel, not the source of truth.

Public displays and operational responses use the public call code and do not
expose the Patient Identifier.

## 6. Optional edge checks

These are useful when there is extra time; they are not required for the normal
walkthrough.

| Check | Action | Expected result |
| --- | --- | --- |
| Unknown Patient | Check in an identifier outside the demo set | No operational presence is created |
| Unknown Totem | Open the Totem with an unconfigured `id` and try a valid Patient | Configuration/check-in is rejected |
| Repeated multi-appointment check-in | Check in `DEMO041` again | Still one DailyPresence and two ServiceAccesses |
| Inactive Queue | Use Queue `99` through Swagger/API | Queue is rejected as inactive |
| Empty Queue | Use NEXT on a Queue with no WAITING access | No-patient conflict is returned |
| Invalid transition | Admit a non-CALLED access or restore a non-SUSPENDED access | Transition is rejected |
| Unknown Room | Call using an unconfigured Room reference through Swagger/API | Call is rejected |
| Unknown display | Connect a display with an unconfigured monitor id | WebSocket is closed with the unknown-monitor application code |

## Demo data notes

The primary Queues are intentionally mixed:

- Queue 1: `BY_APPOINTMENT`, Diagnostics;
- Queue 2: `BY_APPOINTMENT`, Cardiology;
- Queue 3: `BY_ARRIVAL`, Oncology;
- Queue 4: `BY_APPOINTMENT`, Blood Tests;
- Queue 5: `BY_ARRIVAL`, Radiotherapy;
- Queue 6: cross-cover Queue for Cardiology and Blood Tests;
- Queue 99: inactive configuration used only for edge demonstrations.

The `SEEDxxx` Patients provide the in-progress context and are not intended to be
typed at the Totem. The `DEMOxxx` identifiers are the not-yet-arrived Patients
used during the walkthrough.

## Traceability aliases

Earlier report drafts refer to the original fine-grained demo identifiers. They
are retained here only as aliases; they no longer represent separate steps that
must all be executed during a demonstration.

| Previous identifiers | Covered by the current walkthrough |
| --- | --- |
| S01 | 1. Open an in-progress day |
| S02–S10, S18 | 2–3. Check-in, Queue policy and operator calling |
| S11–S17 | 4. Operator state lifecycle |
| S19–S26 | 5. Displays, topology, reconnect and privacy |
| E01–E11 | 6. Optional edge checks, with repeated check-in also shown in section 2 |
