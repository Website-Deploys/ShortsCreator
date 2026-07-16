"""The Project entity.

A Project is the unit of work a creator sees: an uploaded video and everything
Olympus will eventually do with it. This is a technology-free dataclass; how it
is stored is the repository's concern.

``status`` reflects the *honest* state of the work. The MVP can truthfully reach
``UPLOADED`` (the file is stored), ``ANALYZING`` (the video understanding
pipeline is running), ``ANALYZED`` (the Cognitive Engine has produced a
structured understanding), and ``QUEUED`` (the creator asked to generate Shorts,
and the work is awaiting the editing pipeline). ``PROCESSING``, ``COMPLETE``, and
``FAILED`` exist for when the editing pipeline is connected - they are never set
speculatively, so the UI never shows fabricated progress.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class ProjectStatus(StrEnum):
    """Lifecycle status of a project (honest, never fabricated)."""

    UPLOADED = "uploaded"
    ANALYZING = "analyzing"
    ANALYZED = "analyzed"
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass(slots=True)
class Project:
    """A creator's uploaded video and its processing lifecycle."""

    id: str
    name: str
    source_filename: str
    storage_key: str
    size_bytes: int
    video_format: str
    content_type: str | None
    duration_seconds: float | None
    width: int | None
    height: int | None
    status: ProjectStatus
    created_at: datetime
    updated_at: datetime
    # Optional, added without breaking older records (read with .get on load).
    thumbnail_key: str | None = None
    upload_duration_ms: float | None = None
    source_type: str = "upload"
    source_url: str | None = None
    link_ingestion_id: str | None = None
    desired_clip_count: int | None = None
    content_category: str = "auto"
    editing_intensity: str = "balanced"
    music_enabled: bool = True
    sfx_enabled: bool = True
    captions_enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-safe dict (datetimes -> ISO, enum -> value)."""

        return {
            "id": self.id,
            "name": self.name,
            "source_filename": self.source_filename,
            "storage_key": self.storage_key,
            "size_bytes": self.size_bytes,
            "video_format": self.video_format,
            "content_type": self.content_type,
            "duration_seconds": self.duration_seconds,
            "width": self.width,
            "height": self.height,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "thumbnail_key": self.thumbnail_key,
            "upload_duration_ms": self.upload_duration_ms,
            "source_type": self.source_type,
            "source_url": self.source_url,
            "link_ingestion_id": self.link_ingestion_id,
            "desired_clip_count": self.desired_clip_count,
            "content_category": self.content_category,
            "editing_intensity": self.editing_intensity,
            "music_enabled": self.music_enabled,
            "sfx_enabled": self.sfx_enabled,
            "captions_enabled": self.captions_enabled,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Project:
        """Reconstruct a Project from its serialised dict (tolerant of old records)."""

        return cls(
            id=data["id"],
            name=data["name"],
            source_filename=data["source_filename"],
            storage_key=data["storage_key"],
            size_bytes=data["size_bytes"],
            video_format=data["video_format"],
            content_type=data.get("content_type"),
            duration_seconds=data.get("duration_seconds"),
            width=data.get("width"),
            height=data.get("height"),
            status=ProjectStatus(data["status"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            thumbnail_key=data.get("thumbnail_key"),
            upload_duration_ms=data.get("upload_duration_ms"),
            source_type=data.get("source_type", "upload"),
            source_url=data.get("source_url"),
            link_ingestion_id=data.get("link_ingestion_id"),
            desired_clip_count=data.get("desired_clip_count"),
            content_category=data.get("content_category", "auto"),
            editing_intensity=data.get("editing_intensity", "balanced"),
            music_enabled=bool(data.get("music_enabled", True)),
            sfx_enabled=bool(data.get("sfx_enabled", True)),
            captions_enabled=bool(data.get("captions_enabled", True)),
        )
