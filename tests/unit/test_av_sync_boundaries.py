from __future__ import annotations

import json
from pathlib import Path

import pytest
from tools import validate_av_sync_boundaries as validator

from olympus.editing import captions
from olympus.editing import timeline as timeline_utils
from olympus.editing.boundary_repair import (
    repair_clip_source_window,
    validate_clip_source_window,
)
from olympus.editing.timeline_contracts import ClipSourceWindowV1
from olympus.rendering import command as render_command


def _segments() -> list[dict[str, object]]:
    return [
        {
            "start": 1.0,
            "end": 5.0,
            "text": "First complete thought. Final payoff.",
            "words": [
                {"word": "First", "start": 1.0, "end": 1.5},
                {"word": "complete", "start": 1.55, "end": 2.1},
                {"word": "thought.", "start": 2.15, "end": 2.7},
                {"word": "Final", "start": 4.0, "end": 4.4},
                {"word": "payoff.", "start": 4.45, "end": 5.0},
            ],
        }
    ]


def _repair(
    start: float,
    end: float,
    *,
    segments: list[dict[str, object]] | None = None,
    source_duration: float | None = 10.0,
) -> ClipSourceWindowV1:
    return repair_clip_source_window(
        project_id="project",
        clip_id="clip",
        requested_start_seconds=start,
        requested_end_seconds=end,
        transcript_segments=segments,
        source_duration_seconds=source_duration,
    )


def test_timeline_contract_serializes() -> None:
    window = _repair(1.0, 5.0, segments=_segments())

    encoded = json.loads(json.dumps(window.to_dict()))
    restored = ClipSourceWindowV1.from_dict(encoded)

    assert restored == window
    assert encoded["contract_version"] == "1"


def test_repaired_window_clamps_to_source_duration() -> None:
    window = _repair(8.0, 9.8, segments=None, source_duration=10.0)

    assert window.repaired_end_seconds == 10.0
    assert any("clamped" in warning.lower() for warning in window.warnings)


def test_start_boundary_avoids_mid_word() -> None:
    window = _repair(1.25, 4.0, segments=_segments())

    assert window.repaired_start_seconds < 1.0
    assert validate_clip_source_window(window, _segments())["starts_mid_word"] is False


def test_end_boundary_avoids_mid_word() -> None:
    window = _repair(1.0, 4.7, segments=_segments())

    assert window.repaired_end_seconds >= 5.0
    assert validate_clip_source_window(window, _segments())["missing_final_words"] == []


def test_end_boundary_adds_postroll() -> None:
    window = _repair(1.0, 5.0, segments=_segments())

    assert window.postroll_seconds >= 0.3
    assert window.repaired_end_seconds > 5.0


def test_postroll_does_not_exceed_source_duration() -> None:
    window = _repair(1.0, 5.0, segments=_segments(), source_duration=5.2)

    assert window.repaired_end_seconds == 5.2


def test_captions_convert_source_time_to_clip_relative_time() -> None:
    localized = timeline_utils.clip_segments(_segments(), 0.75, 5.45)

    assert localized[0]["start"] == pytest.approx(0.25)
    assert localized[0]["words"][0]["start"] == pytest.approx(0.25)
    assert localized[0]["words"][-1]["end"] == pytest.approx(4.25)


def test_negative_captions_are_removed_or_clamped() -> None:
    events, quality = captions.timed_caption_events(
        [
            {
                "segment_index": 0,
                "text": "Aligned caption",
                "segment_start": -0.2,
                "segment_end": 0.8,
                "timing_source": "estimated",
            },
            {
                "segment_index": 1,
                "text": "Outside caption",
                "segment_start": 3.5,
                "segment_end": 4.0,
                "timing_source": "estimated",
            },
        ],
        3.0,
    )

    assert events
    assert all(0.0 <= event["start"] < event["end"] <= 3.0 for event in events)
    assert any("shifted" in warning or "removed" in warning for warning in quality["warnings"])


def test_renderer_uses_repaired_start_and_end() -> None:
    timeline = {
        "source_start": 99.0,
        "source_end": 100.0,
        "source_window_v1": _repair(3.2, 7.2, segments=None).to_dict(),
    }

    assert render_command.source_range(timeline) == pytest.approx((3.2, 7.7))


def test_video_and_audio_trim_share_same_source_window() -> None:
    timeline = {
        "source_window_v1": _repair(3.2, 7.2, segments=None).to_dict(),
        "tracks": [],
        "metadata": {},
    }

    graph = render_command.filter_complex(timeline, 1080, 1920, 30, None)

    assert "trim=start=3.200:end=7.700,setpts=PTS-STARTPTS" in graph
    assert "atrim=start=3.200:end=7.700,asetpts=PTS-STARTPTS" in graph


def test_speech_master_path_has_no_unsafe_global_shortest() -> None:
    timeline = {
        "source_window_v1": _repair(3.2, 7.2, segments=None).to_dict(),
        "tracks": [],
        "metadata": {},
    }

    args = render_command.build_ffmpeg_command(
        binary="ffmpeg",
        source_path="source.mp4",
        output_path="output.mp4",
        timeline=timeline,
        width=1080,
        height=1920,
        fps=30,
        video_bitrate_kbps=4500,
        audio_bitrate_kbps=160,
    )

    assert "-shortest" not in args
    assert "-t" not in args
    assert "-ss" not in args


def test_missing_transcript_uses_conservative_postroll() -> None:
    window = _repair(2.0, 5.0, segments=None)

    assert window.postroll_seconds == pytest.approx(0.5)
    assert "transcript timing was unavailable" in window.end_reason


def test_abrupt_end_warning_appears_when_repair_is_impossible() -> None:
    window = _repair(1.0, 5.0, segments=_segments(), source_duration=5.0)

    assert any("abrupt end" in warning.lower() for warning in window.warnings)


def test_validation_catches_missing_final_word() -> None:
    window = ClipSourceWindowV1(
        project_id="project",
        clip_id="clip",
        requested_start_seconds=1.0,
        requested_end_seconds=4.7,
        repaired_start_seconds=0.75,
        repaired_end_seconds=4.8,
        duration_seconds=4.05,
        preroll_seconds=0.25,
        postroll_seconds=0.1,
        boundary_repair_applied=True,
        start_reason="test",
        end_reason="test",
    )

    validation = validate_clip_source_window(window, _segments())

    assert validation["passed"] is False
    assert validation["missing_final_words"] == ["payoff."]


def test_validation_catches_audio_video_marker_offset() -> None:
    validation = validator.validate_marker_alignment(1.0, 1.12, tolerance_seconds=0.04)

    assert validation["passed"] is False
    assert validation["offset_seconds"] == pytest.approx(0.12)


def test_validator_simulate_mode_writes_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        validator,
        "_simulate_media_validation",
        lambda *_args, **_kwargs: {
            "passed": True,
            "checks": {"marker_alignment": {"passed": True}},
            "artifacts": {},
        },
    )

    report = validator.run_simulation(output_dir=tmp_path)

    assert report["passed"] is True
    assert (tmp_path / "av_sync_boundaries_report.json").is_file()
    assert (tmp_path / "av_sync_boundaries_summary.md").is_file()
