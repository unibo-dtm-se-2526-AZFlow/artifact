# AZFlow

AZFlow is a healthcare queue management system for outpatient environments.

The system manages the operational patient flow from check-in to queue handling,
patient calling and access to the healthcare service. It exposes an HTTP API
built with FastAPI and uses PostgreSQL for persistence.

## Requirements

- Python 3.10 or newer
- PostgreSQL

AZFlow does not install or manage PostgreSQL. Create an empty PostgreSQL
database before the first start.

## Installation

~~~bash
pip install AZFlow
~~~

## Configuration

AZFlow reads its configuration from environment variables and also supports a
`.env` file in the current working directory.

For a simple installation, create a `.env` file:

~~~dotenv
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=azflow
POSTGRES_PASSWORD=change-me
POSTGRES_DB=azflow

AZFLOW_API_HOST=0.0.0.0
AZFLOW_API_PORT=8000
~~~

The PostgreSQL connection string is built internally from these values.

## First start

Apply the packaged database migrations before starting AZFlow:

~~~bash
python -m AZFlow.migrations upgrade
~~~

Then start the application:

~~~bash
python -m AZFlow
~~~

By default, the API is available on port 8000 and the interactive FastAPI
documentation is available at `/docs`.

Database migrations are explicit and are not run automatically when the
application starts. Before deploying a newer AZFlow version, apply its pending
migrations with the same migration command.

## Project

AZFlow is developed as part of the Software Engineering course of the Digital
Transformation Management programme at the University of Bologna.

The source repository contains the development environment, tests and local
development tooling. Those resources are intentionally not part of the Python
production package.

## License

AZFlow is distributed under the Apache License 2.0.
