"""Schemas for the analysis (Cognitive Engine) API.

These responses expose the *honest* state of a project's video understanding:
each stage carries its status (including ``unavailable`` with a human-readable
reason) so the UI can show real progress and never fabricate results.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from olympus.domain.entities.analysis import (
    STAGE_LABELS,
    Analysis,
    StageResult,
)


class StageResponse(BaseModel):
    """One analysis stage, with its honest status and (optional) data."""

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
    def from_result(cls, result: StageResult, *, include_data: bool) -> StageResponse:
        return cls(
            stage=result.stage,
            label=STAGE_LABELS.get(result.stage, result.stage),
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


class AnalysisResponse(BaseModel):
    """A project's complete, evolving video understanding."""

    project_id: str
    pipeline_version: str
    status: str
    created_at: str
    updated_at: str
    completed_stages: int
    total_stages: int
    stages: list[StageResponse]
    signal_health: dict[str, Any] | None = None
    analysis_signals_v2: dict[str, Any] | None = None

    @classmethod
    def from_entity(cls, analysis: Analysis, *, include_data: bool = True) -> AnalysisResponse:
        completed = sum(1 for s in analysis.stages if s.status.value == "completed")
        signals = analysis.signals_v2()
        signal_health = signals.get("signal_health") if signals else None
        return cls(
            project_id=analysis.project_id,
            pipeline_version=analysis.pipeline_version,
            status=analysis.status.value,
            created_at=analysis.created_at.isoformat(),
            updated_at=analysis.updated_at.isoformat(),
            completed_stages=completed,
            total_stages=len(analysis.stages),
            stages=[
                StageResponse.from_result(s, include_data=include_data)
                for s in analysis.stages
            ],
            signal_health=signal_health if isinstance(signal_health, dict) else None,
            analysis_signals_v2=signals,
        )
