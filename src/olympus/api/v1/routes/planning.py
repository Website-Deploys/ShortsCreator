"""Clip Planner endpoints.

Expose the editing-blueprint pipeline: fetch the current plan set, start or
resume it, re-run a single stage, cancel an in-flight run, fetch the aggregated
summary, list the ranked plans, and fetch a single plan. No endpoint fabricates
results - stages report ``unavailable`` honestly, the planner returns zero clips
with an explanation when appropriate, and every plan carries confidence and
evidence. Nothing here edits or renders video.
"""

from __future__ import annotations

from fastapi import APIRouter, status

from olympus.api.dependencies import ClipPlannerServiceDep, ProjectServiceDep
from olympus.api.v1.schemas.planning import (
    PlanListResponse,
    PlanningResponse,
    PlanningSummaryResponse,
    PlanResponse,
)
from olympus.platform.errors import NotFoundError

router = APIRouter(prefix="/projects/{project_id}/planning", tags=["planning"])


@router.get("", response_model=PlanningResponse)
async def get_planning(
    project_id: str, projects: ProjectServiceDep, planning: ClipPlannerServiceDep
) -> PlanningResponse:
    """Return the project's current clip-planning analysis (404 if none yet)."""

    await projects.get(project_id)  # 404s if the project doesn't exist
    result = await planning.get_planning(project_id)
    if result is None:
        raise NotFoundError(
            "No clip planning exists for this project yet.", details={"id": project_id}
        )
    return PlanningResponse.from_entity(result)


@router.post("/run", response_model=PlanningResponse, status_code=status.HTTP_202_ACCEPTED)
async def run_planning(
    project_id: str, projects: ProjectServiceDep, planning: ClipPlannerServiceDep
) -> PlanningResponse:
    """Start (or resume) the clip-planning pipeline in the background."""

    project = await projects.get(project_id)
    result = await planning.start(project, restart=True)
    return PlanningResponse.from_entity(result, include_data=False)


@router.post("/stages/{stage}/rerun", response_model=PlanningResponse)
async def rerun_planning_stage(
    project_id: str, stage: str, projects: ProjectServiceDep, planning: ClipPlannerServiceDep
) -> PlanningResponse:
    """Re-run a single planning stage, leaving the others untouched."""

    project = await projects.get(project_id)
    result = await planning.rerun_stage(project, stage)
    return PlanningResponse.from_entity(result)


@router.post("/cancel", status_code=status.HTTP_202_ACCEPTED)
async def cancel_planning(project_id: str, planning: ClipPlannerServiceDep) -> dict[str, bool]:
    """Request cancellation of an in-flight planning run."""

    cancelled = await planning.cancel(project_id)
    return {"cancelled": cancelled}


@router.get("/summary", response_model=PlanningSummaryResponse)
async def get_planning_summary(
    project_id: str, projects: ProjectServiceDep, planning: ClipPlannerServiceDep
) -> PlanningSummaryResponse:
    """Return the aggregated planning summary (404 if not produced yet)."""

    await projects.get(project_id)
    summary = await planning.get_summary(project_id)
    if summary is None:
        raise NotFoundError(
            "No planning summary is available for this project yet.",
            details={"id": project_id},
        )
    return PlanningSummaryResponse(project_id=project_id, summary=summary)


@router.get("/plans", response_model=PlanListResponse)
async def list_plans(
    project_id: str, projects: ProjectServiceDep, planning: ClipPlannerServiceDep
) -> PlanListResponse:
    """List the full ranked plans (each with its blueprint). 404 if not ranked yet."""

    await projects.get(project_id)
    plans = await planning.list_plans(project_id)
    if plans is None:
        raise NotFoundError(
            "No ranked plans are available for this project yet.",
            details={"id": project_id},
        )
    return PlanListResponse(project_id=project_id, plan_count=len(plans), plans=plans)


@router.get("/plans/{plan_id}", response_model=PlanResponse)
async def get_plan(
    project_id: str, plan_id: str, projects: ProjectServiceDep, planning: ClipPlannerServiceDep
) -> PlanResponse:
    """Return a single full editing plan by id (404 if not found)."""

    await projects.get(project_id)
    plan = await planning.get_plan(project_id, plan_id)
    if plan is None:
        raise NotFoundError(
            "No such plan for this project.", details={"id": project_id, "plan_id": plan_id}
        )
    return PlanResponse(project_id=project_id, plan=plan)
