from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import olympus.validation.long_video as long_video
import olympus.validation.real_video as real_video
from olympus.validation.long_video import (
    LongVideoOptions,
    analyze_clip_diversity,
    analyze_timeline_coverage,
    build_discovery_report,
    build_stage_timing_report,
    classify_long_video_duration,
    completed_stage_version_warnings,
    discover_long_video_samples,
    expected_clip_range_v2,
    infer_video_types,
    probe_source_video,
    strong_low_output_reason,
    validate_clip_count,
    validate_frontend_payload_v2,
    validate_metadata_survival,
    validate_with_backend,
    watchdog_assessment,
    write_long_video_reports,
)
from olympus.validation.real_video import validate_rendered_clip


def _unified(index: int) -> dict[str, Any]:
    return {
        "source_start": index * 450.0 + 60.0,
        "source_end": index * 450.0 + 90.0,
        "story": {"story_shape": f"shape_{index}", "story_id": f"story_{index}"},
        "virality": {"hook_line": f"Hook {index}", "hook_category": f"pattern_{index}"},
        "planning": {"selected_reason": f"Distinct reason {index}"},
        "editing": {},
    }


def _plan(index: int) -> dict[str, Any]:
    start = index * 450.0 + 60.0
    return {
        "id": f"plan_{index}",
        "story_id": f"story_{index}",
        "start": start,
        "end": start + 30.0,
        "hook_line": f"Hook {index}",
        "unified_clip_intelligence": _unified(index),
    }


def _render(index: int = 0) -> dict[str, Any]:
    unified = _unified(index)
    return {
        "clip_id": f"plan_{index}",
        "plan_id": f"plan_{index}",
        "duration": 30.0,
        "metadata": {
            "planned_duration": 30.0,
            "unified_clip_intelligence": unified,
            "music_intelligence_v2": {
                "selected_asset": {"asset_id": f"music_{index}", "source_type": "curated"},
                "music_library_selection": {"selected_priority_tier": "curated"},
            },
            "caption_intelligence_v2": {"style_decision": {"caption_style": "clean"}},
            "motion_intelligence_v2": {"decision": {"motion_style": "clean_podcast"}},
            "multi_speaker_layout_v2": {"layout_decision": {"mode": "center_fallback"}},
            "internet_trend_research_v2": {"source": "fallback"},
            "warnings": [],
        },
    }


def _completed_bundle() -> dict[str, Any]:
    plans = [_plan(index) for index in range(8)]
    return {
        "project": {
            "id": "proj_long",
            "duration_seconds": None,
            "width": 1920,
            "height": 1080,
            "size_bytes": 1000,
            "source_filename": "motivational_talk.mp4",
            "source_type": "upload",
        },
        "analysis": {
            "status": "completed",
            "stages": [
                {
                    "stage": "video_inspection",
                    "status": "completed",
                    "data": {"duration_seconds": 3600.0, "width": 1920, "height": 1080},
                }
            ],
        },
        "story": {"status": "completed", "stages": []},
        "virality": {"status": "completed", "stages": []},
        "planning": {
            "status": "completed",
            "stages": [
                {
                    "stage": "candidate_generation",
                    "status": "completed",
                    "data": {"candidates": plans, "candidate_count": 8},
                },
                {
                    "stage": "planning_summary",
                    "status": "completed",
                    "data": {"plan_count": 8, "low_output_reason": None},
                },
            ],
        },
        "editing": None,
        "rendering": None,
        "optimization": None,
        "plans": {"plans": plans},
        "manifest": None,
        "workflow": None,
    }


class FakeClient:
    def __init__(self, project: dict[str, Any] | None = None) -> None:
        self.project = project

    def json_request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if path == "/api/v1/health/live":
            return {"status": "alive"}
        return {"cancelled": False}

    def get_json_or_none(self, path: str) -> dict[str, Any] | None:
        if path == "/api/v1/projects/proj_long":
            return self.project
        return None

    def download(self, path: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"render")


