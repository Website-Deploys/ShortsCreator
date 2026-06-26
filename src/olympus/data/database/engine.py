"""Async database engine and session-factory management.

The engine is created *lazily* and held as a process-wide singleton. Lazy
creation is important: it lets the application and its tests import freely and
start without a live database (the engine connects only when first used), while
still sharing one connection pool per process.

Lifecycle:
- ``create_engine()`` is called once at application/worker startup.
- ``dispose_engine()`` is called once at shutdown to close the pool cleanly.
- ``get_engine()`` / ``get_sessionmaker()`` return the singletons for use.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from olympus.platform.config import Settings, get_settings
from olympus.platform.logging import get_logger

log = get_logger(__name__)

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def create_engine(settings: Settings | None = None) -> AsyncEngine:
    """Create (or return the existing) process-wide async engine."""

    global _engine, _sessionmaker
    if _engine is not None:
        return _engine

    settings = settings or get_settings()
    log.info("database_engine_create", pool_size=settings.database.pool_size)

    _engine = create_async_engine(
        settings.database.url,
        echo=settings.database.echo,
        pool_size=settings.database.pool_size,
        max_overflow=settings.database.max_overflow,
        pool_pre_ping=True,  # transparently recover from dropped connections.
        future=True,
    )
    _sessionmaker = async_sessionmaker(
        bind=_engine,
        expire_on_commit=False,
        autoflush=False,
    )
    return _engine


def get_engine() -> AsyncEngine:
    """Return the engine, creating it on first use."""

    return _engine or create_engine()


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Return the session factory, creating the engine on first use."""

    if _sessionmaker is None:
        create_engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def dispose_engine() -> None:
    """Dispose the engine and clear the singletons (call at shutdown)."""

    global _engine, _sessionmaker
    if _engine is not None:
        log.info("database_engine_dispose")
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
