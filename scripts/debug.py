"""Local debug launcher for AZFlow.

Stops only a recognized AZFlow instance already listening on the API port,
starts PostgreSQL, then runs Uvicorn without reload for reliable IDE debugging.
"""

import os

import uvicorn

from dev import (
    compose_environment,
    database_url,
    start_postgres,
    upgrade_database,
    wait_for_postgres,
)
from stop import listening_pids, main as stop_azflow


def main() -> None:
    """Start AZFlow under the debugger, stopping an old instance only if needed."""
    config = compose_environment()
    port = int(config["AZFLOW_API_PORT"])

    if listening_pids(port) and stop_azflow() != 0:
        raise SystemExit(1)

    start_postgres()
    wait_for_postgres()
    upgrade_database()

    config = compose_environment()
    os.environ["AZFLOW_DATABASE_URL"] = database_url()

    print(
        f"Starting AZFlow in debug mode on http://localhost:{config['AZFLOW_API_PORT']}"
    )
    print(f"Swagger UI available at http://localhost:{config['AZFLOW_API_PORT']}/docs")
    uvicorn.run(
        "AZFlow.api:app",
        host=config["AZFLOW_API_HOST"],
        port=int(config["AZFLOW_API_PORT"]),
        reload=False,
    )


if __name__ == "__main__":
    main()