def test_duration_tiers_cover_every_boundary() -> None:
    assert classify_long_video_duration(179.9) == "short_under_3min"
    assert classify_long_video_duration(180) == "medium_3_to_10min"
    assert classify_long_video_duration(600) == "long_10_to_30min"
    assert classify_long_video_duration(1800) == "long_30_to_60min"
    assert classify_long_video_duration(3600) == "very_long_60_to_120min"
    assert classify_long_video_duration(7200) == "stream_over_120min"
    assert classify_long_video_duration(None) == "unknown"


def test_expected_clip_ranges_match_v2_policy() -> None:
    assert expected_clip_range_v2(120) == (1, 5)
    assert expected_clip_range_v2(500) == (2, 8)
    assert expected_clip_range_v2(1200) == (3, 12)
    assert expected_clip_range_v2(2400) == (5, 20)
    assert expected_clip_range_v2(3600) == (8, 30)
    assert expected_clip_range_v2(8000) == (10, 40)


def test_filename_type_inference_is_explicitly_filename_only() -> None:
    inferred = infer_video_types("two_speaker_gaming_podcast.mp4")
    assert {"podcast", "gaming", "two_speaker"}.issubset(inferred)


def test_probe_source_success_and_failure(tmp_path: Path, monkeypatch) -> None:
    video = tmp_path / "podcast.mp4"
    video.write_bytes(b"video")
    monkeypatch.setattr(
        long_video,
        "run_ffprobe",
        lambda _path: {
            "passed": True,
            "container_duration": 1900.0,
            "width": 1920,
            "height": 1080,
            "video_codec": "h264",
            "audio_codec": "aac",
            "audio_sample_rate": 48000,
            "has_audio": True,
        },
    )
    passed = probe_source_video(video)
    assert passed["ffprobe_passed"] is True
    assert passed["classification"]["duration_tier"] == "long_30_to_60min"

    monkeypatch.setattr(
        long_video,
        "run_ffprobe",
        lambda _path: {"passed": False, "errors": ["invalid media"]},
    )
    failed = probe_source_video(video)
    assert failed["ffprobe_passed"] is False
    assert failed["errors"] == ["invalid media"]


def test_discovery_sorts_longest_and_filters_tier(tmp_path: Path, monkeypatch) -> None:
    first = tmp_path / "short.mp4"
    second = tmp_path / "podcast_30min.mp4"
    first.write_bytes(b"a")
    second.write_bytes(b"b")

    def fake_probe(path: Path) -> dict[str, Any]:
        duration = 2000.0 if "30min" in path.name else 120.0
        return {
            "passed": True,
            "container_duration": duration,
            "width": 1920,
            "height": 1080,
            "video_codec": "h264",
            "audio_codec": "aac",
            "audio_sample_rate": 48000,
            "has_audio": True,
        }

    monkeypatch.setattr(long_video, "run_ffprobe", fake_probe)
    samples = discover_long_video_samples(sample_dirs=[tmp_path], tier="30min")
    assert [Path(item["path"]).name for item in samples] == [second.name]


def test_one_long_clip_needs_strong_low_output_reason() -> None:
    failed = validate_clip_count(
        source_duration=3600,
        planned_count=1,
        rendered_count=0,
        low_output_reason=None,
    )
    reason = {
        "explanation": "Only one section contained a complete, distinct story with a payoff.",
        "rejected_reasons": ["remaining sections were repetitive filler"],
        "confidence": 0.8,
    }
    passed = validate_clip_count(
        source_duration=3600,
        planned_count=1,
        rendered_count=0,
        low_output_reason=reason,
    )
    assert failed["passed"] is False
    assert passed["passed"] is True
    assert strong_low_output_reason(reason) is True


def test_rendered_count_mismatch_fails_when_required() -> None:
    result = validate_clip_count(
        source_duration=1200,
        planned_count=4,
        rendered_count=3,
        low_output_reason=None,
        require_rendered=True,
    )
    assert result["passed"] is False
    assert "Rendered 3 of 4" in result["warnings"][0]


