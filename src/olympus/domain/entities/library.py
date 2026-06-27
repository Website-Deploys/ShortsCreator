"""Project Management & Asset Library entities.

This is the production layer that lets creators *manage* everything Olympus has
produced: the assets (source videos, clips, renders, exports), version history,
a clip/export library, global search, dashboard statistics, storage breakdowns,
and an activity feed. It is a read-only aggregation over the engines' real
outputs, plus a small amount of additive, library-owned metadata (favorites,
tags, archive state) and captured version snapshots.

These are technology-free dataclasses. Honesty-first: every record reflects real
stored state. A field that cannot be determined from what an engine actually
produced is ``None`` (UNKNOWN), never fabricated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class AssetKind(StrEnum):
    """The kind of asset in the library."""

    SOURCE_VIDEO = "source_video"
    CLIP = "clip"
    RENDER = "render"
    EXPORT = "export"
    THUMBNAIL = "thumbnail"


@dataclass(slots=True)
class AssetRecord:
    """One managed asset, aggregated from a real engine output or upload."""

    id: str
    project_id: str
    project_name: str
    kind: AssetKind
    name: str
    created_at: datetime | None = None
    storage_key: str | None = None
    size_bytes: int | None = None
    content_type: str | None = None
    tags: list[str] = field(default_factory=list)
    favorite: bool = False
    archived: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "project_name": self.project_name,
            "kind": self.kind.value,
            "name": self.name,
            "created_at": _iso(self.created_at),
            "storage_key": self.storage_key,
            "size_bytes": self.size_bytes,
            "content_type": self.content_type,
            "tags": self.tags,
            "favorite": self.favorite,
            "archived": self.archived,
            "metadata": self.metadata,
        }


@dataclass(slots=True)
class ClipRecord:
    """A clip Olympus produced, with its real per-clip facts (UNKNOWN when absent)."""

    clip_id: str
    project_id: str
    project_name: str
    title: str
    duration: float | None = None
    viral_score: float | None = None
    platform: str | None = None
    status: str = "planned"  # planned | rendered
    thumbnail_key: str | None = None
    render_version: str | None = None
    created_at: datetime | None = None
    tags: list[str] = field(default_factory=list)
    favorite: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "clip_id": self.clip_id,
            "project_id": self.project_id,
            "project_name": self.project_name,
            "title": self.title,
            "duration": self.duration,
            "viral_score": self.viral_score,
            "platform": self.platform,
            "status": self.status,
            "thumbnail_key": self.thumbnail_key,
            "render_version": self.render_version,
            "created_at": _iso(self.created_at),
            "tags": self.tags,
            "favorite": self.favorite,
        }


@dataclass(slots=True)
class ExportRecord:
    """A rendered export, with the renderer's real measured media facts."""

    id: str
    project_id: str
    project_name: str
    clip_id: str
    platform: str | None = None
    resolution: str | None = None
    codec: str | None = None
    bitrate_kbps: int | None = None
    file_size: int | None = None
    render_time_ms: float | None = None
    download_status: str = "unavailable"  # available | unavailable
    storage_key: str | None = None
    checksum: str | None = None
    created_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "project_name": self.project_name,
            "clip_id": self.clip_id,
            "platform": self.platform,
            "resolution": self.resolution,
            "codec": self.codec,
            "bitrate_kbps": self.bitrate_kbps,
            "file_size": self.file_size,
            "render_time_ms": self.render_time_ms,
            "download_status": self.download_status,
            "storage_key": self.storage_key,
            "checksum": self.checksum,
            "created_at": _iso(self.created_at),
        }


@dataclass(slots=True)
class VersionRecord:
    """A captured snapshot of one engine's output for a project.

    Engines overwrite their current output, so the library captures versions when
    it first observes (or is asked to capture) an output. Versions are append-only
    and deduplicated by content checksum - history is never overwritten.
    """

    project_id: str
    engine: str
    version: int
    created_at: datetime
    checksum: str
    status: str | None = None
    summary: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "engine": self.engine,
            "version": self.version,
            "created_at": self.created_at.isoformat(),
            "checksum": self.checksum,
            "status": self.status,
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> VersionRecord:
        return cls(
            project_id=raw["project_id"],
            engine=raw["engine"],
            version=int(raw["version"]),
            created_at=_parse_dt(raw.get("created_at")) or _utc(),
            checksum=raw.get("checksum", ""),
            status=raw.get("status"),
            summary=raw.get("summary", {}) or {},
        )


