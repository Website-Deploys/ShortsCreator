"""Schemas for the clip-planning (Clip Planner) API.

These responses expose the *honest* state of a project's editing plans: each
stage carries its status (including ``unavailable`` with a reason), and completed
stages carry their structured output. Plans and the summary are loosely-typed
``dict`` payloads (the blueprint is rich and evolving), so they pass through
intact - every plan/decision already carries its own confidence and evidence.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from olympus.domain.entities.planning import (
    PLANNING_STAGE_LABELS,
    ClipPlanningAnalysis,
    PlanningStageResult,
)


class PlanningStageResponse(BaseModel):
    """One planning stage, with its honest status and (optional) data."""

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
        cls, result: PlanningStageResult, *, include_data: bool
    ) -> PlanningStageResponse:
        return cls(
            stage=result.stage,
            label=PLANNING_STAGE_LABELS.get(result.stage, result.stage),
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


class PlanningResponse(BaseModel):
    """A project's complete, evolving clip-planning analysis."""

    project_id: str
    pipeline_version: str
    status: str
    created_at: str
    updated_at: str
    completed_stages: int
    total_stages: int
    stages: list[PlanningStageResponse]

    @classmethod
    def from_entity(
        cls, planning: ClipPlanningAnalysis, *, include_data: bool = True
    ) -> PlanningResponse:
        completed = sum(1 for s in planning.stages if s.status.value == "completed")
        return cls(
            project_id=planning.project_id,
            pipeline_version=planning.pipeline_version,
            status=planning.status.value,
            created_at=planning.created_at.isoformat(),
            updated_at=planning.updated_at.isoformat(),
            completed_stages=completed,
            total_stages=len(planning.stages),
            stages=[
                PlanningStageResponse.from_result(s, include_data=include_data)
                for s in planning.stages
            ],
        )


class PlanningSummaryResponse(BaseModel):
    """The aggregated planning summary (the Planning Summary stage's output)."""

    project_id: str
    summary: dict[str, Any]


class PlanListResponse(BaseModel):
    """The full ranked plans (each with its complete editing blueprint)."""

    project_id: str
    plan_count: int
    plans: list[dict[str, Any]]


class PlanResponse(BaseModel):
    """A single full editing plan (with its blueprint)."""

    project_id: str
    plan: dict[str, Any]