def test_timeline_coverage_passes_across_buckets() -> None:
    result = analyze_timeline_coverage(
        source_duration=3600,
        selected_clips=[
            {"start": 30, "end": 60},
            {"start": 500, "end": 530},
            {"start": 1200, "end": 1230},
            {"start": 2200, "end": 2230},
            {"start": 3200, "end": 3230},
        ],
        candidates=[{"raw_start": 100, "raw_end": 130}, {"raw_start": 3000, "raw_end": 3030}],
        analyzed_duration=3599,
        transcript_duration=3590,
    )
    assert result["passed"] is True
    assert result["coverage_score"] == 1.0
    assert all(result["selected_clip_buckets"].values())


def test_timeline_coverage_flags_early_bias_and_truncated_transcript() -> None:
    result = analyze_timeline_coverage(
        source_duration=3600,
        selected_clips=[{"start": 10, "end": 40}, {"start": 100, "end": 130}],
        transcript_duration=300,
    )
    assert result["passed"] is False
    assert result["early_bias_detected"] is True
    assert result["late_video_ignored"] is True
    assert any("Transcript duration" in warning for warning in result["warnings"])


def test_diversity_detects_duplicate_ranges() -> None:
    clips = [
        {"id": "a", "start": 100, "end": 140, "hook_line": "Same hook"},
        {"id": "b", "start": 100.4, "end": 140.2, "hook_line": "Same hook"},
    ]
    result = analyze_clip_diversity(clips, source_duration=3600)
    assert result["passed"] is False
    assert result["overlap_detected"] is True
    assert result["duplicate_ranges"]


def test_diversity_passes_distinct_plans() -> None:
    result = analyze_clip_diversity([_plan(index) for index in range(8)], source_duration=3600)
    assert result["passed"] is True
    assert result["diversity_score"] >= 0.8


def test_watchdog_reports_timeout_and_no_progress() -> None:
    timeout = watchdog_assessment(
        stage="transcription",
        stage_elapsed_seconds=1800,
        no_progress_seconds=20,
        timeout_seconds=1800,
    )
    stalled = watchdog_assessment(
        stage="planning",
        stage_elapsed_seconds=100,
        no_progress_seconds=1800,
        timeout_seconds=1800,
    )
    normal = watchdog_assessment(
        stage="planning",
        stage_elapsed_seconds=100,
        no_progress_seconds=20,
        timeout_seconds=1800,
    )
    assert timeout["error_code"] == "STAGE_TIMEOUT_TRANSCRIPTION"
    assert stalled["error_code"] == "NO_PROGRESS"
    assert normal["passed"] is True


def test_stage_timing_report_includes_substages() -> None:
    bundle = {
        "analysis": {
            "status": "completed",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:10+00:00",
            "stages": [
                {
                    "stage": "speech_transcription",
                    "status": "completed",
                    "started_at": "2026-01-01T00:00:01+00:00",
                    "completed_at": "2026-01-01T00:00:09+00:00",
                }
            ],
        }
    }
    rows = build_stage_timing_report(bundle, timeout_seconds=1800)
    transcription = next(item for item in rows if item["stage"] == "transcription")
    assert transcription["status"] == "completed"
    assert transcription["duration_seconds"] == 8.0


def test_stage_version_check_ignores_cancelled_pending_version_zero() -> None:
    warnings = completed_stage_version_warnings(
        {
            "rendering": {
                "status": "cancelled",
                "stages": [
                    {"stage": "render_preview", "status": "pending", "version": "0"},
                    {"stage": "full_resolution_render", "status": "completed", "version": "9"},
                ],
            }
        }
    )
    assert warnings == []


