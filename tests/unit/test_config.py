"""Tests for the configuration layer."""

from __future__ import annotations

from olympus.platform.config import Settings
from olympus.platform.config.settings import Environment, StorageBackend


def test_defaults_are_sane() -> None:
    """A freshly constructed Settings object has safe development defaults."""

    settings = Settings()
    assert settings.environment is Environment.DEVELOPMENT
    assert settings.storage.backend is StorageBackend.LOCAL
    assert settings.api.port == 8000
    assert settings.is_production is False


def test_cors_origins_parsed_from_csv() -> None:
    """CORS origins provided as a comma-separated string parse into a list."""

    settings = Settings(api={"cors_origins": "http://a.com, http://b.com"})
    assert settings.api.cors_origins_list == ["http://a.com", "http://b.com"]


def test_production_flag() -> None:
    """The production helper reflects the environment."""

    settings = Settings(environment=Environment.PRODUCTION)
    assert settings.is_production is True
