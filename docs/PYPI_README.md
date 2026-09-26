# AZFlow

AZFlow is a healthcare queue management system for outpatient environments.

It manages the operational patient flow from check-in to queue handling,
patient calling and access to the healthcare service. AZFlow exposes a FastAPI
HTTP API and uses PostgreSQL for persistence.

## Requirements

- Python 3.10 or newer
- PostgreSQL

AZFlow does not install or manage PostgreSQL. A PostgreSQL database must be
available before the first start.

## Installation

Install AZFlow from PyPI:

~~~bash
pip install AZFlow
~~~

## Configuration

AZFlow reads its configuration from environment variables. A `.env` file in
the current working directory is also supported.

A minimal configuration is:

~~~dotenv
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=azflow
POSTGRES_PASSWORD=change-me
POSTGRES_DB=azflow
~~~

The PostgreSQL connection URL is built internally from these values.

The API binding can optionally be configured with:

~~~dotenv
AZFLOW_API_HOST=0.0.0.0
AZFLOW_API_PORT=8000
~~~

## Database setup

AZFlow ships with its database migrations.

Before the first start, apply all migrations to the configured PostgreSQL
database:

~~~bash
python -m AZFlow.migrations upgrade
~~~

The same command should be run before starting a newly installed AZFlow
version. Only pending migrations are applied.

Database migrations are intentionally not executed automatically when AZFlow
starts.

## Start AZFlow

Start the application with:

~~~bash
python -m AZFlow
~~~

With the default configuration, the API is available at:

~~~text
http://localhost:8000
~~~

The interactive API documentation is available at:

~~~text
http://localhost:8000/docs
~~~

## Development

The PyPI package contains the AZFlow application and the database migrations
required to run it.

Development tools, tests, Docker Compose configuration and demo seed data are
kept in the source repository and are not included in the production package.

## Project

AZFlow is developed as part of the Software Engineering course of the Digital
Transformation Management programme at the University of Bologna.

The project follows a hexagonal architecture. Business logic is kept separate
from HTTP, database and external-system adapters so that integrations can
evolve without changing the core domain model.

## License

AZFlow is distributed under the Apache License 2.0.
