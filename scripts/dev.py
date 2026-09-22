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


def start_postgres() -> None:
    """Start the Docker Compose ``postgres`` service in detached mode."""
    print("Starting PostgreSQL via Docker Compose...")
    subprocess.run(
        ["docker", "compose", "up", "-d", "postgres"],
        cwd=REPO_ROOT,
        check=True,
    )


def wait_for_postgres() -> None:
    """Wait until PostgreSQL accepts connections."""
    config = compose_environment()
    user = config["POSTGRES_USER"]
    database = config["POSTGRES_DB"]

    print("Waiting for PostgreSQL to become ready...")
    deadline = time.monotonic() + READINESS_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        result = subprocess.run(
            [
                "docker",
                "compose",
                "exec",
                "-T",
                "postgres",
                "pg_isready",
                "-U",
                user,
                "-d",
                database,
            ],
            cwd=REPO_ROOT,
            capture_output=True,
        )
        if result.returncode == 0:
            print("PostgreSQL is ready.")
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
    import psycopg
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


def run_azflow() -> None:
    """Run AZFlow locally with Uvicorn auto-reload in the current venv."""
    config = compose_environment()
    host = config["AZFLOW_API_HOST"]
    port = config["AZFLOW_API_PORT"]

    process_environment = os.environ.copy()
    process_environment["AZFLOW_DATABASE_URL"] = database_url()

    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "AZFlow.api:app",
        "--reload",
        "--host",
        host,
        "--port",
        port,
    ]

    print(f"Starting AZFlow on {host}:{port} with auto-reload...")
    process = subprocess.Popen(
        command,
        cwd=REPO_ROOT,
        env=process_environment,
    )
    try:
        process.wait()
    except KeyboardInterrupt:
        print("\nStopping AZFlow...")
        _terminate(process)


def _terminate(process: subprocess.Popen[bytes]) -> None:
    """Terminate a subprocess cleanly, escalating to kill if needed."""
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _confirm(prompt: str) -> bool:
    """Ask a yes/no question on stdin with a default of No."""
    try:
        answer = input(prompt)
    except (EOFError, KeyboardInterrupt):
        answer = ""

    return answer.strip().lower().startswith("y")


def maybe_stop_postgres() -> None:
    """Ask whether to stop PostgreSQL; default is No."""
    if _confirm("Stop PostgreSQL too? [y/N] "):
        print("Stopping PostgreSQL...")
        subprocess.run(
            ["docker", "compose", "stop", "postgres"],
            cwd=REPO_ROOT,
            check=True,
        )
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
    subprocess.run(
        ["docker", "compose", "down", "-v"],
        cwd=REPO_ROOT,
        check=True,
    )

    print("Recreating PostgreSQL...")
    start_postgres()
    wait_for_postgres()
    print("PostgreSQL is ready. Development database has been reset.")


def main() -> None:
    """Run the development launcher or the database reset command."""
    if len(sys.argv) > 1 and sys.argv[1] == "reset":
        reset_database()
        return

    start_postgres()
    wait_for_postgres()
    run_azflow()
    maybe_stop_postgres()


if __name__ == "__main__":
    main()
