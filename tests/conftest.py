"""Shared pytest fixtures.

Configures a test-oriented environment and provides reusable fixtures:

- ``test_settings`` - settings forced to the ``testing`` environment with a
  temporary local-storage root, so tests never touch real infrastructure.
- ``app`` / ``client`` - the FastAPI app and an HTTP test client wired to it,
  with dependency overrides for anything that would require live infrastructure
  (the database session is overridden so health/route tests run without a DB).

These fixtures embody the architecture's testability: because every dependency
is injected behind a contract, tests substitute fakes trivially.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from olympus.api.app import create_app
from olympus.api.dependencies import db_session_provider
from olympus.platform.config import Settings, get_settings
from olympus.platform.config.settings import Environment


@pytest.fixture
def test_settings(tmp_path: object) -> Settings:
    """Return settings pinned to the testing environment with temp storage."""

    get_settings.cache_clear()
    settings = Settings(
        environment=Environment.TESTING,
        debug=True,
    )
    # Point local storage at a temp directory so tests are isolated.
    settings.storage.local_root = str(tmp_path)  # type: ignore[attr-defined]
    return settings


class _FakeSession:
    """A minimal async session stand-in for route tests that need no real DB."""

    async def execute(self, *_args: object, **_kwargs: object) -> object:
        return object()


async def _fake_session() -> AsyncGenerator[_FakeSession, None]:
    yield _FakeSession()


@pytest.fixture
def app(test_settings: Settings) -> FastAPI:
    """Build the application with the database dependency overridden by a fake."""

    application = create_app(test_settings)
    application.dependency_overrides[db_session_provider] = _fake_session
    return application


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """Provide an HTTP test client bound to the application."""

    with TestClient(app) as test_client:
        yield test_client
