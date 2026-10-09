# AZFlow

AZFlow is a healthcare queue-management backend for outpatient workflows. It
covers patient check-in, operational Queues, calling, state transitions and
public call displays through a FastAPI API backed by PostgreSQL.

## Requirements

- Python 3.10 or newer
- PostgreSQL

## Installation

The course release is published on TestPyPI:

```bash
pip install \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ \
  AZFlow
```

## Configuration

AZFlow reads configuration from environment variables and also supports a
`.env` file in the current working directory.

Minimal PostgreSQL configuration:

```dotenv
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=azflow
POSTGRES_PASSWORD=change-me
POSTGRES_DB=azflow
```

Select appointment sources explicitly using numbered environment variables.
Indices need not be consecutive; for example, the following works even without
entries 1 through 999:

```dotenv
AZFLOW_APPOINTMENT_SOURCE_1000=demo
```

When several entries are present, AZFlow loads them in ascending numeric order.
The current release provides the in-memory `demo` adapter; other identifiers
will be supported when their adapters are implemented. Without any configured
sources, check-in returns HTTP 503. Unknown source identifiers fail at startup.
The demo adapter provides synthetic appointments but never creates database
tables or loads the demonstration SQL seed.

Optional API binding:

```dotenv
AZFLOW_API_HOST=0.0.0.0
AZFLOW_API_PORT=8000
```

## Database and startup

Apply the bundled Alembic migrations before the first start and after upgrading
AZFlow:

```bash
python -m AZFlow.migrations upgrade
```

Then start the application:

```bash
python -m AZFlow
```

With the default configuration, the API is available at
`http://localhost:8000` and the interactive OpenAPI documentation at
`http://localhost:8000/docs`.

Database migrations are deliberately explicit and are not applied silently at
application startup. If PostgreSQL is unreachable, requests needing the
database return HTTP 503; the health endpoint only checks that the API process
responds.

The optional demonstration SQL seed is available separately on GitHub:
[seed_data.sql for v2.0.1](https://github.com/unibo-dtm-se-2526-AZFlow/artifact/blob/v2.0.1/dev/seed_data.sql).
For other AZFlow versions, use the file from the matching Git release tag.
Apply it only by an explicit user operation to a disposable database after
running migrations. It expects a fresh database and must not be loaded into
an existing operational database. With a source checkout, `poe dev-reset`
recreates and seeds the local demonstration database after confirmation.

## Project resources

The published package contains the AZFlow application and database migrations.
Tests, Docker Compose configuration, development tools, demo clients and the
optional SQL seed remain in the source repository.

- Source repository: https://github.com/unibo-dtm-se-2526-AZFlow/artifact
- Project documentation: https://unibo-dtm-se-2526-azflow.github.io/report/

AZFlow is a Software Engineering project for the Digital Transformation
Management programme at the University of Bologna and is distributed under the
Apache License 2.0.
