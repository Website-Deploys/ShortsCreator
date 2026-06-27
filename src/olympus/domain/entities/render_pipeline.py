"""Render-pipeline entities - the evolving state of a project's render run.

Where :mod:`olympus.domain.entities.rendering` defines the *output* contract (the
render manifest the Optimization Engine consumes), this module defines the
*process* state of the Rendering Engine itself: the ordered execution stages and
their honest status, mirroring every other engine's pipeline-state entity.

The Rendering Engine performs execution only - it never makes creative
decisions (those already exist in the upstream engines). These types are
technology-free: a :class:`RenderRun` is the persisted, resumable result of a
project's render, composed of one :class:`RenderStageResult` per stage.

Honesty is built into the type system: a stage is ``UNAVAILABLE`` (with a precise
reason) when the renderer or a required dependency (e.g. FFmpeg) is absent, and
``FAILED`` only for genuine errors. The engine never fabricates a rendered file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class RenderStageStatus(StrEnum):
    """Status of a single render stage."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    UNAVAILABLE = "unavailable"  # honest: renderer/dependency (e.g. FFmpeg) absent
    FAILED = "failed"
    CANCELLED = "cancelled"


class RenderRunStatus(StrEnum):
    """Overall status of a project's render run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# The ordered rendering pipeline. The first stages load/validate inputs and build
# the render plan (deterministic, dependency-free); the middle stages execute the
# encode (require the renderer); the final stages verify, publish the manifest,
# clean up, and validate.
RENDER_STAGE_ORDER: tuple[str, ...] = (
    "load_timeline",
    "validate_timeline",
    "validate_source_assets",
    "prepare_working_directory",
    "build_video_timeline",
    "build_audio_timeline",
    "apply_jump_cuts",
    "apply_zooms",
    "apply_crops",
    "apply_transitions",
    "apply_captions",
    "apply_broll",
    "apply_music",
    "audio_mixing",
    "render_preview",
    "full_resolution_render",
    "render_verification",
    "generate_render_manifest",
    "cleanup_temporary_files",
    "final_validation",
)

RENDER_STAGE_LABELS: dict[str, str] = {
    "load_timeline": "Load Timeline",
    "validate_timeline": "Validate Timeline",
    "validate_source_assets": "Validate Source Assets",
    "prepare_working_directory": "Prepare Working Directory",
    "build_video_timeline": "Build Video Timeline",
    "build_audio_timeline": "Build Audio Timeline",
    "apply_jump_cuts": "Apply Jump Cuts",
    "apply_zooms": "Apply Zooms",
    "apply_crops": "Apply Crops",
    "apply_transitions": "Apply Transitions",
    "apply_captions": "Apply Captions",
    "apply_broll": "Apply B-roll",
    "apply_music": "Apply Music",
    "audio_mixing": "Audio Mixing",
    "render_preview": "Render Preview",
    "full_resolution_render": "Full Resolution Render",
    "render_verification": "Render Verification",
    "generate_render_manifest": "Generate Render Manifest",
    "cleanup_temporary_files": "Cleanup Temporary Files",
    "final_validation": "Final Validation",
}


@dataclass(slots=True)
class RenderStageResult:
    """The result of running one render stage.

    ``data`` holds the stage's structured output (the built render plan, the
    rendered clip outputs, verification report, etc.) plus a ``logs`` list of
    human-readable lines the engine surfaces in its render-logs view.
    """

    stage: str
    status: RenderStageStatus = RenderStageStatus.PENDING
    version: str = "0"
    progress: float = 0.0
    attempts: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
    reason: str | None = None  # explanation for UNAVAILABLE
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def is_terminal(self) -> bool:
        return self.status in (
            RenderStageStatus.COMPLETED,
            RenderStageStatus.UNAVAILABLE,
            RenderStageStatus.FAILED,
            RenderStageStatus.CANCELLED,
        )

    @property
    def logs(self) -> list[str]:
        raw = self.data.get("logs")
        return [str(line) for line in raw] if isinstance(raw, list) else []

    def summary(self) -> dict[str, Any]:
        """Index-friendly summary (excludes the potentially large ``data``)."""

        return {
            "stage": self.stage,
            "status": self.status.value,
            "version": self.version,
            "progress": self.progress,
            "attempts": self.attempts,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error": self.error,
            "reason": self.reason,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.summary(), "data": self.data}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> RenderStageResult:
        return cls(
            stage=raw["stage"],
            status=RenderStageStatus(raw.get("status", "pending")),
            version=str(raw.get("version", "0")),
            progress=float(raw.get("progress", 0.0)),
            attempts=int(raw.get("attempts", 0)),
            started_at=_parse_dt(raw.get("started_at")),
            completed_at=_parse_dt(raw.get("completed_at")),
            error=raw.get("error"),
            reason=raw.get("reason"),
            data=raw.get("data", {}) or {},
        )


@dataclass(slots=True)
class RenderRun:
    """A project's complete (and evolving) render-run state."""

    project_id: str
    pipeline_version: str
    status: RenderRunStatus
    created_at: datetime
    updated_at: datetime
    stages: list[RenderStageResult] = field(default_factory=list)

    def stage(self, name: str) -> RenderStageResult | None:
        return next((s for s in self.stages if s.stage == name), None)

    def index(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "pipeline_version": self.pipeline_version,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "stages": [s.summary() for s in self.stages],
        }


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
