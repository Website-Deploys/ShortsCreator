"""Optimization entities - the structured output of the Optimization Engine.

Where the Rendering Engine produces a finished MP4, the Optimization & AI
Enhancement Engine makes that finished Short as polished and engaging as possible
**without changing the story** the upstream engines decided: it analyses and
enhances audio, recommends copyright-free music, optimizes captions and
typography, refines visuals, generates thumbnail candidates, evaluates quality,
proposes export variants, and assembles a downloadable publish package per
platform.

These are technology-free data types, independent from every other engine's
entities (the Optimization Engine consumes their *output*, never their types). An
:class:`OptimizationAnalysis` is the evolving, persisted result for a project,
composed of one :class:`OptimizationStageResult` per pipeline stage.

Honesty is built into the type system exactly as in the other engines: a stage is
``UNAVAILABLE`` (with a detailed reason) when it lacks the rendered media or the
enhancement model it needs, and any single value that cannot be determined is
recorded as ``UNKNOWN`` (never guessed). ``FAILED`` is reserved for genuine
errors. No enhancement result is ever fabricated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class OptimizationStageStatus(StrEnum):
    """Status of a single optimization stage."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    UNAVAILABLE = "unavailable"  # honest: required render/model not available
    FAILED = "failed"
    CANCELLED = "cancelled"


class OptimizationStatus(StrEnum):
    """Overall status of a project's optimization analysis."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# The ordered optimization pipeline. Order matters: later stages build on earlier
# ones, and the final stages evaluate quality, generate variants, validate, and
# assemble the downloadable publish package.
OPTIMIZATION_STAGE_ORDER: tuple[str, ...] = (
    "load_render",
    "audio_analysis",
    "voice_enhancement",
    "noise_reduction",
    "loudness_normalization",
    "silence_refinement",
    "music_recommendation",
    "music_mixing",
    "caption_optimization",
    "typography_improvement",
    "visual_enhancement",
    "sharpening",
    "color_refinement",
    "frame_cleanup",
    "thumbnail_optimization",
    "title_suggestion",
    "description_suggestion",
    "hashtag_recommendation",
    "platform_optimization",
    "compression_optimization",
    "quality_evaluation",
    "variant_generation",
    "final_validation",
    "publish_package_creation",
)

# Human-friendly labels for the UI.
OPTIMIZATION_STAGE_LABELS: dict[str, str] = {
    "load_render": "Load Render",
    "audio_analysis": "Audio Analysis",
    "voice_enhancement": "Voice Enhancement",
    "noise_reduction": "Noise Reduction",
    "loudness_normalization": "Loudness Normalization",
    "silence_refinement": "Silence Refinement",
    "music_recommendation": "Music Recommendation",
    "music_mixing": "Music Mixing",
    "caption_optimization": "Caption Optimization",
    "typography_improvement": "Typography Improvement",
    "visual_enhancement": "Visual Enhancement",
    "sharpening": "Sharpening",
    "color_refinement": "Color Refinement",
    "frame_cleanup": "Frame Cleanup",
    "thumbnail_optimization": "Thumbnail Optimization",
    "title_suggestion": "Title Suggestion",
    "description_suggestion": "Description Suggestion",
    "hashtag_recommendation": "Hashtag Recommendation",
    "platform_optimization": "Platform Optimization",
    "compression_optimization": "Compression Optimization",
    "quality_evaluation": "Quality Evaluation",
    "variant_generation": "Variant Generation",
    "final_validation": "Final Validation",
    "publish_package_creation": "Publish Package Creation",
}


@dataclass(slots=True)
class OptimizationStageResult:
    """The result of running one optimization stage.

    ``data`` holds the stage's structured output, organized per rendered clip
    where applicable. By convention every recommendation or score carries a
    ``reason``, a ``confidence`` (``None`` = UNKNOWN), and the ``evidence`` it was
    derived from - no enhancement is ever claimed without the real signal (or the
    real model) behind it.
    """

    stage: str
    status: OptimizationStageStatus = OptimizationStageStatus.PENDING
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
            OptimizationStageStatus.COMPLETED,
            OptimizationStageStatus.UNAVAILABLE,
            OptimizationStageStatus.FAILED,
            OptimizationStageStatus.CANCELLED,
        )

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
    def from_dict(cls, raw: dict[str, Any]) -> OptimizationStageResult:
        return cls(
            stage=raw["stage"],
            status=OptimizationStageStatus(raw.get("status", "pending")),
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
class OptimizationAnalysis:
    """A project's complete (and evolving) optimization result."""

    project_id: str
    pipeline_version: str
    status: OptimizationStatus
    created_at: datetime
    updated_at: datetime
    stages: list[OptimizationStageResult] = field(default_factory=list)

    def stage(self, name: str) -> OptimizationStageResult | None:
        return next((s for s in self.stages if s.stage == name), None)

    def index(self) -> dict[str, Any]:
        """The lightweight index document (summaries only, no stage data)."""

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
