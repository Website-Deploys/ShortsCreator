"""Validate Olympus upload-to-optimization rendering with local media only."""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
import traceback
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from olympus.api.v1.schemas.optimization import OptimizationResponse  # noqa: E402
from olympus.api.v1.schemas.projects import ProjectResponse  # noqa: E402
from olympus.api.v1.schemas.rendering import (  # noqa: E402
    RenderManifestResponse,
    RenderRunResponse,
)
from olympus.data.repositories import (  # noqa: E402
    StorageAnalysisRepository,
    StorageEditingRepository,
    StorageOptimizationRepository,
    StoragePlanningRepository,
    StorageProjectRepository,
    StorageRenderManifestRepository,
    StorageRenderRunRepository,
    StorageStoryRepository,
    StorageViralityRepository,
    StorageWorkflowRepository,
)
from olympus.data.storage.local import LocalStorage  # noqa: E402
from olympus.domain.contracts.ai import (  # noqa: E402
    TranscriptionProvider,
    TranscriptResult,
    TranscriptSegment,
)
from olympus.domain.contracts.workflow import EngineRunner  # noqa: E402
from olympus.domain.entities.optimization import OptimizationAnalysis  # noqa: E402
from olympus.domain.entities.project import Project  # noqa: E402
from olympus.domain.entities.render_pipeline import RenderRun  # noqa: E402
from olympus.domain.entities.rendering import RenderManifest  # noqa: E402
from olympus.domain.entities.workflow import Job, Workflow  # noqa: E402
from olympus.jobs import CheckpointValidator  # noqa: E402
from olympus.rendering.artifacts import (  # noqa: E402
    canonical_render_manifest_path,
    legacy_render_manifest_path,
    resolve_render_manifest,
)
from olympus.rendering.ffmpeg_renderer import FfmpegClipRenderer  # noqa: E402
from olympus.services.analysis import AnalysisService  # noqa: E402
from olympus.services.editing import EditingService  # noqa: E402
from olympus.services.intake import IntakeService  # noqa: E402
from olympus.services.optimization import OptimizationService  # noqa: E402
from olympus.services.planning import ClipPlannerService  # noqa: E402
from olympus.services.projects import NewProjectInput, ProjectService  # noqa: E402
from olympus.services.rendering import RenderingService  # noqa: E402
from olympus.services.story import StoryService  # noqa: E402
from olympus.services.virality import ViralityService  # noqa: E402
from olympus.services.workflow import WorkflowService  # noqa: E402
from olympus.validation.real_video import (  # noqa: E402
    as_dict,
    as_float,
    as_list,
    run_ffprobe,
    validate_frontend_payload,
)
from olympus.workflow.runners import UploadRunner, build_service_runner  # noqa: E402

DEFAULT_REPORT_DIR = ROOT / "work" / "validation_reports" / "real_rendering_e2e"
REPORT_NAME = "real_rendering_e2e_report.json"
SUMMARY_NAME = "real_rendering_e2e_summary.md"
DEFAULT_STORAGE_ROOT = ROOT / "storage_data"
SYNTHETIC_DURATION_SECONDS = 60.0
MINIMUM_MP4_BYTES = 1024
AV_TOLERANCE_SECONDS = 0.15

ProbeFunction = Callable[[Path], dict[str, Any]]


@dataclass(slots=True)
class RuntimeBundle:
    workflow: WorkflowService
    project_repo: StorageProjectRepository


class FixtureTranscriptionProvider(TranscriptionProvider):
    """Deterministic local transcript fixture used only by this validator."""

    def __init__(self, storage: LocalStorage, duration_seconds: float) -> None:
        self._storage = storage
        self._duration = duration_seconds

    @property
    def name(self) -> str:
        return "real_rendering_e2e_fixture"

    async def transcribe(
        self,
        audio_key: str,
        *,
        language_hint: str | None = None,
    ) -> TranscriptResult:
        del language_hint
        if not await self._storage.exists(audio_key):
            raise RuntimeError(f"Validator transcript input is missing: {audio_key}")
        return synthetic_transcript(self._duration)


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def base_report(mode: str, project_id: str | None = None) -> dict[str, Any]:
    return {
        "passed": False,
        "project_id": project_id,
        "mode": mode,
        "generated_at": utc_now_iso(),
        "stages": {
            "analysis": "missing",
            "story": "missing",
            "virality": "missing",
            "planning": "missing",
            "editing": "missing",
            "rendering": "missing",
            "optimization": "missing",
        },
        "clip_count": 0,
        "clips": [],
        "render_manifest_valid": False,
        "optimization_manifest_valid": False,
        "api_payload_valid": False,
        "frontend_payload_valid": False,
        "render_checkpoint": {},
        "optimization_handoff": {},
        "artifact_paths": {},
        "metadata": {},
        "external_calls_made": False,
        "real_user_media_used": False if mode == "local_synthetic" else None,
        "manual_playback_performed": False,
        "warnings": [],
        "errors": [],
    }


