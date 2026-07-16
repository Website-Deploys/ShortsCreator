"""Optimization Engine endpoints.

Expose the post-render polish pipeline: fetch the current optimization analysis,
start or resume it, re-run a single stage, cancel an in-flight run, fetch the
quality report / variants / music recommendations / publish packages, and
download a package's real assets (metadata JSON, caption files, the rendered
MP4). No endpoint fabricates enhancement - stages report ``unavailable`` honestly
when the rendered media or a model is absent, undeterminable values are
``unknown``, and an asset that cannot exist returns an honest 404 with the exact
reason rather than a broken file. Nothing here re-renders or changes the story.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status
from fastapi.responses import FileResponse, RedirectResponse

from olympus.api.dependencies import OptimizationServiceDep, ProjectServiceDep, StorageDep
from olympus.api.v1.schemas.optimization import (
    MusicRecommendationsResponse,
    OptimizationResponse,
    PackageListResponse,
    PackageResponse,
    QualityReportResponse,
    VariantListResponse,
)
from olympus.platform.errors import NotFoundError

router = APIRouter(prefix="/projects/{project_id}/optimization", tags=["optimization"])

# Content types for downloadable package assets, by asset kind.
_ASSET_MEDIA_TYPES = {
    "metadata": "application/json",
    "upload_metadata_v2": "application/json",
    "quality_report": "application/json",
    "captions_srt": "application/x-subrip",
    "captions_vtt": "text/vtt",
    "optimized_mp4": "video/mp4",
}
_ASSET_FILENAMES = {
    "metadata": "metadata.json",
    "upload_metadata_v2": "upload_metadata_v2.json",
    "quality_report": "quality_report.json",
    "captions_srt": "captions.srt",
    "captions_vtt": "captions.vtt",
    "optimized_mp4": "optimized.mp4",
}


@router.get("", response_model=OptimizationResponse)
async def get_optimization(
    project_id: str, projects: ProjectServiceDep, optimization: OptimizationServiceDep
) -> OptimizationResponse:
    """Return the project's current optimization analysis (404 if none yet)."""

    await projects.get(project_id)  # 404s if the project doesn't exist
    result = await optimization.get_optimization(project_id)
    if result is None:
        raise NotFoundError(
            "No optimization analysis exists for this project yet.", details={"id": project_id}
        )
    return OptimizationResponse.from_entity(result)


@router.post("/run", response_model=OptimizationResponse, status_code=status.HTTP_202_ACCEPTED)
async def run_optimization(
    project_id: str, projects: ProjectServiceDep, optimization: OptimizationServiceDep
) -> OptimizationResponse:
    """Start (or resume) the optimization pipeline in the background."""

    project = await projects.get(project_id)
    result = await optimization.start(project, restart=True)
    return OptimizationResponse.from_entity(result, include_data=False)


@router.post("/stages/{stage}/rerun", response_model=OptimizationResponse)
async def rerun_optimization_stage(
    project_id: str,
    stage: str,
    projects: ProjectServiceDep,
    optimization: OptimizationServiceDep,
) -> OptimizationResponse:
    """Re-run a single optimization stage, leaving the others untouched."""

    project = await projects.get(project_id)
    result = await optimization.rerun_stage(project, stage)
    return OptimizationResponse.from_entity(result)


@router.post("/cancel", status_code=status.HTTP_202_ACCEPTED)
async def cancel_optimization(
    project_id: str, optimization: OptimizationServiceDep
) -> dict[str, bool]:
    """Request cancellation of an in-flight optimization run."""

    cancelled = await optimization.cancel(project_id)
    return {"cancelled": cancelled}


@router.get("/quality", response_model=QualityReportResponse)
async def get_quality_report(
    project_id: str, projects: ProjectServiceDep, optimization: OptimizationServiceDep
) -> QualityReportResponse:
    """Return the quality evaluation report (404 if not produced yet)."""

    await projects.get(project_id)
    report = await optimization.quality_report(project_id)
    if report is None:
        raise NotFoundError(
            "No quality report is available for this project yet.", details={"id": project_id}
        )
    return QualityReportResponse(project_id=project_id, report=report)


