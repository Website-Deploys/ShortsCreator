from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from olympus.validation.real_video import (
    build_empty_report,
    classify_duration,
    discover_video_samples,
    output_count_assessment,
    parse_probe,
    stage_version_warnings,
    terminal_pipeline_state,
    timeline_coverage,
    utc_now_iso,
    validate_frontend_payload,
    validate_rendered_clip,
    write_reports,
)


def test_classifies_duration_tiers() -> None:
    assert classify_duration(12) == "tiny"
    assert classify_duration(240) == "short"
    assert classify_duration(900) == "medium"
    assert classify_duration(2400) == "long"
    assert classify_duration(5400) == "very_long"
    assert classify_duration(None) == "unknown"


def test_discovery_finds_explicit_video_when_ffprobe_unavailable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    video = tmp_path / "sample.mp4"
    video.write_bytes(b"not-real-video")

    def fake_probe(path: Path, *, timeout_seconds: float = 60.0) -> dict:
        return {
            "passed": True,
            "path": str(path),
            "container_duration": 122.0,
            "width": 1080,
            "height": 1920,
            "fps": 30.0,
            "has_audio": True,
            "audio_codec": "aac",
            "video_codec": "h264",
        }

    monkeypatch.setattr("olympus.validation.real_video.run_ffprobe", fake_probe)

    samples = discover_video_samples(explicit_files=[video], sample_dirs=[])

    assert len(samples) == 1
    assert samples[0].tier == "tiny"
    assert samples[0].duration == 122.0


def test_parse_probe_handles_missing_audio() -> None:
    parsed = parse_probe(
        {
            "format": {"duration": "8.0", "size": "123"},
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1080,
                    "height": 1920,
                    "duration": "8.0",
                    "avg_frame_rate": "30/1",
                }
            ],
        }
    )

    assert parsed["has_audio"] is False
    assert parsed["audio_codec"] is None
    assert parsed["container_duration"] == 8.0
    assert parsed["fps"] == 30.0


def test_terminal_pipeline_state_detects_failed_workflow() -> None:
    assert terminal_pipeline_state({"workflow": {"status": "failed"}}) == {
        "source": "workflow",
        "status": "failed",
    }
    assert terminal_pipeline_state({"workflow": {"status": "running"}}) is None
    assert terminal_pipeline_state({"rendering": {"status": "completed"}}) is None
    assert terminal_pipeline_state({"optimization": {"status": "completed"}}) == {
        "source": "optimization",
        "status": "completed",
    }


def test_output_count_requires_low_output_reason() -> None:
    failed = output_count_assessment(
        source_duration=3600,
        planned_clip_count=1,
        rendered_clip_count=1,
        low_output_reason=None,
    )
    explained = output_count_assessment(
        source_duration=3600,
        planned_clip_count=1,
        rendered_clip_count=1,
        low_output_reason={"explanation": "low story density"},
    )

    assert failed["passed"] is False
    assert explained["passed"] is True
    assert explained["low_output_reason_present"] is True


def test_timeline_coverage_flags_first_ten_percent_without_explanation() -> None:
    clustered = timeline_coverage(
        source_duration=3600,
        clips=[{"start": 10}, {"start": 100}, {"start": 200}],
    )
    explained = timeline_coverage(
        source_duration=3600,
        clips=[{"start": 10}, {"start": 100}, {"start": 200}],
        explanation="strong section clustered early",
    )

    assert clustered["diversity_passed"] is False
    assert clustered["warning"]
    assert explained["diversity_passed"] is True


def test_frontend_payload_requires_unified_metadata() -> None:
    payload = validate_frontend_payload(
        manifest={
            "manifest": {
                "renders": [
                    {
                        "clip_id": "clip_a",
                        "metadata": {
                            "unified_clip_intelligence": {
                                "story": {"story_shape": "problem_solution"},
                                "virality": {"hook_line": "Why this works"},
                                "planning": {"selected_reason": "strong payoff"},
                            }
                        },
                    }
                ]
            }
        },
        plans={"plans": [{"id": "clip_a"}]},
    )

    assert payload["passed"] is True
    assert payload["why_this_clip_works_present"] is True


def test_stale_artifact_version_warning() -> None:
    warnings = stage_version_warnings(
        {
            "planning": {
                "stages": [
                    {
                        "stage": "planning_summary",
                        "status": "completed",
                        "version": "1",
                    }
                ]
            }
        }
    )

    assert warnings
    assert "planning_summary" in warnings[0]


def test_stage_version_warning_supports_engine_specific_names() -> None:
    warnings = stage_version_warnings(
        {
            "rendering": {
                "stages": [{"stage": "final_validation", "version": "8"}],
            },
            "optimization": {
                "stages": [{"stage": "final_validation", "version": "1"}],
            },
        }
    )

    assert warnings == []


def test_current_v2_stage_versions_do_not_warn() -> None:
    warnings = stage_version_warnings(
        {
            "virality": {"stages": [{"stage": "trend_research", "version": "2"}]},
            "planning": {
                "stages": [
                    {"stage": "clip_scoring", "version": "5"},
                    {"stage": "planning_summary", "version": "5"},
                ]
            },
            "editing": {
                "stages": [
                    {"stage": "subtitle_segmentation", "version": "4"},
                    {"stage": "timeline_validation", "version": "8"},
                ]
            },
            "rendering": {
                "stages": [
                    {"stage": "full_resolution_render", "version": "9"},
                    {"stage": "generate_render_manifest", "version": "11"},
                    {"stage": "final_validation", "version": "8"},
                ]
            },
        }
    )

    assert warnings == []


