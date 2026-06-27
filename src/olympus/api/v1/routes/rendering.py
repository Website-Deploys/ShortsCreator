"""Rendering Engine endpoints.

Expose the render execution pipeline: fetch the current render run, start or
resume it, re-run a single stage, cancel an in-flight run, fetch the published
render manifest (and download it), the validation report, the render logs, and
download a rendered clip. No endpoint fabricates a render - when FFmpeg (or
another backend) is unavailable the execution stages report ``unavailable``
honestly, and a clip/manifest that does not exist returns an honest 404 with the
reason rather than a broken file. Nothing here makes creative decisions.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Response, status
from fastapi.responses import FileResponse, RedirectResponse

from olympus.api.dependencies import ProjectServiceDep, RenderingServiceDep, StorageDep
from olympus.api.v1.schemas.rendering import (
    RenderLogsResponse,
    RenderManifestResponse,
    RenderRunResponse,
    RenderValidationResponse,
)
from olympus.platform.errors import NotFoundError

router = APIRouter(prefix="/projects/{project_id}/rendering", tags=["rendering"])


@router.get("", response_model=RenderRunResponse)
async def get_render(
    project_id: str, projects: ProjectServiceDep, rendering: RenderingServiceDep
) -> RenderRunResponse:
    """Return the project's current render run (404 if none yet)."""

    await projects.get(project_id)
    run = await rendering.get_run(project_id)
    if run is None:
        raise NotFoundError(
            "No render run exists for this project yet.", details={"id": project_id}
        )
    return RenderRunResponse.from_entity(run)


@router.post("/run", response_model=RenderRunResponse, status_code=status.HTTP_202_ACCEPTED)
async def run_render(
    project_id: str, projects: ProjectServiceDep, rendering: RenderingServiceDep
) -> RenderRunResponse:
    """Start (or resume) the render pipeline in the background."""

    project = await projects.get(project_id)
    run = await rendering.start(project, restart=True)
    return RenderRunResponse.from_entity(run, include_data=False)


@router.post("/stages/{stage}/rerun", response_model=RenderRunResponse)
async def rerun_render_stage(
    project_id: str, stage: str, projects: ProjectServiceDep, rendering: RenderingServiceDep
) -> RenderRunResponse:
    """Re-run a single render stage, leaving the others untouched."""

    project = await projects.get(project_id)
    run = await rendering.rerun_stage(project, stage)
    return RenderRunResponse.from_entity(run)


@router.post("/cancel", status_code=status.HTTP_202_ACCEPTED)
async def cancel_render(project_id: str, rendering: RenderingServiceDep) -> dict[str, bool]:
    """Request cancellation of an in-flight render run."""

    cancelled = await rendering.cancel(project_id)
    return {"cancelled": cancelled}


@router.get("/manifest", response_model=RenderManifestResponse)
async def get_manifest(
    project_id: str, projects: ProjectServiceDep, rendering: RenderingServiceDep
) -> RenderManifestResponse:
    """Return the published render manifest (404 if not produced yet)."""

    await projects.get(project_id)
    manifest = await rendering.manifest(project_id)
    if manifest is None:
        raise NotFoundError(
            "No render manifest has been produced for this project yet.",
            details={"id": project_id},
        )
    return RenderManifestResponse.from_entity(manifest)


@router.get("/manifest/download")
async def download_manifest(
    project_id: str, projects: ProjectServiceDep, rendering: RenderingServiceDep
) -> Response:
    """Download the render manifest as a JSON file (404 if not produced)."""

    await projects.get(project_id)
    manifest = await rendering.manifest(project_id)
    if manifest is None:
        raise NotFoundError(
            "No render manifest has been produced for this project yet.",
            details={"id": project_id},
        )
    body = json.dumps(manifest.to_dict(), indent=2)
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="render_manifest.json"'},
    )


@router.get("/validation", response_model=RenderValidationResponse)
async def get_validation(
    project_id: str, projects: ProjectServiceDep, rendering: RenderingServiceDep
) -> RenderValidationResponse:
    """Return the final render validation report (404 if not produced yet)."""

    await projects.get(project_id)
    report = await rendering.validation_report(project_id)
    if report is None:
        raise NotFoundError(
            "No render validation report is available yet.", details={"id": project_id}
        )
    return RenderValidationResponse(project_id=project_id, report=report)


@router.get("/logs", response_model=RenderLogsResponse)
async def get_logs(
    project_id: str, projects: ProjectServiceDep, rendering: RenderingServiceDep
) -> RenderLogsResponse:
    """Return per-stage render logs (404 if the render has not started)."""

    await projects.get(project_id)
    stages = await rendering.logs(project_id)
    if stages is None:
        raise NotFoundError("No render logs are available yet.", details={"id": project_id})
    return RenderLogsResponse(project_id=project_id, stages=stages)


@router.get("/clips/{clip_id}/download")
async def download_clip(
    project_id: str,
    clip_id: str,
    projects: ProjectServiceDep,
    rendering: RenderingServiceDep,
    storage: StorageDep,
) -> Response:
    """Download a rendered clip's MP4 (404 with reason if not rendered)."""

    await projects.get(project_id)
    key = await rendering.resolve_clip(project_id, clip_id)
    if key is None:
        raise NotFoundError(
            "No rendered MP4 exists for this clip. The render may not have completed, or "
            "rendering was unavailable (e.g. FFmpeg not installed).",
            details={"id": project_id, "clip_id": clip_id},
        )
    path = storage.local_path(key)
    if path is not None:
        return FileResponse(path, media_type="video/mp4", filename=f"{clip_id}.mp4")
    return RedirectResponse(await storage.generate_access_url(key))
