"""Schemas for the optimization (Optimization Engine) API.

These responses expose the *honest* state of a project's post-render polish: each
stage carries its status (including ``unavailable`` with a reason), and completed
stages carry their structured output. Quality reports, variants, music
recommendations, and publish packages are loosely-typed ``dict`` payloads (rich
and evolving), so they pass through intact - every recommendation/score already
carries its own reason, confidence, and evidence, and every UNKNOWN is explicit.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from olympus.domain.entities.optimization import (
    OPTIMIZATION_STAGE_LABELS,
    OptimizationAnalysis,
    OptimizationStageResult,
)


class OptimizationStageResponse(BaseModel):
    """One optimization stage, with its honest status and (optional) data."""

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
        cls, result: OptimizationStageResult, *, include_data: bool
    ) -> OptimizationStageResponse:
        return cls(
            stage=result.stage,
            label=OPTIMIZATION_STAGE_LABELS.get(result.stage, result.stage),
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


class OptimizationResponse(BaseModel):
    """A project's complete, evolving optimization analysis."""

    project_id: str
    pipeline_version: str
    status: str
    created_at: str
    updated_at: str
    completed_stages: int
    total_stages: int
    stages: list[OptimizationStageResponse]

    @classmethod
    def from_entity(
        cls, optimization: OptimizationAnalysis, *, include_data: bool = True
    ) -> OptimizationResponse:
        completed = sum(1 for s in optimization.stages if s.status.value == "completed")
        return cls(
            project_id=optimization.project_id,
            pipeline_version=optimization.pipeline_version,
            status=optimization.status.value,
            created_at=optimization.created_at.isoformat(),
            updated_at=optimization.updated_at.isoformat(),
            completed_stages=completed,
            total_stages=len(optimization.stages),
            stages=[
                OptimizationStageResponse.from_result(s, include_data=include_data)
                for s in optimization.stages
            ],
        )


class QualityReportResponse(BaseModel):
    """The per-clip quality evaluation (graded dimensions + honest UNKNOWNs)."""

    project_id: str
    report: dict[str, Any]


class VariantListResponse(BaseModel):
    """The generated export variants per clip."""

    project_id: str
    variants: dict[str, Any]


class MusicRecommendationsResponse(BaseModel):
    """Copyright-free music recommendations per clip + provider availability."""

    project_id: str
    music: dict[str, Any]


class PackageListResponse(BaseModel):
    """All publish packages for a project (each with its downloadable assets)."""

    project_id: str
    package_count: int
    packages: list[dict[str, Any]]


class PackageResponse(BaseModel):
    """A single clip's publish package."""

    project_id: str
    package: dict[str, Any]
