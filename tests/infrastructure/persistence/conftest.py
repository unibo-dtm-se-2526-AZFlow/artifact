"""Fixtures for PostgreSQL persistence integration tests.

These tests run against a real PostgreSQL database. The DSN is read ONLY from
the ``AZFLOW_TEST_DATABASE_URL`` environment variable. It deliberately does
NOT fall back to ``AZFLOW_DATABASE_URL``, because the per-test isolation
truncates every table: falling back would let the destructive ``TRUNCATE``
run against the developer's seeded ``azflow`` database. Using a dedicated test
DSN guarantees the truncation only ever touches an explicitly provided test
database. When ``AZFLOW_TEST_DATABASE_URL`` is not set the whole module is
skipped, so domain, application and API tests remain runnable without a
database. psycopg is only imported and connected inside fixtures, so
collection never requires a reachable database.
"""

from __future__ import annotations

import os
from typing import Iterator, Optional

import pytest


def _test_dsn() -> Optional[str]:
    return os.environ.get("AZFLOW_TEST_DATABASE_URL")


# Skip every test in modules that use these fixtures unless a dedicated test
# DSN is provided.
pytestmark = pytest.mark.skipif(
    _test_dsn() is None,
    reason="no PostgreSQL test DSN provided (set AZFLOW_TEST_DATABASE_URL)",
)

# All tables in dependency-safe truncation order (children before parents).
_ALL_TABLES = (
    "service_access",
    "ticket_sequence",
    "daily_presence",
    "appointment",
    "queue_agenda",
    "queue",
    "external_agenda",
    "agenda",
    "ticket_master",
    "external_source",
)


@pytest.fixture(scope="session")
def dsn() -> str:
    value = _test_dsn()
    if value is None:  # pragma: no cover - guarded by pytestmark
        pytest.skip("no PostgreSQL test DSN provided")
    return value


@pytest.fixture(scope="session", autouse=True)
def _schema(dsn: str) -> None:
    """Ensure the schema exists once for the test session."""
    import psycopg

    from AZFlow.infrastructure.persistence.schema import apply_schema

    with psycopg.connect(dsn) as conn:
        apply_schema(conn)
        conn.commit()


@pytest.fixture
def connection(dsn: str) -> Iterator["object"]:
    """Provide a clean connection with truncated tables for each test."""
    import psycopg

    with psycopg.connect(dsn) as conn:
        _truncate_all(conn)
        yield conn
        _truncate_all(conn)


def _truncate_all(conn: "object") -> None:
    import psycopg  # noqa: F401  (typing/import parity with fixtures)

    with conn.cursor() as cursor:  # type: ignore[attr-defined]
        cursor.execute(
            "TRUNCATE {} RESTART IDENTITY CASCADE".format(", ".join(_ALL_TABLES))
        )
    conn.commit()  # type: ignore[attr-defined]
