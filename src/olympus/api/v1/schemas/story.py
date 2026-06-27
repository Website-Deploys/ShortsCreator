"""Schemas for the story (Story Engine) API.

These responses expose the *honest* state of a project's narrative understanding:
each stage carries its status (including ``unavailable`` with a reason), and
completed stages carry their structured conclusions - every one of which
includes a confidence score and supporting evidence.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from olympus.domain.entities.story import (
    STORY_STAGE_LABELS,
    StoryAnalysis,
    StoryStageResult,
)


class StoryStageResponse(BaseModel):
    """One story stage, with its honest status and (optional) data."""

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
    def from_result(cls, result: StoryStageResult, *, include_data: bool) -> StoryStageResponse:
        return cls(
            stage=result.stage,
            label=STORY_STAGE_LABELS.get(result.stage, result.stage),
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


class StoryResponse(BaseModel):
    """A project's complete, evolving narrative understanding."""

    project_id: str
    pipeline_version: str
    status: str
    created_at: str
    updated_at: str
    completed_stages: int
    total_stages: int
    stages: list[StoryStageResponse]

    @classmethod
    def from_entity(cls, story: StoryAnalysis, *, include_data: bool = True) -> StoryResponse:
        completed = sum(1 for s in story.stages if s.status.value == "completed")
        return cls(
            project_id=story.project_id,
            pipeline_version=story.pipeline_version,
            status=story.status.value,
            created_at=story.created_at.isoformat(),
            updated_at=story.updated_at.isoformat(),
            completed_stages=completed,
            total_stages=len(story.stages),
            stages=[
                StoryStageResponse.from_result(s, include_data=include_data)
                for s in story.stages
            ],
        )


class StorySummaryResponse(BaseModel):
    """The engineering story summary (the Story Summary stage's output)."""

    project_id: str
    summary: dict[str, Any]
