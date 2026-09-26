"""Alembic environment for AZFlow PostgreSQL migrations."""

from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, pool

from AZFlow.infrastructure.config import load_settings

config = context.config
target_metadata = None


def database_url() -> str:
    """Return the PostgreSQL URL from the shared AZFlow configuration."""
    url = load_settings().database_url
    if not url:
        raise RuntimeError(
            "PostgreSQL is not configured. Set POSTGRES_USER, "
            "POSTGRES_PASSWORD and POSTGRES_DB."
        )
    return url.replace("postgresql://", "postgresql+psycopg://", 1)


def run_migrations_offline() -> None:
    """Run migrations without creating a database connection."""
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations using a database connection."""
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = database_url()
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
