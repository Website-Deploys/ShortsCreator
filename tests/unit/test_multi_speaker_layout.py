from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from olympus.editing.multi_speaker import (
    associate_speakers,
    build_multi_speaker_layout,
    consolidate_face_tracks,
)
from olympus.integration.clip_intelligence import unified_clip_intelligence
from olympus.rendering import command as render_command
from olympus.rendering.ffmpeg_renderer import _render_metadata


def _detections(
    centers: list[tuple[float, float]],
    *,
    confidence: float = 0.9,
    start: float = 0.0,
    end: float = 6.0,
    step: float = 0.5,
) -> list[dict[str, float]]:
    output: list[dict[str, float]] = []
    timestamp = start
    while timestamp <= end + 0.001:
        for x_center, y_center in centers:
            output.append(
                {
                    "time": round(timestamp, 3),
                    "x_center": x_center,
                    "y_center": y_center,
                    "width": 0.16,
                    "height": 0.28,
                    "confidence": confidence,
                }
            )
        timestamp += step
    return output


def _layout(
    detections: list[dict[str, float]],
    *,
    speakers: list[dict[str, object]] | None = None,
    width: float = 1920,
    height: float = 1080,
    duration: float = 6.0,
) -> dict[str, object]:
    return build_multi_speaker_layout(
        detections=detections,
        speaker_timeline=speakers or [],
        clip_id="clip_a",
        project_id="project_a",
        clip_start=0.0,
        duration=duration,
        source_width=width,
        source_height=height,
        fps=30.0,
    )


def _identified_detections(
    face_id: str,
    x_center: float,
    *,
    start: float,
    end: float,
    step: float = 0.2,
) -> list[dict[str, object]]:
    return [
        {**item, "face_id": face_id}
        for item in _detections(
            [(x_center, 0.42)],
            start=start,
            end=end,
            step=step,
        )
    ]


def test_anonymous_tracks_stay_stable_without_source_ids() -> None:
    tracks = consolidate_face_tracks(_detections([(0.28, 0.42), (0.72, 0.43)]), 6.0)

    assert len(tracks) == 2
    assert {track["face_track_id"] for track in tracks} == {
        "face_track_1",
        "face_track_2",
    }
    assert all(track["observation_count"] == 13 for track in tracks)


def test_anonymous_tracks_preserve_motion_through_a_crossing() -> None:
    detections: list[dict[str, float]] = []
    positions = [
        (0.0, 0.2, 0.8),
        (0.5, 0.3, 0.7),
        (1.0, 0.4, 0.6),
        (1.5, 0.55, 0.45),
        (2.0, 0.7, 0.3),
    ]
    for index, (timestamp, first_x, second_x) in enumerate(positions):
        frame = [
            {
                "time": timestamp,
                "x_center": first_x,
                "y_center": 0.35,
                "width": 0.16,
                "height": 0.28,
                "confidence": 0.92,
            },
            {
                "time": timestamp,
                "x_center": second_x,
                "y_center": 0.58,
                "width": 0.16,
                "height": 0.28,
                "confidence": 0.91,
            },
        ]
        detections.extend(reversed(frame) if index % 2 else frame)

    tracks = consolidate_face_tracks(detections, 2.0)
    upper_track = min(tracks, key=lambda item: item["average_box"]["y_center"])
    lower_track = max(tracks, key=lambda item: item["average_box"]["y_center"])

    assert len(tracks) == 2
    assert upper_track["observations"][0]["x_center"] == 0.2
    assert upper_track["observations"][-1]["x_center"] == 0.7
    assert lower_track["observations"][0]["x_center"] == 0.8
    assert lower_track["observations"][-1]["x_center"] == 0.3


def test_short_detection_gap_keeps_track_and_low_confidence_jump_is_rejected() -> None:
    detections = _detections([(0.3, 0.42)], end=2.0)
    detections += _detections([(0.32, 0.42)], start=2.8, end=4.0)
    detections.append(
        {
            "time": 3.0,
            "x_center": 0.9,
            "y_center": 0.8,
            "width": 0.16,
            "height": 0.28,
            "confidence": 0.56,
        }
    )

    tracks = consolidate_face_tracks(detections, 4.0)

    stable = max(tracks, key=lambda item: item["observation_count"])
    assert stable["observation_count"] >= 7
    assert stable["face_track_id"] == "face_track_1"


