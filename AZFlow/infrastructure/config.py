"""Application configuration from environment variables."""

import os
import re
from urllib.parse import quote

from dotenv import dotenv_values
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_API_HOST = "0.0.0.0"
DEFAULT_API_PORT = 8000
DEFAULT_DISPLAY_RECENT_CALLS_MAX = 10
DEFAULT_POSTGRES_HOST = "localhost"
DEFAULT_POSTGRES_PORT = 5432

_APPOINTMENT_SOURCE_PREFIX = "AZFLOW_APPOINTMENT_SOURCE_"
_APPOINTMENT_SOURCE_KEY = re.compile(r"^AZFLOW_APPOINTMENT_SOURCE_([1-9][0-9]*)$")


class Settings(BaseSettings):
    """AZFlow application settings."""

    model_config = SettingsConfigDict(
        env_prefix="AZFLOW_",
        env_file=".env",
        extra="ignore",
    )

    api_host: str = DEFAULT_API_HOST
    api_port: int = DEFAULT_API_PORT
    display_recent_calls_max: int = DEFAULT_DISPLAY_RECENT_CALLS_MAX
    # Populated from numbered AZFLOW_APPOINTMENT_SOURCE_<n> entries.
    appointment_sources: tuple[str, ...] = ()
    postgres_host: str = Field(DEFAULT_POSTGRES_HOST, validation_alias="POSTGRES_HOST")
    postgres_port: int = Field(DEFAULT_POSTGRES_PORT, validation_alias="POSTGRES_PORT")
    postgres_user: str | None = Field(None, validation_alias="POSTGRES_USER")
    postgres_password: str | None = Field(None, validation_alias="POSTGRES_PASSWORD")
    postgres_db: str | None = Field(None, validation_alias="POSTGRES_DB")

    @property
    def database_url(self) -> str | None:
        """Build the PostgreSQL URL when database credentials are configured."""
        if (
            not self.postgres_user
            or self.postgres_password is None
            or not self.postgres_db
        ):
            return None
        user = quote(self.postgres_user, safe="")
        password = quote(self.postgres_password, safe="")
        database = quote(self.postgres_db, safe="")
        return (
            f"postgresql://{user}:{password}@"
            f"{self.postgres_host}:{self.postgres_port}/{database}"
        )


def _numbered_appointment_sources() -> tuple[str, ...]:
    """Load sparse, numbered source entries from .env and the environment."""
    config = {**dotenv_values(".env"), **os.environ}
    indexed: dict[int, str] = {}

    for name, value in config.items():
        if not name.startswith(_APPOINTMENT_SOURCE_PREFIX):
            continue
        match = _APPOINTMENT_SOURCE_KEY.fullmatch(name)
        if match is None:
            raise ValueError(f"Invalid appointment source setting: {name}")
        index = int(match.group(1))
        if index in indexed:
            raise ValueError(f"Duplicate appointment source index: {index}")
        if value and value.strip():
            indexed[index] = value.strip()

    return tuple(indexed[index] for index in sorted(indexed))


def load_settings() -> Settings:
    """Load standard settings and sparse appointment-source configuration."""
    settings = Settings()  # type: ignore[call-arg]
    return settings.model_copy(
        update={"appointment_sources": _numbered_appointment_sources()}
    )
