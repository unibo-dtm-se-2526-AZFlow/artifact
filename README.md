# AZFlow

AZFlow is a healthcare queue management system for outpatient environments.

It originates from a real healthcare use case: managing the patient journey from arrival and check-in to queue handling and access to the healthcare service. The project is developed as part of the Software Engineering course of the Digital Transformation Management programme at the University of Bologna, with the goal of keeping the model suitable for further evolution beyond the university project.

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

Install the dependencies:

~~~bash
pip install -r requirements.txt
poetry install
~~~

Start AZFlow locally:

~~~bash
poetry run poe dev
~~~

Run the portable test suite:

~~~bash
poetry run poe test
~~~

Run the complete suite with the local integration test environment:

~~~bash
poetry run poe test-integration
~~~

Static checks and formatting can be verified with:

~~~bash
poetry run poe static-checks
poetry run poe format-check
~~~

Continuous integration verifies the project on the supported Python versions and operating systems, with dedicated integration tests for infrastructure adapters.

## License

AZFlow is distributed under the Apache License 2.0. See LICENSE for details.