class ActivityType(StrEnum):
    """Categories of activity-feed events."""

    PROJECT_CREATED = "project_created"
    WORKFLOW_STARTED = "workflow_started"
    WORKFLOW_COMPLETED = "workflow_completed"
    WORKFLOW_FAILED = "workflow_failed"
    WORKFLOW_CANCELLED = "workflow_cancelled"
    STAGE_FINISHED = "stage_finished"
    VERSION_CAPTURED = "version_captured"
    PROJECT_ARCHIVED = "project_archived"
    PROJECT_RESTORED = "project_restored"
    ASSET_FAVORITED = "asset_favorited"
    ASSET_TAGGED = "asset_tagged"
    CLEANUP_PERFORMED = "cleanup_performed"
    EXPORT_DOWNLOADED = "export_downloaded"
    OTHER = "other"


@dataclass(slots=True)
class ActivityEvent:
    """One entry on the activity feed (a real action that occurred)."""

    id: str
    ts: datetime
    type: ActivityType
    message: str
    project_id: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "ts": self.ts.isoformat(),
            "type": self.type.value,
            "message": self.message,
            "project_id": self.project_id,
            "detail": self.detail,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ActivityEvent:
        return cls(
            id=raw["id"],
            ts=_parse_dt(raw.get("ts")) or _utc(),
            type=_safe_activity_type(raw.get("type")),
            message=raw.get("message", ""),
            project_id=raw.get("project_id"),
            detail=raw.get("detail", {}) or {},
        )


@dataclass(slots=True)
class StorageBreakdown:
    """Per-project storage consumption, broken down by namespace."""

    project_id: str
    project_name: str
    namespaces: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.namespaces.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "project_name": self.project_name,
            "namespaces": self.namespaces,
            "total": self.total,
        }


@dataclass(slots=True)
class DashboardStats:
    """Global statistics across everything Olympus has produced."""

    total_projects: int = 0
    videos_processed: int = 0
    minutes_analyzed: float = 0.0
    clips_generated: int = 0
    renders_completed: int = 0
    exports: int = 0
    average_viral_score: float | None = None
    storage_bytes: int = 0
    archived_projects: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_projects": self.total_projects,
            "videos_processed": self.videos_processed,
            "minutes_analyzed": round(self.minutes_analyzed, 2),
            "clips_generated": self.clips_generated,
            "renders_completed": self.renders_completed,
            "exports": self.exports,
            "average_viral_score": self.average_viral_score,
            "storage_bytes": self.storage_bytes,
            "archived_projects": self.archived_projects,
        }


@dataclass(slots=True)
class ProjectLibraryMeta:
    """Library-owned, additive metadata for a project (never touches engine data).

    ``assets`` holds per-asset overrides (favorite/tags) keyed by asset id, so the
    library can tag/favorite individual clips and exports without modifying any
    engine output.
    """

    project_id: str
    archived: bool = False
    favorite: bool = False
    tags: list[str] = field(default_factory=list)
    assets: dict[str, dict[str, Any]] = field(default_factory=dict)

    def asset_meta(self, asset_id: str) -> dict[str, Any]:
        return self.assets.get(asset_id, {})

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "archived": self.archived,
            "favorite": self.favorite,
            "tags": self.tags,
            "assets": self.assets,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ProjectLibraryMeta:
        return cls(
            project_id=raw["project_id"],
            archived=bool(raw.get("archived", False)),
            favorite=bool(raw.get("favorite", False)),
            tags=list(raw.get("tags", [])),
            assets=raw.get("assets", {}) or {},
        )


@dataclass(slots=True)
class SearchHit:
    """One global-search hit across projects/clips/videos/exports."""

    kind: str  # project | clip | video | export
    id: str
    project_id: str
    title: str
    subtitle: str = ""
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "id": self.id,
            "project_id": self.project_id,
            "title": self.title,
            "subtitle": self.subtitle,
            "detail": self.detail,
        }


@dataclass(slots=True)
class CleanupResult:
    """The honest outcome of a cleanup operation (what was actually removed)."""

    operation: str
    deleted_keys: list[str] = field(default_factory=list)
    freed_bytes: int = 0
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "deleted_count": len(self.deleted_keys),
            "deleted_keys": self.deleted_keys,
            "freed_bytes": self.freed_bytes,
            "note": self.note,
        }


# -- helpers ------------------------------------------------------------------
def _safe_activity_type(value: Any) -> ActivityType:
    try:
        return ActivityType(value)
    except ValueError:
        return ActivityType.OTHER


def _utc() -> datetime:
    from olympus.utils import utc_now

    return utc_now()


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
