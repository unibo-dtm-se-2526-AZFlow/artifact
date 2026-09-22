"""Run tests with the local PostgreSQL test database."""

from __future__ import annotations

import os
import subprocess
import sys

from dev import database_url, ensure_database, start_postgres, wait_for_postgres

TEST_DATABASE = "azflow_test"


def main() -> int:
    """Prepare the test database and run pytest."""
    start_postgres()
    wait_for_postgres()
    ensure_database(TEST_DATABASE)

    environment = os.environ.copy()
    environment["AZFLOW_TEST_DATABASE_URL"] = database_url(TEST_DATABASE)

    return subprocess.call(
        [sys.executable, "-m", "pytest", *sys.argv[1:]],
        env=environment,
    )


if __name__ == "__main__":
    raise SystemExit(main())
