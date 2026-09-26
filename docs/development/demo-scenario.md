# Development Demo Scenario

The current deterministic demo is documented in `docs/demo-scenarios.md`.

That document is the source of truth for:
- the mid-morning HOSPITAL snapshot;
- the four browser demo clients;
- operator Room and Queue selection;
- NEXT and LIST workflows;
- check-in and multi-appointment cases;
- WAITING, SUSPENDED, CALLED and ADMITTED workflows;
- cancel, admission and recall transitions;
- Room and waiting-room display behaviour;
- topology/WebSocket scenarios and edge cases;
- the DEMO031..DEMO080 mock Patients.

Reset and seed the local database with:

~~~bash
poetry run poe dev-reset
~~~

Then start AZFlow with:

~~~bash
poetry run poe dev
~~~

Open the demo clients at `http://localhost/demo/`. The development seed
represents Patients already inside HOSPITAL. Future Patients exist in
`MockAppointmentSource` and enter the operational model only when they check in.

Authentication and per-user Queue filtering are future work.
