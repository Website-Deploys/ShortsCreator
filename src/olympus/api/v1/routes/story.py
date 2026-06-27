"""Story (Story Engine) endpoints.

Expose the narrative understanding pipeline: fetch the current understanding,
start or resume it, re-run a single stage, cancel an in-flight run, and fetch the
engineering summary. No endpoint fabricates results - stages report
``unavailable`` honestly when they lack the inputs they need (most need a
transcript), and every completed conclusion carries confidence and evidence.
"""

from __future__ import annotations

from fastapi import APIRouter, status

from olympus.api.dependencies import ProjectServiceDep, StoryServiceDep
from olympus.api.v1.schemas.story import StoryResponse, StorySummaryResponse
from olympus.platform.errors import NotFoundError

router = APIRouter(prefix="/projects/{project_id}/story", tags=["story"])


@router.get("", response_model=StoryResponse)
async def get_story(
    project_id: str, projects: ProjectServiceDep, story: StoryServiceDep
) -> StoryResponse:
    """Return the project's current narrative understanding (404 if none yet)."""

    await projects.get(project_id)  # 404s if the project doesn't exist
    result = await story.get_story(project_id)
    if result is None:
        raise NotFoundError(
            "No story analysis exists for this project yet.", details={"id": project_id}
        )
    return StoryResponse.from_entity(result)


@router.post("/run", response_model=StoryResponse, status_code=status.HTTP_202_ACCEPTED)
async def run_story(
    project_id: str, projects: ProjectServiceDep, story: StoryServiceDep
) -> StoryResponse:
    """Start (or resume) the story pipeline in the background."""

    project = await projects.get(project_id)
    result = await story.start(project, restart=True)
    return StoryResponse.from_entity(result, include_data=False)


@router.post("/stages/{stage}/rerun", response_model=StoryResponse)
async def rerun_story_stage(
    project_id: str, stage: str, projects: ProjectServiceDep, story: StoryServiceDep
) -> StoryResponse:
    """Re-run a single story stage, leaving the others untouched."""

    project = await projects.get(project_id)
    result = await story.rerun_stage(project, stage)
    return StoryResponse.from_entity(result)


@router.post("/cancel", status_code=status.HTTP_202_ACCEPTED)
async def cancel_story(project_id: str, story: StoryServiceDep) -> dict[str, bool]:
    """Request cancellation of an in-flight story run."""

    cancelled = await story.cancel(project_id)
    return {"cancelled": cancelled}


@router.get("/summary", response_model=StorySummaryResponse)
async def get_story_summary(
    project_id: str, projects: ProjectServiceDep, story: StoryServiceDep
) -> StorySummaryResponse:
    """Return the engineering story summary (404 if not produced yet)."""

    await projects.get(project_id)
    summary = await story.get_summary(project_id)
    if summary is None:
        raise NotFoundError(
            "No story summary is available for this project yet.",
            details={"id": project_id},
        )
    return StorySummaryResponse(project_id=project_id, summary=summary)
