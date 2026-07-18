from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from tools import validate_av_sync_boundaries as validator

from olympus.editing import timeline as timeline_utils
from olympus.editing.boundary_repair import repair_clip_source_window
from olympus.editing.timeline_contracts import ClipSourceWindowV1
from olympus.rendering import command as render_command
from olympus.rendering.ffmpeg_renderer import _render_metadata


def _segments() -> list[dict[str, object]]:
    return [
        {
            "start": 1.0,
            "end": 3.0,
            "text": "Hook continues through payoff.",
            "words": [
                {"word": "Hook", "start": 1.0, "end": 1.3},
                {"word": "continues", "start": 1.5, "end": 2.0},
                {"word": "payoff.", "start": 2.6, "end": 3.0},
            ],
        }
    ]


def _window(
    start: float = 1.15,
    end: float = 2.8,
    *,
    segments: list[dict[str, object]] | None = None,
    source_duration: float = 4.0,
) -> ClipSourceWindowV1:
    return repair_clip_source_window(
        project_id="stress_project",
        clip_id="stress_clip",
        requested_start_seconds=start,
        requested_end_seconds=end,
        transcript_segments=segments if segments is not None else _segments(),
        source_duration_seconds=source_duration,
    )


def _render_args(window: ClipSourceWindowV1) -> list[str]:
    return render_command.build_ffmpeg_command(
        binary="ffmpeg",
        source_path="source.mp4",
        output_path="output.mp4",
        timeline={"source_window_v1": window.to_dict(), "tracks": [], "metadata": {}},
        width=1080,
        height=1920,
        fps=30,
        video_bitrate_kbps=4500,
        audio_bitrate_kbps=160,
    )