def test_sparse_track_holds_then_uses_bounded_interpolation() -> None:
    detections = [
        {
            "time": timestamp,
            "x_center": x_center,
            "y_center": 0.42,
            "width": 0.16,
            "height": 0.28,
            "confidence": 0.94,
            "face_id": "temporal_hint",
        }
        for timestamp, x_center in ((0.0, 0.25), (2.0, 0.55), (4.0, 0.7))
    ]

    layout = _layout(detections, duration=4.0)
    keyframe_times = [item["time"] for item in layout["crop_keyframes"]]

    assert layout["mode"] == "single_face_tracking"
    assert 0.6 in keyframe_times
    assert 1.0 in keyframe_times
    assert keyframe_times[-1] == 4.0


def test_long_track_keyframe_limit_preserves_full_duration() -> None:
    layout = _layout(
        _detections([(0.32, 0.42)], end=20.0, step=0.2),
        duration=20.0,
    )

    assert layout["mode"] == "single_face_tracking"
    assert len(layout["crop_keyframes"]) <= 32
    assert layout["crop_keyframes"][0]["time"] == 0.0
    assert layout["crop_keyframes"][-1]["time"] == 20.0


def test_sparse_endpoint_detections_do_not_fake_full_track_coverage() -> None:
    detections = [
        {
            "time": 0.0,
            "x_center": 0.3,
            "y_center": 0.42,
            "width": 0.16,
            "height": 0.28,
            "confidence": 0.95,
            "face_id": "temporal_hint",
        },
        {
            "time": 3.0,
            "x_center": 0.31,
            "y_center": 0.42,
            "width": 0.16,
            "height": 0.28,
            "confidence": 0.95,
            "face_id": "temporal_hint",
        },
    ]

    layout = _layout(detections, duration=6.0)

    assert layout["mode"] == "center_fallback"
    assert layout["input_analysis"]["stable_face_count"] == 0


def test_speaker_association_requires_unique_visibility() -> None:
    first = consolidate_face_tracks(_detections([(0.28, 0.42)], end=2.8), 6.0)
    second = consolidate_face_tracks(
        _detections([(0.72, 0.42)], start=3.0, end=6.0),
        6.0,
    )
    tracks = [first[0], {**second[0], "face_track_id": "face_track_2"}]
    associations = associate_speakers(
        tracks,
        [
            {"speaker": "spk_0", "start": 0.0, "end": 2.8},
            {"speaker": "spk_1", "start": 3.0, "end": 6.0},
        ],
        clip_start=0.0,
        clip_duration=6.0,
    )

    assert len([item for item in associations if item["face_track_id"]]) == 2
    assert all("biometric" in item["warnings"][0] for item in associations)


def test_conflicting_speaker_association_remains_unknown() -> None:
    detections = [
        *_identified_detections("left_hint", 0.28, start=0.0, end=1.9),
        *_identified_detections("right_hint", 0.72, start=2.1, end=4.0),
    ]
    tracks = consolidate_face_tracks(detections, 4.0)

    associations = associate_speakers(
        tracks,
        [
            {"speaker": "spk_0", "start": 0.0, "end": 1.9},
            {"speaker": "spk_0", "start": 2.1, "end": 4.0},
        ],
        clip_start=0.0,
        clip_duration=4.0,
    )

    assert len(associations) == 1
    assert associations[0]["face_track_id"] is None
    assert associations[0]["method"] == "unresolved_visibility_overlap"
    assert associate_speakers(tracks, [], clip_start=0.0, clip_duration=4.0) == []


def test_one_stable_face_keeps_single_face_tracking() -> None:
    layout = _layout(_detections([(0.32, 0.42)]))

    assert layout["mode"] == "single_face_tracking"
    assert layout["render_plan"]["renderable"] is True
    assert len(layout["crop_keyframes"]) >= 2


def test_two_visible_faces_without_association_use_stack() -> None:
    layout = _layout(_detections([(0.28, 0.42), (0.74, 0.43)]))

    assert layout["mode"] == "two_speaker_stack"
    assert len(layout["layout_regions"]) == 2
    assert layout["input_analysis"]["active_speaker_evidence_available"] is False


def test_reliable_diarized_turns_can_use_active_speaker_focus() -> None:
    detections = _detections([(0.28, 0.42)], end=2.8)
    detections += _detections([(0.74, 0.43)], start=3.0, end=5.5)
    layout = _layout(
        detections,
        speakers=[
            {"speaker": "spk_0", "start": 0.0, "end": 2.8},
            {"speaker": "spk_1", "start": 3.0, "end": 5.5},
        ],
        duration=5.5,
    )

    assert layout["mode"] == "active_speaker_focus"
    assert len(layout["speaker_switches"]) == 1
    assert layout["decision"]["active_speaker_method"].startswith("diarized")


