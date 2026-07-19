from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from tools import validate_multi_speaker_layout as validator

from olympus.validation.face_motion import validate_local_face_path
from olympus.validation.multi_speaker import (
    MultiSpeakerLayoutValidationResultV1,
    active_speaker_switch_count,
    evaluate_assigned_subject_regions,
    fallback_is_consistent,
    layout_motion_metrics,
    speaker_region_coverage_ratio,
    write_multi_speaker_report,
)


def _result(**overrides: Any) -> MultiSpeakerLayoutValidationResultV1:
    values: dict[str, Any] = {
        "project_id": None,
        "clip_id": "clip",
        "mode": "test",
        "real_multi_speaker_sample_used": False,
        "synthetic_sample_used": False,
        "speaker_signals_available": False,
        "face_signals_available": False,
        "detected_speaker_count": 0,
        "expected_speaker_count": 2,
        "layout_strategy": "center_fallback",
        "active_speaker_switches": 0,
        "frames_sampled": 0,
        "layout_regions_present": False,
        "speaker_region_coverage_ratio": 0.0,
        "face_inside_region_ratio": 0.0,
        "subject_cutoff_detected": False,
        "layout_jitter_score": 0.0,
        "max_region_shift_per_second": 0.0,
        "wrong_speaker_focus_warnings": [],
        "fallback_used": True,
        "fallback_reason": "signals_unavailable",
        "render_completed": False,
        "output_mp4_valid": False,
        "passed": True,
        "warnings": [],
        "errors": [],
    }
    values.update(overrides)
    return MultiSpeakerLayoutValidationResultV1(**values)


def _mock_synthetic_render(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        validator,
        "_run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stderr="", stdout=""),
    )
    monkeypatch.setattr(
        validator,
        "_render_layout",
        lambda **_kwargs: {
            "render_completed": True,
            "output_mp4_valid": True,
            "stack_filter_present": True,
            "duration_delta": 0.0,
            "probe": {"passed": True, "video_codec": "h264", "audio_codec": "aac"},
            "errors": [],
        },
    )


def test_validation_contract_serializes() -> None:
    serialized = json.loads(json.dumps(_result().to_dict()))

    assert serialized["contract_version"] == "1"
    assert serialized["raw_frames_stored"] is False
    assert serialized["wrong_speaker_focus_warnings"] == []


def test_self_check_passes_with_mocked_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(validator.shutil, "which", lambda _binary: "C:/tools/binary.exe")

    result, details = validator.run_self_check()

    assert result.passed is True
    assert details["module_imports_passed"] is True
    assert details["external_access_required"] is False


def test_synthetic_mode_reports_real_multi_speaker_sample_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_synthetic_render(monkeypatch)

    result, _details = validator.run_synthetic_two_speaker()

    assert result.passed is True
    assert result.real_multi_speaker_sample_used is False
    assert result.synthetic_sample_used is True


def test_synthetic_mode_does_not_claim_real_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_synthetic_render(monkeypatch)

    result, details = validator.run_synthetic_two_speaker()

    assert details["real_multi_speaker_proof"] is False
    assert result.layout_strategy == "two_speaker_stack"
    assert result.output_mp4_valid is True


def test_missing_local_file_fails_clearly(tmp_path: Path) -> None:
    result, _details = validator.run_local_multi_speaker_file(
        tmp_path / "missing.mp4",
        rights_confirmed=True,
    )

    assert result.passed is False
    assert any("does not exist" in error for error in result.errors)
    assert result.real_multi_speaker_sample_used is False


def test_local_file_mode_rejects_unsafe_nonlocal_path(tmp_path: Path) -> None:
    unsafe = tmp_path / ".venv" / "sample.mp4"
    unsafe.parent.mkdir()
    unsafe.write_bytes(b"video")

    network_path, network_errors = validate_local_face_path(
        "https://example.com/two-speaker.mp4",
        rights_confirmed=True,
    )
    unsafe_path, unsafe_errors = validate_local_face_path(unsafe, rights_confirmed=True)

    assert network_path is None
    assert any("URL" in error for error in network_errors)
    assert unsafe_path is None
    assert any("repository-internal" in error for error in unsafe_errors)


