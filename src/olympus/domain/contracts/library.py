"""Project Management contracts (ports).

The library aggregates the engines' real outputs read-only, but it owns a small
amount of additive state of its own - captured version snapshots, an activity
log, and per-project/per-asset metadata (favorites, tags, archive). These ports
persist that state without binding to a backend; the current implementations are
storage-backed under a dedicated ``library/`` namespace that no engine touches.

A database-backed implementation can replace any of these later behind the same
contract.
"""

from __future__ import annotations

import abc
from typing import Any

from olympus.domain.entities.library import ActivityEvent, ProjectLibraryMeta, VersionRecord


class VersionRepository(abc.ABC):
    """Append-only, deduplicated version snapshots per project + engine."""

    @abc.abstractmethod
    async def capture(
        self,
        project_id: str,
        engine: str,
        payload: dict[str, Any],
        *,
        status: str | None,
        summary: dict[str, Any],
    ) -> VersionRecord | None:
        """Capture a new version if it differs from the latest (by checksum).

        Returns the new :class:`VersionRecord`, or ``None`` if the content was
        identical to the latest captured version (no new version is created -
        history is never duplicated or overwritten).
        """

    @abc.abstractmethod
    async def list_engines(self, project_id: str) -> list[str]:
        """Return the engines that have captured versions for a project."""

    @abc.abstractmethod
    async def list_versions(self, project_id: str, engine: str) -> list[VersionRecord]:
        """Return all captured versions for a project + engine, newest last."""

    @abc.abstractmethod
    async def get_payload(
        self, project_id: str, engine: str, version: int
    ) -> dict[str, Any] | None:
        """Return the full captured payload for a specific version, or ``None``."""

    @abc.abstractmethod
    async def delete(self, project_id: str) -> None:
        """Delete all captured versions for a project (idempotent)."""


class ActivityRepository(abc.ABC):
    """Append-only activity log for library-originated actions."""

    @abc.abstractmethod
    async def append(self, event: ActivityEvent) -> None:
        """Record an activity event."""

    @abc.abstractmethod
    async def list(self, project_id: str | None = None, *, limit: int = 200) -> list[ActivityEvent]:
        """Return recorded events (optionally for one project), newest first."""

    @abc.abstractmethod
    async def delete(self, project_id: str) -> None:
        """Delete a project's recorded activity (idempotent)."""


class LibraryMetaRepository(abc.ABC):
    """Library-owned, additive project/asset metadata (favorites, tags, archive)."""

    @abc.abstractmethod
    async def get(self, project_id: str) -> ProjectLibraryMeta:
        """Return the project's library metadata (an empty default if none)."""

    @abc.abstractmethod
    async def save(self, meta: ProjectLibraryMeta) -> None:
        """Persist the project's library metadata."""

    @abc.abstractmethod
    async def list_all(self) -> list[ProjectLibraryMeta]:
        """Return all stored library metadata records."""

    @abc.abstractmethod
    async def delete(self, project_id: str) -> None:
        """Delete a project's library metadata (idempotent)."""
