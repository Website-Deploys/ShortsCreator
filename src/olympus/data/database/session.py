"""Database session helpers.

Two ways to obtain a session:

- :func:`get_session` - an async generator suitable for use as a FastAPI
  dependency (``Depends(get_session)``). It yields a session and guarantees it
  is closed; the route is responsible for committing.
- :func:`session_scope` - an async context manager for use in workers and
  scripts that commits on success and rolls back on error.

Both source sessions from the shared session factory so they share one pool.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from olympus.data.database.engine import get_sessionmaker
from olympus.platform.logging import get_logger

log = get_logger(__name__)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a database session (FastAPI dependency).

    The session is always closed; committing is the caller's responsibility so
    that read-only requests incur no commit.
    """

    factory = get_sessionmaker()
    async with factory() as session:
        yield session


@asynccontextmanager
async def session_scope() -> AsyncGenerator[AsyncSession, None]:
    """Provide a transactional session scope for workers/scripts.

    Commits on clean exit, rolls back on exception, always closes.
    """

    factory = get_sessionmaker()
    session = factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        log.error("session_rolled_back")
        raise
    finally:
        await session.close()
