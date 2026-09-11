"""Application configuration from environment variables"""

from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_API_HOST = "0.0.0.0"
DEFAULT_API_PORT = 8000


class Settings(BaseSettings):
    """AZFlow application settings"""

    model_config = SettingsConfigDict(
        env_prefix="AZFLOW_",
        env_file=".env",
        extra="ignore",
    )

    api_host: str = DEFAULT_API_HOST
    api_port: int = DEFAULT_API_PORT
    database_url: Optional[str] = None


def load_settings() -> Settings:
    """Load AZFlow settings"""
    return Settings()
