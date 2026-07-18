"""Tests for the Rendering Engine: pipeline, stages, manifest, downloads, chain.

These verify the *honest* contract of render execution:
- With no working renderer (FFmpeg absent - the real environment), the
  plan/validation stages run for real, but the execution stages report
  ``UNAVAILABLE`` with a precise reason, no manifest is published, and the
  Optimization Engine is not triggered. Nothing is fabricated.
- With a working renderer (a test-double :class:`StubClipRenderer` that writes a
  real file - dependency injection, not "mocked rendering in production"), the
  engine renders real files, verifies them, publishes a real manifest (with a
  checksum over the actual bytes) at ``render/{id}/index.json``, and the manifest
  is exactly what the Optimization Engine's repository reads - proving the
  producer/consumer contract end to end.
- Work persists; runs resume; single stages re-run; cancellation is cooperative.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from olympus.api.dependencies import (
    optimization_service_provider,
    project_service_provider,
    rendering_service_provider,
    storage_provider,
)
from olympus.data.repositories import (
    StorageAnalysisRepository,
    StorageEditingRepository,
    StorageOptimizationRepository,
    StoragePlanningRepository,
    StorageProjectRepository,
    StorageRenderManifestRepository,
    StorageRenderRunRepository,
    StorageStoryRepository,
    StorageViralityRepository,
)
from olympus.data.storage.local import LocalStorage
from olympus.domain.contracts.rendering import (
    ClipRenderer,
    ClipRenderOutput,
    ClipRenderSpec,
    RendererAvailability,
)
from olympus.domain.contracts.storage import StoragePort
from olympus.domain.entities.analysis import Analysis, AnalysisStatus, StageResult, StageStatus
from olympus.domain.entities.planning import (
    ClipPlanningAnalysis,
    PlanningStageResult,
    PlanningStageStatus,
    PlanningStatus,
)
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.domain.entities.render_pipeline import (
    RENDER_STAGE_ORDER,
    RenderRunStatus,
    RenderStageStatus,
)
from olympus.editing import build_default_editing_analyzers
from olympus.editing.pipeline import EditingPipeline
from olympus.rendering import RenderPipeline, build_default_render_stages
from olympus.rendering import assets as render_assets
from olympus.rendering import command as render_command
from olympus.rendering.ffmpeg_renderer import FfmpegClipRenderer, _render_metadata
from olympus.services.optimization import OptimizationService
from olympus.services.projects import ProjectService
from olympus.services.rendering import RenderingService
from olympus.utils import new_id, utc_now

TRANSCRIPT = [
    {
        "start": 0.0,
        "end": 7.0,
        "speaker": "spk_0",
        "text": "Why do most people fail at this? I struggled for years.",
    },
    {
        "start": 7.0,
        "end": 16.0,
        "speaker": "spk_0",
        "text": "Honestly, um, I tried like every approach and nothing worked.",
    },
    {
        "start": 16.0,
        "end": 30.0,
        "speaker": "spk_0",
        "text": "The real problem was treating every task as equally urgent.",
    },
    {
        "start": 30.0,
        "end": 45.0,
        "speaker": "spk_0",
        "text": "But then I discovered time blocking and it changed everything.",
    },
]

# A real (small) byte payload standing in for an encoded MP4 in storage.
_FAKE_MP4 = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isomSTUB-RENDER-FIXTURE-BYTES"


def test_video_filter_escapes_windows_subtitle_path_for_ffmpeg() -> None:
    rendered = render_command.video_filter({}, 1080, 1920, srt_path=r"D:\Olympus\work\captions.srt")

    assert "subtitles='D\\:/Olympus/work/captions.srt'" in rendered
    assert r"\Olympus" not in rendered


def test_video_filter_preserves_short_format_when_zooming() -> None:
    timeline = {"tracks": [{"kind": "video", "events": [{"type": "zoom_in", "start": 0.0}]}]}

    rendered = render_command.video_filter(timeline, 1080, 1920, fps=30)

    assert "zoompan=z=" in rendered
    assert "s=1080x1920:fps=30" in rendered
    assert "eq=contrast" in rendered
    assert "unsharp" in rendered


def test_video_filter_consumes_face_tracking_plan() -> None:
    timeline = {
        "metadata": {
            "face_tracking_plan": {
                "mode": "single_face_tracking",
                "crop_keyframes": [
                    {"time": 0.0, "x_center": 0.35, "y_center": 0.42, "confidence": 0.8},
                    {"time": 2.0, "x_center": 0.55, "y_center": 0.44, "confidence": 0.85},
                ],
            }
        }
    }

    rendered = render_command.video_filter(timeline, 1080, 1920, fps=30)

    assert "crop=1080:1920:x=" in rendered
    assert "between(t,0.000,2.000)" in rendered
    assert render_command.crop_op(timeline)["face_tracking_applied"] is True


def test_invalid_face_tracking_falls_back_to_center_crop() -> None:
    timeline = {
        "metadata": {
            "face_tracking_plan": {
                "mode": "center_fallback",
                "fallback_reason": "low_confidence",
                "crop_keyframes": [],
            }
        }
    }

    rendered = render_command.video_filter(timeline, 1080, 1920, fps=30)

    assert "crop=1080:1920," in rendered
    assert "crop=1080:1920:x=" not in rendered


def test_ass_caption_generation_highlights_words() -> None:
    timeline = {
        "metadata": {
            "editing_v2": {
                "caption_style": {"style": "motivational_cinematic"},
            }
        }
    }
    ass = render_command.build_ass(
        [
            {
                "start": 0.0,
                "end": 1.4,
                "text": "never forget this truth",
                "highlighted_words": ["never", "truth"],
            }
        ],
        timeline,
    )

    assert "[V4+ Styles]" in ass
    assert "Dialogue:" in ass
    assert "NEVER" in ass
    assert r"\c&H0032F4FF&" in ass


def test_audio_video_filtergraph_includes_v2_effects() -> None:
    timeline = {
        "duration": 8.0,
        "tracks": [
            {
                "kind": "video",
                "events": [{"type": "hook_punch_zoom", "start": 0.0, "end": 0.8, "scale": 1.16}],
            }
        ],
        "metadata": {
            "editing_v2": {
                "video_enhancement_plan": {"profile": "high_energy"},
                "voice_enhancement_plan": {"filters": ["highpass", "loudnorm"]},
            }
        },
    }

    graph = render_command.filter_complex(timeline, 1080, 1920, 30, None)

    assert "zoompan=z=" in graph
    assert "eq=contrast" in graph
    assert "highpass=f=80" in graph
    assert "loudnorm=I=-16" in graph


def test_ffmpeg_command_uses_exact_trim_reset_and_no_shortest() -> None:
    timeline = {
        "source_start": 3.0,
        "source_end": 11.0,
        "duration": 8.0,
        "tracks": [{"kind": "video", "events": []}, {"kind": "caption", "events": []}],
        "metadata": {},
    }

    args = render_command.build_ffmpeg_command(
        binary="ffmpeg",
        source_path="source.mp4",
        output_path="out.mp4",
        timeline=timeline,
        width=1080,
        height=1920,
        fps=30,
        video_bitrate_kbps=4500,
        audio_bitrate_kbps=160,
    )
    graph = args[args.index("-filter_complex") + 1]

    assert "trim=start=3.000:end=11.000,setpts=PTS-STARTPTS" in graph
    assert "atrim=start=3.000:end=11.000,asetpts=PTS-STARTPTS" in graph
    assert "amix=inputs=1:duration=first" in graph
    assert "-shortest" not in args
    assert "-ss" not in args
    assert "-to" not in args
    assert "-t" not in args


def test_asset_resolution_is_honest_when_missing(tmp_path: Path) -> None:
    timeline = {"metadata": {"v2_metadata": {"content_category": "motivational"}}}

    resolved = render_assets.resolve_assets(timeline, tmp_path)

    assert resolved["music"]["mixed"] is False
    assert resolved["music"]["status"] == "unavailable"
    assert resolved["sfx"]["mixed_count"] == 0


def test_static_sfx_assets_are_rejected_by_default(tmp_path: Path) -> None:
    assets = tmp_path
    (assets / "sfx").mkdir()
    (assets / "sfx" / "static.wav").write_bytes(b"static")
    (assets / "sfx" / "pop.wav").write_bytes(b"pop")
    (assets / "manifest.json").write_text(
        json.dumps(
            {
                "assets": [
                    {
                        "id": "sfx_static",
                        "filename": "sfx/static.wav",
                        "type": "sfx",
                        "categories": ["whoosh", "noise"],
                        "usage_allowed": True,
                        "noise_like": True,
                        "safe_default": False,
                    },
                    {
                        "id": "sfx_pop",
                        "filename": "sfx/pop.wav",
                        "type": "sfx",
                        "categories": ["pop", "caption"],
                        "usage_allowed": True,
                        "noise_like": False,
                        "safe_default": True,
                        "recommended_gain_db": -15,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    timeline = {
        "duration": 8.0,
        "tracks": [
            {
                "kind": "markers",
                "events": [{"type": "sfx_pop", "start": 0.2, "reason": "caption accent"}],
            }
        ],
    }

    selected = render_assets.select_sfx(timeline, assets)

    assert selected["mixed_count"] == 1
    assert selected["events"][0]["asset_id"] == "sfx_pop"
    assert selected["safety_applied"] is True
    assert "rejected_noise_like_sfx" in selected["skipped_reasons"]


def test_generated_installer_does_not_create_static_whoosh() -> None:
    source = Path("tools/install_editing_assets.py").read_text(encoding="utf-8")

    assert "anoisesrc" not in source
    assert "noise_like" in source
    assert "sine-envelope whoosh" in source


def test_music_gain_policy_is_audible_but_speech_first(tmp_path: Path) -> None:
    assets = tmp_path
    (assets / "music").mkdir()
    (assets / "music" / "bed.wav").write_bytes(b"music")
    (assets / "manifest.json").write_text(
        json.dumps(
            {
                "assets": [
                    {
                        "id": "music_bed",
                        "filename": "music/bed.wav",
                        "type": "music",
                        "categories": ["educational", "talking_head"],
                        "duration": 36.0,
                        "energy_level": 0.4,
                        "folder_type": "generated",
                        "usage_allowed": True,
                        "license": "project_generated_safe",
                        "license_verified": True,
                        "safe_default": True,
                        "speech_safe": True,
                        "has_vocals": False,
                        "loopable": True,
                        "source": "generated_validation_asset",
                        "quality_status": "passed",
                        "auto_select_allowed": True,
                        "recommended_gain_db": -30,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    selected = render_assets.select_music(
        {"duration": 9.0, "metadata": {"v2_metadata": {"content_category": "educational"}}},
        assets,
    )

    assert selected["mixed"] is True
    assert selected["gain_db"] == -24.0
    assert selected["looped"] is False
    assert selected["duration_used"] == 9.0


def test_render_metadata_stores_sync_validation_warning() -> None:
    metadata = _render_metadata(
        {
            "duration": 8.0,
            "source_start": 0.0,
            "source_end": 8.0,
            "source_window_v1": {
                "contract_version": "1",
                "requested_start_seconds": 0.2,
                "requested_end_seconds": 7.8,
                "repaired_start_seconds": 0.0,
                "repaired_end_seconds": 8.0,
                "duration_seconds": 8.0,
                "preroll_seconds": 0.2,
                "postroll_seconds": 0.2,
                "boundary_repair_applied": True,
                "warnings": [],
            },
            "metadata": {},
        },
        logs=[],
        probe={
            "format": {"duration": "7.600"},
            "streams": [
                {"codec_type": "video", "duration": "7.600"},
                {"codec_type": "audio", "duration": "7.200"},
            ],
        },
    )

    assert metadata["sync_validation"]["passed"] is False
    assert metadata["duration_validation"]["passed"] is False
    assert metadata["sync_validation"]["audio_video_delta"] == -0.4
    assert metadata["timeline"]["requested_start_seconds"] == 0.2
    assert metadata["timeline"]["repaired_end_seconds"] == 8.0
    assert metadata["timeline"]["sync_validation"] == metadata["sync_validation"]


def test_render_metadata_preserves_unified_clip_intelligence() -> None:
    metadata = _render_metadata(
        {
            "clip_id": "clip_a",
            "plan_id": "clip_a",
            "duration": 8.0,
            "source_start": 10.0,
            "source_end": 18.0,
            "metadata": {
                "editing_v2": {
                    "editing_style": "podcast_talking_head",
                    "caption_style": {"highlight_words": ["constraints"]},
                },
                "unified_clip_intelligence": {
                    "clip_id": "clip_a",
                    "story_id": "story_a",
                    "story": {"story_shape": "problem_solution"},
                    "virality": {"hook_line": "Why do people fail?"},
                    "trend_research": {
                        "snapshot_id": "trend_test",
                        "research_status": "skipped",
                        "cache_status": "fallback",
                        "fallback_used": True,
                    },
                },
            },
        },
        logs=[],
        probe={
            "format": {"duration": "8.000"},
            "streams": [
                {"codec_type": "video", "duration": "8.000"},
                {"codec_type": "audio", "duration": "8.000"},
            ],
        },
    )

    unified = metadata["unified_clip_intelligence"]
    assert unified["story_id"] == "story_a"
    assert unified["story"]["story_shape"] == "problem_solution"
    assert unified["virality"]["hook_line"] == "Why do people fail?"
    assert unified["trend_research"]["snapshot_id"] == "trend_test"
    assert unified["rendering"]["sync_validation"]["passed"] is True


def test_command_includes_music_and_sfx_inputs_when_assets_resolved(tmp_path: Path) -> None:
    music = tmp_path / "music.wav"
    sfx = tmp_path / "hit.wav"
    music.write_bytes(b"music")
    sfx.write_bytes(b"sfx")
    timeline = {
        "source_start": 0.0,
        "source_end": 8.0,
        "duration": 8.0,
        "tracks": [{"kind": "video", "events": []}, {"kind": "caption", "events": []}],
        "metadata": {
            "render_assets_v2": {
                "music": {"mixed": True, "path": str(music), "gain_db": -24},
                "sfx": {
                    "mixed_count": 1,
                    "events": [{"mixed": True, "path": str(sfx), "time": 0.2, "gain_db": -12}],
                },
            }
        },
    }

    args = render_command.build_ffmpeg_command(
        binary="ffmpeg",
        source_path="source.mp4",
        output_path="out.mp4",
        timeline=timeline,
        width=1080,
        height=1920,
        fps=30,
        video_bitrate_kbps=4500,
        audio_bitrate_kbps=160,
    )

    assert str(music) in args
    assert str(sfx) in args
    assert "-filter_complex" in args
    graph = args[args.index("-filter_complex") + 1]
    assert "amix=inputs=3" in graph
    assert "duration=first" in graph
    assert "apad,atrim=0:8.000" in graph


class StubClipRenderer(ClipRenderer):
    """A test renderer that writes a real file (exercises the COMPLETED path).

    This is a test double injected via the renderer abstraction - NOT a
    production renderer. It writes real bytes to storage so the pipeline's
    verification, manifest (with checksum), download, and the Rendering ->
    Optimization chain can all be exercised without FFmpeg.
    """

    name = "stub"

    def availability(self) -> RendererAvailability:
        return RendererAvailability(available=True, renderer=self.name, version="test")

    async def render_clip(self, spec: ClipRenderSpec, storage: StoragePort) -> ClipRenderOutput:
        await storage.put(spec.output_key, _FAKE_MP4, content_type="video/mp4")
        duration = float(spec.timeline.get("duration") or 0.0)
        return ClipRenderOutput(
            clip_id=spec.clip_id,
            output_key=spec.output_key,
            width=spec.width,
            height=spec.height,
            duration=duration,
            fps=float(spec.fps),
            video_codec="h264",
            audio_codec="aac",
            has_audio=True,
            bitrate_kbps=spec.video_bitrate_kbps,
            audio_sample_rate=48000,
            size_bytes=len(_FAKE_MP4),
            logs=[f"[stub] rendered {spec.clip_id} at {spec.width}x{spec.height}"],
            metadata={
                "music_mixed": False,
                "sfx_mixed_count": 0,
                "voice_enhancement_applied": True,
                "video_enhancement_applied": True,
            },
        )


class CaptionProofStubRenderer(StubClipRenderer):
    """A stub whose metadata proves the pre-manifest caption render steps."""

    async def render_clip(self, spec: ClipRenderSpec, storage: StoragePort) -> ClipRenderOutput:
        output = await super().render_clip(spec, storage)
        output.metadata.update(
            {
                "caption_render_validation": {
                    "captions_planned": True,
                    "ass_file_exists": True,
                    "ass_event_count": 2,
                    "ass_styles_count": 6,
                    "ffmpeg_filter_present": True,
                    "render_manifest_confirmed": False,
                    "output_exists": True,
                    "passed": True,
                    "warnings": [],
                },
                "caption_intelligence_v2": {
                    "style_decision": {"caption_style": "clean_podcast"},
                    "validation": {
                        "captions_planned": True,
                        "captions_rendered": True,
                        "render_manifest_confirmed": False,
                        "passed": True,
                        "warnings": [],
                    },
                },
                "render_effects_v2": {
                    "captions": {
                        "included": True,
                        "validation": {"passed": True},
                    }
                },
            }
        )
        return output


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(root=str(tmp_path))


@pytest.fixture
def run_repo(storage: LocalStorage) -> StorageRenderRunRepository:
    return StorageRenderRunRepository(storage)


@pytest.fixture
def manifest_store(storage: LocalStorage) -> StorageRenderManifestRepository:
    return StorageRenderManifestRepository(storage)


def _project() -> Project:
    now = utc_now()
    return Project(
        id=new_id("proj"),
        name="Render Test",
        source_filename="clip.mp4",
        storage_key="uploads/u1/source.mp4",
        size_bytes=1024,
        video_format="mp4",
        content_type="video/mp4",
        duration_seconds=60.0,
        width=1920,
        height=1080,
        status=ProjectStatus.ANALYZED,
        created_at=now,
        updated_at=now,
    )


def _analysis() -> Analysis:
    now = utc_now()
    return Analysis(
        project_id="placeholder",
        pipeline_version="1",
        status=AnalysisStatus.COMPLETED,
        created_at=now,
        updated_at=now,
        stages=[
            StageResult(
                stage="video_inspection",
                status=StageStatus.COMPLETED,
                version="1",
                data={"duration_seconds": 60.0, "width": 1920, "height": 1080, "fps": 30},
            ),
            StageResult(
                stage="speech_transcription",
                status=StageStatus.COMPLETED,
                version="1",
                data={"language": "en", "confidence": 0.9, "segments": TRANSCRIPT},
            ),
        ],
    )


def _planning() -> ClipPlanningAnalysis:
    now = utc_now()
    plans = _plans(1)
    plans[0]["id"] = "clip_a"
    return ClipPlanningAnalysis(
        project_id="placeholder",
        pipeline_version="1",
        status=PlanningStatus.COMPLETED,
        created_at=now,
        updated_at=now,
        stages=[
            PlanningStageResult(
                stage="ranking",
                status=PlanningStageStatus.COMPLETED,
                data={"plan_count": len(plans), "plans": plans},
            )
        ],
    )


def _planning_many(count: int) -> ClipPlanningAnalysis:
    planning = _planning()
    plans = _plans(count)
    planning.stages[0].data = {"plan_count": len(plans), "plans": plans}
    return planning


def _plans(count: int) -> list[dict[str, object]]:
    plans: list[dict[str, object]] = []
    for index in range(count):
        start = float(index * 12)
        end = start + 10.0
        plans.append(
            {
                "id": f"clip_{index}",
                "rank": index + 1,
                "source_video": {"filename": "clip.mp4", "storage_key": "uploads/u1/source.mp4"},
                "start": start,
                "end": end,
                "duration": end - start,
                "start_frame": round(start * 30),
                "end_frame": round(end * 30),
                "fps": 30,
                "scores": {"hook": 0.7},
                "quality_score": 0.72,
                "confidence": 0.6,
                "explanation": "test clip",
                "evidence": [],
                "alternatives": [],
                "blueprint": {
                    "opening_hook": {
                        "text": "Why do people fail?",
                        "timestamp": start,
                        "evidence": "q",
                    },
                    "pacing": {"value": "fast", "reason": "dense"},
                    "aspect_ratio": {"value": "9:16", "reason": "vertical"},
                    "subtitle_style": {"style": "karaoke", "reason": "fast"},
                    "zoom_suggestions": [{"timestamp": start + 5.0, "reason": "emphasis"}],
                    "jump_cuts": [{"timestamp": start + 7.0, "reason": "filler removal"}],
                    "scene_cuts": {"cuts": [], "note": "none"},
                    "speaker_switches": {"switches": [], "note": "single"},
                },
            }
        )
    return plans


async def _editing(storage: LocalStorage, analysis: Analysis, planning: ClipPlanningAnalysis):
    return await EditingPipeline(
        build_default_editing_analyzers(), StorageEditingRepository(storage)
    ).run(_project(), storage, analysis=analysis, planning=planning)


def _render_pipeline(run_repo: StorageRenderRunRepository) -> RenderPipeline:
    return RenderPipeline(build_default_render_stages(), run_repo)


# --------------------------------------------------------------------------- #
# Honest behaviour without a working renderer (FFmpeg absent)
# --------------------------------------------------------------------------- #
async def test_pipeline_runs_all_stages(
    storage: LocalStorage, run_repo: StorageRenderRunRepository, manifest_store
) -> None:
    analysis, planning = _analysis(), _planning()
    editing = await _editing(storage, analysis, planning)
    run = await _render_pipeline(run_repo).run(
        _project(), storage, FfmpegClipRenderer(), manifest_store, editing=editing
    )
    assert [s.stage for s in run.stages] == list(RENDER_STAGE_ORDER)
    assert all(s.is_terminal for s in run.stages)


async def test_ffmpeg_absent_is_honest(
    storage: LocalStorage, run_repo: StorageRenderRunRepository, manifest_store
) -> None:
    if shutil.which("ffmpeg") is not None:
        pytest.skip("Validates the FFmpeg-absent path; FFmpeg is installed in this environment.")
    analysis, planning = _analysis(), _planning()
    editing = await _editing(storage, analysis, planning)
    project = _project()
    await storage.put(project.storage_key, _FAKE_MP4, content_type="video/mp4")

    run = await _render_pipeline(run_repo).run(
        project, storage, FfmpegClipRenderer(), manifest_store, editing=editing
    )
    # Plan + validation stages run for real.
    for name in (
        "load_timeline",
        "validate_timeline",
        "validate_source_assets",
        "build_video_timeline",
        "apply_jump_cuts",
        "apply_zooms",
        "apply_captions",
        "audio_mixing",
        "cleanup_temporary_files",
        "final_validation",
    ):
        assert run.stage(name).status is RenderStageStatus.COMPLETED, name
    # Execution stages are honestly UNAVAILABLE with an FFmpeg reason.
    for name in (
        "render_preview",
        "full_resolution_render",
        "render_verification",
        "generate_render_manifest",
    ):
        s = run.stage(name)
        assert s.status is RenderStageStatus.UNAVAILABLE, name
    assert "FFmpeg" in (run.stage("full_resolution_render").reason or "")
    # No manifest is fabricated.
    assert await manifest_store.load(project.id) is None
    final = run.stage("final_validation").data
    assert final["rendered"] is False
    assert final["manifest_written"] is False
    assert "full_resolution_render" in {u["stage"] for u in final["unavailable_stages"]}


async def test_apply_stages_translate_real_timeline(
    storage: LocalStorage, run_repo: StorageRenderRunRepository, manifest_store
) -> None:
    analysis, planning = _analysis(), _planning()
    editing = await _editing(storage, analysis, planning)
    run = await _render_pipeline(run_repo).run(
        _project(), storage, FfmpegClipRenderer(), manifest_store, editing=editing
    )
    jump = run.stage("apply_jump_cuts").data
    assert "clips" in jump and isinstance(jump["total"], int)
    captions = run.stage("apply_captions").data["clips"][0]
    assert "caption_count" in captions
    crops = run.stage("apply_crops").data["clips"][0]["crop"]
    assert crops["target_aspect"]


async def test_load_timeline_unavailable_without_editing(
    storage: LocalStorage, run_repo: StorageRenderRunRepository, manifest_store
) -> None:
    run = await _render_pipeline(run_repo).run(
        _project(), storage, FfmpegClipRenderer(), manifest_store, editing=None
    )
    assert run.stage("load_timeline").status is RenderStageStatus.UNAVAILABLE


# --------------------------------------------------------------------------- #
# Real render path via the stub renderer (produces a real file + manifest)
# --------------------------------------------------------------------------- #
async def test_stub_render_produces_manifest_and_files(
    storage: LocalStorage, run_repo: StorageRenderRunRepository, manifest_store
) -> None:
    analysis, planning = _analysis(), _planning()
    editing = await _editing(storage, analysis, planning)
    project = _project()
    await storage.put(project.storage_key, _FAKE_MP4, content_type="video/mp4")

    run = await _render_pipeline(run_repo).run(
        project, storage, StubClipRenderer(), manifest_store, editing=editing
    )
    assert run.status is RenderRunStatus.COMPLETED
    fr = run.stage("full_resolution_render")
    assert fr.status is RenderStageStatus.COMPLETED
    assert fr.data["rendered_count"] == 1
    assert await storage.exists(f"render/{project.id}/clips/clip_a.mp4")

    verification = run.stage("render_verification")
    assert verification.status is RenderStageStatus.COMPLETED
    assert verification.data["valid"] is True

    gen = run.stage("generate_render_manifest")
    assert gen.status is RenderStageStatus.COMPLETED
    assert gen.data["written"] is True and gen.data["clip_count"] == 1

    # The manifest is real, with a checksum over the actual bytes.
    manifest = await manifest_store.load(project.id)
    assert manifest is not None and len(manifest.renders) == 1
    rv = manifest.renders[0]
    assert rv.checksum and rv.checksum.startswith("sha256:")
    assert rv.subtitles_included is True
    assert rv.metadata["voice_enhancement_applied"] is True
    assert rv.metadata["video_enhancement_applied"] is True
    assert rv.metadata["music_mixed"] is False
    assert rv.metadata["copyright_safety_v2"]["overall"]["risk_level"] == "unknown"
    assert rv.metadata["copyright_safety_v2"]["manual_review"]["required"] is True
    assert rv.metadata["copyright_safety_v2"]["overall"]["disclaimer"] == (
        "This is a technical risk assessment, not legal advice."
    )
    assert rv.metadata["unified_clip_intelligence"]["copyright_safety"][
        "manual_review_required"
    ] is True
    upload_metadata = rv.metadata["upload_metadata_v2"]
    assert upload_metadata["generator_version"] == "2"
    assert upload_metadata["youtube_shorts"]["title"]
    assert upload_metadata["universal"]["manual_review_required"] is True
    assert upload_metadata["artifact"]["status"] == "available"
    assert await storage.exists(upload_metadata["artifact"]["storage_key"])
    assert rv.metadata["unified_clip_intelligence"]["upload_metadata"][
        "youtube_title"
    ] == upload_metadata["youtube_shorts"]["title"]
    assert manifest.render_id and manifest.rendering_version
    assert manifest.timeline_version == editing.pipeline_version


async def test_upload_metadata_failure_does_not_block_manifest(
    storage: LocalStorage,
    run_repo: StorageRenderRunRepository,
    manifest_store,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from olympus.rendering import stages as render_stages

    def fail_metadata(**_kwargs: object) -> object:
        raise RuntimeError("metadata test failure")

    monkeypatch.setattr(render_stages, "generate_upload_metadata", fail_metadata)
    analysis, planning = _analysis(), _planning()
    editing = await _editing(storage, analysis, planning)
    project = _project()
    await storage.put(project.storage_key, _FAKE_MP4, content_type="video/mp4")

    run = await _render_pipeline(run_repo).run(
        project, storage, StubClipRenderer(), manifest_store, editing=editing
    )
    manifest = await manifest_store.load(project.id)

    assert run.stage("generate_render_manifest").status is RenderStageStatus.COMPLETED
    assert manifest is not None
    upload_metadata = manifest.renders[0].metadata["upload_metadata_v2"]
    assert upload_metadata["status"] == "unavailable"
    assert "metadata test failure" in upload_metadata["reason"]


async def test_manifest_confirms_caption_render_truth(
    storage: LocalStorage, run_repo: StorageRenderRunRepository, manifest_store
) -> None:
    analysis, planning = _analysis(), _planning()
    editing = await _editing(storage, analysis, planning)
    project = _project()
    await storage.put(project.storage_key, _FAKE_MP4, content_type="video/mp4")

    run = await _render_pipeline(run_repo).run(
        project,
        storage,
        CaptionProofStubRenderer(),
        manifest_store,
        editing=editing,
    )
    manifest = await manifest_store.load(project.id)

    assert run.stage("generate_render_manifest").status is RenderStageStatus.COMPLETED
    assert manifest is not None
    metadata = manifest.renders[0].metadata
    assert metadata["caption_render_validation"]["render_manifest_confirmed"] is True
    assert metadata["caption_render_validation"]["passed"] is True
    assert metadata["caption_intelligence_v2"]["validation"][
        "render_manifest_confirmed"
    ] is True
    assert metadata["unified_clip_intelligence"]["caption_intelligence"][
        "render_validation_passed"
    ] is True


async def test_stub_render_produces_manifest_for_all_selected_timelines(
    storage: LocalStorage, run_repo: StorageRenderRunRepository, manifest_store
) -> None:
    analysis, planning = _analysis(), _planning_many(3)
    editing = await _editing(storage, analysis, planning)
    project = _project()
    await storage.put(project.storage_key, _FAKE_MP4, content_type="video/mp4")

    run = await _render_pipeline(run_repo).run(
        project, storage, StubClipRenderer(), manifest_store, editing=editing
    )

    assert run.status is RenderRunStatus.COMPLETED
    assert run.stage("full_resolution_render").data["rendered_count"] == 3
    manifest = await manifest_store.load(project.id)
    assert manifest is not None
    assert [render.clip_id for render in manifest.renders] == ["clip_0", "clip_1", "clip_2"]
    exists = [await storage.exists(render.storage_key) for render in manifest.renders]
    assert all(exists)


async def test_manifest_is_what_optimization_consumes(
    storage: LocalStorage, run_repo: StorageRenderRunRepository, manifest_store
) -> None:
    """The Rendering Engine's published manifest is exactly the Optimizer's input."""

    analysis, planning = _analysis(), _planning()
    editing = await _editing(storage, analysis, planning)
    project = _project()
    await storage.put(project.storage_key, _FAKE_MP4, content_type="video/mp4")
    await _render_pipeline(run_repo).run(
        project, storage, StubClipRenderer(), manifest_store, editing=editing
    )
    # The Optimization Engine reads via its own read-only repository.
    optimizer_view = await StorageRenderManifestRepository(storage).load(project.id)
    assert optimizer_view is not None
    assert optimizer_view.render("clip_a") is not None


# --------------------------------------------------------------------------- #
# Orchestration: resume, cancel, rerun, repo
# --------------------------------------------------------------------------- #
async def test_resume_skips_completed_stages(
    storage: LocalStorage, run_repo: StorageRenderRunRepository, manifest_store
) -> None:
    analysis, planning = _analysis(), _planning()
    editing = await _editing(storage, analysis, planning)
    project = _project()
    pipeline = _render_pipeline(run_repo)
    first = await pipeline.run(
        project, storage, FfmpegClipRenderer(), manifest_store, editing=editing
    )
    ts = first.stage("validate_timeline").completed_at
    second = await pipeline.run(
        project, storage, FfmpegClipRenderer(), manifest_store, editing=editing
    )
    assert second.stage("validate_timeline").completed_at == ts


async def test_cancellation_marks_remaining_cancelled(
    storage: LocalStorage, run_repo: StorageRenderRunRepository, manifest_store
) -> None:
    cancel = asyncio.Event()
    cancel.set()
    run = await _render_pipeline(run_repo).run(
        _project(), storage, FfmpegClipRenderer(), manifest_store, editing=None, cancel_event=cancel
    )
    assert run.status is RenderRunStatus.CANCELLED
    assert all(s.status is RenderStageStatus.CANCELLED for s in run.stages)


async def test_rerun_only_targets_one_stage(
    storage: LocalStorage, run_repo: StorageRenderRunRepository, manifest_store
) -> None:
    analysis, planning = _analysis(), _planning()
    editing = await _editing(storage, analysis, planning)
    project = _project()
    pipeline = _render_pipeline(run_repo)
    await pipeline.run(project, storage, FfmpegClipRenderer(), manifest_store, editing=editing)
    rerun = await pipeline.run(
        project,
        storage,
        FfmpegClipRenderer(),
        manifest_store,
        editing=editing,
        only={"validate_timeline"},
    )
    assert rerun.stage("validate_timeline").status is RenderStageStatus.COMPLETED


async def test_repository_roundtrip_and_delete(
    storage: LocalStorage, run_repo: StorageRenderRunRepository, manifest_store
) -> None:
    analysis, planning = _analysis(), _planning()
    editing = await _editing(storage, analysis, planning)
    project = _project()
    await storage.put(project.storage_key, _FAKE_MP4, content_type="video/mp4")
    await _render_pipeline(run_repo).run(
        project, storage, StubClipRenderer(), manifest_store, editing=editing
    )
    assert await run_repo.load(project.id) is not None
    manifest = await manifest_store.load(project.id)
    assert manifest is not None
    upload_key = manifest.renders[0].metadata["upload_metadata_v2"]["artifact"]["storage_key"]
    assert await storage.exists(upload_key)
    await run_repo.delete(project.id)
    await manifest_store.delete(project.id)
    assert await run_repo.load(project.id) is None
    assert await manifest_store.load(project.id) is None
    assert not await storage.exists(f"render/{project.id}/clips/clip_a.mp4")
    assert not await storage.exists(upload_key)


# --------------------------------------------------------------------------- #
# Service lifecycle + Rendering -> Optimization chain
# --------------------------------------------------------------------------- #
async def _seed(storage: LocalStorage, project: Project) -> None:
    project_repo = StorageProjectRepository(storage)
    await project_repo.save(project)
    await storage.put(project.storage_key, _FAKE_MP4, content_type="video/mp4")

    analysis = _analysis()
    analysis.project_id = project.id
    analysis_repo = StorageAnalysisRepository(storage)
    await analysis_repo.save_index(analysis)
    for s in analysis.stages:
        await analysis_repo.save_stage(project.id, s)

    planning = _planning()
    planning.project_id = project.id
    planning_repo = StoragePlanningRepository(storage)
    await planning_repo.save_index(planning)
    for s in planning.stages:
        await planning_repo.save_stage(project.id, s)

    editing = await _editing(storage, analysis, planning)
    editing.project_id = project.id
    editing_repo = StorageEditingRepository(storage)
    await editing_repo.save_index(editing)
    for s in editing.stages:
        await editing_repo.save_stage(project.id, s)


def _rendering_service(
    storage: LocalStorage, renderer: ClipRenderer, **kw: Any
) -> RenderingService:
    return RenderingService(
        render_run_repo=StorageRenderRunRepository(storage),
        manifest_store=StorageRenderManifestRepository(storage),
        renderer=renderer,
        editing_repo=StorageEditingRepository(storage),
        planning_repo=StoragePlanningRepository(storage),
        virality_repo=StorageViralityRepository(storage),
        story_repo=StorageStoryRepository(storage),
        analysis_repo=StorageAnalysisRepository(storage),
        project_repo=StorageProjectRepository(storage),
        storage=storage,
        **kw,
    )


async def _await_done(service: RenderingService, project_id: str) -> None:
    for _ in range(800):
        if not service.is_running(project_id):
            break
        await asyncio.sleep(0.01)


async def test_service_render_triggers_optimization(storage: LocalStorage) -> None:
    project = _project()
    await _seed(storage, project)
    triggered: list[str] = []

    async def _on_complete(p: Project, _run: object) -> None:
        triggered.append(p.id)

    service = _rendering_service(storage, StubClipRenderer(), on_complete=_on_complete)
    await service.start(project)
    await _await_done(service, project.id)

    run = await service.get_run(project.id)
    assert run is not None and run.status is RenderRunStatus.COMPLETED
    # The completion hook fired because a real manifest was produced.
    assert triggered == [project.id]

    # And a real Optimization run now finds the rendered manifest.
    optimizer = OptimizationService(
        optimization_repo=StorageOptimizationRepository(storage),
        render_repo=StorageRenderManifestRepository(storage),
        editing_repo=StorageEditingRepository(storage),
        planning_repo=StoragePlanningRepository(storage),
        virality_repo=StorageViralityRepository(storage),
        story_repo=StorageStoryRepository(storage),
        analysis_repo=StorageAnalysisRepository(storage),
        project_repo=StorageProjectRepository(storage),
        storage=storage,
    )
    await optimizer.start(project)
    for _ in range(800):
        if not optimizer.is_running(project.id):
            break
        await asyncio.sleep(0.01)
    optimization = await optimizer.get_optimization(project.id)
    assert optimization is not None
    load = optimization.stage("load_render")
    assert load.status.value == "completed"
    assert load.data["render_count"] == 1


async def test_service_no_optimization_when_render_unavailable(storage: LocalStorage) -> None:
    project = _project()
    await _seed(storage, project)
    triggered: list[str] = []

    async def _on_complete(p: Project, _run: object) -> None:
        triggered.append(p.id)

    # Real FFmpeg renderer (unavailable here) -> no manifest -> no chaining.
    service = _rendering_service(storage, FfmpegClipRenderer(), on_complete=_on_complete)
    await service.start(project)
    await _await_done(service, project.id)
    assert triggered == []
    assert await service.manifest(project.id) is None


async def test_service_logs_and_validation(storage: LocalStorage) -> None:
    project = _project()
    await _seed(storage, project)
    service = _rendering_service(storage, StubClipRenderer())
    await service.start(project)
    await _await_done(service, project.id)
    logs = await service.logs(project.id)
    assert logs and any(entry["lines"] for entry in logs)
    report = await service.validation_report(project.id)
    assert report is not None and report["manifest_written"] is True
    assert await service.resolve_clip(project.id, "clip_a") is not None


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #
def test_rendering_api_flow(app: Any, tmp_path: Path) -> None:
    store = LocalStorage(root=str(tmp_path))
    project = _project()
    asyncio.run(_seed(store, project))

    app.dependency_overrides[project_service_provider] = lambda: ProjectService(
        StorageProjectRepository(store), store
    )
    app.dependency_overrides[storage_provider] = lambda: store
    app.dependency_overrides[rendering_service_provider] = lambda: _rendering_service(
        store, StubClipRenderer()
    )
    # Avoid the real optimization chain reaching for a different storage.
    app.dependency_overrides[optimization_service_provider] = lambda: OptimizationService(
        optimization_repo=StorageOptimizationRepository(store),
        render_repo=StorageRenderManifestRepository(store),
        editing_repo=StorageEditingRepository(store),
        planning_repo=StoragePlanningRepository(store),
        virality_repo=StorageViralityRepository(store),
        story_repo=StorageStoryRepository(store),
        analysis_repo=StorageAnalysisRepository(store),
        project_repo=StorageProjectRepository(store),
        storage=store,
    )

    with TestClient(app) as client:
        run = client.post(f"/api/v1/projects/{project.id}/rendering/run")
        assert run.status_code == 202

        final = None
        for _ in range(200):
            resp = client.get(f"/api/v1/projects/{project.id}/rendering")
            if resp.status_code == 200:
                final = resp.json()
                if final["status"] in ("completed", "failed", "cancelled"):
                    break
        assert final is not None and final["status"] == "completed"
        assert final["total_stages"] == len(RENDER_STAGE_ORDER)

        manifest = client.get(f"/api/v1/projects/{project.id}/rendering/manifest")
        assert manifest.status_code == 200
        assert manifest.json()["manifest"]["renders"][0]["clip_id"] == "clip_a"

        dl_manifest = client.get(f"/api/v1/projects/{project.id}/rendering/manifest/download")
        assert dl_manifest.status_code == 200

        validation = client.get(f"/api/v1/projects/{project.id}/rendering/validation")
        assert validation.status_code == 200 and validation.json()["report"]["manifest_written"]

        logs = client.get(f"/api/v1/projects/{project.id}/rendering/logs")
        assert logs.status_code == 200 and logs.json()["stages"]

        clip = client.get(f"/api/v1/projects/{project.id}/rendering/clips/clip_a/download")
        assert clip.status_code == 200

        missing = client.get(f"/api/v1/projects/{project.id}/rendering/clips/nope/download")
        assert missing.status_code == 404

        rerun = client.post(
            f"/api/v1/projects/{project.id}/rendering/stages/validate_timeline/rerun"
        )
        assert rerun.status_code == 200
        cancel = client.post(f"/api/v1/projects/{project.id}/rendering/cancel")
        assert cancel.status_code == 202
