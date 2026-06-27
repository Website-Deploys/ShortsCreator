"""Schemas for the virality (Virality Engine) API.

These responses expose the *honest* state of a project's virality assessment:
each stage carries its status (including ``unavailable`` with a reason), and
completed stages carry their structured conclusions - every score with its
confidence, supporting evidence, and limitations.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from olympus.domain.entities.virality import (
    VIRALITY_STAGE_LABELS,
    ViralityAnalysis,
    ViralityStageResult,
)


class ViralityStageResponse(BaseModel):
    """One virality stage, with its honest status and (optional) data."""

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
    def from_result(
        cls, result: ViralityStageResult, *, include_data: bool
    ) -> ViralityStageResponse:
        return cls(
            stage=result.stage,
            label=VIRALITY_STAGE_LABELS.get(result.stage, result.stage),
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


class ViralityResponse(BaseModel):
    """A project's complete, evolving virality assessment."""

    project_id: str
    pipeline_version: str
    status: str
    created_at: str
    updated_at: str
    completed_stages: int
    total_stages: int
    stages: list[ViralityStageResponse]

    @classmethod
    def from_entity(
        cls, virality: ViralityAnalysis, *, include_data: bool = True
    ) -> ViralityResponse:
        completed = sum(1 for s in virality.stages if s.status.value == "completed")
        return cls(
            project_id=virality.project_id,
            pipeline_version=virality.pipeline_version,
            status=virality.status.value,
            created_at=virality.created_at.isoformat(),
            updated_at=virality.updated_at.isoformat(),
            completed_stages=completed,
            total_stages=len(virality.stages),
            stages=[
                ViralityStageResponse.from_result(s, include_data=include_data)
                for s in virality.stages
            ],
        )


class ViralitySummaryResponse(BaseModel):
    """The aggregated virality summary (the Virality Summary stage's output)."""

    project_id: str
    summary: dict[str, Any]
