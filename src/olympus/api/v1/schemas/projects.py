"""Schemas for the projects API."""

from __future__ import annotations

from typing import Any, Literal

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
    desired_clip_count: int | None = Field(
        default=None, ge=1, le=10, description="Optional desired number of Shorts."
    )
    content_category: str = Field(default="auto", max_length=40)
    editing_intensity: str = Field(default="balanced", max_length=40)
    music_enabled: bool = True
    sfx_enabled: bool = True
    captions_enabled: bool = True


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
    source_type: str
    source_url: str | None
    link_ingestion_id: str | None
    desired_clip_count: int | None
    content_category: str
    editing_intensity: str
    music_enabled: bool
    sfx_enabled: bool
    captions_enabled: bool

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
            source_type=project.source_type,
            source_url=project.source_url,
            link_ingestion_id=project.link_ingestion_id,
            desired_clip_count=project.desired_clip_count,
            content_category=project.content_category,
            editing_intensity=project.editing_intensity,
            music_enabled=project.music_enabled,
            sfx_enabled=project.sfx_enabled,
            captions_enabled=project.captions_enabled,
        )


class CreateProjectFromLinkRequest(BaseModel):
    """Download a permitted video link, create a project, and start analysis."""

    url: str = Field(min_length=8, max_length=2048)
    permission_confirmed: bool = Field(
        default=False,
        description="Caller confirms they own or have permission to edit the linked video.",
    )
    start_processing: bool = True
    quality: Literal["best"] = "best"
    mode: Literal["metadata_only", "download_only", "full_pipeline"] = "full_pipeline"
    desired_clip_count: int | None = Field(default=None, ge=1, le=10)
    content_category: str = Field(default="auto", max_length=40)
    editing_intensity: str = Field(default="balanced", max_length=40)
    music_enabled: bool = True
    sfx_enabled: bool = True
    captions_enabled: bool = True


class LinkDownloadResponse(BaseModel):
    """Structured status for video-link ingestion."""

    ingestion_id: str
    status: str
    url: str
    original_url: str
    reason: str | None = None
    filename: str | None = None
    storage_key: str | None = None
    size_bytes: int | None = None
    video_format: str | None = None
    content_type: str | None = None
    project_id: str | None = None
    job_id: str | None = None
    status_url: str | None = None
    resume_url: str | None = None
    link_source: dict[str, Any] = Field(default_factory=dict)
    video_metadata: dict[str, Any] = Field(default_factory=dict)
    download_selection: dict[str, Any] = Field(default_factory=dict)
    link_ingestion_status: dict[str, Any] = Field(default_factory=dict)
    rights_confirmation: dict[str, Any] = Field(default_factory=dict)
    media_probe: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)


class CreateProjectFromLinkResponse(BaseModel):
    """Result of link ingestion plus optional auto-created project."""

    download: LinkDownloadResponse
    project: ProjectResponse | None = None
