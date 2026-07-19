"""Prove Olympus can complete a real multi-clip render from a 30+ minute source."""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
import time
import traceback
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for import_root in (ROOT, SRC):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from tools import validate_real_rendering_e2e as real_e2e  # noqa: E402

from olympus.data.repositories import (  # noqa: E402
    StorageAnalysisRepository,
    StorageEditingRepository,
    StorageOptimizationRepository,
    StoragePlanningRepository,
    StorageProjectRepository,
    StorageRenderManifestRepository,
    StorageRenderRunRepository,
    StorageWorkflowRepository,
)
from olympus.data.storage.local import LocalStorage  # noqa: E402
from olympus.domain.contracts.ai import (  # noqa: E402
    TranscriptionProvider,
    TranscriptResult,
    TranscriptSegment,
)
from olympus.domain.contracts.rendering import (  # noqa: E402
    ClipRenderOutput,
    ClipRenderSpec,
)
from olympus.domain.contracts.storage import StoragePort  # noqa: E402
from olympus.platform.config import get_settings  # noqa: E402
from olympus.rendering.artifacts import canonical_render_manifest_path  # noqa: E402
from olympus.rendering.ffmpeg_renderer import FfmpegClipRenderer  # noqa: E402
from olympus.validation.long_video import (  # noqa: E402
    LONG_VIDEO_AV_TOLERANCE_SECONDS,
    LongVideoFullRenderResultV1,
    LongVideoStageResultV1,
    analyze_long_video_source_intervals,
    long_video_ffprobe_result,
    long_video_self_check,
    long_video_stage_result,
    validate_long_source_duration,
    validate_long_video_clip_counts,
    validate_long_video_final_payload,
    validate_long_video_manifest_presence,
    validated_long_video_report_dir,
    write_long_video_full_render_report,
)
from olympus.validation.real_video import as_dict, as_list, run_ffprobe  # noqa: E402

DEFAULT_REPORT_DIR = ROOT / "work" / "validation_reports" / "long_video_full_render"
DEFAULT_STORAGE_ROOT = ROOT / "storage_data"
DEFAULT_MINUTES = 30.0
DEFAULT_MINIMUM_CLIPS = 3
DEFAULT_TIMEOUT_SECONDS = 7200.0
DEFAULT_SOURCE_FPS = 30
DEFAULT_RENDER_PRESET = "veryfast"
DEFAULT_RENDER_THREADS = 1
DEFAULT_FILTER_THREADS = 1
MINIMUM_MP4_BYTES = 1024

JsonDict = dict[str, Any]


class LongFixtureTranscriptionProvider(TranscriptionProvider):
    """Deterministic full-duration transcript used only by this local validator."""

    def __init__(self, storage: LocalStorage, duration_seconds: float) -> None:
        self._storage = storage
        self._duration_seconds = duration_seconds

    @property
    def name(self) -> str:
        return "long_video_full_render_fixture"

    async def transcribe(
        self,
        audio_key: str,
        *,
        language_hint: str | None = None,
    ) -> TranscriptResult:
        del language_hint
        if not await self._storage.exists(audio_key):
            raise RuntimeError(f"Long-video transcript input is missing: {audio_key}")
        return synthetic_long_transcript(self._duration_seconds)


