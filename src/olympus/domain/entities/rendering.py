"""Render-output entities - the stable contract the Optimization Engine consumes.

The Optimization & AI Enhancement Engine operates on *finished, rendered MP4s*.
Those MP4s are produced by the Rendering Engine - a separate, independent layer.
To keep the two engines decoupled and independently replaceable (exactly like
every other Olympus engine boundary), the Optimization Engine never reaches into
the renderer; it reads a small, durable **render manifest** that the Rendering
Engine writes once it has produced real output.

These technology-free data types define that manifest. A :class:`RenderManifest`
lists one :class:`RenderedVideo` per produced Short, each describing the encoded
file (its storage key) and the *real* media metadata the renderer measured
(dimensions, duration, codecs, bitrate). The Optimization Engine treats every
field as authoritative input it did not itself compute.

Honesty note: when no manifest exists for a project (the Rendering Engine has not
run, or produced nothing), the Optimization Engine reports ``UNAVAILABLE`` with a
precise reason rather than inventing media to optimize. Nothing here renders or
decodes video; it is a description of what a renderer already produced.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class RenderStatus(StrEnum):
    """Overall status of a project's render output."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class RenderedVideo:
    """One finished, encoded Short produced by the Rendering Engine.

    All media fields are values the renderer *measured* from the encoded file
    (e.g. via ffprobe); the Optimization Engine consumes them as ground truth and
    never re-derives them. ``storage_key`` points at the real MP4 bytes in
    storage. ``clip_id``/``plan_id`` tie the render back to the editing timeline
    and clip plan it was rendered from, so optimization can align its work with
    the decisions the upstream engines made.
    """

    clip_id: str
    storage_key: str
    plan_id: str | None = None
    rank: int | None = None
    container: str = "mp4"
    width: int | None = None
    height: int | None = None
    duration: float | None = None
    fps: float | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    has_audio: bool | None = None
    bitrate_kbps: int | None = None
    audio_sample_rate: int | None = None
    size_bytes: int | None = None
    checksum: str | None = None
    subtitles_included: bool | None = None
    music_included: bool | None = None
    timeline_version: str | None = None
    rendered_at: str | None = None
    source_video: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def aspect_ratio(self) -> str | None:
        """Best-effort aspect label from the measured dimensions, else ``None``."""

        if not (self.width and self.height):
            return None
        from math import gcd

        divisor = gcd(self.width, self.height) or 1
        return f"{self.width // divisor}:{self.height // divisor}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "clip_id": self.clip_id,
            "storage_key": self.storage_key,
            "plan_id": self.plan_id,
            "rank": self.rank,
            "container": self.container,
            "width": self.width,
            "height": self.height,
            "duration": self.duration,
            "fps": self.fps,
            "video_codec": self.video_codec,
            "audio_codec": self.audio_codec,
            "has_audio": self.has_audio,
            "bitrate_kbps": self.bitrate_kbps,
            "audio_sample_rate": self.audio_sample_rate,
            "size_bytes": self.size_bytes,
            "checksum": self.checksum,
            "subtitles_included": self.subtitles_included,
            "music_included": self.music_included,
            "timeline_version": self.timeline_version,
            "rendered_at": self.rendered_at,
            "source_video": self.source_video,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> RenderedVideo:
        return cls(
            clip_id=str(raw["clip_id"]),
            storage_key=str(raw["storage_key"]),
            plan_id=raw.get("plan_id"),
            rank=raw.get("rank"),
            container=str(raw.get("container", "mp4")),
            width=raw.get("width"),
            height=raw.get("height"),
            duration=raw.get("duration"),
            fps=raw.get("fps"),
            video_codec=raw.get("video_codec"),
            audio_codec=raw.get("audio_codec"),
            has_audio=raw.get("has_audio"),
            bitrate_kbps=raw.get("bitrate_kbps"),
            audio_sample_rate=raw.get("audio_sample_rate"),
            size_bytes=raw.get("size_bytes"),
            checksum=raw.get("checksum"),
            subtitles_included=raw.get("subtitles_included"),
            music_included=raw.get("music_included"),
            timeline_version=raw.get("timeline_version"),
            rendered_at=raw.get("rendered_at"),
            source_video=raw.get("source_video", {}) or {},
            metadata=raw.get("metadata", {}) or {},
        )


@dataclass(slots=True)
class RenderManifest:
    """A project's complete set of rendered Shorts (the Rendering Engine output)."""

    project_id: str
    status: RenderStatus
    created_at: datetime
    updated_at: datetime
    renderer: str = "unknown"
    render_id: str | None = None
    rendering_version: str | None = None
    timeline_version: str | None = None
    renders: list[RenderedVideo] = field(default_factory=list)

    def render(self, clip_id: str) -> RenderedVideo | None:
        return next((r for r in self.renders if r.clip_id == clip_id), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "status": self.status.value,
            "renderer": self.renderer,
            "render_id": self.render_id,
            "rendering_version": self.rendering_version,
            "timeline_version": self.timeline_version,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "renders": [r.to_dict() for r in self.renders],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> RenderManifest:
        return cls(
            project_id=str(raw["project_id"]),
            status=RenderStatus(raw.get("status", "completed")),
            renderer=str(raw.get("renderer", "unknown")),
            render_id=raw.get("render_id"),
            rendering_version=raw.get("rendering_version"),
            timeline_version=raw.get("timeline_version"),
            created_at=_parse_dt(raw.get("created_at")),
            updated_at=_parse_dt(raw.get("updated_at")),
            renders=[
                RenderedVideo.from_dict(r) for r in raw.get("renders", []) if isinstance(r, dict)
            ],
        )


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    from olympus.utils import utc_now

    return utc_now()
