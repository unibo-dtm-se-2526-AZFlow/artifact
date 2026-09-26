import pytest
from pydantic import ValidationError

from AZFlow.infrastructure.config import (
    DEFAULT_API_HOST,
    DEFAULT_API_PORT,
    DEFAULT_POSTGRES_HOST,
    DEFAULT_POSTGRES_PORT,
    load_settings,
)

_ENV_VARS = (
    "AZFLOW_API_HOST",
    "AZFLOW_API_PORT",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DB",
)


@pytest.fixture(autouse=True)
def clear_settings_env(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_defaults_when_env_unset():
    settings = load_settings()
    assert settings.api_host == DEFAULT_API_HOST
    assert settings.api_port == DEFAULT_API_PORT
    assert settings.postgres_host == DEFAULT_POSTGRES_HOST
    assert settings.postgres_port == DEFAULT_POSTGRES_PORT
    assert settings.database_url is None


def test_reads_database_values_from_env(monkeypatch):
    monkeypatch.setenv("POSTGRES_HOST", "db")
    monkeypatch.setenv("POSTGRES_PORT", "5433")
    monkeypatch.setenv("POSTGRES_USER", "user")
    monkeypatch.setenv("POSTGRES_PASSWORD", "p@ss")
    monkeypatch.setenv("POSTGRES_DB", "azflow")

    settings = load_settings()

    assert settings.postgres_host == "db"
    assert settings.postgres_port == 5433
    assert settings.database_url == "postgresql://user:p%40ss@db:5433/azflow"


def test_missing_database_credentials_do_not_build_url():
    settings = load_settings()
    assert settings.database_url is None


def test_invalid_api_port_raises_validation_error(monkeypatch):
    monkeypatch.setenv("AZFLOW_API_PORT", "not-a-number")
    with pytest.raises(ValidationError):
        load_settings()


def test_invalid_postgres_port_raises_validation_error(monkeypatch):
    monkeypatch.setenv("POSTGRES_PORT", "not-a-number")
    with pytest.raises(ValidationError):
        load_settings()
