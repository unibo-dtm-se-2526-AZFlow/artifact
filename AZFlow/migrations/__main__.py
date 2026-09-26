"""Run AZFlow database migrations from an installed package."""

from __future__ import annotations

import sys
from pathlib import Path

from alembic import command
from alembic.config import Config


def alembic_config() -> Config:
    """Build Alembic configuration using packaged migration resources."""
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).resolve().parent))
    return config


def main() -> None:
    """Run a supported AZFlow migration command."""
    action = sys.argv[1] if len(sys.argv) > 1 else "upgrade"
    config = alembic_config()

    if action == "upgrade":
        revision = sys.argv[2] if len(sys.argv) > 2 else "head"
        command.upgrade(config, revision)
        return
    if action == "current":
        command.current(config)
        return
    if action == "history":
        command.history(config)
        return

    raise SystemExit(
        "Usage: python -m AZFlow.migrations [upgrade [revision]|current|history]"
    )


if __name__ == "__main__":
    main()
