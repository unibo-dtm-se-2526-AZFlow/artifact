# AZFlow

AZFlow is a healthcare queue management system for outpatient environments.

It originates from a real healthcare use case: managing the patient journey from arrival and check-in to queue handling and access to the healthcare service. The project is developed as part of the Software Engineering course of the Digital Transformation Management programme at the University of Bologna, with the goal of keeping the model suitable for further evolution beyond the university project.

The complete project documentation is available at [AZFlow Documentation](https://unibo-dtm-se-2526-azflow.github.io/report/). For package installation and production-oriented usage, see the [AZFlow package on TestPyPI](https://test.pypi.org/project/AZFlow/). The development setup below is intended for running the complete local development and demo environment.

## The idea

AZFlow is not a traditional ticket-only queue system.

Its operational model is built around healthcare Agendas, ServiceAccesses and Queues. Agendas represent healthcare activities, while Queues provide operational views over one or more Agendas. The same Agenda can participate in different Queues, each with its own ordering policy.

A patient checks in using an identifier and AZFlow retrieves the relevant appointments from configured external sources. The system creates or reuses the patient's daily operational presence and assigns a public call code. This code is used throughout the operational flow so that patient identity does not need to be exposed on public displays.

Operators can work with the ServiceAccesses visible through their selected Queue. Depending on the Queue policy, patients can be ordered by appointment time or arrival order.

## Project scope

AZFlow covers the operational patient flow from check-in to access to the healthcare service. The main workflow includes:

- patient identification and check-in;
- integration with external appointment sources;
- generation and reuse of a daily public call code;
- creation of operational ServiceAccesses;
- operator Queue views and queue policies;
- patient calling and operational state transitions;
- waiting-room and room displays;
- audit of relevant operational actions.

Not all of these capabilities are implemented yet. AZFlow is under active development and functionality is added incrementally while keeping the system simple and extensible.

## Architecture

AZFlow follows Hexagonal Architecture and applies Domain-Driven Design principles. Business rules stay in the application core, while databases, HTTP APIs and external healthcare systems are connected through ports and adapters.

The current project remains a single deployable application: internal separation is used to keep responsibilities clear, not to introduce unnecessary distributed infrastructure.

## Technology

AZFlow is developed in Python using FastAPI for the HTTP API and PostgreSQL as the current persistence implementation. The architecture keeps persistence behind application ports, so the core domain remains independent from the database technology.

Poetry manages the Python environment and dependencies, while pytest, Ruff and mypy are used for testing and code quality. Docker Compose provides the PostgreSQL instance used by the local development and integration test environments.

## Development

### Prerequisites

AZFlow requires:

- Python `>= 3.10` and `< 4.0`
- Docker with Docker Compose V2
- Git

### Setup

Clone the repository and install Poetry and the project dependencies:

~~~bash
git clone <repository-url>
cd artifact
python3.12 -m pip install -r requirements.txt
poetry install
~~~

`python3.12` can be replaced with any installed Python version supported by
AZFlow.

Create the local environment configuration:

~~~bash
cp .env.example .env
~~~

The example enables the synthetic appointment source with
`AZFLOW_APPOINTMENT_SOURCE_1=demo`. Numbering is sparse: `_1000=demo` works
without indices 1-999. An unset source list disables check-in (HTTP 503).
Selecting `demo` does not seed PostgreSQL; `poe dev-reset` explicitly loads
the local demonstration dataset.
Adjust `.env` if different ports or database settings are required.

Prepare the deterministic demo database:

~~~bash
poetry run poe dev-reset
~~~

This recreates the local database, applies all pending Alembic migrations and
loads the demo data. Then start AZFlow:

~~~bash
poetry run poe dev
~~~

The development launcher starts PostgreSQL, Adminer and the demo web gateway,
applies any pending migrations, and then starts AZFlow. A normal `dev` start
preserves the existing database and does not reload demo data.

The seeded data supports a set of repeatable scenarios covering check-in, Queue
ordering, calling, admission, suspension, display propagation and topology.
See [`docs/demo-scenarios.md`](docs/demo-scenarios.md) for the complete demo
script and the expected result of each scenario.

### Development URLs

The development gateway is available on the standard HTTP port (`80`).

| Client / service | URL | Configuration |
| --- | --- | --- |
| Swagger UI | `http://localhost/docs` | — |
| Adminer | `http://localhost/adminer/` | — |
| Totem | `http://localhost/demo/totem/?id=1` | `id` selects the Totem |
| Operator | `http://localhost/demo/operator/?room=1&queue=1` | `room` selects the Room; `queue` selects the Queue |
| Waiting room display | `http://localhost/demo/waiting_room/?id=1` | `id` selects the WaitingRoomMonitor |
| Room display | `http://localhost/demo/room_display/?id=1` | `id` selects the RoomMonitor |

The deterministic demo seed provides Rooms `1-3`, RoomMonitors `1-3`,
WaitingRoomMonitors `1-4` and Totem `1`. Operator and display clients can
be opened in multiple browser tabs with different URL parameters to represent
different workstations and displays.

AZFlow is also directly available at `http://localhost:8000`, with Swagger UI
at `http://localhost:8000/docs`.

### Demo topology

The deterministic demo represents a small hospital with two floors. Devices and
Rooms are arranged as follows:

~~~text
HOSPITAL
├── Totem 1 [Totem id=1]
├── BAR [WaitingRoomMonitor id=4]
├── Ground Floor
│   ├── Waiting Room 1 [WaitingRoomMonitor id=1]
│   ├── Waiting Room 2 [WaitingRoomMonitor id=2]
│   ├── Room 1 [RoomMonitor id=1]
│   └── Room 2 [RoomMonitor id=2]
└── First Floor
    ├── Waiting Room 11 [WaitingRoomMonitor id=3]
    └── Room 11 [RoomMonitor id=3]
~~~

The topology is functional, not only descriptive: waiting-room monitors receive
calls for Rooms covered by their position in the topology, while Room displays
show calls for their own Room. `BAR`, attached at hospital level, receives calls
from all Rooms.

The seeded snapshot represents the system in the middle of a working day, with
Patients already progressing through the workflow and additional appointments
still available for check-in. See `docs/demo-scenarios.md` for the complete
demonstration scenarios.

### Development commands

Run the portable test suite:

~~~bash
poetry run poe test
~~~

Run the complete suite with the local integration test environment:

~~~bash
poetry run poe test-integration
~~~

Run the portable test suite with coverage and show the report:

~~~bash
poetry run poe coverage
poetry run poe coverage-report
~~~

To generate a browsable HTML coverage report:

~~~bash
poetry run poe coverage-html
~~~

The HTML report is written to `htmlcov/` and can be opened locally to inspect
coverage down to individual source lines.

Static checks and formatting can be verified with:

~~~bash
poetry run poe static-checks
poetry run poe format-check
~~~

Stop AZFlow and the development services without deleting database data:

~~~bash
poetry run poe dev-stop
~~~

Continuous integration verifies the project on the supported Python versions
and operating systems, with dedicated integration tests for infrastructure
adapters. Integration tests use a fresh PostgreSQL database and apply the
Alembic migrations before running.

## Database migrations

Alembic is the source of truth for the PostgreSQL schema. Database schema
changes must be introduced through migrations; PostgreSQL and Docker Compose
do not bootstrap the schema automatically.

The main migration commands are:

~~~bash
poetry run poe db-upgrade
poetry run poe db-current
poetry run poe db-history
~~~

AZFlow uses the PostgreSQL settings from the environment or `.env`:
`POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`
and `POSTGRES_DB`. The connection URL is built internally.

In a deployment, migrations must be applied explicitly before starting a new
AZFlow application version. Migration files are part of the AZFlow Python
package and can also be applied from an installed release with:

~~~bash
python -m AZFlow.migrations upgrade
~~~

Migrations are intentionally not executed by the application process at
startup, avoiding concurrent migration attempts when multiple application
instances are started.

Development/demo seed data is not part of the migration lifecycle and must
never be loaded in production.

## License

AZFlow is distributed under the Apache License 2.0. See LICENSE for details.