def synthetic_media_plan(
    output_path: Path,
    *,
    ffmpeg_binary: str = "ffmpeg",
    duration_seconds: float = SYNTHETIC_DURATION_SECONDS,
) -> list[str]:
    """Return a shell-free FFmpeg command for original local test media."""

    if not 60.0 <= duration_seconds <= 120.0:
        raise ValueError("Synthetic validation media must be 60-120 seconds long.")
    marker_filter = (
        "drawbox=x=0:y=0:w=iw:h=24:color=red@0.8:t=fill:"
        "enable=between(t\\,0\\,22),"
        "drawbox=x=0:y=0:w=iw:h=24:color=green@0.8:t=fill:"
        "enable=between(t\\,22\\,44),"
        "drawbox=x=0:y=0:w=iw:h=24:color=blue@0.8:t=fill:"
        f"enable=between(t\\,44\\,{duration_seconds}),"
        "drawbox=x='mod(t*80\\,iw-96)':y=132:w=96:h=96:color=white@0.9:t=fill,"
        "format=yuv420p"
    )
    return [
        ffmpeg_binary,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c=0x202430:size=640x360:rate=30:duration={duration_seconds}",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=210:sample_rate=48000:duration={duration_seconds}",
        "-vf",
        marker_filter,
        "-af",
        "tremolo=f=4:d=0.7,volume=0.22",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-ar",
        "48000",
        "-t",
        str(duration_seconds),
        str(output_path),
    ]


def generate_synthetic_media(
    output_path: Path,
    *,
    ffmpeg_binary: str = "ffmpeg",
    duration_seconds: float = SYNTHETIC_DURATION_SECONDS,
) -> dict[str, Any]:
    binary = shutil.which(ffmpeg_binary)
    if binary is None:
        raise RuntimeError(f"FFmpeg binary {ffmpeg_binary!r} is unavailable.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = synthetic_media_plan(
        output_path,
        ffmpeg_binary=binary,
        duration_seconds=duration_seconds,
    )
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
        shell=False,
    )
    if completed.returncode != 0 or not output_path.is_file():
        raise RuntimeError(
            "Synthetic FFmpeg generation failed: "
            f"{completed.stderr.strip() or completed.stdout.strip()}"
        )
    probe = run_ffprobe(output_path)
    if not probe.get("passed") or not probe.get("has_audio"):
        raise RuntimeError(f"Synthetic source failed FFprobe validation: {probe}")
    return {
        "path": str(output_path.resolve()),
        "duration_seconds": probe.get("container_duration"),
        "resolution": f"{probe.get('width')}x{probe.get('height')}",
        "audio_stream": bool(probe.get("has_audio")),
        "video_stream": bool(probe.get("width") and probe.get("height")),
        "file_size_bytes": output_path.stat().st_size,
        "generated_locally": True,
        "copyrighted_content_used": False,
        "external_calls_made": False,
    }


def synthetic_transcript(duration_seconds: float) -> TranscriptResult:
    texts = [
        "Weak openings lose attention without a clear promise.",
        "Missing context creates tension and causes premature cuts.",
        "Complete endings land the payoff and build lasting trust.",
    ]
    start_margin = 0.4
    speech_end = min(duration_seconds - 0.4, 8.0)
    slot = max(1.0, (speech_end - start_margin) / len(texts))
    segments: list[TranscriptSegment] = []
    for index, text in enumerate(texts):
        start = start_margin + index * slot
        end = min(speech_end, start + slot - 0.2)
        words = text.split()
        word_slot = max(0.01, (end - start) / len(words))
        word_data = [
            {
                "word": word,
                "start": round(start + word_index * word_slot, 3),
                "end": round(min(end, start + (word_index + 0.86) * word_slot), 3),
                "confidence": 0.99,
            }
            for word_index, word in enumerate(words)
        ]
        segments.append(
            TranscriptSegment(
                start=round(start, 3),
                end=round(end, 3),
                text=text,
                confidence=0.99,
                speaker="speaker_1",
                words=word_data,
            )
        )
    return TranscriptResult(language="en", segments=segments, confidence=0.99)


async def _file_chunks(path: Path) -> AsyncIterator[bytes]:
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            yield chunk


