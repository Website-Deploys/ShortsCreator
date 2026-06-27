"""Project repository contract (port).

Defines persistence for projects without binding to a backend. The MVP
implements it on top of the storage abstraction (durable JSON documents), so
projects survive both browser refreshes and server restarts with no additional
infrastructure. A database-backed implementation can replace it later behind
this same contract.
"""

from __future__ import annotations

import abc

from olympus.domain.entities.project import Project


class ProjectRepository(abc.ABC):
    """Durable storage for :class:`Project` records."""

    @abc.abstractmethod
    async def save(self, project: Project) -> None:
        """Create or update a project (idempotent on id)."""

    @abc.abstractmethod
    async def get(self, project_id: str) -> Project | None:
        """Return the project, or ``None`` if it does not exist."""

    @abc.abstractmethod
    async def list(self) -> list[Project]:
        """Return all projects, newest first."""

    @abc.abstractmethod
    async def delete(self, project_id: str) -> None:
        """Delete a project record (idempotent)."""