def test_valid_render_passes_and_sync_delta_failure_is_caught(
    tmp_path: Path,
    monkeypatch,
) -> None:
    rendered = tmp_path / "clip.mp4"
    rendered.write_bytes(b"render")
    monkeypatch.setattr(
        real_video,
        "run_ffprobe",
        lambda _path: {
            "passed": True,
            "container_duration": 8.0,
            "video_duration": 8.0,
            "audio_duration": 8.0,
            "width": 1080,
            "height": 1920,
            "video_codec": "h264",
            "audio_codec": "aac",
            "audio_sample_rate": 48000,
            "has_audio": True,
        },
    )
    passed = validate_rendered_clip(
        clip={"clip_id": "clip"},
        rendered_path=rendered,
        planned_duration=8.0,
        require_audio=True,
    )
    assert passed["pass_fail"] is True

    monkeypatch.setattr(
        real_video,
        "run_ffprobe",
        lambda _path: {
            "passed": True,
            "container_duration": 7.5,
            "video_duration": 8.0,
            "audio_duration": 7.5,
            "width": 1080,
            "height": 1920,
            "video_codec": "h264",
            "audio_codec": "aac",
            "audio_sample_rate": 48000,
            "has_audio": True,
        },
    )
    failed = validate_rendered_clip(
        clip={"clip_id": "clip"},
        rendered_path=rendered,
        planned_duration=8.0,
        require_audio=True,
    )
    assert failed["pass_fail"] is False
    assert failed["validation"]["sync_passed"] is False
    assert failed["validation"]["duration_passed"] is False


def test_long_render_validation_warns_and_fails_bad_codec(tmp_path: Path, monkeypatch) -> None:
    client = FakeClient()
    monkeypatch.setattr(
        long_video,
        "validate_rendered_clip",
        lambda **_kwargs: {
            "pass_fail": True,
            "ffprobe": {
                "container_duration": 30.0,
                "video_duration": 30.0,
                "audio_duration": 30.0,
                "width": 1080,
                "height": 1920,
                "video_codec": "vp9",
                "audio_codec": "opus",
                "audio_sample_rate": 48000,
                "fps": 30.0,
            },
            "validation": {"sync_delta_seconds": 0.0, "duration_delta_seconds": 0.0},
            "warnings": [],
            "errors": [],
        },
    )
    reports = long_video._download_and_validate_renders(
        client=client,
        project_id="proj_long",
        report_dir=tmp_path,
        renders=[_render()],
        require_audio=True,
    )
    assert reports[0]["validation_passed"] is False
    assert any("Expected H.264" in warning for warning in reports[0]["warnings"])
    assert any("Expected AAC" in warning for warning in reports[0]["warnings"])


def test_metadata_survival_checks_render_features() -> None:
    passed = validate_metadata_survival(
        plans=[_plan(0)],
        renders=[_render()],
        require_render_metadata=True,
    )
    assert passed["unified_clip_intelligence_found"] is True
    assert passed["music_intelligence_found"] is True
    assert passed["captions_v2_found"] is True
    assert passed["motion_v2_found"] is True
    assert passed["multi_speaker_found"] is True

    missing = validate_metadata_survival(
        plans=[_plan(0)],
        renders=[{"clip_id": "missing", "metadata": {}}],
        require_render_metadata=True,
    )
    assert missing["unified_clip_intelligence_found"] is False
    assert any("Motion Graphics V2" in warning for warning in missing["warnings"])


def test_frontend_payload_checks_download_and_why_fields() -> None:
    result = validate_frontend_payload_v2(
        project_id="proj_long",
        plans=[_plan(0)],
        renders=[_render()],
        base_url="http://127.0.0.1:8000",
    )
    assert result["passed"] is True
    assert result["clips_visible"] is True
    assert result["download_urls_present"] is True
    assert result["why_this_clip_works_present"] is True


