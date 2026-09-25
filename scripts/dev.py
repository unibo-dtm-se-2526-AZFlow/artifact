"""Local development launcher for AZFlow.

Starts PostgreSQL via Docker Compose, waits until it is ready, then runs AZFlow
with Uvicorn auto-reload.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote

import psycopg
import uvicorn

REPO_ROOT = Path(__file__).resolve().parent.parent

READINESS_TIMEOUT_SECONDS = 60
READINESS_POLL_INTERVAL_SECONDS = 1.0

REQUIRED_ENV_VARS = (
    "AZFLOW_API_HOST",
    "AZFLOW_API_PORT",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DB",
    "AZFLOW_DB_HOST_PORT",
)


def compose_environment() -> dict[str, str]:
    """Read and validate the local .env file."""
    env_file = REPO_ROOT / ".env"
    example_file = REPO_ROOT / ".env.example"

    if not env_file.exists():
        if not example_file.exists():
            raise RuntimeError(".env and .env.example are both missing")
        env_file.write_text(example_file.read_text(encoding="utf-8"), encoding="utf-8")
        print("Created .env from .env.example.")

    environment: dict[str, str] = {}
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        environment[key.strip()] = value.strip().strip('"').strip("'")

    missing = [name for name in REQUIRED_ENV_VARS if not environment.get(name)]
    if missing:
        raise RuntimeError("Missing required variables in .env: " + ", ".join(missing))

    return environment


def compose(
    *args: str, check: bool = True, capture_output: bool = False
) -> subprocess.CompletedProcess[bytes]:
    """Run a Docker Compose command from the repository root."""
    return subprocess.run(
        ["docker", "compose", *args],
        cwd=REPO_ROOT,
        check=check,
        capture_output=capture_output,
    )


def start_postgres() -> None:
    """Start PostgreSQL and local development tools via Docker Compose."""
    print("Starting PostgreSQL and Adminer via Docker Compose...")
    compose("--profile", "dev", "up", "-d", "postgres", "adminer")


def wait_for_postgres() -> None:
    """Wait until PostgreSQL accepts connections."""
    config = compose_environment()
    user = config["POSTGRES_USER"]
    database = config["POSTGRES_DB"]

    print("Waiting for PostgreSQL to become ready...")
    deadline = time.monotonic() + READINESS_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        result = compose(
            "exec",
            "-T",
            "postgres",
            "pg_isready",
            "-U",
            user,
            "-d",
            database,
            check=False,
            capture_output=True,
        )
        if result.returncode == 0:
            print("PostgreSQL is ready.")
            print("Adminer available at http://localhost:8080")
            return
        time.sleep(READINESS_POLL_INTERVAL_SECONDS)

    print(
        f"PostgreSQL did not become ready within {READINESS_TIMEOUT_SECONDS}s. "
        "Leaving the container running for inspection.",
        file=sys.stderr,
    )
    sys.exit(1)


def ensure_database(name: str) -> None:
    """Create a local PostgreSQL database when it does not exist."""
    from psycopg import sql

    admin_url = database_url("postgres")

    with psycopg.connect(admin_url, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,))
            if cursor.fetchone() is not None:
                return
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))


def database_url(name: str | None = None) -> str:
    """Build a local PostgreSQL URL from the development configuration."""
    config = compose_environment()
    user = quote(config["POSTGRES_USER"], safe="")
    password = quote(config["POSTGRES_PASSWORD"], safe="")
    database = quote(name or config["POSTGRES_DB"], safe="")
    port = config["AZFLOW_DB_HOST_PORT"]
    return f"postgresql://{user}:{password}@localhost:{port}/{database}"


def migration_environment(name: str | None = None) -> dict[str, str]:
    """Build an environment for Alembic against a local database."""
    environment = os.environ.copy()
    environment["AZFLOW_DATABASE_URL"] = database_url(name)
    return environment


def upgrade_database(name: str | None = None) -> None:
    """Upgrade a local database to the latest Alembic revision."""
    print("Applying database migrations...")
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=REPO_ROOT,
        env=migration_environment(name),
        check=True,
    )


def seed_database() -> None:
    """Load development/demo data into the local development database."""
    seed_path = (
        REPO_ROOT / "AZFlow" / "infrastructure" / "persistence" / "seed_data.sql"
    )
    print("Loading development seed data...")
    with psycopg.connect(database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(seed_path.read_text(encoding="utf-8"))
        connection.commit()


def run_azflow() -> None:
    """Run AZFlow locally with Uvicorn auto-reload."""
    config = compose_environment()
    os.environ["AZFLOW_DATABASE_URL"] = database_url()

    print(f"Starting AZFlow on http://localhost:{config['AZFLOW_API_PORT']}")
    print(f"Swagger UI available at http://localhost:{config['AZFLOW_API_PORT']}/docs")
    uvicorn.run(
        "AZFlow.api:app",
        host=config["AZFLOW_API_HOST"],
        port=int(config["AZFLOW_API_PORT"]),
        reload=True,
    )


def _confirm(prompt: str) -> bool:
    """Ask for confirmation, defaulting to No."""
    try:
        return input(prompt).strip().lower() in {"y", "yes"}
    except (EOFError, KeyboardInterrupt):
        return False


def maybe_stop_postgres() -> None:
    """Ask whether to stop PostgreSQL; default is No."""
    if _confirm("Stop PostgreSQL too? [y/N] "):
        print("Stopping PostgreSQL...")
        compose("stop", "postgres")
    else:
        print("Leaving PostgreSQL running.")


def reset_database() -> None:
    """Reset the local development database after explicit confirmation."""
    print(
        "WARNING: This will DESTROY the local development database and delete "
        "ALL of its data. This action cannot be undone."
    )
    if not _confirm("Reset the development database and delete all its data? [y/N] "):
        print("Aborted.")
        return

    print("Stopping services and removing the development volume...")
    compose("--profile", "dev", "down", "-v", "--remove-orphans")

    print("Recreating PostgreSQL...")
    start_postgres()
    wait_for_postgres()
    upgrade_database()
    seed_database()
    print("Development database has been reset, migrated, and seeded.")


def main() -> None:
    """Run the development launcher or the database reset command."""
    if len(sys.argv) > 1 and sys.argv[1] == "reset":
        reset_database()
        return

    start_postgres()
    wait_for_postgres()
    upgrade_database()
    run_azflow()
    maybe_stop_postgres()


if __name__ == "__main__":
    main()
