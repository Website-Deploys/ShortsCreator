"""The project service.

Coordinates the project lifecycle on top of the repository and storage. Every
operation reflects the *honest* state of the work - the service never advances a
project to ``PROCESSING`` or ``COMPLETE`` without a real pipeline doing the work.
Creating a project records an uploaded video; queuing marks it as awaiting the
(not-yet-connected) editing pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass

from olympus.domain.contracts.projects import ProjectRepository
from olympus.domain.contracts.storage import StoragePort
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.platform.errors import NotFoundError, ValidationError
from olympus.platform.logging import get_logger
from olympus.utils import new_id, project_write_lock, utc_now

log = get_logger(__name__)


@dataclass(slots=True)
class NewProjectInput:
    """Inputs for creating a project from an already-uploaded video."""

    storage_key: str
    source_filename: str
    size_bytes: int
    video_format: str
    content_type: str | None = None
    duration_seconds: float | None = None
    width: int | None = None
    height: int | None = None
    upload_duration_ms: float | None = None


# Maximum length of a project name. Enforced both when deriving a name from an
# uploaded filename and when a user renames a project, so the two paths cannot
# diverge. Chosen to comfortably fit real titles while bounding payload/UI size.
MAX_PROJECT_NAME_LENGTH = 200


def _derive_name(filename: str) -> str:
    """Turn a filename into a friendly project name (drop the extension).

    The result is bounded to :data:`MAX_PROJECT_NAME_LENGTH` so that a hostile or
    accidental multi-thousand-character filename cannot produce an unbounded
    project name - which would bloat API payloads and persisted state and break
    the UI layout. This honours the same ceiling enforced by
    :meth:`ProjectService.rename`, so derived and user-set names are consistent.
    """

    stem = filename.rsplit(".", 1)[0].strip()
    name = stem or filename.strip() or "Untitled"
    if len(name) > MAX_PROJECT_NAME_LENGTH:
        name = name[:MAX_PROJECT_NAME_LENGTH].rstrip()
    return name


class ProjectService:
    """Application logic for managing projects."""

    def __init__(self, repository: ProjectRepository, storage: StoragePort) -> None:
        self._repo = repository
        self._storage = storage

    async def create(self, data: NewProjectInput) -> Project:
        """Create and persist a project for an uploaded video."""

        # The referenced upload must actually exist in storage.
        if not await self._storage.exists(data.storage_key):
            raise ValidationError(
                "The referenced upload was not found.",
                details={"storage_key": data.storage_key},
            )

        now = utc_now()
        project = Project(
            id=new_id("proj"),
            name=_derive_name(data.source_filename),
            source_filename=data.source_filename,
            storage_key=data.storage_key,
            size_bytes=data.size_bytes,
            video_format=data.video_format,
            content_type=data.content_type,
            duration_seconds=data.duration_seconds,
            width=data.width,
            height=data.height,
            status=ProjectStatus.UPLOADED,
            created_at=now,
            updated_at=now,
            upload_duration_ms=data.upload_duration_ms,
        )
        await self._repo.save(project)
        log.info("project_created", project_id=project.id, name=project.name)
        return project

    async def get(self, project_id: str) -> Project:
        project = await self._repo.get(project_id)
        if project is None:
            raise NotFoundError("Project not found.", details={"id": project_id})
        return project

    async def list(self) -> list[Project]:
        return await self._repo.list()

    async def queue(self, project_id: str) -> Project:
        """Mark a project as queued for the editing pipeline (honest: not run)."""

        async with project_write_lock(project_id):
            project = await self.get(project_id)
            if project.status in (ProjectStatus.UPLOADED, ProjectStatus.FAILED):
                project.status = ProjectStatus.QUEUED
                project.updated_at = utc_now()
                await self._repo.save(project)
                log.info("project_queued", project_id=project.id)
            return project

    async def rename(self, project_id: str, name: str) -> Project:
        """Rename a project."""

        cleaned = name.strip()
        if not cleaned:
            raise ValidationError("Project name cannot be empty.")
        if len(cleaned) > MAX_PROJECT_NAME_LENGTH:
            raise ValidationError("Project name is too long.")
        async with project_write_lock(project_id):
            project = await self.get(project_id)
            project.name = cleaned
            project.updated_at = utc_now()
            await self._repo.save(project)
            log.info("project_renamed", project_id=project_id)
            return project

    async def set_thumbnail(
        self, project_id: str, data: bytes, *, content_type: str | None
    ) -> Project:
        """Store a thumbnail image for the project (a real frame from the video)."""

        key = f"projects/{project_id}/thumbnail.jpg"
        await self._storage.put(key, data, content_type=content_type or "image/jpeg")
        async with project_write_lock(project_id):
            project = await self.get(project_id)
            project.thumbnail_key = key
            project.updated_at = utc_now()
            await self._repo.save(project)
            log.info("project_thumbnail_set", project_id=project_id, size_bytes=len(data))
            return project

    async def delete(self, project_id: str) -> None:
        """Delete a project and its stored artifacts (source + thumbnail)."""

        async with project_write_lock(project_id):
            project = await self._repo.get(project_id)
            if project is None:
                return  # idempotent
            await self._storage.delete(project.storage_key)
            if project.thumbnail_key:
                await self._storage.delete(project.thumbnail_key)
            await self._repo.delete(project_id)
            log.info("project_deleted", project_id=project_id)
