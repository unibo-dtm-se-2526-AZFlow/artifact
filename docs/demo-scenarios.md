# AZFlow 1.1 demo scenarios

This document defines the deterministic development demo and the behaviours
that the future debug UI must expose. It follows the current domain model.

## Operator UI assumptions

There is no login in 1.1. Authentication and per-user Queue visibility are future work.

The operator selects:
- a Room, remembered only by the browser for convenience;
- a Queue, selected for the current work.

The compact operator panel offers NEXT and LIST. LIST expands the panel.
Room and Queue selections are client state and are not persisted by AZFlow.

The UI uses Queue terminology. Agendas are healthcare schedules imported from
external systems; a Queue is the operational grouping used for calling.

## Core gap found while defining the scenarios

The current Queue View exposes only WAITING ServiceAccesses. The intended LIST
also needs SUSPENDED entries so the operator can restore or call them.
The 1.1 operator read model therefore needs to expose at least WAITING and
SUSPENDED states without changing the existing Queue ordering semantics.

CALL on a SUSPENDED entry is a UI convenience: restore it first, then call it.
No SUSPENDED -> CALLED domain transition is added.

## Demo snapshot

The demo starts in the middle of a working day:
- 30 Patients have already checked in;
- 17 are ADMITTED, 3 are CALLED and 10 are WAITING;
- 50 more Patients have appointments today but have not checked in;
- five of those 50 have two appointments; the others have one;
- five Agendas and multiple Queues exercise both ordering policies.

Topology:

    HOSPITAL
    |-- Totem 1
    |-- BAR (whole-hospital waiting-room monitor)
    |-- Ground Floor
    |   |-- Waiting Room 1
    |   |-- Waiting Room 2
    |   |-- Room 1
    |   '-- Room 2
    '-- First Floor
        |-- Waiting Room 11
        '-- Room 11

## Main operational scenarios

### S01 - Open the mid-morning system
Initial: fresh demo reset.
Action: open the operator UI and display pages.
Expected: existing calls are visible from persisted history; 10 accesses remain
WAITING and future Patients do not appear because they have not checked in.
Shows: realistic operational snapshot and separation between appointments and presence.

### S02 - Select Room and Queue
Action: select Room 2 and Queue 2.
Expected: subsequent calls use Room 2; LIST shows Queue 2 operational entries.
Change to Queue 4 without changing Room.
Expected: LIST changes immediately to Queue 4 data.
Shows: Room and Queue are independent client selections.

### S03 - Remember Room locally
Action: select Room 2, close/reopen the operator page.
Expected: the browser can preselect Room 2 from local client state.
Shows: convenience only; AZFlow does not persist the operator's Room selection.

### S04 - Normal check-in
Initial: DEMO032 has one valid appointment and has not arrived.
Action: check in DEMO032 at Totem 1.
Expected: one DailyPresence, one ServiceAccess and one public call code.
Shows: appointment lookup, Totem origin and creation of operational presence.

### S05 - Late Patient in BY_APPOINTMENT
Initial: a Patient with a later appointment is already WAITING.
DEMO031 has an earlier appointment but has not yet arrived.
Action: check in DEMO031, select the relevant BY_APPOINTMENT Queue and press NEXT.
Expected: DEMO031 is called first despite arriving later.
Shows: scheduled time controls BY_APPOINTMENT ordering.

### S06 - Arrival order in BY_ARRIVAL
Initial: two Patients are WAITING in a BY_ARRIVAL Queue and their DailyPresences
were created in a known order.
Action: press NEXT.
Expected: the earlier arrival is called first even if the other appointment is earlier.
Shows: arrival order is independent from appointment time.

### S07 - Multi-appointment check-in
Initial: DEMO041 has two appointments on different Agendas.
Action: check in DEMO041 once.
Expected: one DailyPresence and public code, but two ServiceAccesses.
Shows: one physical arrival can create multiple service accesses.

### S08 - Same code in different Queues
Initial: S07 completed and the two Agendas are visible through relevant Queues.
Action: inspect both Queue lists.
Expected: both ServiceAccesses use DEMO041's same public call code.
Shows: public call identity belongs to DailyPresence.

### S09 - NEXT
Initial: several WAITING entries exist in the selected Queue.
Action: press NEXT from Room 1.
Expected: the first entry according to Queue policy becomes CALLED in Room 1
and disappears from the callable WAITING set.
Shows: Queue ordering and call-time Room.

### S10 - Direct CALL from LIST
Initial: several WAITING entries exist.
Action: expand LIST and CALL an entry that is not first.
Expected: that specific ServiceAccess becomes CALLED in the selected Room.
Shows: operator override through call-specific.

### S11 - Suspend from LIST
Initial: a WAITING entry is visible.
Action: press SUSPEND.
Expected: state becomes SUSPENDED; it is not eligible for NEXT.
Shows: temporary exclusion from calling without deleting the ServiceAccess.

### S12 - Restore from LIST
Initial: a SUSPENDED entry is visible in the operator list.
Action: press RESTORE.
Expected: state becomes WAITING and normal Queue ordering applies again.
Shows: restoration does not create a new access or artificial priority.

