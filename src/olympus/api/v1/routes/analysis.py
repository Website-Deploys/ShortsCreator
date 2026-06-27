"""Analysis (Cognitive Engine) endpoints.

Expose the video understanding pipeline: fetch the current understanding, start
or resume it, re-run a single stage, and cancel an in-flight run. No endpoint
fabricates results - stages report ``unavailable`` honestly when their tooling or
model is not configured in this environment.
"""

from __future__ import annotations

from fastapi import APIRouter, status

from olympus.api.dependencies import AnalysisServiceDep, ProjectServiceDep
from olympus.api.v1.schemas.analysis import AnalysisResponse
from olympus.platform.errors import NotFoundError

router = APIRouter(prefix="/projects/{project_id}/analysis", tags=["analysis"])


@router.get("", response_model=AnalysisResponse)
async def get_analysis(
    project_id: str, projects: ProjectServiceDep, analysis: AnalysisServiceDep
) -> AnalysisResponse:
    """Return the project's current video understanding (404 if none yet)."""

    await projects.get(project_id)  # 404s if the project doesn't exist
    result = await analysis.get_analysis(project_id)
    if result is None:
        raise NotFoundError(
            "No analysis exists for this project yet.", details={"id": project_id}
        )
    return AnalysisResponse.from_entity(result)


@router.post("/run", response_model=AnalysisResponse, status_code=status.HTTP_202_ACCEPTED)
async def run_analysis(
    project_id: str, projects: ProjectServiceDep, analysis: AnalysisServiceDep
) -> AnalysisResponse:
    """Start (or resume) the analysis pipeline in the background."""

    project = await projects.get(project_id)
    result = await analysis.start(project, restart=True)
    return AnalysisResponse.from_entity(result, include_data=False)


@router.post("/stages/{stage}/rerun", response_model=AnalysisResponse)
async def rerun_stage(
    project_id: str, stage: str, projects: ProjectServiceDep, analysis: AnalysisServiceDep
) -> AnalysisResponse:
    """Re-run a single analysis stage, leaving the others untouched."""

    project = await projects.get(project_id)
    result = await analysis.rerun_stage(project, stage)
    return AnalysisResponse.from_entity(result)


@router.post("/cancel", status_code=status.HTTP_202_ACCEPTED)
async def cancel_analysis(
    project_id: str, analysis: AnalysisServiceDep
) -> dict[str, bool]:
    """Request cancellation of an in-flight analysis run."""

    cancelled = await analysis.cancel(project_id)
    return {"cancelled": cancelled}