def test_planning_only_existing_project_uses_completed_artifacts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bundle = _completed_bundle()
    bundle["manifest"] = {"manifest": {"renders": [_render()]}}
    client = FakeClient(project=bundle["project"])
    monkeypatch.setattr(
        long_video,
        "poll_project",
        lambda **_kwargs: (bundle, {"passed": True, "warnings": [], "errors": []}),
    )
    report = validate_with_backend(
        workspace=tmp_path,
        branch="test",
        client=client,  # type: ignore[arg-type]
        base_url="http://127.0.0.1:8000",
        report_dir=tmp_path / "reports",
        options=LongVideoOptions(mode="planning_only"),
        project_id="proj_long",
    )
    top = report["long_video_validation_v2"]
    assert top["result"]["passed"] is True
    assert top["planning"]["planned_clip_count"] == 8
    assert top["source_video"]["duration_seconds"] == 3600.0
    assert top["rendered_clips"] == []
    assert top["preexisting_rendered_clip_count"] == 1
    assert top["frontend_payload"]["checked"] is False
    assert "render was not claimed" in top["result"]["message"]


def test_missing_project_returns_clear_error(tmp_path: Path) -> None:
    report = validate_with_backend(
        workspace=tmp_path,
        branch="test",
        client=FakeClient(project=None),  # type: ignore[arg-type]
        base_url="http://127.0.0.1:8000",
        report_dir=tmp_path / "reports",
        options=LongVideoOptions(mode="existing_project"),
        project_id="proj_long",
    )
    result = report["long_video_validation_v2"]["result"]
    assert result["passed"] is False
    assert result["error_code"] == "PROJECT_NOT_FOUND"
    assert "Project not found" in result["message"]


def test_reports_are_json_serializable_and_include_next_command(tmp_path: Path) -> None:
    report = build_discovery_report(
        workspace=tmp_path,
        branch="test",
        tier=None,
        samples=[],
        report_dir=tmp_path / "reports",
    )
    paths = write_long_video_reports(report, tmp_path / "reports")
    parsed = json.loads(Path(paths["long_video_validation_report.json"]).read_text())
    result = parsed["long_video_validation_v2"]["result"]
    markdown = Path(paths["long_video_validation_summary.md"]).read_text()
    assert result["command_to_try"]
    assert "Olympus Long-Video Validation V2" in markdown
    assert "Next action" in markdown


def test_cli_discover_no_files_and_smoke_create_reports(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    discover_dir = tmp_path / "discover_reports"
    discovered = subprocess.run(
        [
            sys.executable,
            "tools/validate_long_video.py",
            "--discover",
            "--samples-dir",
            str(empty),
            "--report-dir",
            str(discover_dir),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert discovered.returncode == 0, discovered.stderr
    assert (discover_dir / "long_video_validation_report.json").exists()
    assert json.loads((discover_dir / "long_video_validation_report.json").read_text())[
        "long_video_validation_v2"
    ]["result"]["status"] == "NO_SAMPLES"

    smoke_dir = tmp_path / "smoke_reports"
    smoke = subprocess.run(
        [
            sys.executable,
            "tools/validate_long_video.py",
            "--smoke",
            "--samples-dir",
            str(empty),
            "--report-dir",
            str(smoke_dir),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert smoke.returncode == 0, smoke.stderr
    smoke_top = json.loads((smoke_dir / "long_video_validation_report.json").read_text())[
        "long_video_validation_v2"
    ]
    assert smoke_top["smoke"]["synthetic"] is True
    assert smoke_top["real_video_validation"] is False


def test_cli_missing_file_and_invalid_tier_are_clear(tmp_path: Path) -> None:
    report_dir = tmp_path / "missing_reports"
    missing = subprocess.run(
        [
            sys.executable,
            "tools/validate_long_video.py",
            "--file",
            str(tmp_path / "missing.mp4"),
            "--report-dir",
            str(report_dir),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert missing.returncode == 1
    parsed = json.loads((report_dir / "long_video_validation_report.json").read_text())
    assert parsed["long_video_validation_v2"]["result"]["error_code"] == "SOURCE_PROBE_FAILED"

    invalid = subprocess.run(
        [sys.executable, "tools/validate_long_video.py", "--tier", "25min", "--discover"],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert invalid.returncode != 0
    assert "invalid choice" in invalid.stderr
