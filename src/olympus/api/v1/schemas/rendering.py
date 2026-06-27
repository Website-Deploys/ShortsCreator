"""Schemas for the rendering (Rendering Engine) API.

These responses expose the *honest* state of a project's render: each stage
carries its status (including ``unavailable`` with a reason - e.g. FFmpeg
missing), and completed stages carry their structured output (the built render
plan, rendered clip outputs, verification report). The render manifest, logs, and
validation report are returned as-is. No endpoint fabricates a rendered file.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from olympus.domain.entities.render_pipeline import (
    RENDER_STAGE_LABELS,
    RenderRun,
    RenderStageResult,
)
from olympus.domain.entities.rendering import RenderManifest


class RenderStageResponse(BaseModel):
    """One render stage, with its honest status and (optional) data."""

    stage: str
    label: str
    status: str
    version: str
    progress: float
    attempts: int
    started_at: str | None
    completed_at: str | None
    error: str | None
    reason: str | None
    data: dict[str, Any] | None

    @classmethod
    def from_result(cls, result: RenderStageResult, *, include_data: bool) -> RenderStageResponse:
        return cls(
            stage=result.stage,
            label=RENDER_STAGE_LABELS.get(result.stage, result.stage),
            status=result.status.value,
            version=result.version,
            progress=result.progress,
            attempts=result.attempts,
            started_at=result.started_at.isoformat() if result.started_at else None,
            completed_at=result.completed_at.isoformat() if result.completed_at else None,
            error=result.error,
            reason=result.reason,
            data=result.data if include_data else None,
        )


class RenderRunResponse(BaseModel):
    """A project's complete, evolving render run."""

    project_id: str
    pipeline_version: str
    status: str
    created_at: str
    updated_at: str
    completed_stages: int
    total_stages: int
    stages: list[RenderStageResponse]

    @classmethod
    def from_entity(cls, run: RenderRun, *, include_data: bool = True) -> RenderRunResponse:
        completed = sum(1 for s in run.stages if s.status.value == "completed")
        return cls(
            project_id=run.project_id,
            pipeline_version=run.pipeline_version,
            status=run.status.value,
            created_at=run.created_at.isoformat(),
            updated_at=run.updated_at.isoformat(),
            completed_stages=completed,
            total_stages=len(run.stages),
            stages=[
                RenderStageResponse.from_result(s, include_data=include_data) for s in run.stages
            ],
        )


class RenderManifestResponse(BaseModel):
    """The published render manifest (the contract the Optimizer consumes)."""

    project_id: str
    manifest: dict[str, Any]

    @classmethod
    def from_entity(cls, manifest: RenderManifest) -> RenderManifestResponse:
        return cls(project_id=manifest.project_id, manifest=manifest.to_dict())


class RenderValidationResponse(BaseModel):
    """The final render validation report."""

    project_id: str
    report: dict[str, Any]


class RenderLogsResponse(BaseModel):
    """Per-stage render logs, in pipeline order."""

    project_id: str
    stages: list[dict[str, Any]]