class ObservedFfmpegClipRenderer(FfmpegClipRenderer):
    """The production FFmpeg renderer with validator-only timing observations."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._active = 0
        self.max_parallel = 0
        self.invocation_count = 0
        self.records: list[JsonDict] = []
        self.failures: list[JsonDict] = []

    async def render_clip(
        self,
        spec: ClipRenderSpec,
        storage: StoragePort,
    ) -> ClipRenderOutput:
        self.invocation_count += 1
        self._active += 1
        self.max_parallel = max(self.max_parallel, self._active)
        started = time.perf_counter()
        phase = "preview" if spec.preview else "full"
        try:
            output = await super().render_clip(spec, storage)
        except Exception as exc:
            details = getattr(exc, "details", {})
            details = details if isinstance(details, dict) else {}
            self.failures.append(
                {
                    "clip_id": spec.clip_id,
                    "phase": phase,
                    "duration_seconds": round(time.perf_counter() - started, 3),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "stderr_tail": as_list(details.get("stderr_tail")),
                    "resource_exhaustion": details.get("resource_exhaustion") is True,
                    "resource_hint": details.get("resource_hint"),
                }
            )
            raise
        else:
            self.records.append(
                {
                    "clip_id": spec.clip_id,
                    "phase": phase,
                    "duration_seconds": round(time.perf_counter() - started, 3),
                    "output_duration_seconds": output.duration,
                    "size_bytes": output.size_bytes,
                }
            )
            return output
        finally:
            self._active -= 1

    def observations(self) -> JsonDict:
        return {
            "renderer_ffmpeg_process_count": self.invocation_count,
            "render_invocations": list(self.records),
            "render_failures": list(self.failures),
            "maximum_concurrent_render_invocations": self.max_parallel,
            "rendering_mode": "sequential" if self.max_parallel <= 1 else "parallel",
            "resource_exhaustion_detected": any(
                item.get("resource_exhaustion") is True for item in self.failures
            ),
        }


def synthetic_long_transcript(duration_seconds: float) -> TranscriptResult:
    """Return timestamped fixture speech spanning the entire synthetic source."""

    duration = max(0.0, float(duration_seconds))
    if duration < 60.0:
        raise ValueError("Long synthetic transcript requires at least 60 seconds.")
    templates = (
        "Most creators miss chapter {chapter}: the opening must promise a concrete result.",
        "The setup explains the audience problem before any solution is introduced.",
        "But the usual shortcut creates tension because it removes the evidence viewers need.",
        "Here is the turning point: preserve context, then tighten only the empty space.",
        "The payoff is clear because complete boundaries protect the final lesson.",
        "Finally, chapter {chapter} ends with a practical rule the viewer can remember.",
        "A bridge example number {index} keeps this source continuous across the full timeline.",
        "This section compares a weak fragment with a complete and distinct editorial moment.",
        "Notice why the reason matters: clarity makes the result useful and shareable.",
        "The next transition introduces a different topic marker for timeline diversity.",
    )
    segments: list[TranscriptSegment] = []
    start = 1.0
    index = 0
    while start < duration - 0.5:
        chapter = int(start // 300.0) + 1
        text = templates[index % len(templates)].format(chapter=chapter, index=index + 1)
        end = min(duration - 0.2, start + 10.0)
        words = text.split()
        word_slot = max(0.01, (end - start) / max(1, len(words)))
        word_data = [
            {
                "word": word,
                "start": round(start + word_index * word_slot, 3),
                "end": round(
                    min(end, start + (word_index + 0.88) * word_slot),
                    3,
                ),
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
        index += 1
        start += 20.0
    return TranscriptResult(language="en", segments=segments, confidence=0.99)


def synthetic_long_media_plan(
    output_path: Path,
    *,
    duration_seconds: float,
    ffmpeg_binary: str = "ffmpeg",
    source_fps: int = DEFAULT_SOURCE_FPS,
) -> list[str]:
    """Build a bounded, shell-free command for genuine low-entropy long media."""

    if duration_seconds <= 0:
        raise ValueError("Synthetic duration must be positive.")
    if source_fps < 1 or source_fps > 30:
        raise ValueError("Synthetic source FPS must be between 1 and 30.")
    colors = ("0x172036", "0x24324d", "0x183a38", "0x3d283f", "0x3d3522", "0x24344a")
    section = duration_seconds / len(colors)
    filters: list[str] = []
    for index, color in enumerate(colors):
        start = round(index * section, 3)
        end = round(duration_seconds if index == len(colors) - 1 else (index + 1) * section, 3)
        filters.append(
            "drawbox=x=0:y=0:w=iw:h=ih:"
            f"color={color}:t=fill:enable=between(t\\,{start}\\,{end})"
        )
    filters.extend(
        [
            "drawbox=x='mod(floor(t/5)*72\\,iw-88)':y=118:w=88:h=88:"
            "color=white@0.88:t=fill",
            "drawbox=x=0:y=0:w=iw:h=18:color=0x56d6ff@0.9:t=fill",
            "format=yuv420p",
        ]
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
        f"color=c=0x172036:size=640x360:rate={source_fps}:duration={duration_seconds}",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=220:sample_rate=48000:duration={duration_seconds}",
        "-vf",
        ",".join(filters),
        "-af",
        "tremolo=f=2:d=0.25,volume=0.08",
        "-threads",
        "1",
        "-filter_threads",
        "1",
        "-filter_complex_threads",
        "1",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        "-r",
        str(source_fps),
        "-c:a",
        "aac",
        "-b:a",
        "64k",
        "-ar",
        "48000",
        "-t",
        str(duration_seconds),
        "-movflags",
        "+faststart",
        str(output_path),
    ]


def generate_long_synthetic_media(
    output_path: Path,
    *,
    minutes: float,
    ffmpeg_binary: str = "ffmpeg",
    timeout_seconds: float = 1200.0,
) -> JsonDict:
    """Generate and FFprobe a real 30+ minute local source."""

    binary = shutil.which(ffmpeg_binary)
    if binary is None:
        raise RuntimeError(f"FFmpeg binary {ffmpeg_binary!r} is unavailable.")
    duration_seconds = float(minutes) * 60.0
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = synthetic_long_media_plan(
        output_path,
        duration_seconds=duration_seconds,
        ffmpeg_binary=binary,
    )
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        shell=False,
    )
    runtime = round(time.perf_counter() - started, 3)
    if completed.returncode != 0 or not output_path.is_file():
        stderr_tail = (completed.stderr or completed.stdout or "").splitlines()[-40:]
        raise RuntimeError(
            "Long synthetic FFmpeg generation failed: " + " | ".join(stderr_tail)
        )
    probe = run_ffprobe(output_path)
    duration_check = validate_long_source_duration(
        _optional_number(probe.get("container_duration")),
        minimum_minutes=minutes,
    )
    if probe.get("passed") is not True or probe.get("has_audio") is not True:
        raise RuntimeError(f"Long synthetic source failed FFprobe validation: {probe}")
    if duration_check.get("passed") is not True:
        raise RuntimeError("; ".join(str(item) for item in duration_check["errors"]))
    return {
        "path": str(output_path.resolve()),
        "duration_seconds": probe.get("container_duration"),
        "duration_minutes": round(_optional_number(probe.get("container_duration")) / 60.0, 3),
        "width": probe.get("width"),
        "height": probe.get("height"),
        "fps": probe.get("fps"),
        "has_audio": probe.get("has_audio"),
        "audio_codec": probe.get("audio_codec"),
        "video_codec": probe.get("video_codec"),
        "file_size_bytes": output_path.stat().st_size,
        "generation_runtime_seconds": runtime,
        "ffmpeg_process_count": 1,
        "generated_locally": True,
        "external_calls_made": False,
        "copyrighted_content_used": False,
        "probe": probe,
    }


async def _file_chunks(path: Path) -> AsyncIterator[bytes]:
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            yield chunk


async def run_long_local_pipeline(
    media_path: Path,
    *,
    mode: str,
    minimum_minutes: float,
    minimum_clips: int,
    storage_root: Path = DEFAULT_STORAGE_ROOT,
    ffmpeg_binary: str = "ffmpeg",
    ffprobe_binary: str = "ffprobe",
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    render_preset: str = DEFAULT_RENDER_PRESET,
    render_threads: int = DEFAULT_RENDER_THREADS,
    render_filter_threads: int = DEFAULT_FILTER_THREADS,
    source_generation: JsonDict | None = None,
) -> LongVideoFullRenderResultV1:
    """Create a normal project and execute the real durable workflow."""

    started = time.perf_counter()
    probe = run_ffprobe(media_path)
    duration = _optional_number(probe.get("container_duration"))
    duration_check = validate_long_source_duration(
        duration,
        minimum_minutes=minimum_minutes,
    )
    if probe.get("passed") is not True or probe.get("has_audio") is not True:
        return _failure_result(
            mode,
            minimum_minutes,
            f"Input media failed FFprobe validation: {probe}",
            duration=duration,
        )
    if duration_check.get("passed") is not True:
        return _failure_result(
            mode,
            minimum_minutes,
            "; ".join(str(item) for item in duration_check["errors"]),
            duration=duration,
        )

    storage = LocalStorage(root=str(storage_root))
    network_safety = _force_local_only_settings()
    project = await real_e2e.create_local_project(
        media_path,
        storage,
        probe,
        desired_clip_count=minimum_clips,
    )
    renderer = ObservedFfmpegClipRenderer(
        ffmpeg_binary=ffmpeg_binary,
        ffprobe_binary=ffprobe_binary,
        encoder_preset=render_preset,
        encoder_threads=render_threads,
        filter_threads=render_filter_threads,
        render_timeout_seconds=timeout_seconds,
    )
    runtime = real_e2e._build_runtime(
        storage,
        duration_seconds=duration,
        ffmpeg_binary=ffmpeg_binary,
        ffprobe_binary=ffprobe_binary,
        timeout_seconds=timeout_seconds,
        render_preset=render_preset,
        render_threads=render_threads,
        render_filter_threads=render_filter_threads,
        transcription_provider=LongFixtureTranscriptionProvider(storage, duration),
        renderer=renderer,
    )
    runtime_errors: list[str] = []
    runtime_tracebacks: list[JsonDict] = []
    try:
        await runtime.workflow.start(
            project,
            source=f"long_video_full_render:{mode}",
            idempotency_key=f"long_video_full_render:{project.id}",
        )
        await runtime.workflow.wait_for(project.id, timeout=timeout_seconds)
    except Exception as exc:
        runtime_errors.append(f"workflow execution: {type(exc).__name__}: {exc}")
        runtime_tracebacks.append(
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
            runtime_errors.append(f"workflow shutdown: {type(exc).__name__}: {exc}")
            runtime_tracebacks.append(
                {
                    "context": "workflow shutdown",
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "traceback": traceback.format_exc(limit=25),
                }
            )

    result = await inspect_long_video_project(
        project.id,
        mode=mode,
        storage_root=storage_root,
        minimum_minutes=minimum_minutes,
        minimum_clips=minimum_clips,
        ffprobe_binary=ffprobe_binary,
        renderer_observations=renderer.observations(),
        total_runtime_seconds=round(time.perf_counter() - started, 3),
    )
    result.warnings = [
        warning
        for warning in result.warnings
        if "cannot determine whether the original source was user media" not in warning
    ]
    result.errors.extend(runtime_errors)
    result.resource_observations["runtime_exceptions"] = runtime_tracebacks
    result.resource_observations["renderer_resource_profile"] = {
        "encoder_preset": render_preset,
        "encoder_threads": render_threads,
        "filter_threads": render_filter_threads,
        "render_timeout_seconds": timeout_seconds,
        "output_resolution": "1080x1920",
    }
    result.resource_observations["network_safety"] = network_safety
    if source_generation:
        result.resource_observations["source_generation"] = source_generation
        result.resource_observations["ffmpeg_process_count_observed"] = int(
            source_generation.get("ffmpeg_process_count") or 0
        ) + int(result.resource_observations.get("renderer_ffmpeg_process_count") or 0)
    result.warnings.append(
        "Transcript content is a deterministic full-duration fixture; transcription "
        "accuracy and real speech alignment were not tested."
    )
    result.warnings.append(
        "Synthetic proof is not equivalent to rights-cleared creator-footage proof."
        if mode == "synthetic_long"
        else "Local-file mode assumes the caller has rights to process the supplied media."
    )
    result.errors = _unique(result.errors)
    result.warnings = _unique(result.warnings)
    result.passed = bool(result.passed and not result.errors)
    return result


async def inspect_long_video_project(
    project_id: str,
    *,
    mode: str = "project_id",
    storage_root: Path = DEFAULT_STORAGE_ROOT,
    minimum_minutes: float = DEFAULT_MINUTES,
    minimum_clips: int = DEFAULT_MINIMUM_CLIPS,
    ffprobe_binary: str = "ffprobe",
    renderer_observations: JsonDict | None = None,
    total_runtime_seconds: float | None = None,
) -> LongVideoFullRenderResultV1:
    """Inspect persisted artifacts only; this function never starts or repairs work."""

    storage = LocalStorage(root=str(storage_root))
    project = await StorageProjectRepository(storage).get(project_id)
    if project is None:
        return _failure_result(
            mode,
            minimum_minutes,
            "Project does not exist in configured storage.",
            project_id=project_id,
        )

    source_path_value = storage.local_path(project.storage_key)
    source_path = Path(source_path_value) if source_path_value else None
    source_probe = run_ffprobe(source_path) if source_path and source_path.is_file() else {}
    source_duration = _optional_number(source_probe.get("container_duration"))
    duration_check = validate_long_source_duration(
        source_duration,
        minimum_minutes=minimum_minutes,
    )

    workflow = await StorageWorkflowRepository(storage).load(project_id)
    analysis = await StorageAnalysisRepository(storage).load(project_id)
    planning = await StoragePlanningRepository(storage).load(project_id)
    editing = await StorageEditingRepository(storage).load(project_id)
    render_run = await StorageRenderRunRepository(storage).load(project_id)
    manifest = await StorageRenderManifestRepository(storage).load(project_id)
    optimization = await StorageOptimizationRepository(storage).load(project_id)
    canonical_manifest = canonical_render_manifest_path(project_id)
    optimization_manifest = f"optimization/{project_id}/index.json"

    artifact_keys = {
        "ingestion": project.storage_key,
        "analysis": f"analysis/{project_id}/index.json",
        "story": f"story/{project_id}/index.json",
        "virality": f"virality/{project_id}/index.json",
        "planning": f"planning/{project_id}/index.json",
        "editing": f"editing/{project_id}/index.json",
        "rendering": canonical_manifest,
        "optimization": optimization_manifest,
    }
    job_names = {
        "ingestion": "upload",
        "analysis": "cognitive",
        "story": "story",
        "virality": "virality",
        "planning": "planning",
        "editing": "editing",
        "rendering": "rendering",
        "optimization": "optimization",
    }
    stages: list[LongVideoStageResultV1] = []
    for name, job_name in job_names.items():
        job = workflow.job(job_name) if workflow else None
        present = await storage.exists(artifact_keys[name])
        stage_errors = [str(job.error)] if job and job.error else []
        stages.append(
            long_video_stage_result(
                name=name,
                status=job.status.value if job else "missing",
                started_at=job.started_at.isoformat() if job and job.started_at else None,
                finished_at=job.finished_at.isoformat() if job and job.finished_at else None,
                artifact_present=present,
                warnings=list(job.warnings) if job else [],
                errors=stage_errors,
            )
        )

    plans_stage = planning.stage("ranking") if planning else None
    plans = [
        as_dict(item)
        for item in as_list(as_dict(plans_stage.data if plans_stage else {}).get("plans"))
    ]
    timelines_stage = editing.stage("timeline_validation") if editing else None
    timelines = [
        as_dict(item)
        for item in as_list(
            as_dict(timelines_stage.data if timelines_stage else {}).get("timelines")
        )
    ]
    renders = list(manifest.renders) if manifest else []
    publish_stage = optimization.stage("publish_package_creation") if optimization else None
    packages = [
        as_dict(item)
        for item in as_list(as_dict(publish_stage.data if publish_stage else {}).get("packages"))
    ]
    optimized_ids: set[str] = set()
    for package in packages:
        clip_id = str(package.get("clip_id") or "")
        for asset in as_list(package.get("assets")):
            item = as_dict(asset)
            key = str(item.get("storage_key") or "")
            if (
                item.get("kind") == "optimized_mp4"
                and item.get("status") == "available"
                and key
                and await storage.exists(key)
            ):
                optimized_ids.add(clip_id)

    probe_results: list[JsonDict] = []
    accepted_ids: set[str] = set()
    rendered_ids: set[str] = set()
    output_sizes: dict[str, int] = {}
    for render in renders:
        rendered_ids.add(render.clip_id)
        local_value = storage.local_path(render.storage_key)
        local_path = Path(local_value) if local_value else None
        probe = run_ffprobe(local_path) if local_path and local_path.is_file() else {
            "passed": False,
            "errors": ["Rendered MP4 is missing from local storage."],
        }
        normalized = long_video_ffprobe_result(
            clip_id=render.clip_id,
            path_or_key=render.storage_key,
            probe=probe,
            expected_duration=render.duration,
        )
        normalized["local_path"] = str(local_path) if local_path else None
        normalized["file_size_bytes"] = (
            local_path.stat().st_size if local_path and local_path.is_file() else 0
        )
        output_sizes[render.clip_id] = int(normalized["file_size_bytes"])
        if normalized["valid"] and normalized["file_size_bytes"] > MINIMUM_MP4_BYTES:
            accepted_ids.add(render.clip_id)
        elif normalized["file_size_bytes"] <= MINIMUM_MP4_BYTES:
            normalized["errors"].append("Rendered MP4 is too small to be accepted.")
            normalized["valid"] = False
        probe_results.append(normalized)

    rendered_timelines = [
        timeline for timeline in timelines if str(timeline.get("clip_id") or "") in rendered_ids
    ]
    interval_report = analyze_long_video_source_intervals(
        rendered_timelines,
        source_duration=source_duration,
    )
    count_validation = validate_long_video_clip_counts(
        planned=len(plans),
        rendered=len(renders),
        accepted=len(accepted_ids),
        optimized=len(optimized_ids),
        minimum=minimum_clips,
    )

    final_payload = {
        "project_id": project_id,
        "manifest": manifest.to_dict() if manifest else None,
        "clips": [
            {
                "clip_id": render.clip_id,
                "storage_key": render.storage_key,
                "duration": render.duration,
                "download_url": (
                    f"/api/v1/projects/{project_id}/rendering/clips/"
                    f"{render.clip_id}/download"
                ),
            }
            for render in renders
        ],
        "download_urls": [
            f"/api/v1/projects/{project_id}/rendering/clips/{render.clip_id}/download"
            for render in renders
        ],
        "optimization": {
            "status": optimization.status.value if optimization else None,
            "package_count": len(packages),
            "optimized_clip_ids": sorted(optimized_ids),
        },
    }
    payload_validation = validate_long_video_final_payload(
        final_payload,
        minimum_clips=minimum_clips,
    )
    manifest_validation = validate_long_video_manifest_presence(
        render_manifest_present=await storage.exists(canonical_manifest),
        optimization_manifest_present=await storage.exists(optimization_manifest),
    )
    try:
        e2e_report = await real_e2e.inspect_existing_project(
            project_id,
            storage_root=storage_root,
            ffprobe_binary=ffprobe_binary,
            minimum_size_bytes=MINIMUM_MP4_BYTES,
        )
    except Exception as exc:
        e2e_report = {
            "passed": False,
            "api_payload_valid": False,
            "frontend_payload_valid": False,
            "render_manifest_valid": False,
            "optimization_manifest_valid": False,
            "errors": [f"E2E inspection failed: {type(exc).__name__}: {exc}"],
            "warnings": [],
        }

    renderer_metrics = dict(renderer_observations or {})
    analysis_ffmpeg_estimate = 0
    audio_stage = analysis.stage("audio_extraction") if analysis else None
    if audio_stage is not None and audio_stage.status.value == "completed":
        analysis_ffmpeg_estimate += 1
    scene_stage = analysis.stage("scene_detection") if analysis else None
    if scene_stage is not None and scene_stage.status.value == "completed":
        analysis_ffmpeg_estimate += 2
    remaining_work_keys = await storage.list_keys(f"render/{project_id}/work/")
    resource_exhaustion = _resource_exhaustion_detected(
        workflow=workflow,
        render_run=render_run,
        renderer_metrics=renderer_metrics,
    )
    resource_observations = {
        **renderer_metrics,
        "analysis_ffmpeg_process_count_estimate": analysis_ffmpeg_estimate,
        "ffmpeg_process_count_estimate": analysis_ffmpeg_estimate
        + int(renderer_metrics.get("renderer_ffmpeg_process_count") or 0),
        "ffmpeg_process_count_scope": (
            "renderer invocations observed; analysis count inferred from completed stages"
        ),
        "output_file_sizes_bytes": output_sizes,
        "output_total_size_bytes": sum(output_sizes.values()),
        "rendering_sequential": renderer_metrics.get("maximum_concurrent_render_invocations", 1)
        <= 1,
        "storage_render_work_keys_remaining": remaining_work_keys,
        "temp_files_cleaned": not remaining_work_keys,
        "resource_exhaustion_detected": resource_exhaustion
        or renderer_metrics.get("resource_exhaustion_detected") is True,
        "peak_ram": "peak RAM not measured",
        "analysis_signals_v2_present": bool(analysis and analysis.signals_v2()),
        "real_external_calls_made": False,
        "source_path": str(source_path) if source_path else None,
        "inspection_only": mode == "project_id",
        "e2e_inspection": {
            "passed": e2e_report.get("passed"),
            "render_manifest_valid": e2e_report.get("render_manifest_valid"),
            "optimization_manifest_valid": e2e_report.get("optimization_manifest_valid"),
            "api_payload_valid": e2e_report.get("api_payload_valid"),
            "frontend_payload_valid": e2e_report.get("frontend_payload_valid"),
            "optimization_handoff": e2e_report.get("optimization_handoff"),
        },
    }

    warnings = [
        *[str(item) for item in as_list(interval_report.get("warnings"))],
        *[str(item) for item in as_list(e2e_report.get("warnings"))],
    ]
    errors = [
        *[str(item) for item in as_list(duration_check.get("errors"))],
        *[str(item) for item in as_list(count_validation.get("errors"))],
        *[str(item) for item in as_list(interval_report.get("errors"))],
        *[str(item) for item in as_list(payload_validation.get("errors"))],
        *[str(item) for item in as_list(manifest_validation.get("errors"))],
    ]
    for stage in stages:
        if stage.status != "completed":
            errors.append(f"Required stage {stage.name} status is {stage.status}.")
        if not stage.artifact_present:
            errors.append(f"Required stage artifact is missing: {artifact_keys[stage.name]}")
        errors.extend(stage.errors)
    if not analysis or not analysis.signals_v2():
        errors.append("analysis_signals_v2 is missing from the completed analysis artifact.")
    timeline_ids = {str(item.get("clip_id") or "") for item in timelines}
    if rendered_ids != timeline_ids:
        errors.append("Rendered clip IDs do not exactly match edited timeline IDs.")
    if not accepted_ids.issubset(optimized_ids):
        errors.append("Optimization package does not include every accepted rendered clip.")
    for item in probe_results:
        errors.extend(str(error) for error in as_list(item.get("errors")))
    if resource_observations["resource_exhaustion_detected"]:
        errors.append("FFmpeg resource exhaustion was detected.")
    if remaining_work_keys:
        errors.append("Render work files remain after cleanup.")
    if e2e_report.get("render_manifest_valid") is not True:
        errors.append("Canonical render manifest/checkpoint validation failed.")
    if e2e_report.get("optimization_manifest_valid") is not True:
        errors.append("Optimization manifest/package validation failed.")
    if e2e_report.get("api_payload_valid") is not True:
        errors.append("Final API payload inspection failed.")
    if e2e_report.get("frontend_payload_valid") is not True:
        errors.append("Final frontend payload inspection failed.")
    errors.extend(str(item) for item in as_list(e2e_report.get("errors")))
    warnings.extend(_duplicate_hook_warnings(plans))

    started_values = [stage.started_at for stage in stages if stage.started_at]
    finished_values = [stage.finished_at for stage in stages if stage.finished_at]
    result = LongVideoFullRenderResultV1(
        project_id=project_id,
        mode=mode,
        source_duration_seconds=source_duration,
        source_duration_minutes=(
            round(source_duration / 60.0, 3) if source_duration is not None else None
        ),
        minimum_required_minutes=minimum_minutes,
        pipeline_started_at=min(started_values) if started_values else None,
        pipeline_finished_at=max(finished_values) if finished_values else None,
        total_runtime_seconds=total_runtime_seconds,
        stages=stages,
        planned_clip_count=len(plans),
        edited_clip_count=len(timelines),
        rendered_clip_count=len(renders),
        accepted_mp4_count=len(accepted_ids),
        optimized_clip_count=len(optimized_ids),
        duplicate_source_intervals_detected=bool(
            interval_report.get("duplicate_source_intervals_detected")
        ),
        source_interval_coverage=interval_report,
        render_manifest_present=await storage.exists(canonical_manifest),
        optimization_manifest_present=await storage.exists(optimization_manifest),
        final_payload_valid=bool(
            payload_validation.get("passed")
            and e2e_report.get("api_payload_valid")
            and e2e_report.get("frontend_payload_valid")
        ),
        artifact_paths={
            **artifact_keys,
            "source": project.storage_key,
        },
        final_payload=final_payload,
        ffprobe_results=probe_results,
        av_delta_results=[
            {
                "clip_id": item.get("clip_id"),
                "audio_video_delta_seconds": item.get("av_delta_seconds"),
                "tolerance_seconds": LONG_VIDEO_AV_TOLERANCE_SECONDS,
                "passed": bool(
                    item.get("av_delta_seconds") is not None
                    and abs(float(item["av_delta_seconds"]))
                    <= LONG_VIDEO_AV_TOLERANCE_SECONDS
                ),
            }
            for item in probe_results
        ],
        resource_observations=resource_observations,
        warnings=_unique(warnings),
        errors=_unique(errors),
    )
    result.passed = bool(
        duration_check.get("passed")
        and count_validation.get("passed")
        and interval_report.get("passed")
        and result.render_manifest_present
        and result.optimization_manifest_present
        and result.final_payload_valid
        and len(accepted_ids) >= minimum_clips
        and all(item.get("valid") for item in probe_results)
        and not result.resource_observations["resource_exhaustion_detected"]
        and not result.errors
    )
    return result


def _duplicate_hook_warnings(plans: list[JsonDict]) -> list[str]:
    normalized = [
        " ".join(str(plan.get("hook_line") or "").lower().split())
        for plan in plans
        if plan.get("hook_line")
    ]
    if len(normalized) != len(set(normalized)):
        return ["Duplicate hook lines were selected across long-video clips."]
    return []


def _force_local_only_settings() -> JsonDict:
    settings = get_settings().trend_research
    settings.enabled = True
    settings.provider = "evergreen"
    settings.allow_official_source_refresh = False
    settings.allow_configured_web_search = False
    settings.allow_live_web_provider = False
    settings.force_live_refresh = False
    settings.configured_search_endpoint = None
    settings.web_search_endpoint = None
    settings.web_search_api_key = None
    return {
        "external_access_allowed": False,
        "trend_provider": settings.provider,
        "official_refresh_allowed": settings.allow_official_source_refresh,
        "configured_web_search_allowed": settings.allow_configured_web_search,
        "live_web_provider_allowed": settings.allow_live_web_provider,
    }


def _resource_exhaustion_detected(
    *,
    workflow: Any,
    render_run: Any,
    renderer_metrics: JsonDict,
) -> bool:
    if renderer_metrics.get("resource_exhaustion_detected") is True:
        return True
    evidence: list[str] = []
    for job in getattr(workflow, "jobs", []) or []:
        evidence.extend(
            str(value)
            for value in (
                getattr(job, "error", None),
                *list(getattr(job, "warnings", []) or []),
                *list(getattr(job, "logs", []) or []),
            )
            if value
        )
    for stage in getattr(render_run, "stages", []) or []:
        evidence.extend(
            str(value)
            for value in (
                getattr(stage, "error", None),
                getattr(stage, "reason", None),
                *list(getattr(stage, "logs", []) or []),
            )
            if value
        )
        for skipped in as_list(as_dict(getattr(stage, "data", {})).get("skipped")):
            if as_dict(skipped).get("resource_exhaustion") is True:
                return True
    text = " ".join(evidence).lower()
    return any(
        marker in text
        for marker in (
            "winerror 1450",
            "resource exhausted",
            "resource_exhausted",
            "cannot allocate memory",
            "not enough memory",
            "insufficient system resources",
        )
    )


def _failure_result(
    mode: str,
    minimum_minutes: float,
    error: str,
    *,
    project_id: str | None = None,
    duration: float | None = None,
) -> LongVideoFullRenderResultV1:
    return LongVideoFullRenderResultV1(
        project_id=project_id,
        mode=mode,
        source_duration_seconds=duration,
        source_duration_minutes=round(duration / 60.0, 3) if duration else None,
        minimum_required_minutes=minimum_minutes,
        resource_observations={"peak_ram": "peak RAM not measured"},
        errors=[error],
    )


def _optional_number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if value))


async def run_selected_mode(args: argparse.Namespace) -> LongVideoFullRenderResultV1 | JsonDict:
    if args.self_check:
        return long_video_self_check(
            storage_root=args.storage_root,
            report_dir=args.report_dir,
            ffmpeg_binary=args.ffmpeg_binary,
            ffprobe_binary=args.ffprobe_binary,
        )
    if args.project_id:
        return await inspect_long_video_project(
            str(args.project_id),
            mode="project_id",
            storage_root=args.storage_root,
            minimum_minutes=args.minimum_minutes,
            minimum_clips=args.min_clips,
            ffprobe_binary=args.ffprobe_binary,
        )
    if args.synthetic_long:
        source_path = args.report_dir / "runtime" / "synthetic_long_source.mp4"
        source_generation = generate_long_synthetic_media(
            source_path,
            minutes=args.minutes,
            ffmpeg_binary=args.ffmpeg_binary,
            timeout_seconds=args.source_generation_timeout_seconds,
        )
        return await run_long_local_pipeline(
            source_path,
            mode="synthetic_long",
            minimum_minutes=args.minimum_minutes,
            minimum_clips=args.min_clips,
            storage_root=args.storage_root,
            ffmpeg_binary=args.ffmpeg_binary,
            ffprobe_binary=args.ffprobe_binary,
            timeout_seconds=args.timeout_seconds,
            render_preset=args.render_preset,
            render_threads=args.render_threads,
            render_filter_threads=args.render_filter_threads,
            source_generation=source_generation,
        )
    local_file = Path(args.local_file)
    if not local_file.is_file():
        return _failure_result(
            "local_file",
            args.minimum_minutes,
            f"Local rights-cleared video does not exist: {local_file}",
        )
    return await run_long_local_pipeline(
        local_file.resolve(),
        mode="local_file",
        minimum_minutes=args.minimum_minutes,
        minimum_clips=args.min_clips,
        storage_root=args.storage_root,
        ffmpeg_binary=args.ffmpeg_binary,
        ffprobe_binary=args.ffprobe_binary,
        timeout_seconds=args.timeout_seconds,
        render_preset=args.render_preset,
        render_threads=args.render_threads,
        render_filter_threads=args.render_filter_threads,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--self-check", action="store_true")
    modes.add_argument("--synthetic-long", action="store_true")
    modes.add_argument("--local-file", type=Path)
    modes.add_argument("--project-id")
    parser.add_argument("--minutes", type=float, default=DEFAULT_MINUTES)
    parser.add_argument(
        "--minimum-minutes",
        type=float,
        default=DEFAULT_MINUTES,
        help="Explicitly lower only for development with a shorter local file.",
    )
    parser.add_argument("--min-clips", type=int, default=DEFAULT_MINIMUM_CLIPS)
    parser.add_argument("--storage-root", type=Path, default=DEFAULT_STORAGE_ROOT)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--ffmpeg-binary", default="ffmpeg")
    parser.add_argument("--ffprobe-binary", default="ffprobe")
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--source-generation-timeout-seconds", type=float, default=1200.0)
    parser.add_argument(
        "--render-preset",
        choices=("ultrafast", "superfast", "veryfast", "faster", "fast", "medium"),
        default=DEFAULT_RENDER_PRESET,
    )
    parser.add_argument("--render-threads", type=int, default=DEFAULT_RENDER_THREADS)
    parser.add_argument("--render-filter-threads", type=int, default=DEFAULT_FILTER_THREADS)
    return parser


def _validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.minutes <= 0:
        parser.error("--minutes must be positive")
    if args.minimum_minutes <= 0:
        parser.error("--minimum-minutes must be positive")
    if args.min_clips < 1:
        parser.error("--min-clips must be at least 1")
    if args.timeout_seconds <= 0 or args.source_generation_timeout_seconds <= 0:
        parser.error("timeout values must be positive")
    if args.render_threads < 1 or args.render_filter_threads < 1:
        parser.error("render thread limits must be at least 1")


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    _validate_args(parser, args)
    args.report_dir = validated_long_video_report_dir(
        args.report_dir,
        workspace_root=ROOT,
    )
    try:
        selected = asyncio.run(run_selected_mode(args))
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        mode = (
            "self_check"
            if args.self_check
            else "project_id"
            if args.project_id
            else "synthetic_long"
            if args.synthetic_long
            else "local_file"
        )
        selected = _failure_result(
            mode,
            args.minimum_minutes,
            f"{type(exc).__name__}: {exc}",
            project_id=str(args.project_id) if args.project_id else None,
        )
    if isinstance(selected, LongVideoFullRenderResultV1):
        paths = write_long_video_full_render_report(
            selected,
            args.report_dir,
            workspace_root=ROOT,
        )
        output = {
            "passed": selected.passed,
            "mode": selected.mode,
            "project_id": selected.project_id,
            "source_duration_seconds": selected.source_duration_seconds,
            "planned_clip_count": selected.planned_clip_count,
            "rendered_clip_count": selected.rendered_clip_count,
            "accepted_mp4_count": selected.accepted_mp4_count,
            "optimized_clip_count": selected.optimized_clip_count,
            "reports": paths,
            "warnings": selected.warnings,
            "errors": selected.errors,
        }
        passed = selected.passed
    else:
        self_check_path = args.report_dir / "long_video_full_render_self_check.json"
        args.report_dir.mkdir(parents=True, exist_ok=True)
        self_check_path.write_text(json.dumps(selected, indent=2) + "\n", encoding="utf-8")
        output = {**selected, "report": str(self_check_path)}
        passed = selected.get("passed") is True
    print(json.dumps(output, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