### S13 - CALL a suspended Patient with one UI click
Initial: a SUSPENDED entry is visible.
Action: press CALL on that entry.
Expected: UI performs RESTORE then call-specific; final state is CALLED.
If restore succeeds and call fails, the entry remains WAITING and the UI reports the failure.
Shows: UI orchestration without adding a SUSPENDED -> CALLED domain transition.

### S14 - Admission
Initial: a ServiceAccess is CALLED into Room 1.
Action: confirm admission.
Expected: state becomes ADMITTED and the persisted call-time Room is returned.
Shows: admission reuses the Room chosen at call time.

### S15 - Switch Queue with already checked-in Patients
Initial: Room 2 is selected. Queue 2 and Queue 4 contain different accesses
created by Patients who are already inside HOSPITAL.
Action: view Queue 2, then switch the selector to Queue 4.
Expected: Queue 4's existing Patients appear immediately; no new check-in occurs.
Shows: Queue selection changes the operator's working view, not domain state.

## Display and topology scenarios

### S16 - Ground Floor scope
Action: call a Patient into Room 1.
Expected: Waiting Room 1, Waiting Room 2 and BAR receive the call;
Waiting Room 11 does not.
Shows: both Ground Floor monitors share the Ground Floor scope.

### S17 - Second Ground Floor Room
Action: call a Patient into Room 2.
Expected: Waiting Room 1, Waiting Room 2 and BAR receive the call;
Waiting Room 11 does not.
Shows: scope follows topology rather than a fixed Room binding.

### S18 - First Floor isolation
Action: call a Patient into Room 11.
Expected: Waiting Room 11 and BAR receive the call; Ground Floor monitors do not.
Shows: sibling topology branches remain isolated.

### S19 - BAR catch-all
Action: make calls into Room 1, Room 2 and Room 11.
Expected: BAR receives all three.
Shows: a monitor scoped to HOSPITAL covers every descendant Room.

### S20 - Room display isolation
Action: make separate calls into Room 1, Room 2 and Room 11.
Expected: each RoomMonitor shows only the latest call for its own Room.
Shows: over-door display binding.

### S21 - Live display update
Initial: relevant display WebSockets are connected.
Action: make a call.
Expected: covered waiting-room and Room displays receive a live call message.
Shows: real-time publication.

### S22 - Reconnect display
Initial: calls already happened while the display was closed.
Action: reconnect the display.
Expected: its initial snapshot is rebuilt from persisted call history.
Shows: WebSocket delivery is not the source of truth.

### S23 - Privacy on operator/display output
Action: inspect Queue and display responses during the scenarios.
Expected: public call code and operational data are exposed, not Patient identifiers.
Shows: privacy boundary of operational/read interfaces.

## Check-in and configuration edge scenarios

### E01 - Unknown Patient
Action: check in an identifier absent from the mock source.
Expected: 404 and no DailyPresence.

### E02 - Unknown Totem
Action: check in a valid Patient with an unknown Totem reference.
Expected: 400 and no check-in data.

### E03 - Repeated check-in
Action: check in the same Patient twice on the same day.
Expected: existing DailyPresence/public code and ServiceAccesses are reused.

### E04 - Multi-appointment repeated check-in
Action: check in DEMO041 twice.
Expected: still one DailyPresence and two ServiceAccesses, with no duplicates.

### E05 - Inactive Queue
Action: view or call the inactive demo Queue.
Expected: 409 queue is not active.

### E06 - Empty Queue
Action: press NEXT when no WAITING access is available.
Expected: 409 no patient to call.

### E07 - Specific access outside selected Queue
Action: call-specific an access not visible through the selected Queue.
Expected: 404 service access not found in queue.

### E08 - Call non-callable state
Action: call-specific a CALLED or ADMITTED access.
Expected: 409 service access is not callable.

### E09 - Invalid state transitions
Action: admit a non-CALLED access, restore a non-SUSPENDED access, or suspend
a non-WAITING access.
Expected: 409 for each invalid transition.

### E10 - Unknown Room
Action: call using an unknown Room reference.
Expected: 409 room is not configured.

### E11 - Unknown display monitor
Action: connect using an unknown monitor id.
Expected: WebSocket closes with the unknown-monitor application code.

### E12 - SUSPENDED CALL partial failure
Initial: SUSPENDED access.
Action: UI restores it, but call-specific fails before completion.
Expected: access remains WAITING and UI refreshes LIST and reports the call failure.
Shows: expected consequence of the two-request UI convenience.

## Deterministic demo Patients

DEMO031..DEMO080 are not checked in at reset time and exist only in the mock
appointment source until they arrive. DEMO041, DEMO052, DEMO061, DEMO067 and
DEMO074 have two appointments. The remaining 45 have one.

DEMO031 is intentionally an early appointment arriving late for S05.
Other identifiers are distributed across the five Agendas so the operator can
check in new Patients throughout the demo without emptying the background data.

The 30 SEED Patients are already inside at reset time. They provide historical
calls, current calls and the ten initial WAITING entries. They are context data,
not identifiers intended to be typed at the Totem.

## Future work explicitly outside 1.1

- Login and authentication.
- Per-user Queue authorization/filtering.
- Persisting operator Room or Queue selection in AZFlow.
- A direct SUSPENDED -> CALLED domain transition.
