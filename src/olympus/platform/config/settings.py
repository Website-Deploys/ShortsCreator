"""Typed, validated application settings.

Configuration is loaded from environment variables (and an optional ``.env``
file in development) into strongly-typed, validated models using
``pydantic-settings``. This gives us:

- a single source of truth for configuration,
- validation at startup (the app fails loudly on misconfiguration rather than
  failing silently later - per the Constitution),
- no secrets in code.

All variables are prefixed with ``OLYMPUS_`` and nested groups use ``__`` as a
delimiter, e.g. ``OLYMPUS_DATABASE__URL``.

Settings are accessed exclusively through :func:`get_settings`, which is cached
so the environment is parsed once per process.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    """Deployment environments. Behaviour (logging, docs exposure) keys off this."""

    DEVELOPMENT = "development"
    TESTING = "testing"
    STAGING = "staging"
    PRODUCTION = "production"


class LogFormat(StrEnum):
    """Log rendering format. ``console`` for humans, ``json`` for machines."""

    CONSOLE = "console"
    JSON = "json"


class ApiSettings(BaseModel):
    """HTTP API server settings."""

    host: str = "0.0.0.0"
    port: int = 8000
    # Origins permitted by CORS, stored as a comma-separated string. Kept as a
    # plain string (rather than list) so it loads cleanly from a single
    # environment variable; use :attr:`cors_origins_list` to get the parsed list.
    cors_origins: str = "http://localhost:3000"

    @property
    def cors_origins_list(self) -> list[str]:
        """The configured CORS origins, parsed into a list."""

        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


class DatabaseSettings(BaseModel):
    """PostgreSQL connection settings (async driver)."""

    url: str = "postgresql+asyncpg://olympus:olympus@localhost:5432/olympus"
    pool_size: int = 5
    max_overflow: int = 10
    # Emit SQL to the logs (development debugging only).
    echo: bool = False


class RedisSettings(BaseModel):
    """Redis settings (caching and ephemeral state)."""

    url: str = "redis://localhost:6379/0"


class QueueSettings(BaseModel):
    """Celery broker / result backend settings."""

    broker_url: str = "redis://localhost:6379/1"
    result_backend: str = "redis://localhost:6379/2"
    # Hard ceiling on task runtime to prevent runaway jobs (seconds).
    task_time_limit: int = 60 * 30


class StorageBackend(StrEnum):
    """Selectable storage adapters."""

    LOCAL = "local"
    S3 = "s3"


class StorageSettings(BaseModel):
    """Storage abstraction settings.

    Defaults to the ``local`` backend so the application starts with no cloud
    credentials. The ``s3`` backend is selected explicitly in deployed
    environments.
    """

    backend: StorageBackend = StorageBackend.LOCAL
    local_root: str = "./storage_data"
    s3_bucket: str | None = None
    s3_region: str | None = None
    s3_endpoint_url: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None


class AiSettings(BaseModel):
    """AI service abstraction settings.

    ``noop`` providers let the application start and run end-to-end wiring tests
    without any model credentials. Real providers are selected in deployed
    environments.
    """

    transcription_provider: str = "noop"


class RenderingSettings(BaseModel):
    """Rendering abstraction settings."""

    backend: str = "ffmpeg"
    ffmpeg_binary: str = "ffmpeg"


class Settings(BaseSettings):
    """Root settings object, composed of typed sub-sections."""

    model_config = SettingsConfigDict(
        env_prefix="OLYMPUS_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    environment: Environment = Environment.DEVELOPMENT
    debug: bool = False
    log_level: str = "INFO"
    log_format: LogFormat = LogFormat.CONSOLE

    api: ApiSettings = Field(default_factory=ApiSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    queue: QueueSettings = Field(default_factory=QueueSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    ai: AiSettings = Field(default_factory=AiSettings)
    rendering: RenderingSettings = Field(default_factory=RenderingSettings)

    @property
    def is_production(self) -> bool:
        """True in production - used to gate debug behaviour and docs exposure."""

        return self.environment == Environment.PRODUCTION


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached, validated application settings.

    Cached so the environment is parsed exactly once per process. Tests may
    clear the cache via ``get_settings.cache_clear()`` to inject overrides.
    """

    return Settings()
