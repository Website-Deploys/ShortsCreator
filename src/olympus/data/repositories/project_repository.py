"""Storage-backed project repository.

Persists each project as a JSON document via the storage abstraction
(``projects/{id}/project.json``). This gives durable persistence - projects
survive browser refreshes and server restarts - using only the existing storage
backend, with no database required for the MVP. A database-backed repository can
later replace this behind the same :class:`ProjectRepository` contract.
"""

from __future__ import annotations

import json

from olympus.domain.contracts.projects import ProjectRepository
from olympus.domain.contracts.storage import StoragePort
from olympus.domain.entities.project import Project
from olympus.platform.errors import StorageError
from olympus.platform.logging import get_logger

log = get_logger(__name__)

_DOC = "project.json"
_PREFIX = "projects/"


class StorageProjectRepository(ProjectRepository):
    """Persist projects as JSON documents in object storage."""

    def __init__(self, storage: StoragePort) -> None:
        self._storage = storage

    @staticmethod
    def _key(project_id: str) -> str:
        return f"{_PREFIX}{project_id}/{_DOC}"

    async def save(self, project: Project) -> None:
        data = json.dumps(project.to_dict()).encode("utf-8")
        await self._storage.put(self._key(project.id), data, content_type="application/json")

    async def get(self, project_id: str) -> Project | None:
        key = self._key(project_id)
        if not await self._storage.exists(key):
            return None
        raw = await self._storage.get(key)
        try:
            return Project.from_dict(json.loads(raw))
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            raise StorageError("Stored project is corrupt.", details={"id": project_id}) from exc

    async def list(self) -> list[Project]:
        keys = await self._storage.list_keys(_PREFIX)
        projects: list[Project] = []
        for key in keys:
            if not key.endswith(_DOC):
                continue
            try:
                raw = await self._storage.get(key)
                projects.append(Project.from_dict(json.loads(raw)))
            except (json.JSONDecodeError, KeyError, ValueError):
                log.warning("skipping_corrupt_project", key=key)
                continue
        projects.sort(key=lambda p: p.created_at, reverse=True)
        return projects

    async def delete(self, project_id: str) -> None:
        await self._storage.delete(self._key(project_id))
