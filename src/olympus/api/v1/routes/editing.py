"""Editing Engine endpoints.

Expose the edit-timeline pipeline: fetch the current editing analysis, start or
resume it, re-run a single stage, cancel an in-flight run, list the assembled
timelines, fetch a single clip's timeline or its flattened events, and fetch the
validation report. No endpoint fabricates edits - stages report ``unavailable``
honestly, undeterminable decisions are ``unknown``, and every event carries a
timestamp, reason, confidence, and evidence. Nothing here renders or exports.
"""

from __future__ import annotations

from fastapi import APIRouter, status

from olympus.api.dependencies import EditingServiceDep, ProjectServiceDep
from olympus.api.v1.schemas.editing import (
    EditingResponse,
    TimelineEventsResponse,
    TimelineListResponse,
    TimelineResponse,
    ValidationReportResponse,
)
from olympus.platform.errors import NotFoundError

router = APIRouter(prefix="/projects/{project_id}/editing", tags=["editing"])


@router.get("", response_model=EditingResponse)
async def get_editing(
    project_id: str, projects: ProjectServiceDep, editing: EditingServiceDep
) -> EditingResponse:
    """Return the project's current editing analysis (404 if none yet)."""

    await projects.get(project_id)  # 404s if the project doesn't exist
    result = await editing.get_editing(project_id)
    if result is None:
        raise NotFoundError(
            "No editing analysis exists for this project yet.", details={"id": project_id}
        )
    return EditingResponse.from_entity(result)


@router.post("/run", response_model=EditingResponse, status_code=status.HTTP_202_ACCEPTED)
async def run_editing(
    project_id: str, projects: ProjectServiceDep, editing: EditingServiceDep
) -> EditingResponse:
    """Start (or resume) the editing pipeline in the background."""

    project = await projects.get(project_id)
    result = await editing.start(project, restart=True)
    return EditingResponse.from_entity(result, include_data=False)


@router.post("/stages/{stage}/rerun", response_model=EditingResponse)
async def rerun_editing_stage(
    project_id: str, stage: str, projects: ProjectServiceDep, editing: EditingServiceDep
) -> EditingResponse:
    """Re-run a single editing stage, leaving the others untouched."""

    project = await projects.get(project_id)
    result = await editing.rerun_stage(project, stage)
    return EditingResponse.from_entity(result)


@router.post("/cancel", status_code=status.HTTP_202_ACCEPTED)
async def cancel_editing(project_id: str, editing: EditingServiceDep) -> dict[str, bool]:
    """Request cancellation of an in-flight editing run."""

    cancelled = await editing.cancel(project_id)
    return {"cancelled": cancelled}


@router.get("/timelines", response_model=TimelineListResponse)
async def list_timelines(
    project_id: str, projects: ProjectServiceDep, editing: EditingServiceDep
) -> TimelineListResponse:
    """List the assembled edit timelines (404 if not assembled yet)."""

    await projects.get(project_id)
    timelines = await editing.list_timelines(project_id)
    if timelines is None:
        raise NotFoundError(
            "No timelines are available for this project yet.", details={"id": project_id}
        )
    return TimelineListResponse(
        project_id=project_id, timeline_count=len(timelines), timelines=timelines
    )


@router.get("/timelines/{clip_id}", response_model=TimelineResponse)
async def get_timeline(
    project_id: str, clip_id: str, projects: ProjectServiceDep, editing: EditingServiceDep
) -> TimelineResponse:
    """Return a single clip's complete edit timeline (404 if not found)."""

    await projects.get(project_id)
    timeline = await editing.get_timeline(project_id, clip_id)
    if timeline is None:
        raise NotFoundError(
            "No such timeline for this project.",
            details={"id": project_id, "clip_id": clip_id},
        )
    return TimelineResponse(project_id=project_id, timeline=timeline)


@router.get("/timelines/{clip_id}/events", response_model=TimelineEventsResponse)
async def get_timeline_events(
    project_id: str, clip_id: str, projects: ProjectServiceDep, editing: EditingServiceDep
) -> TimelineEventsResponse:
    """Return a single clip's events flattened across all tracks (404 if absent)."""

    await projects.get(project_id)
    events = await editing.timeline_events(project_id, clip_id)
    if events is None:
        raise NotFoundError(
            "No such timeline for this project.",
            details={"id": project_id, "clip_id": clip_id},
        )
    return TimelineEventsResponse(
        project_id=project_id, clip_id=clip_id, event_count=len(events), events=events
    )


@router.get("/validation", response_model=ValidationReportResponse)
async def get_validation_report(
    project_id: str, projects: ProjectServiceDep, editing: EditingServiceDep
) -> ValidationReportResponse:
    """Return the timeline validation report (404 if not produced yet)."""

    await projects.get(project_id)
    report = await editing.validation_report(project_id)
    if report is None:
        raise NotFoundError(
            "No validation report is available for this project yet.",
            details={"id": project_id},
        )
    return ValidationReportResponse(project_id=project_id, report=report)
