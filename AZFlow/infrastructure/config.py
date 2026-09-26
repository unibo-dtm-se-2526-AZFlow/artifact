"""Application configuration from environment variables."""

from urllib.parse import quote

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_API_HOST = "0.0.0.0"
DEFAULT_API_PORT = 8000
DEFAULT_DISPLAY_RECENT_CALLS_MAX = 10
DEFAULT_POSTGRES_HOST = "localhost"
DEFAULT_POSTGRES_PORT = 5432


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


def load_settings() -> Settings:
    """Load AZFlow settings."""
    return Settings()  # type: ignore[call-arg]
