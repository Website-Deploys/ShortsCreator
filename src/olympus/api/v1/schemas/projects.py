"""Schemas for the projects API."""

from __future__ import annotations

from pydantic import BaseModel, Field

from olympus.domain.entities.project import Project


class CreateProjectRequest(BaseModel):
    """Create a project from an already-uploaded video (see POST /uploads)."""

    storage_key: str = Field(description="Storage key returned by the upload endpoint.")
    source_filename: str
    size_bytes: int
    video_format: str
    content_type: str | None = None
    # Optional metadata the client probed from the file (duration/resolution).
    duration_seconds: float | None = None
    width: int | None = None
    height: int | None = None
    upload_duration_ms: float | None = None


class RenameProjectRequest(BaseModel):
    """Rename a project."""

    name: str = Field(min_length=1, max_length=200)


class ProjectResponse(BaseModel):
    """A project, as returned to the client."""

    id: str
    name: str
    source_filename: str
    size_bytes: int
    video_format: str
    content_type: str | None
    duration_seconds: float | None
    width: int | None
    height: int | None
    status: str
    created_at: str
    updated_at: str
    has_thumbnail: bool
    upload_duration_ms: float | None

    @classmethod
    def from_entity(cls, project: Project) -> ProjectResponse:
        return cls(
            id=project.id,
            name=project.name,
            source_filename=project.source_filename,
            size_bytes=project.size_bytes,
            video_format=project.video_format,
            content_type=project.content_type,
            duration_seconds=project.duration_seconds,
            width=project.width,
            height=project.height,
            status=project.status.value,
            created_at=project.created_at.isoformat(),
            updated_at=project.updated_at.isoformat(),
            has_thumbnail=project.thumbnail_key is not None,
            upload_duration_ms=project.upload_duration_ms,
        )