def test_speaker_region_coverage_metric_computes_correctly() -> None:
    assert speaker_region_coverage_ratio(
        expected_speaker_count=2,
        region_counts_by_frame=[2, 2, 1, 2],
    ) == 0.875
    assert speaker_region_coverage_ratio(
        expected_speaker_count=0,
        region_counts_by_frame=[2],
    ) == 0.0


def test_face_subject_inside_region_metric_computes_correctly() -> None:
    metrics = evaluate_assigned_subject_regions(
        [
            {
                "detections": [
                    {
                        "time": 0.0,
                        "x_center": 0.25,
                        "y_center": 0.5,
                        "width": 0.15,
                        "height": 0.25,
                    }
                ],
                "crop_keyframes": [
                    {"time": 0.0, "x_center": 0.25, "y_center": 0.46}
                ],
                "source_width": 1920,
                "source_height": 1080,
                "region_width": 1080,
                "region_height": 960,
            }
        ]
    )

    assert metrics["evaluated"] is True
    assert metrics["face_inside_region_ratio"] == 1.0


def test_subject_cutoff_detection_works() -> None:
    metrics = evaluate_assigned_subject_regions(
        [
            {
                "detections": [
                    {
                        "time": 0.0,
                        "x_center": 0.95,
                        "y_center": 0.5,
                        "width": 0.2,
                        "height": 0.25,
                    }
                ],
                "crop_keyframes": [
                    {"time": 0.0, "x_center": 0.25, "y_center": 0.46}
                ],
                "source_width": 1920,
                "source_height": 1080,
                "region_width": 1080,
                "region_height": 960,
            }
        ]
    )

    assert metrics["subject_cutoff_detected"] is True
    assert metrics["face_inside_region_ratio"] == 0.0


def test_layout_jitter_detects_sudden_jump() -> None:
    metrics = layout_motion_metrics(
        [
            {
                "crop_keyframes": [
                    {"time": 0.0, "x_center": 0.25, "y_center": 0.46},
                    {"time": 1.0, "x_center": 0.27, "y_center": 0.46},
                    {"time": 1.1, "x_center": 0.8, "y_center": 0.46},
                ]
            }
        ]
    )

    assert metrics["layout_jitter_score"] > 0.08
    assert metrics["max_region_shift_per_second"] > 0.22


def test_active_speaker_switch_count_works() -> None:
    assert active_speaker_switch_count(
        [
            {"from_speaker": "speaker_1", "to_speaker": "speaker_2"},
            {"from_speaker": "speaker_2", "to_speaker": "speaker_2"},
            {"from_speaker": "speaker_2", "to_speaker": "speaker_1"},
        ]
    ) == 2


def test_fallback_is_reported_when_speaker_face_signals_are_missing() -> None:
    assert fallback_is_consistent(
        speaker_signals_available=False,
        face_signals_available=False,
        layout_strategy="center_fallback",
        fallback_used=True,
        fallback_reason="face_detection_unavailable",
    )
    assert not fallback_is_consistent(
        speaker_signals_available=False,
        face_signals_available=False,
        layout_strategy="center_fallback",
        fallback_used=False,
        fallback_reason=None,
    )