def test_active_speaker_switches_remain_clip_relative_for_trimmed_source() -> None:
    detections = [
        *_identified_detections("left_hint", 0.28, start=0.0, end=2.8),
        *_identified_detections("right_hint", 0.74, start=3.0, end=5.5, step=0.1),
    ]
    layout = build_multi_speaker_layout(
        detections=detections,
        speaker_timeline=[
            {"speaker": "spk_0", "start": 10.0, "end": 12.8},
            {"speaker": "spk_1", "start": 13.0, "end": 15.5},
        ],
        clip_id="clip_offset",
        project_id="project_a",
        clip_start=10.0,
        duration=5.5,
        source_width=1920,
        source_height=1080,
        fps=30.0,
    )

    assert layout["mode"] == "active_speaker_focus"
    assert [item["time"] for item in layout["speaker_switches"]] == [3.0]
    assert all(0.0 <= item["time"] <= 5.5 for item in layout["crop_keyframes"])


def test_short_interjection_does_not_trigger_rapid_active_speaker_switch() -> None:
    detections = [
        *_identified_detections("left_hint", 0.28, start=0.0, end=1.8),
        *_identified_detections("right_hint", 0.74, start=2.0, end=2.4),
        *_identified_detections("left_hint", 0.28, start=2.5, end=3.9),
        *_identified_detections("right_hint", 0.74, start=4.0, end=6.0),
    ]
    layout = _layout(
        detections,
        speakers=[
            {"speaker": "spk_0", "start": 0.0, "end": 1.9},
            {"speaker": "spk_1", "start": 2.0, "end": 2.4},
            {"speaker": "spk_0", "start": 2.5, "end": 3.9},
            {"speaker": "spk_1", "start": 4.0, "end": 6.0},
        ],
    )

    assert layout["mode"] == "active_speaker_focus"
    assert [item["time"] for item in layout["speaker_switches"]] == [4.0]


def test_vertical_natural_two_face_frame_is_preserved() -> None:
    layout = _layout(
        _detections([(0.35, 0.4), (0.65, 0.42)]),
        width=1080,
        height=1920,
    )

    assert layout["mode"] == "natural_frame_preserved"


def test_three_faces_use_multi_face_safe_frame() -> None:
    layout = _layout(_detections([(0.2, 0.42), (0.5, 0.4), (0.8, 0.43)]))

    assert layout["mode"] == "multi_face_safe_frame"
    assert len(layout["crop_keyframes"]) >= 2


def test_low_confidence_faces_use_honest_center_fallback() -> None:
    layout = _layout(_detections([(0.3, 0.4)], confidence=0.2))

    assert layout["mode"] == "center_fallback"
    assert layout["fallback_reason"] == "sparse_or_low_confidence_faces"
    assert layout["render_plan"]["renderable"] is False


def _stack_timeline() -> dict[str, object]:
    layout = _layout(_detections([(0.28, 0.42), (0.74, 0.43)]))
    return {
        "source_start": 0.0,
        "source_end": 6.0,
        "duration": 6.0,
        "tracks": [{"kind": "caption", "events": []}],
        "metadata": {
            "multi_speaker_layout_v2": layout,
            "face_tracking_plan": layout,
            "render_assets_v2": {"music": {"mixed": False}, "sfx": {"events": []}},
        },
    }


def test_two_speaker_filtergraph_uses_independent_crops_and_vstack() -> None:
    graph = render_command.filter_complex(
        _stack_timeline(),
        1080,
        1920,
        30,
        "captions.ass",
    )

    assert "split=2[top_source][bottom_source]" in graph
    assert graph.count("crop=w=") == 2
    assert "vstack=inputs=2" in graph
    assert "scale=1080:960" in graph
    assert "subtitles='captions.ass'" in graph
    assert graph.count("[0:a]atrim=") == 1
    assert "atrim=0:6.000" in graph
    assert "-shortest" not in graph


def test_command_maps_one_master_audio_stream_for_stack(tmp_path: Path) -> None:
    args = render_command.build_ffmpeg_command(
        binary="ffmpeg",
        source_path="source.mp4",
        output_path=str(tmp_path / "out.mp4"),
        timeline=_stack_timeline(),
        width=1080,
        height=1920,
        fps=30,
        video_bitrate_kbps=4500,
        audio_bitrate_kbps=160,
    )

    assert args.count("[a]") == 1
    assert "-shortest" not in args