def _build_runtime(
    storage: LocalStorage,
    *,
    duration_seconds: float,
    ffmpeg_binary: str,
    ffprobe_binary: str,
    timeout_seconds: float,
) -> RuntimeBundle:
    project_repo = StorageProjectRepository(storage)
    analysis_repo = StorageAnalysisRepository(storage)
    story_repo = StorageStoryRepository(storage)
    virality_repo = StorageViralityRepository(storage)
    planning_repo = StoragePlanningRepository(storage)
    editing_repo = StorageEditingRepository(storage)
    render_run_repo = StorageRenderRunRepository(storage)
    render_manifest_repo = StorageRenderManifestRepository(storage)
    optimization_repo = StorageOptimizationRepository(storage)

    analysis = AnalysisService(
        analysis_repo=analysis_repo,
        project_repo=project_repo,
        storage=storage,
        transcription_provider=FixtureTranscriptionProvider(storage, duration_seconds),
    )
    story = StoryService(
        story_repo=story_repo,
        analysis_repo=analysis_repo,
        project_repo=project_repo,
        storage=storage,
    )
    virality = ViralityService(
        virality_repo=virality_repo,
        story_repo=story_repo,
        analysis_repo=analysis_repo,
        project_repo=project_repo,
        storage=storage,
    )
    planning = ClipPlannerService(
        planning_repo=planning_repo,
        virality_repo=virality_repo,
        story_repo=story_repo,
        analysis_repo=analysis_repo,
        project_repo=project_repo,
        storage=storage,
    )
    editing = EditingService(
        editing_repo=editing_repo,
        planning_repo=planning_repo,
        virality_repo=virality_repo,
        story_repo=story_repo,
        analysis_repo=analysis_repo,
        project_repo=project_repo,
        storage=storage,
    )
    rendering = RenderingService(
        render_run_repo=render_run_repo,
        manifest_store=render_manifest_repo,
        renderer=FfmpegClipRenderer(
            ffmpeg_binary=ffmpeg_binary,
            ffprobe_binary=ffprobe_binary,
        ),
        editing_repo=editing_repo,
        planning_repo=planning_repo,
        virality_repo=virality_repo,
        story_repo=story_repo,
        analysis_repo=analysis_repo,
        project_repo=project_repo,
        storage=storage,
    )
    optimization = OptimizationService(
        optimization_repo=optimization_repo,
        render_repo=render_manifest_repo,
        editing_repo=editing_repo,
        planning_repo=planning_repo,
        virality_repo=virality_repo,
        story_repo=story_repo,
        analysis_repo=analysis_repo,
        project_repo=project_repo,
        storage=storage,
    )
    services: dict[str, tuple[object, str]] = {
        "cognitive": (analysis, "get_analysis"),
        "story": (story, "get_story"),
        "virality": (virality, "get_virality"),
        "planning": (planning, "get_planning"),
        "editing": (editing, "get_editing"),
        "rendering": (rendering, "get_run"),
        "optimization": (optimization, "get_optimization"),
    }
    runners: dict[str, EngineRunner] = {"upload": UploadRunner(storage)}
    runners.update(
        {
            engine: build_service_runner(
                engine,
                service,
                getter=getter,
                timeout_seconds=timeout_seconds,
            )
            for engine, (service, getter) in services.items()
        }
    )
    workflow = WorkflowService(
        repository=StorageWorkflowRepository(storage),
        project_repo=project_repo,
        runners=runners,
        concurrency=1,
        max_attempts=1,
        backoff_base_seconds=0.01,
        heartbeat_interval_seconds=2.0,
        stale_after_seconds=max(120.0, timeout_seconds),
        worker_poll_interval_seconds=0.02,
        checkpoint_validator=CheckpointValidator(
            storage,
            ffprobe_binary=ffprobe_binary,
        ),
    )
    return RuntimeBundle(workflow=workflow, project_repo=project_repo)


async def create_local_project(
    media_path: Path,
    storage: LocalStorage,
    probe: dict[str, Any],
) -> Project:
    upload = await IntakeService(storage).store_upload(
        filename=media_path.name,
        content_type="video/mp4",
        chunks=_file_chunks(media_path),
    )
    return await ProjectService(StorageProjectRepository(storage), storage).create(
        NewProjectInput(
            storage_key=upload.storage_key,
            source_filename=upload.filename,
            size_bytes=upload.size_bytes,
            video_format=upload.video_format,
            content_type=upload.content_type,
            duration_seconds=as_float(probe.get("container_duration")),
            width=int(as_float(probe.get("width"))),
            height=int(as_float(probe.get("height"))),
            desired_clip_count=1,
            content_category="educational",
            editing_intensity="balanced",
            music_enabled=False,
            sfx_enabled=False,
            captions_enabled=True,
        )
    )


def _contains_key(value: Any, targets: set[str]) -> bool:
    if isinstance(value, dict):
        return any(
            str(key) in targets or _contains_key(item, targets)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_key(item, targets) for item in value)
    return False