def test_validate_rendered_clip_fails_missing_file(tmp_path: Path) -> None:
    report = validate_rendered_clip(
        clip={"clip_id": "clip_a"},
        rendered_path=tmp_path / "missing.mp4",
        planned_duration=8.0,
    )

    assert report["pass_fail"] is False
    assert report["errors"] == ["rendered file does not exist"]


def test_validate_rendered_clip_surfaces_multi_speaker_truth(
    tmp_path: Path,
    monkeypatch,
) -> None:
    rendered = tmp_path / "stack.mp4"
    rendered.write_bytes(b"rendered")
    monkeypatch.setattr(
        "olympus.validation.real_video.run_ffprobe",
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

    report = validate_rendered_clip(
        clip={
            "clip_id": "clip_stack",
            "metadata": {
                "multi_speaker_layout_v2": {
                    "layout_decision": {"mode": "two_speaker_stack"}
                },
                "multi_speaker_validation": {
                    "applied": True,
                    "applied_mode": "two_speaker_stack",
                    "face_tracks_used": 2,
                    "speaker_associations_used": 0,
                    "rendered_regions": 2,
                    "rendered_switches": 0,
                    "passed": True,
                },
                "caption_intelligence_v2": {
                    "style_decision": {"caption_style": "clean_podcast"},
                    "caption_timing_quality": {
                        "source": "word_level",
                        "estimated": False,
                    },
                    "caption_readability_validation": {"passed": True},
                },
                "caption_render_validation": {
                    "captions_planned": True,
                    "passed": True,
                    "render_manifest_confirmed": True,
                },
            },
            "subtitles_included": True,
        },
        rendered_path=rendered,
        planned_duration=8.0,
        require_audio=True,
    )

    assert report["pass_fail"] is True
    assert report["validation"]["multi_speaker_layout_mode"] == "two_speaker_stack"
    assert report["validation"]["multi_speaker_layout_applied"] is True
    assert report["validation"]["multi_speaker_layout_passed"] is True
    assert report["validation"]["multi_speaker_regions"] == 2
    assert report["validation"]["captions_status"] == "included"
    assert report["validation"]["caption_style"] == "clean_podcast"
    assert report["validation"]["caption_timing_source"] == "word_level"
    assert report["validation"]["caption_render_passed"] is True


def test_caption_readability_advisory_is_non_blocking_unless_marked_blocking(
    tmp_path: Path,
    monkeypatch,
) -> None:
    rendered = tmp_path / "captions.mp4"
    rendered.write_bytes(b"rendered")
    monkeypatch.setattr(
        "olympus.validation.real_video.run_ffprobe",
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
    readability = {
        "passed": False,
        "warnings": ["caption reads at 38 characters/second"],
    }
    clip = {
        "clip_id": "clip_captions",
        "metadata": {
            "caption_readability_validation": readability,
            "caption_render_validation": {"captions_planned": True, "passed": True},
        },
        "subtitles_included": True,
    }

    advisory = validate_rendered_clip(
        clip=clip,
        rendered_path=rendered,
        planned_duration=8.0,
        require_audio=True,
    )
    readability["blocking"] = True
    blocking = validate_rendered_clip(
        clip=clip,
        rendered_path=rendered,
        planned_duration=8.0,
        require_audio=True,
    )

    assert advisory["pass_fail"] is True
    assert advisory["validation"]["caption_readability_warning_count"] == 1
    assert advisory["validation"]["caption_readability_blocking"] is False
    assert blocking["pass_fail"] is False
    assert blocking["validation"]["caption_readability_blocking"] is True


def test_report_writes_expected_files(tmp_path: Path) -> None:
    report = build_empty_report(
        workspace=tmp_path,
        branch="test",
        mode="discover",
        samples=[],
        synthetic_validation=True,
    )

    paths = write_reports(report, tmp_path / "reports")

    assert (tmp_path / "reports" / "validation_report.json").exists()
    assert (tmp_path / "reports" / "validation_summary.md").exists()
    assert (
        json.loads(Path(paths["validation_report.json"]).read_text())[
            "real_video_validation_report"
        ]["real_video_validation"]
        is False
    )


def test_cli_no_video_mode_writes_honest_report(tmp_path: Path) -> None:
    report_dir = tmp_path / "reports"
    sample_dir = tmp_path / "empty"
    sample_dir.mkdir()
    completed = subprocess.run(
        [
            sys.executable,
            "tools/validate_real_video_flow.py",
            "--discover",
            "--samples-dir",
            str(sample_dir),
            "--report-dir",
            str(report_dir),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    report = json.loads((report_dir / "validation_report.json").read_text())
    top = report["real_video_validation_report"]
    assert top["real_video_validation"] is False
    assert "No local validation videos found" in top["warnings"][0]


def test_utc_now_iso_is_json_string() -> None:
    assert isinstance(utc_now_iso(), str)
