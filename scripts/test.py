"""Run tests with a fresh local PostgreSQL test database."""

from __future__ import annotations

import os
import subprocess
import sys

import psycopg
from psycopg import sql

from dev import database_url, ensure_database, start_postgres, wait_for_postgres

TEST_DATABASE = "azflow_test"


def reset_test_database() -> None:
    """Recreate the disposable local test database from scratch."""
    admin_url = database_url("postgres")
    with psycopg.connect(admin_url, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(TEST_DATABASE)
                )
            )
    ensure_database(TEST_DATABASE)


def main() -> int:
    """Prepare a fresh test database and run pytest."""
    start_postgres()
    wait_for_postgres()
    reset_test_database()

    environment = os.environ.copy()
    environment["AZFLOW_TEST_DATABASE_URL"] = database_url(TEST_DATABASE)

    return subprocess.call(
        [sys.executable, "-m", "pytest", *sys.argv[1:]],
        env=environment,
    )


if __name__ == "__main__":
    raise SystemExit(main())