def test_project_id_inspection_does_not_rerender(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = "project_existing"
    editing_path = (
        tmp_path / "editing" / project_id / "run" / "stages" / "timeline_validation.json"
    )
    render_path = tmp_path / "render" / project_id / "run" / "index.json"
    output_path = tmp_path / "render" / project_id / "clips" / "clip.mp4"
    editing_path.parent.mkdir(parents=True)
    render_path.parent.mkdir(parents=True)
    output_path.parent.mkdir(parents=True)
    output_path.write_bytes(b"rendered")
    keyframes = [
        {"time": 0.0, "x_center": 0.25, "y_center": 0.46},
        {"time": 4.0, "x_center": 0.25, "y_center": 0.46},
    ]
    layout = {
        "mode": "two_speaker_stack",
        "fallback_reason": None,
        "input_analysis": {
            "speaker_count": 0,
            "diarization_available": False,
            "face_tracking_available": True,
        },
        "layout_regions": [
            {"role": "top", "crop_keyframes": keyframes},
            {"role": "bottom", "crop_keyframes": keyframes},
        ],
        "speaker_switches": [],
    }
    editing_path.write_text(
        json.dumps(
            {
                "data": {
                    "timelines": [
                        {
                            "clip_id": "clip",
                            "metadata": {"multi_speaker_layout_v2": layout},
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    render_path.write_text(
        json.dumps(
            {
                "render_manifest": {
                    "renders": [
                        {
                            "clip_id": "clip",
                            "storage_key": f"render/{project_id}/clips/clip.mp4",
                            "metadata": {
                                "multi_speaker_validation": {
                                    "applied": True,
                                    "planned_mode": "two_speaker_stack",
                                    "expected_regions": 2,
                                    "rendered_regions": 2,
                                }
                            },
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        validator,
        "run_ffprobe",
        lambda _path: {
            "passed": True,
            "video_codec": "h264",
            "audio_codec": "aac",
            "has_audio": True,
        },
    )
    monkeypatch.setattr(
        validator,
        "_render_layout",
        lambda **_kwargs: pytest.fail("project inspection must not rerender"),
    )

    result, details = validator.inspect_project(project_id, storage_root=tmp_path)

    assert result.passed is True
    assert details["inspection_only"] is True
    assert details["rerendered"] is False


def test_missing_project_fails_clearly(tmp_path: Path) -> None:
    result, details = validator.inspect_project("missing_project", storage_root=tmp_path)

    assert result.passed is False
    assert any("editing" in error for error in result.errors)
    assert any("render manifest" in error for error in result.errors)
    assert details["searched_editing_paths"]
    assert details["searched_render_paths"]


def test_report_writes_under_work_validation_reports_only(tmp_path: Path) -> None:
    allowed = tmp_path / "work" / "validation_reports" / "multi_speaker_layout"

    path = write_multi_speaker_report(
        _result(),
        workspace_root=tmp_path,
        report_dir=allowed,
    )

    assert path.is_file()
    assert path.is_relative_to(tmp_path / "work" / "validation_reports")
    with pytest.raises(ValueError, match="work"):
        write_multi_speaker_report(
            _result(),
            workspace_root=tmp_path,
            report_dir=tmp_path / "reports",
        )


def test_report_stores_no_raw_frames(tmp_path: Path) -> None:
    path = write_multi_speaker_report(
        _result(frames_sampled=4),
        workspace_root=tmp_path,
        report_dir=tmp_path / "work" / "validation_reports" / "multi_speaker_layout",
        details={"numeric_metric": 0.5},
    )
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert "raw_frames" not in payload
    assert "raw_frames" not in payload["multi_speaker_layout_validation_result_v1"]
    assert "face_images" not in json.dumps(payload)


def test_synthetic_mode_makes_no_external_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[list[str]] = []

    def capture_command(command: list[str], **_kwargs: Any) -> SimpleNamespace:
        commands.append(command)
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(validator, "_run", capture_command)
    monkeypatch.setattr(
        validator,
        "_render_layout",
        lambda **_kwargs: {
            "render_completed": True,
            "output_mp4_valid": True,
            "stack_filter_present": True,
            "duration_delta": 0.0,
            "probe": {},
            "errors": [],
        },
    )

    result, _details = validator.run_synthetic_two_speaker()

    assert result.external_calls_made is False
    assert commands
    assert not any("://" in argument for command in commands for argument in command)
