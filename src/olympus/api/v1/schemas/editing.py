"""Schemas for the editing (Editing Engine) API.

These responses expose the *honest* state of a project's edit timelines: each
stage carries its status (including ``unavailable`` with a reason), and completed
stages carry their structured output. Timelines, events, and the validation
report are loosely-typed ``dict`` payloads (the timeline is rich and evolving),
so they pass through intact - every event already carries its own start/end,
reason, confidence, and evidence.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from olympus.domain.entities.editing import (
    EDITING_STAGE_LABELS,
    EditingAnalysis,
    EditingStageResult,
)


class EditingStageResponse(BaseModel):
    """One editing stage, with its honest status and (optional) data."""

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
    def from_result(cls, result: EditingStageResult, *, include_data: bool) -> EditingStageResponse:
        return cls(
            stage=result.stage,
            label=EDITING_STAGE_LABELS.get(result.stage, result.stage),
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


class EditingResponse(BaseModel):
    """A project's complete, evolving editing analysis."""

    project_id: str
    pipeline_version: str
    status: str
    created_at: str
    updated_at: str
    completed_stages: int
    total_stages: int
    stages: list[EditingStageResponse]

    @classmethod
    def from_entity(cls, editing: EditingAnalysis, *, include_data: bool = True) -> EditingResponse:
        completed = sum(1 for s in editing.stages if s.status.value == "completed")
        return cls(
            project_id=editing.project_id,
            pipeline_version=editing.pipeline_version,
            status=editing.status.value,
            created_at=editing.created_at.isoformat(),
            updated_at=editing.updated_at.isoformat(),
            completed_stages=completed,
            total_stages=len(editing.stages),
            stages=[
                EditingStageResponse.from_result(s, include_data=include_data)
                for s in editing.stages
            ],
        )


class TimelineListResponse(BaseModel):
    """All assembled edit timelines for a project (each with full tracks)."""

    project_id: str
    timeline_count: int
    timelines: list[dict[str, Any]]


class TimelineResponse(BaseModel):
    """A single clip's complete edit timeline."""

    project_id: str
    timeline: dict[str, Any]


class TimelineEventsResponse(BaseModel):
    """A single clip's events, flattened across tracks (track on each event)."""

    project_id: str
    clip_id: str
    event_count: int
    events: list[dict[str, Any]]


class ValidationReportResponse(BaseModel):
    """The timeline validation report for a project."""

    project_id: str
    report: dict[str, Any]