@router.get("/variants", response_model=VariantListResponse)
async def get_variants(
    project_id: str, projects: ProjectServiceDep, optimization: OptimizationServiceDep
) -> VariantListResponse:
    """Return the generated export variants (404 if not produced yet)."""

    await projects.get(project_id)
    variants = await optimization.variants(project_id)
    if variants is None:
        raise NotFoundError(
            "No variants are available for this project yet.", details={"id": project_id}
        )
    return VariantListResponse(project_id=project_id, variants=variants)


@router.get("/music", response_model=MusicRecommendationsResponse)
async def get_music_recommendations(
    project_id: str, projects: ProjectServiceDep, optimization: OptimizationServiceDep
) -> MusicRecommendationsResponse:
    """Return the copyright-free music recommendations (404 if not produced yet)."""

    await projects.get(project_id)
    music = await optimization.music_recommendations(project_id)
    if music is None:
        raise NotFoundError(
            "No music recommendations are available for this project yet.",
            details={"id": project_id},
        )
    return MusicRecommendationsResponse(project_id=project_id, music=music)


@router.get("/packages", response_model=PackageListResponse)
async def list_packages(
    project_id: str, projects: ProjectServiceDep, optimization: OptimizationServiceDep
) -> PackageListResponse:
    """List the publish packages (404 if not assembled yet)."""

    await projects.get(project_id)
    packages = await optimization.list_packages(project_id)
    if packages is None:
        raise NotFoundError(
            "No publish packages are available for this project yet.", details={"id": project_id}
        )
    return PackageListResponse(
        project_id=project_id, package_count=len(packages), packages=packages
    )


@router.get("/packages/{clip_id}", response_model=PackageResponse)
async def get_package(
    project_id: str,
    clip_id: str,
    projects: ProjectServiceDep,
    optimization: OptimizationServiceDep,
) -> PackageResponse:
    """Return a single clip's publish package (404 if not found)."""

    await projects.get(project_id)
    package = await optimization.get_package(project_id, clip_id)
    if package is None:
        raise NotFoundError(
            "No such publish package for this project.",
            details={"id": project_id, "clip_id": clip_id},
        )
    return PackageResponse(project_id=project_id, package=package)


async def _download_asset(
    project_id: str,
    clip_id: str,
    kind: str,
    optimization: OptimizationServiceDep,
    storage: StorageDep,
) -> Response:
    """Resolve and stream a package asset, or 404 with the honest reason."""

    asset = await optimization.resolve_asset(project_id, clip_id, kind)
    if asset is None:
        raise NotFoundError(
            "No such asset for this package.",
            details={"id": project_id, "clip_id": clip_id, "asset": kind},
        )
    if asset.get("status") != "available" or not asset.get("storage_key"):
        # Honest: the asset cannot exist here; return why, never a broken file.
        raise NotFoundError(
            asset.get("reason") or "This asset is not available.",
            details={"id": project_id, "clip_id": clip_id, "asset": kind},
        )
    key = asset["storage_key"]
    media_type = _ASSET_MEDIA_TYPES.get(kind, "application/octet-stream")
    path = storage.local_path(key)
    if path is not None:
        return FileResponse(path, media_type=media_type, filename=_ASSET_FILENAMES.get(kind, kind))
    url = await storage.generate_access_url(key)
    return RedirectResponse(url)


@router.get("/packages/{clip_id}/metadata")
async def download_metadata(
    project_id: str,
    clip_id: str,
    projects: ProjectServiceDep,
    optimization: OptimizationServiceDep,
    storage: StorageDep,
) -> Response:
    """Download a package's metadata JSON (404 with reason if unavailable)."""

    await projects.get(project_id)
    return await _download_asset(project_id, clip_id, "metadata", optimization, storage)


@router.get("/packages/{clip_id}/thumbnail")
async def download_thumbnail(
    project_id: str,
    clip_id: str,
    projects: ProjectServiceDep,
    optimization: OptimizationServiceDep,
    storage: StorageDep,
) -> Response:
    """Download a package's thumbnail (404 with reason - requires a vision model)."""

    await projects.get(project_id)
    return await _download_asset(project_id, clip_id, "thumbnail", optimization, storage)


@router.get("/packages/{clip_id}/assets/{kind}")
async def download_asset(
    project_id: str,
    clip_id: str,
    kind: str,
    projects: ProjectServiceDep,
    optimization: OptimizationServiceDep,
    storage: StorageDep,
) -> Response:
    """Download any package asset by kind (404 with the honest reason if absent)."""

    await projects.get(project_id)
    return await _download_asset(project_id, clip_id, kind, optimization, storage)
