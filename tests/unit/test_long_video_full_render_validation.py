from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from tools import validate_long_video_full_render as validator

from olympus.validation.long_video import (
    LongVideoFullRenderResultV1,
    LongVideoStageResultV1,
    analyze_long_video_source_intervals,
    is_generated_validation_artifact,
    long_video_ffprobe_result,
    long_video_self_check,
    long_video_stage_result,
    validate_long_source_duration,
    validate_long_video_clip_counts,
    validate_long_video_final_payload,
    validate_long_video_manifest_presence,
    write_long_video_full_render_report,
)


def _probe(duration: float = 30.0) -> dict[str, Any]:
    return {
        "passed": True,
        "container_duration": duration,
        "video_duration": duration,
        "audio_duration": duration,
        "width": 1080,
        "height": 1920,
        "video_codec": "h264",
        "audio_codec": "aac",
        "audio_sample_rate": 48000,
        "fps": 30.0,
        "has_audio": True,
    }


def _args(**overrides: Any) -> argparse.Namespace:
    values = {
        "self_check": False,
        "synthetic_long": False,
        "local_file": None,
        "project_id": None,
        "minutes": 30.0,
        "minimum_minutes": 30.0,
        "min_clips": 3,
        "storage_root": Path("storage_data"),
        "report_dir": validator.DEFAULT_REPORT_DIR,
        "ffmpeg_binary": "ffmpeg",
        "ffprobe_binary": "ffprobe",
        "timeout_seconds": 1.0,
        "source_generation_timeout_seconds": 1.0,
        "render_preset": "veryfast",
        "render_threads": 1,
        "render_filter_threads": 1,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_validation_contract_serializes() -> None:
    result = LongVideoFullRenderResultV1(
        project_id="proj_long",
        mode="synthetic_long",
        stages=[LongVideoStageResultV1(name="analysis", status="completed")],
        resource_observations={"peak_ram": "peak RAM not measured"},
    )

    payload = json.loads(json.dumps(result.to_dict()))

    assert payload["project_id"] == "proj_long"
    assert payload["stages"][0]["name"] == "analysis"


def test_stage_timing_summary_works() -> None:
    stage = long_video_stage_result(
        name="rendering",
        status="completed",
        started_at="2026-01-01T00:00:00+00:00",
        finished_at="2026-01-01T00:00:12.500000+00:00",
        artifact_present=True,
    )

    assert stage.duration_seconds == 12.5
    assert stage.artifact_present is True


def test_self_check_reports_missing_ffmpeg_clearly(tmp_path: Path) -> None:
    result = long_video_self_check(
        storage_root=tmp_path / "storage",
        report_dir=tmp_path / "reports",
        which=lambda binary: None if binary == "ffmpeg" else f"/{binary}",
    )

    assert result["passed"] is False
    assert any("ffmpeg not found" in error for error in result["errors"])


def test_synthetic_duration_check_rejects_fake_or_short_source() -> None:
    missing = validate_long_source_duration(None)
    short = validate_long_source_duration(1799.0)

    assert missing["passed"] is False
    assert short["passed"] is False


def test_ffprobe_parser_validates_thirty_minute_duration() -> None:
    probe = _probe(1800.0)
    duration = validate_long_source_duration(probe["container_duration"])
    clip = long_video_ffprobe_result(
        clip_id="clip_long",
        path_or_key="render/project/clips/clip_long.mp4",
        probe=probe,
        expected_duration=1800.0,
    )

    assert duration["passed"] is True
    assert clip["valid"] is True
    assert clip["frame_count"] == 54000


def test_minimum_clip_count_fails_on_one_clip() -> None:
    result = validate_long_video_clip_counts(
        planned=1,
        rendered=1,
        accepted=1,
        optimized=1,
        minimum=3,
    )

    assert result["passed"] is False
    assert "long-video multi-clip proof not satisfied" in result["errors"]


def test_accepted_mp4_count_check_works() -> None:
    failed = validate_long_video_clip_counts(
        planned=3,
        rendered=3,
        accepted=2,
        optimized=3,
        minimum=3,
    )
    passed = validate_long_video_clip_counts(
        planned=3,
        rendered=3,
        accepted=3,
        optimized=3,
        minimum=3,
    )

    assert failed["passed"] is False
    assert passed["passed"] is True


def test_duplicate_interval_detection_catches_exact_duplicates() -> None:
    result = analyze_long_video_source_intervals(
        [
            {"clip_id": "one", "source_start": 10.0, "source_end": 40.0},
            {"clip_id": "two", "source_start": 10.0, "source_end": 40.0},
        ],
        source_duration=1800.0,
    )

    assert result["duplicate_source_intervals_detected"] is True
    assert result["passed"] is False


def test_overlap_detection_catches_high_overlap() -> None:
    result = analyze_long_video_source_intervals(
        [
            {"clip_id": "one", "source_start": 10.0, "source_end": 50.0},
            {"clip_id": "two", "source_start": 17.0, "source_end": 57.0},
        ],
        source_duration=1800.0,
    )

    assert result["high_overlaps"]
    assert result["high_overlaps"][0]["overlap_ratio"] > 0.8


def test_render_manifest_missing_fails() -> None:
    result = validate_long_video_manifest_presence(
        render_manifest_present=False,
        optimization_manifest_present=True,
    )

    assert result["passed"] is False
    assert result["errors"] == ["Canonical render manifest is missing."]


def test_optimization_manifest_missing_fails() -> None:
    result = validate_long_video_manifest_presence(
        render_manifest_present=True,
        optimization_manifest_present=False,
    )

    assert result["passed"] is False
    assert result["errors"] == ["Optimization manifest is missing."]


def test_final_payload_missing_clips_fails() -> None:
    result = validate_long_video_final_payload(
        {"clips": [], "download_urls": []},
        minimum_clips=3,
    )

    assert result["passed"] is False
    assert result["clip_count"] == 0


def test_project_id_mode_does_not_rerender(monkeypatch: Any) -> None:
    calls = {"inspect": 0, "pipeline": 0}

    async def fake_inspect(*_args: Any, **_kwargs: Any) -> LongVideoFullRenderResultV1:
        calls["inspect"] += 1
        return LongVideoFullRenderResultV1(project_id="existing", mode="project_id")

    async def forbidden_pipeline(*_args: Any, **_kwargs: Any) -> LongVideoFullRenderResultV1:
        calls["pipeline"] += 1
        raise AssertionError("project-id inspection must not start the pipeline")

    monkeypatch.setattr(validator, "inspect_long_video_project", fake_inspect)
    monkeypatch.setattr(validator, "run_long_local_pipeline", forbidden_pipeline)

    result = asyncio.run(validator.run_selected_mode(_args(project_id="existing")))

    assert isinstance(result, LongVideoFullRenderResultV1)
    assert calls == {"inspect": 1, "pipeline": 0}


def test_local_file_mode_rejects_missing_file(tmp_path: Path) -> None:
    result = asyncio.run(
        validator.run_selected_mode(_args(local_file=tmp_path / "missing.mp4"))
    )

    assert isinstance(result, LongVideoFullRenderResultV1)
    assert result.passed is False
    assert "does not exist" in result.errors[0]


def test_local_file_mode_rejects_short_file_by_default(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    media = tmp_path / "short.mp4"
    media.write_bytes(b"fixture")
    monkeypatch.setattr(validator, "run_ffprobe", lambda _path: _probe(60.0))

    result = asyncio.run(
        validator.run_long_local_pipeline(
            media,
            mode="local_file",
            minimum_minutes=30.0,
            minimum_clips=3,
            storage_root=tmp_path / "storage",
        )
    )

    assert result.passed is False
    assert "at least 1800.000s" in result.errors[0]


def test_report_writes_under_work_validation_reports_only(tmp_path: Path) -> None:
    report_dir = tmp_path / "work" / "validation_reports" / "long_video"
    paths = write_long_video_full_render_report(
        LongVideoFullRenderResultV1(project_id="project", mode="synthetic_long"),
        report_dir,
        workspace_root=tmp_path,
    )
    inspection_paths = write_long_video_full_render_report(
        LongVideoFullRenderResultV1(project_id="project", mode="project_id"),
        report_dir,
        workspace_root=tmp_path,
    )

    assert Path(paths["json"]).is_relative_to(tmp_path / "work" / "validation_reports")
    assert Path(paths["summary"]).is_file()
    assert paths["json"] != inspection_paths["json"]


def test_generated_media_and_reports_are_never_publishable() -> None:
    assert is_generated_validation_artifact("work/validation_reports/report.json") is True
    assert is_generated_validation_artifact("storage_data/render/clip.mp4") is True
    assert is_generated_validation_artifact("media/rights-cleared.mov") is True
    assert is_generated_validation_artifact("src/olympus/validation/long_video.py") is False


def test_resource_observations_serialize() -> None:
    result = LongVideoFullRenderResultV1(
        project_id="project",
        mode="synthetic_long",
        resource_observations={
            "peak_ram": "peak RAM not measured",
            "renderer_ffmpeg_process_count": 6,
            "rendering_sequential": True,
            "render_invocations": [{"clip_id": "one", "duration_seconds": 2.5}],
        },
    )

    payload = json.loads(json.dumps(result.to_dict()))

    assert payload["resource_observations"]["rendering_sequential"] is True
    assert payload["resource_observations"]["peak_ram"] == "peak RAM not measured"
    assert validator._resource_exhaustion_detected(
        workflow=None,
        render_run=None,
        renderer_metrics={"resource_exhaustion_detected": False},
    ) is False
