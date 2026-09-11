import pytest
from pydantic import ValidationError

from AZFlow.infrastructure.config import (
    DEFAULT_API_HOST,
    DEFAULT_API_PORT,
    load_settings,
)

_ENV_VARS = (
    "AZFLOW_API_HOST",
    "AZFLOW_API_PORT",
    "AZFLOW_DATABASE_URL",
    "DATABASE_URL",
)


@pytest.fixture(autouse=True)
def clear_settings_env(monkeypatch):
    for name in _ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_defaults_when_env_unset():
    settings = load_settings()
    assert settings.api_host == DEFAULT_API_HOST
    assert settings.api_port == DEFAULT_API_PORT
    assert settings.database_url is None


def test_reads_values_from_env(monkeypatch):
    monkeypatch.setenv("AZFLOW_API_HOST", "127.0.0.1")
    monkeypatch.setenv("AZFLOW_API_PORT", "9000")
    monkeypatch.setenv("AZFLOW_DATABASE_URL", "postgresql://user:pass@db:5432/azflow")

    settings = load_settings()

    assert settings.api_host == "127.0.0.1"
    assert settings.api_port == 9000
    assert settings.database_url == "postgresql://user:pass@db:5432/azflow"


def test_missing_database_url_does_not_raise():
    settings = load_settings()
    assert settings.database_url is None


def test_invalid_port_raises_validation_error(monkeypatch):
    monkeypatch.setenv("AZFLOW_API_PORT", "not-a-number")
    with pytest.raises(ValidationError):
        load_settings()