def test_stress_validator_generates_all_scenarios(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report_dir = tmp_path / "work" / "validation_reports" / "av_sync_boundaries"
    window = _window()
    scenarios = [
        validator._scenario_record(name, window=window, passed=True)
        for name in validator.STRESS_SCENARIO_NAMES
    ]
    monkeypatch.setattr(validator, "ROOT", tmp_path)
    monkeypatch.setattr(validator, "_stress_scenarios", lambda *_args, **_kwargs: scenarios)

    report = validator.run_stress_simulation(output_dir=report_dir)

    assert report["passed"] is True
    assert [item["name"] for item in report["scenarios"]] == list(
        validator.STRESS_SCENARIO_NAMES
    )
    assert (report_dir / validator.STRESS_REPORT_NAME).is_file()
    assert (report_dir / validator.STRESS_SUMMARY_NAME).is_file()


def test_voice_filter_latency_compensation_stays_within_tolerance() -> None:
    measured_after_compensation = render_command.VOICE_PROCESSING_LATENCY_SECONDS

    result = validator.validate_marker_alignment(
        0.5,
        0.5 + measured_after_compensation,
        tolerance_seconds=0.04,
    )

    assert result["passed"] is True


def test_final_word_tail_is_preserved_after_repair() -> None:
    window = _window()

    result = validator.validate_final_word_tail(window.repaired_end_seconds, 3.0)

    assert result["passed"] is True
    assert result["tail_seconds"] >= 0.3


def test_mid_word_start_is_repaired() -> None:
    window = _window(start=1.15, end=3.4)

    assert window.boundary_repair_applied is True
    assert window.repaired_start_seconds < 1.0


def test_no_word_fallback_adds_conservative_postroll() -> None:
    window = _window(
        start=1.0,
        end=3.0,
        segments=[{"start": 1.0, "end": 8.0, "text": "Segment timing only."}],
        source_duration=10.0,
    )

    assert window.postroll_seconds >= 0.3
    assert window.warnings


def test_source_end_clamp_keeps_valid_duration() -> None:
    window = _window(
        start=2.0,
        end=3.0,
        segments=[
            {
                "start": 2.0,
                "end": 3.2,
                "text": "Ending now.",
                "words": [{"word": "now.", "start": 2.9, "end": 3.2}],
            }
        ],
        source_duration=3.25,
    )

    assert window.duration_seconds > 0.0
    assert window.repaired_end_seconds <= 3.25


def test_captions_are_converted_to_clip_relative_time() -> None:
    localized = timeline_utils.clip_segments(
        [
            {
                "start": 10.0,
                "end": 11.0,
                "text": "Caption timing.",
                "words": [{"word": "Caption", "start": 10.0, "end": 10.5}],
            }
        ],
        9.75,
        11.5,
    )

    assert localized[0]["words"][0]["start"] == pytest.approx(0.25)
    assert localized[0]["words"][0]["end"] == pytest.approx(0.75)


def test_captions_never_exceed_repaired_duration() -> None:
    result = validator.validate_caption_alignment(
        [{"start": 0.2, "end": 2.1}],
        2.0,
    )

    assert result["passed"] is False
    assert result["invalid_cue_indexes"] == [0]


def test_stale_output_t_is_not_present_in_render_command() -> None:
    assert "-t" not in _render_args(_window())


def test_unsafe_shortest_is_not_present_in_speech_master_path() -> None:
    assert "-shortest" not in _render_args(_window())


def test_renderer_metadata_includes_sync_validation() -> None:
    window = _window()
    metadata = _render_metadata(
        {
            "source_window_v1": window.to_dict(),
            "metadata": {"timeline": {**window.to_dict(), "boundary_warnings": []}},
        },
        logs=[],
        probe={
            "format": {"duration": str(window.duration_seconds)},
            "streams": [
                {
                    "codec_type": "video",
                    "duration": str(window.duration_seconds),
                    "start_time": "0",
                },
                {
                    "codec_type": "audio",
                    "duration": str(window.duration_seconds),
                    "start_time": "0",
                },
            ],
        },
    )

    assert metadata["sync_validation"]["passed"] is True
    assert metadata["timeline"]["sync_validation"] == metadata["sync_validation"]


def test_renderer_metadata_includes_boundary_warnings() -> None:
    window = _window()
    metadata = _render_metadata(
        {
            "source_window_v1": window.to_dict(),
            "metadata": {
                "timeline": {
                    **window.to_dict(),
                    "boundary_warnings": ["synthetic warning"],
                }
            },
        },
        logs=[],
        probe={},
    )

    assert metadata["timeline"]["boundary_warnings"] == ["synthetic warning"]


def test_validator_fails_when_marker_offset_exceeds_tolerance() -> None:
    assert validator.validate_marker_alignment(1.0, 1.1)["passed"] is False


def test_validator_fails_when_final_word_tail_is_missing() -> None:
    result = validator.validate_final_word_tail(3.1, 3.0, minimum_tail_seconds=0.3)

    assert result["passed"] is False


def test_stress_report_path_is_restricted_to_validation_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(validator, "ROOT", tmp_path)
    allowed = tmp_path / "work" / "validation_reports" / "av_sync_boundaries"

    validator._require_stress_report_path(allowed)
    with pytest.raises(ValueError, match="work/validation_reports"):
        validator._require_stress_report_path(tmp_path / "docs")


def test_stress_validator_uses_no_real_media_or_external_calls() -> None:
    source = Path("tools/validate_av_sync_boundaries.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_roots = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_roots.update(
        str(node.module).split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    )

    assert not imported_roots.intersection({"httpx", "requests", "urllib", "yt_dlp"})
    assert validator.SYNTHETIC_INPUT_POLICY == {
        "generated_synthetic_media_only": True,
        "real_user_media_used": False,
        "downloads_used": False,
        "external_api_calls_used": False,
        "network_used": False,
    }


def test_project_inspection_fails_clearly_when_project_missing(tmp_path: Path) -> None:
    storage_root = tmp_path / "storage_data"
    storage_root.mkdir()

    report = validator.run_project_validation(
        "missing_project",
        output_dir=tmp_path / "reports",
        storage_root=storage_root,
    )

    assert report["passed"] is False
    assert report["project_found"] is False
    assert report["repair_attempted"] is False
    assert "project not found" in report["checks"]["project"]["reason"]
    assert report["searched_paths"]


def test_project_inspection_validates_manifest_mp4_and_timing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage_root = tmp_path / "storage_data"
    project_id = "project_ready"
    window = _window(start=1.0, end=2.5)
    project_path = storage_root / "projects" / project_id / "project.json"
    editing_path = (
        storage_root / "editing" / project_id / "stages" / "timeline_validation.json"
    )
    render_key = f"render/{project_id}/clips/clip.mp4"
    output_path = storage_root / render_key
    manifest_path = storage_root / "render" / project_id / "run" / "index.json"
    for path in (project_path, editing_path, output_path, manifest_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    output_path.write_bytes(b"synthetic mp4 fixture")
    timeline = {
        "clip_id": "stress_clip",
        "source_window_v1": window.to_dict(),
        "tracks": [
            {
                "kind": "caption",
                "events": [{"start": 0.2, "end": 0.8, "text": "Caption"}],
            }
        ],
        "metadata": {"timeline": window.to_dict()},
    }
    editing_path.write_text(
        json.dumps({"data": {"timelines": [timeline]}}),
        encoding="utf-8",
    )
    render_timeline = {
        **window.to_dict(),
        "boundary_warnings": [],
    }
    manifest_path.write_text(
        json.dumps(
            {
                "render_manifest": {
                    "project_id": project_id,
                    "status": "completed",
                    "renders": [
                        {
                            "clip_id": "stress_clip",
                            "storage_key": render_key,
                            "metadata": {
                                "timeline": render_timeline,
                                "sync_validation": {"passed": True},
                            },
                        }
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(validator.shutil, "which", lambda _binary: "ffprobe")
    monkeypatch.setattr(
        validator,
        "_probe",
        lambda *_args, **_kwargs: {
            "format": {"duration": str(window.duration_seconds)},
            "streams": [
                {"codec_type": "video", "duration": str(window.duration_seconds)},
                {"codec_type": "audio", "duration": str(window.duration_seconds)},
            ],
        },
    )

    report = validator.run_project_validation(
        project_id,
        output_dir=tmp_path / "reports",
        storage_root=storage_root,
    )

    assert report["passed"] is True
    assert report["repair_attempted"] is False
    assert report["checks"]["render_manifest"]["passed"] is True
    assert report["checks"]["rendered_clips"]["clips"]["stress_clip"]["passed"] is True