def _path_inside(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def inspect_rendered_clip(
    *,
    render: dict[str, Any],
    storage: LocalStorage,
    storage_root: Path,
    captions_enabled: bool,
    probe_function: ProbeFunction = run_ffprobe,
    minimum_size_bytes: int = MINIMUM_MP4_BYTES,
) -> dict[str, Any]:
    clip_id = str(render.get("clip_id") or "")
    storage_key = str(render.get("storage_key") or "")
    local_value = storage.local_path(storage_key) if storage_key else None
    local_path = Path(local_value) if local_value else None
    exists = bool(local_path and local_path.is_file())
    size_bytes = local_path.stat().st_size if exists and local_path else 0
    inside_storage = bool(local_path and _path_inside(storage_root, local_path))
    incomplete_temp = bool(
        local_path
        and (
            local_path.suffix.lower() in {".tmp", ".part"}
            or any(local_path.parent.glob(f"{local_path.name}.*.tmp"))
        )
    )
    probe = probe_function(local_path) if exists and local_path else {}
    video_stream = bool(probe.get("width") and probe.get("height"))
    audio_stream = bool(probe.get("has_audio"))
    video_duration = as_float(probe.get("video_duration"))
    audio_duration = as_float(probe.get("audio_duration"))
    av_delta = round(audio_duration - video_duration, 3) if audio_stream else None
    metadata = as_dict(render.get("metadata"))
    timeline = as_dict(metadata.get("timeline"))
    timeline_present = bool(
        timeline
        and (
            timeline.get("repaired_start_seconds") is not None
            or timeline.get("contract_version") is not None
            or _contains_key(metadata, {"source_window_v1"})
        )
    )
    boundary_present = _contains_key(metadata, {"boundary_quality"})
    captions_present = _contains_key(
        metadata,
        {"caption_render_validation", "caption_intelligence_v2"},
    )
    warnings: list[str] = []
    errors: list[str] = []
    if not exists:
        errors.append("rendered MP4 is missing")
    elif size_bytes <= minimum_size_bytes:
        errors.append(
            f"rendered MP4 is only {size_bytes} bytes; minimum is {minimum_size_bytes + 1}"
        )
    if not inside_storage:
        errors.append("rendered MP4 path is outside the configured storage root")
    if incomplete_temp:
        errors.append("rendered MP4 or adjacent output is an incomplete temporary file")
    if exists and not probe.get("passed"):
        errors.append("ffprobe could not validate rendered MP4")
    if probe.get("passed") and not video_stream:
        errors.append("rendered MP4 has no video stream")
    if probe.get("passed") and not audio_stream:
        errors.append("rendered MP4 has no audio stream")
    if probe.get("passed") and str(probe.get("video_codec") or "").lower() != "h264":
        errors.append(f"unexpected video codec: {probe.get('video_codec')}")
    if probe.get("passed") and str(probe.get("audio_codec") or "").lower() != "aac":
        errors.append(f"unexpected audio codec: {probe.get('audio_codec')}")
    if probe.get("passed") and (probe.get("width"), probe.get("height")) != (1080, 1920):
        errors.append(
            f"unexpected resolution: {probe.get('width')}x{probe.get('height')}"
        )
    if av_delta is not None and abs(av_delta) > AV_TOLERANCE_SECONDS:
        errors.append(f"audio/video delta {av_delta}s exceeds {AV_TOLERANCE_SECONDS}s")
    if not timeline_present:
        errors.append("repaired timeline metadata is missing")
    if not boundary_present:
        errors.append("boundary quality metadata is missing")
    if captions_enabled and not captions_present:
        errors.append("caption metadata is missing while captions are enabled")
    if not _contains_key(metadata, {"boba"}):
        warnings.append("BOBA compact truth is unavailable for this clip")
    if not _contains_key(metadata, {"upload_metadata_v2", "upload_metadata"}):
        warnings.append("upload metadata is unavailable for this clip")
    if not _contains_key(metadata, {"copyright_safety_v2", "copyright_safety"}):
        warnings.append("safety metadata is unavailable for this clip")
    return {
        "clip_id": clip_id,
        "storage_key": storage_key,
        "path": str(local_path.resolve()) if local_path else None,
        "exists": exists,
        "size_bytes": size_bytes,
        "duration_seconds": probe.get("container_duration"),
        "resolution": (
            f"{probe.get('width')}x{probe.get('height')}" if video_stream else None
        ),
        "video_codec": probe.get("video_codec"),
        "audio_codec": probe.get("audio_codec"),
        "audio_sample_rate": probe.get("audio_sample_rate"),
        "audio_stream": audio_stream,
        "video_stream": video_stream,
        "av_delta_seconds": av_delta,
        "timeline_metadata_present": timeline_present,
        "boundary_quality_present": boundary_present,
        "captions_metadata_present": captions_present,
        "download_url": (
            f"/api/v1/projects/{{project_id}}/rendering/clips/{clip_id}/download"
            if clip_id
            else None
        ),
        "downloadable": bool(exists and inside_storage and probe.get("passed")),
        "warnings": warnings,
        "errors": errors,
        "passed": not errors,
    }


async def inspect_render_bundle(
    *,
    storage: LocalStorage,
    storage_root: Path,
    project_id: str,
    captions_enabled: bool,
    probe_function: ProbeFunction = run_ffprobe,
    minimum_size_bytes: int = MINIMUM_MP4_BYTES,
) -> dict[str, Any]:
    resolution = await resolve_render_manifest(storage, project_id)
    manifest = as_dict(resolution.manifest)
    renders = [as_dict(item) for item in as_list(manifest.get("renders"))]
    clips = [
        inspect_rendered_clip(
            render=render,
            storage=storage,
            storage_root=storage_root,
            captions_enabled=captions_enabled,
            probe_function=probe_function,
            minimum_size_bytes=minimum_size_bytes,
        )
        for render in renders
    ]
    warnings = [*resolution.warnings, *resolution.errors]
    canonical = canonical_render_manifest_path(project_id)
    canonical_present = bool(resolution.path_exists.get(canonical))
    if resolution.artifact_path == legacy_render_manifest_path(project_id):
        warnings.append("Only the stale legacy root render manifest was found.")
    valid = bool(
        canonical_present
        and resolution.artifact_path == canonical
        and manifest.get("status") == "completed"
        and renders
        and all(clip.get("passed") for clip in clips)
    )
    return {
        "valid": valid,
        "artifact_path": resolution.artifact_path,
        "manifest_source_path": resolution.manifest_source_path,
        "canonical_path": canonical,
        "legacy_path": legacy_render_manifest_path(project_id),
        "canonical_present": canonical_present,
        "manifest": manifest,
        "clips": clips,
        "warnings": warnings,
        "errors": [] if valid else ["Canonical render bundle validation failed."],
    }


def validate_optimization_handoff(
    workflow: Workflow | None,
    *,
    render_checkpoint_valid: bool,
) -> dict[str, Any]:
    rendering = workflow.job("rendering") if workflow else None
    optimization = workflow.job("optimization") if workflow else None
    timing_valid = bool(
        rendering
        and optimization
        and rendering.finished_at
        and optimization.started_at
        and optimization.started_at >= rendering.finished_at
    )
    passed = bool(
        render_checkpoint_valid
        and rendering
        and rendering.status.value == "completed"
        and optimization
        and optimization.status.value == "completed"
        and timing_valid
    )
    return {
        "passed": passed,
        "rendering_status": rendering.status.value if rendering else None,
        "optimization_status": optimization.status.value if optimization else None,
        "render_checkpoint_valid_before_optimization": render_checkpoint_valid,
        "optimization_started_after_rendering_finished": timing_valid,
    }


async def _optimization_validation(
    storage: LocalStorage,
    project_id: str,
    optimization: OptimizationAnalysis | None,
) -> dict[str, Any]:
    index_key = f"optimization/{project_id}/index.json"
    index_exists = await storage.exists(index_key)
    publish = optimization.stage("publish_package_creation") if optimization else None
    packages = as_list(as_dict(publish.data if publish else {}).get("packages"))
    optimized_assets: list[dict[str, Any]] = []
    for package in packages:
        for asset in as_list(as_dict(package).get("assets")):
            item = as_dict(asset)
            if item.get("kind") != "optimized_mp4":
                continue
            key = str(item.get("storage_key") or "")
            optimized_assets.append(
                {
                    **item,
                    "exists": bool(key and await storage.exists(key)),
                }
            )
    valid = bool(
        index_exists
        and optimization
        and optimization.status.value == "completed"
        and packages
        and optimized_assets
        and all(
            item.get("status") == "available" and item.get("exists")
            for item in optimized_assets
        )
    )
    return {
        "valid": valid,
        "artifact_path": index_key,
        "index_exists": index_exists,
        "status": optimization.status.value if optimization else None,
        "package_count": len(packages),
        "optimized_mp4_assets": optimized_assets,
    }


def _workflow_stages(workflow: Workflow | None) -> dict[str, str]:
    mapping = {
        "analysis": "cognitive",
        "story": "story",
        "virality": "virality",
        "planning": "planning",
        "editing": "editing",
        "rendering": "rendering",
        "optimization": "optimization",
    }
    statuses: dict[str, str] = {}
    for output, stage in mapping.items():
        job = workflow.job(stage) if workflow is not None else None
        statuses[output] = job.status.value if job is not None else "missing"
    return statuses


def _stored_render_job(workflow: Workflow | None) -> Job | None:
    return workflow.job("rendering") if workflow else None


def _api_payload_validation(
    *,
    project: Project,
    render_run: RenderRun | None,
    manifest: RenderManifest | None,
    optimization: OptimizationAnalysis | None,
    plans: list[dict[str, Any]],
    clips: list[dict[str, Any]],
) -> dict[str, Any]:
    warnings: list[str] = []
    try:
        payload: dict[str, Any] = {
            "project": ProjectResponse.from_entity(project).model_dump(mode="json"),
            "rendering": (
                RenderRunResponse.from_entity(render_run).model_dump(mode="json")
                if render_run
                else None
            ),
            "manifest": (
                RenderManifestResponse.from_entity(manifest).model_dump(mode="json")
                if manifest
                else None
            ),
            "optimization": (
                OptimizationResponse.from_entity(optimization).model_dump(mode="json")
                if optimization
                else None
            ),
            "download_urls": [
                str(clip.get("download_url") or "").replace("{project_id}", project.id)
                for clip in clips
                if clip.get("clip_id")
            ],
        }
        json.dumps(payload)
    except (TypeError, ValueError) as exc:
        return {
            "valid": False,
            "frontend_valid": False,
            "payload": {},
            "warnings": [],
            "errors": [f"API payload serialization failed: {exc}"],
        }
    frontend = validate_frontend_payload(
        manifest=payload.get("manifest"),
        plans={"plans": plans},
    )
    warnings.extend(str(item) for item in as_list(frontend.get("warnings")))
    downloads_valid = bool(clips) and all(clip.get("downloadable") for clip in clips)
    metadata_valid = bool(clips) and all(
        clip.get("timeline_metadata_present") and clip.get("boundary_quality_present")
        for clip in clips
    )
    api_valid = bool(
        project.status.value == "complete"
        and render_run
        and render_run.status.value == "completed"
        and manifest
        and manifest.renders
        and optimization
        and optimization.status.value == "completed"
        and downloads_valid
    )
    frontend_valid = bool(frontend.get("passed") and downloads_valid and metadata_valid)
    return {
        "valid": api_valid,
        "frontend_valid": frontend_valid,
        "payload": payload,
        "frontend": frontend,
        "warnings": warnings,
        "errors": (
            []
            if api_valid and frontend_valid
            else ["Final API/frontend payload is incomplete."]
        ),
    }


async def inspect_existing_project(
    project_id: str,
    *,
    storage_root: Path = DEFAULT_STORAGE_ROOT,
    ffprobe_binary: str = "ffprobe",
    probe_function: ProbeFunction = run_ffprobe,
    minimum_size_bytes: int = MINIMUM_MP4_BYTES,
) -> dict[str, Any]:
    report = base_report("project_id", project_id)
    report["real_user_media_used"] = None
    report["warnings"].append(
        "Existing-project inspection cannot determine whether the original source was user media."
    )
    storage = LocalStorage(root=str(storage_root))
    project = await StorageProjectRepository(storage).get(project_id)
    if project is None:
        report["errors"].append("Project does not exist in configured storage.")
        return report
    workflow = await StorageWorkflowRepository(storage).load(project_id)
    analysis = await StorageAnalysisRepository(storage).load(project_id)
    story = await StorageStoryRepository(storage).load(project_id)
    virality = await StorageViralityRepository(storage).load(project_id)
    planning = await StoragePlanningRepository(storage).load(project_id)
    editing = await StorageEditingRepository(storage).load(project_id)
    render_run = await StorageRenderRunRepository(storage).load(project_id)
    optimization = await StorageOptimizationRepository(storage).load(project_id)
    report["stages"] = _workflow_stages(workflow)
    render_bundle = await inspect_render_bundle(
        storage=storage,
        storage_root=storage_root,
        project_id=project_id,
        captions_enabled=project.captions_enabled,
        probe_function=probe_function,
        minimum_size_bytes=minimum_size_bytes,
    )
    render_job = _stored_render_job(workflow)
    stored_path = (
        str(render_job.checkpoint.get("artifact_path"))
        if render_job and render_job.checkpoint.get("artifact_path")
        else None
    )
    checkpoint = await CheckpointValidator(
        storage,
        ffprobe_binary=ffprobe_binary,
    ).inspect_render(project_id, stored_artifact_path=stored_path)
    manifest = await StorageRenderManifestRepository(storage).load(project_id)
    optimization_validation = await _optimization_validation(storage, project_id, optimization)
    plans_stage = planning.stage("blueprint_generation") if planning else None
    plans = [
        as_dict(item)
        for item in as_list(
            as_dict(plans_stage.data if plans_stage else {}).get("plans")
        )
    ]
    api = _api_payload_validation(
        project=project,
        render_run=render_run,
        manifest=manifest,
        optimization=optimization,
        plans=plans,
        clips=render_bundle["clips"],
    )
    handoff = validate_optimization_handoff(
        workflow,
        render_checkpoint_valid=bool(checkpoint.get("valid")),
    )
    report.update(
        {
            "clip_count": len(render_bundle["clips"]),
            "clips": render_bundle["clips"],
            "render_manifest_valid": bool(
                render_bundle["valid"] and checkpoint.get("valid")
            ),
            "optimization_manifest_valid": optimization_validation["valid"],
            "api_payload_valid": api["valid"],
            "frontend_payload_valid": api["frontend_valid"],
            "render_checkpoint": checkpoint,
            "optimization_handoff": handoff,
            "artifact_paths": {
                "render_manifest": render_bundle["artifact_path"],
                "render_manifest_expected": canonical_render_manifest_path(project_id),
                "optimization_manifest": optimization_validation["artifact_path"],
            },
            "metadata": {
                "persisted_engine_artifacts": {
                    "analysis": analysis.status.value if analysis else None,
                    "story": story.status.value if story else None,
                    "virality": virality.status.value if virality else None,
                    "planning": planning.status.value if planning else None,
                    "editing": editing.status.value if editing else None,
                    "rendering": render_run.status.value if render_run else None,
                    "optimization": optimization.status.value if optimization else None,
                },
                "boba_compact_truth_available": bool(
                    render_bundle["clips"]
                    and any(
                        _contains_key(as_dict(item), {"boba"})
                        for item in as_list(as_dict(render_bundle.get("manifest")).get("renders"))
                    )
                ),
                "boundary_quality_present": bool(render_bundle["clips"])
                and all(item["boundary_quality_present"] for item in render_bundle["clips"]),
                "repaired_timeline_present": bool(render_bundle["clips"])
                and all(item["timeline_metadata_present"] for item in render_bundle["clips"]),
                "safety_or_upload_metadata_available": bool(
                    render_bundle["clips"]
                    and any(
                        _contains_key(
                            as_dict(item),
                            {
                                "copyright_safety_v2",
                                "copyright_safety",
                                "upload_metadata_v2",
                                "upload_metadata",
                            },
                        )
                        for item in as_list(as_dict(render_bundle.get("manifest")).get("renders"))
                    )
                ),
            },
        }
    )
    report["warnings"].extend(render_bundle["warnings"])
    report["warnings"].extend(api["warnings"])
    if not report["render_manifest_valid"]:
        report["errors"].extend(render_bundle["errors"])
        report["errors"].extend(str(item) for item in as_list(checkpoint.get("warnings")))
    if not optimization_validation["valid"]:
        report["errors"].append("Optimization manifest or optimized MP4 package is invalid.")
    if not handoff["passed"]:
        report["errors"].append("Optimization did not follow a valid render checkpoint.")
    report["errors"].extend(api["errors"])
    report["passed"] = bool(
        workflow
        and workflow.status.value == "completed"
        and all(value == "completed" for value in report["stages"].values())
        and report["clip_count"] > 0
        and report["render_manifest_valid"]
        and report["optimization_manifest_valid"]
        and report["api_payload_valid"]
        and report["frontend_payload_valid"]
        and handoff["passed"]
        and all(item.get("passed") for item in report["clips"])
        and not report["errors"]
    )
    report["warnings"] = list(dict.fromkeys(str(item) for item in report["warnings"]))
    report["errors"] = list(dict.fromkeys(str(item) for item in report["errors"]))
    return report


async def run_local_pipeline(
    media_path: Path,
    *,
    mode: str,
    storage_root: Path = DEFAULT_STORAGE_ROOT,
    ffmpeg_binary: str = "ffmpeg",
    ffprobe_binary: str = "ffprobe",
    timeout_seconds: float = 1800.0,
    minimum_size_bytes: int = MINIMUM_MP4_BYTES,
) -> dict[str, Any]:
    probe = run_ffprobe(media_path)
    if not probe.get("passed") or not probe.get("has_audio"):
        report = base_report(mode)
        report["real_user_media_used"] = mode == "local_file"
        report["errors"].append(f"Input media failed FFprobe validation: {probe}")
        return report
    duration = as_float(probe.get("container_duration"))
    storage = LocalStorage(root=str(storage_root))
    project = await create_local_project(media_path, storage, probe)
    runtime = _build_runtime(
        storage,
        duration_seconds=duration,
        ffmpeg_binary=ffmpeg_binary,
        ffprobe_binary=ffprobe_binary,
        timeout_seconds=timeout_seconds,
    )
    runtime_exceptions: list[dict[str, str]] = []
    try:
        await runtime.workflow.start(
            project,
            source=f"real_rendering_e2e:{mode}",
            idempotency_key=f"real_rendering_e2e:{project.id}",
        )
        await runtime.workflow.wait_for(project.id, timeout=timeout_seconds)
    except Exception as exc:
        runtime_exceptions.append(
            {
                "context": "workflow execution",
                "type": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(limit=25),
            }
        )
    finally:
        try:
            await runtime.workflow.stop_pool()
        except Exception as exc:
            runtime_exceptions.append(
                {
                    "context": "workflow pool shutdown",
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "traceback": traceback.format_exc(limit=25),
                }
            )
    try:
        report = await inspect_existing_project(
            project.id,
            storage_root=storage_root,
            ffprobe_binary=ffprobe_binary,
            minimum_size_bytes=minimum_size_bytes,
        )
    except Exception as exc:
        runtime_exceptions.append(
            {
                "context": "post-run project inspection",
                "type": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(limit=25),
            }
        )
        report = base_report(mode, project.id)
    report["mode"] = mode
    report["real_user_media_used"] = mode == "local_file"
    report["input_media"] = {
        "path": str(media_path.resolve()),
        "duration_seconds": duration,
        "width": probe.get("width"),
        "height": probe.get("height"),
        "has_audio": probe.get("has_audio"),
        "transcript_source": "deterministic validator fixture, not speech recognition",
    }
    report["warnings"] = [
        warning
        for warning in report["warnings"]
        if "cannot determine whether the original source" not in warning
    ]
    report["warnings"].append(
        "Transcript content is a deterministic validator fixture; transcription "
        "accuracy was not tested."
    )
    if runtime_exceptions:
        report["metadata"]["runtime_exceptions"] = runtime_exceptions
        report["errors"].extend(
            f"{item['context']}: {item['type']}: {item['message']}"
            for item in runtime_exceptions
        )
        report["passed"] = False
    return report


def _validated_report_dir(report_dir: Path) -> Path:
    allowed = (ROOT / "work" / "validation_reports").resolve()
    resolved = report_dir.resolve()
    if not _path_inside(allowed, resolved) and resolved != allowed:
        raise ValueError(f"Report directory must stay under {allowed}.")
    return resolved


def write_reports(report: dict[str, Any], report_dir: Path = DEFAULT_REPORT_DIR) -> dict[str, str]:
    output = _validated_report_dir(report_dir)
    output.mkdir(parents=True, exist_ok=True)
    json_path = output / REPORT_NAME
    summary_path = output / SUMMARY_NAME
    json_path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    lines = [
        "# Real Rendering E2E Validation V2",
        "",
        f"- Passed: `{str(bool(report.get('passed'))).lower()}`",
        f"- Mode: `{report.get('mode')}`",
        f"- Project: `{report.get('project_id') or 'not created'}`",
        f"- Rendered clips: `{report.get('clip_count', 0)}`",
        f"- Canonical render manifest: `{str(bool(report.get('render_manifest_valid'))).lower()}`",
        "- Optimization manifest: "
        f"`{str(bool(report.get('optimization_manifest_valid'))).lower()}`",
        f"- API payload: `{str(bool(report.get('api_payload_valid'))).lower()}`",
        f"- Frontend payload: `{str(bool(report.get('frontend_payload_valid'))).lower()}`",
        "- External calls: `false`",
        "- Manual playback: `false`",
    ]
    if report.get("warnings"):
        lines.extend(["", "## Warnings", *[f"- {item}" for item in report["warnings"]]])
    if report.get("errors"):
        lines.extend(["", "## Errors", *[f"- {item}" for item in report["errors"]]])
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": str(json_path), "summary": str(summary_path)}


async def run_selected_mode(args: argparse.Namespace) -> dict[str, Any]:
    if args.project_id:
        return await inspect_existing_project(
            str(args.project_id),
            storage_root=args.storage_root,
            ffprobe_binary=args.ffprobe_binary,
            minimum_size_bytes=args.minimum_mp4_bytes,
        )
    if args.local_synthetic:
        media_path = args.report_dir / "runtime" / "synthetic_source.mp4"
        synthetic = generate_synthetic_media(
            media_path,
            ffmpeg_binary=args.ffmpeg_binary,
        )
        report = await run_local_pipeline(
            media_path,
            mode="local_synthetic",
            storage_root=args.storage_root,
            ffmpeg_binary=args.ffmpeg_binary,
            ffprobe_binary=args.ffprobe_binary,
            timeout_seconds=args.timeout_seconds,
            minimum_size_bytes=args.minimum_mp4_bytes,
        )
        report["synthetic_media"] = synthetic
        return report
    return await run_local_pipeline(
        args.local_file,
        mode="local_file",
        storage_root=args.storage_root,
        ffmpeg_binary=args.ffmpeg_binary,
        ffprobe_binary=args.ffprobe_binary,
        timeout_seconds=args.timeout_seconds,
        minimum_size_bytes=args.minimum_mp4_bytes,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--local-synthetic", action="store_true")
    modes.add_argument("--project-id")
    modes.add_argument("--local-file", type=Path)
    parser.add_argument("--storage-root", type=Path, default=DEFAULT_STORAGE_ROOT)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--ffmpeg-binary", default="ffmpeg")
    parser.add_argument("--ffprobe-binary", default="ffprobe")
    parser.add_argument("--timeout-seconds", type=float, default=1800.0)
    parser.add_argument("--minimum-mp4-bytes", type=int, default=MINIMUM_MP4_BYTES)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    args.report_dir = _validated_report_dir(args.report_dir)
    if args.local_file is not None:
        args.local_file = args.local_file.resolve()
        if not args.local_file.is_file():
            raise SystemExit(f"Local video does not exist: {args.local_file}")
    try:
        report = asyncio.run(run_selected_mode(args))
    except Exception as exc:
        if args.project_id:
            mode = "project_id"
        elif args.local_synthetic:
            mode = "local_synthetic"
        else:
            mode = "local_file"
        report = base_report(mode, str(args.project_id) if args.project_id else None)
        report["real_user_media_used"] = mode == "local_file"
        report["errors"].append(f"{type(exc).__name__}: {exc}")
        report["metadata"]["runtime_exceptions"] = [
            {
                "context": "validator entrypoint",
                "type": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(limit=25),
            }
        ]
    paths = write_reports(report, args.report_dir)
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "project_id": report.get("project_id"),
                "mode": report["mode"],
                "clip_count": report["clip_count"],
                "reports": paths,
                "warnings": report["warnings"],
                "errors": report["errors"],
            },
            indent=2,
        )
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