def test_stack_graph_preserves_music_sfx_captions_and_enhancement() -> None:
    timeline = _stack_timeline()
    timeline["metadata"]["render_assets_v2"] = {
        "music": {
            "mixed": True,
            "path": "music.wav",
            "looped": True,
            "gain_db": -18.0,
        },
        "sfx": {
            "events": [
                {
                    "mixed": True,
                    "path": "pop.wav",
                    "time": 1.0,
                    "gain_db": -15.0,
                }
            ]
        },
    }
    timeline["metadata"]["editing_v2"] = {
        "video_enhancement_plan": {"profile": "balanced"}
    }

    graph = render_command.filter_complex(
        timeline,
        1080,
        1920,
        30,
        "captions.ass",
    )

    assert "vstack=inputs=2" in graph
    assert "subtitles='captions.ass'" in graph
    assert "eq=contrast=" in graph
    assert "[1:a]atrim=0:6.000" in graph
    assert "[2:a]asetpts=PTS-STARTPTS" in graph
    assert "amix=inputs=3:duration=first" in graph


def test_invalid_stack_geometry_falls_back_without_vstack() -> None:
    timeline = _stack_timeline()
    timeline["metadata"]["multi_speaker_layout_v2"]["layout_regions"] = []

    graph = render_command.filter_complex(timeline, 1080, 1920, 30, None)

    assert "vstack" not in graph
    assert "crop=1080:1920" in graph


def test_active_focus_without_switches_never_claims_applied() -> None:
    timeline = _stack_timeline()
    plan = timeline["metadata"]["multi_speaker_layout_v2"]
    plan["mode"] = "active_speaker_focus"
    plan["decision"]["mode"] = "active_speaker_focus"
    plan["crop_keyframes"] = plan["layout_regions"][0]["crop_keyframes"]
    plan["layout_regions"] = []
    plan["speaker_switches"] = []
    plan["render_plan"]["layout_filter_type"] = "dynamic_crop"

    graph = render_command.filter_complex(timeline, 1080, 1920, 30, None)
    metadata = _render_metadata(
        timeline,
        logs=[],
        probe={
            "format": {"duration": "6.000"},
            "streams": [
                {
                    "codec_type": "video",
                    "duration": "6.000",
                    "width": 1080,
                    "height": 1920,
                },
                {"codec_type": "audio", "duration": "6.000"},
            ],
        },
    )

    assert "crop=1080:1920" in graph
    assert metadata["multi_speaker_validation"]["applied"] is False
    assert metadata["multi_speaker_validation"]["applied_mode"] == "center_fallback"
    assert metadata["multi_speaker_validation"]["passed"] is False


def test_render_metadata_proves_applied_stack_and_unified_truth() -> None:
    timeline = _stack_timeline()
    metadata = _render_metadata(
        timeline,
        logs=[],
        probe={
            "format": {"duration": "6.000"},
            "streams": [
                {
                    "codec_type": "video",
                    "duration": "6.000",
                    "width": 1080,
                    "height": 1920,
                },
                {"codec_type": "audio", "duration": "6.000"},
            ],
        },
    )

    validation = metadata["multi_speaker_validation"]
    assert validation["applied"] is True
    assert validation["applied_mode"] == "two_speaker_stack"
    assert validation["rendered_regions"] == 2
    assert validation["passed"] is True
    assert metadata["unified_clip_intelligence"]["multi_speaker_layout"]["applied"] is True


def test_unified_layout_falls_back_safely_without_render_metadata() -> None:
    layout = _layout([])
    unified = unified_clip_intelligence(
        clip={"clip_id": "clip_a", "duration": 6.0},
        editing_v2={"multi_speaker_layout_v2": layout},
    )

    assert unified["multi_speaker_layout"]["mode"] == "center_fallback"
    assert unified["multi_speaker_layout"]["applied"] is False


def test_validation_cli_simulates_stack_as_json() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "tools/validate_multi_speaker_layout.py",
            "--simulate",
            "--faces",
            "2",
            "--speakers",
            "0",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    report = json.loads(completed.stdout)["multi_speaker_validation_report"]
    assert completed.returncode == 0
    assert report["layout_decision"]["mode"] == "two_speaker_stack"
    assert report["pass_fail"] is True
