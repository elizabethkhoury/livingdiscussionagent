import pytest

from src.app.settings import AppSettings, get_settings


@pytest.fixture(autouse=True)
def clear_settings_cache(monkeypatch: pytest.MonkeyPatch):
    get_settings.cache_clear()
    monkeypatch.delenv("POSTGRES_DSN", raising=False)
    yield
    get_settings.cache_clear()


def test_postgres_dsn_defaults_to_psycopg_driver():
    settings = AppSettings(postgres_dsn="postgresql://localhost/prompthunt")

    assert settings.postgres_dsn == "postgresql+psycopg://localhost/prompthunt"


def test_postgres_dsn_normalizes_postgres_alias(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("POSTGRES_DSN", "postgres://localhost/prompthunt")

    settings = get_settings()

    assert settings.postgres_dsn == "postgresql+psycopg://localhost/prompthunt"
