"""Virality (Virality Engine) endpoints.

Expose the viral-potential assessment pipeline: fetch the current assessment,
start or resume it, re-run a single stage, cancel an in-flight run, and fetch the
aggregated summary. No endpoint fabricates results - stages report
``unavailable`` honestly when they lack the evidence they need, and every score
carries confidence, evidence, and limitations.
"""

from __future__ import annotations

from fastapi import APIRouter, status

from olympus.api.dependencies import ProjectServiceDep, ViralityServiceDep
from olympus.api.v1.schemas.virality import ViralityResponse, ViralitySummaryResponse
from olympus.platform.errors import NotFoundError

router = APIRouter(prefix="/projects/{project_id}/virality", tags=["virality"])


@router.get("", response_model=ViralityResponse)
async def get_virality(
    project_id: str, projects: ProjectServiceDep, virality: ViralityServiceDep
) -> ViralityResponse:
    """Return the project's current virality assessment (404 if none yet)."""

    await projects.get(project_id)  # 404s if the project doesn't exist
    result = await virality.get_virality(project_id)
    if result is None:
        raise NotFoundError(
            "No virality analysis exists for this project yet.", details={"id": project_id}
        )
    return ViralityResponse.from_entity(result)


@router.post("/run", response_model=ViralityResponse, status_code=status.HTTP_202_ACCEPTED)
async def run_virality(
    project_id: str, projects: ProjectServiceDep, virality: ViralityServiceDep
) -> ViralityResponse:
    """Start (or resume) the virality pipeline in the background."""

    project = await projects.get(project_id)
    result = await virality.start(project, restart=True)
    return ViralityResponse.from_entity(result, include_data=False)


@router.post("/stages/{stage}/rerun", response_model=ViralityResponse)
async def rerun_virality_stage(
    project_id: str, stage: str, projects: ProjectServiceDep, virality: ViralityServiceDep
) -> ViralityResponse:
    """Re-run a single virality stage, leaving the others untouched."""

    project = await projects.get(project_id)
    result = await virality.rerun_stage(project, stage)
    return ViralityResponse.from_entity(result)


@router.post("/cancel", status_code=status.HTTP_202_ACCEPTED)
async def cancel_virality(project_id: str, virality: ViralityServiceDep) -> dict[str, bool]:
    """Request cancellation of an in-flight virality run."""

    cancelled = await virality.cancel(project_id)
    return {"cancelled": cancelled}


@router.get("/summary", response_model=ViralitySummaryResponse)
async def get_virality_summary(
    project_id: str, projects: ProjectServiceDep, virality: ViralityServiceDep
) -> ViralitySummaryResponse:
    """Return the aggregated virality summary (404 if not produced yet)."""

    await projects.get(project_id)
    summary = await virality.get_summary(project_id)
    if summary is None:
        raise NotFoundError(
            "No virality summary is available for this project yet.",
            details={"id": project_id},
        )
    return ViralitySummaryResponse(project_id=project_id, summary=summary)
