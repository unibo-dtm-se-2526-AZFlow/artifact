# Development Demo Scenario

The AZFlow 1.1 deterministic demo has moved to `docs/demo-scenarios.md`.

That document is the source of truth for:
- the mid-morning HOSPITAL snapshot;
- operator Room and Queue selection;
- NEXT and expandable LIST workflows;
- check-in and multi-appointment cases;
- WAITING, SUSPENDED, CALLED and ADMITTED workflows;
- Room and waiting-room display behaviour;
- topology/WebSocket scenarios and edge cases;
- the DEMO031..DEMO080 mock Patients.

Reset the local database with:

~~~bash
poetry run poe dev-reset
~~~

Then start AZFlow with:

~~~bash
poetry run poe dev
~~~

The development seed represents Patients already inside HOSPITAL. Future
Patients exist in `MockAppointmentSource` and enter the operational model only
when they check in.

The operator LIST described by the demo requires a 1.1 read-model extension:
the current Queue View contains only WAITING entries, while LIST must also show
SUSPENDED entries. Authentication and per-user Queue filtering are future work.
