from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from tools import validate_face_tracking_motion as validator

from olympus.validation.face_motion import (
    FaceMotionValidationResultV1,
    crop_motion_metrics,
    evaluate_face_crop_safety,
    fallback_is_consistent,
    report_contains_private_frame_data,
    tracking_coverage_ratio,
    validate_local_face_path,
    write_face_motion_report,
)


def _result(**overrides: Any) -> FaceMotionValidationResultV1:
    values: dict[str, Any] = {
        "project_id": None,
        "clip_id": "clip",
        "mode": "test",
        "face_sample_used": False,
        "real_face_sample_used": False,
        "face_tracking_available": False,
        "face_count_detected": 0,
        "frames_sampled": 0,
        "tracked_frames": 0,
        "tracking_coverage_ratio": 0.0,
        "crop_keyframes_present": False,
        "motion_effects_present": False,
        "face_inside_safe_zone_ratio": 0.0,
        "jitter_score": 0.0,
        "max_crop_shift_per_second": 0.0,
        "face_cutoff_detected": False,
        "center_fallback_used": True,
        "render_completed": False,
        "output_mp4_valid": False,
        "passed": True,
        "warnings": [],
        "errors": [],
    }
    values.update(overrides)
    return FaceMotionValidationResultV1(**values)


def _mock_synthetic_render(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        validator,
        "_run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stderr="", stdout=""),
    )
    monkeypatch.setattr(
        validator,
        "_render_validation_clip",
        lambda **_kwargs: {
            "render_completed": True,
            "output_mp4_valid": True,
            "filtergraph_contains_motion": True,
            "duration_delta": 0.0,
            "probe": {"passed": True, "video_codec": "h264", "audio_codec": "aac"},
            "errors": [],
            "warnings": [],
        },
    )


def test_validation_contract_serializes() -> None:
    serialized = json.loads(json.dumps(_result().to_dict()))

    assert serialized["contract_version"] == "1"
    assert serialized["raw_frames_stored"] is False
    assert serialized["errors"] == []


def test_self_check_passes_with_mocked_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(validator.shutil, "which", lambda _binary: "C:/tools/binary.exe")

    result, details = validator.run_self_check()

    assert result.passed is True
    assert details["module_imports_passed"] is True
    assert details["external_access_required"] is False


def test_synthetic_fallback_reports_real_face_sample_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_synthetic_render(monkeypatch)

    result, _details = validator.run_synthetic_fallback()

    assert result.passed is True
    assert result.real_face_sample_used is False
    assert result.center_fallback_used is True


def test_synthetic_fallback_does_not_claim_real_face_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_synthetic_render(monkeypatch)

    result, details = validator.run_synthetic_fallback()

    assert details["real_face_proof"] is False
    assert result.face_tracking_available is False
    assert result.motion_effects_present is True


def test_missing_local_face_file_fails_clearly(tmp_path: Path) -> None:
    result, _details = validator.run_local_face_file(
        tmp_path / "missing.mp4",
        rights_confirmed=True,
    )

    assert result.passed is False
    assert any("does not exist" in error for error in result.errors)
    assert result.real_face_sample_used is False


def test_local_face_file_rejects_nonlocal_and_unsafe_paths(tmp_path: Path) -> None:
    unsafe = tmp_path / ".venv" / "sample.mp4"
    unsafe.parent.mkdir()
    unsafe.write_bytes(b"video")

    network_path, network_errors = validate_local_face_path(
        "https://example.com/video.mp4",
        rights_confirmed=True,
    )
    unsafe_path, unsafe_errors = validate_local_face_path(unsafe, rights_confirmed=True)

    assert network_path is None
    assert any("URL" in error for error in network_errors)
    assert unsafe_path is None
    assert any("repository-internal" in error for error in unsafe_errors)


def test_tracking_coverage_metric_computes_correctly() -> None:
    assert tracking_coverage_ratio(sampled_frames=10, tracked_frames=7) == 0.7
    assert tracking_coverage_ratio(sampled_frames=0, tracked_frames=0) == 0.0
    assert tracking_coverage_ratio(sampled_frames=2, tracked_frames=4) == 1.0


def test_safe_zone_ratio_computes_correctly() -> None:
    result = evaluate_face_crop_safety(
        detections=[
            {
                "time": 0.0,
                "x_center": 0.5,
                "y_center": 0.44,
                "width": 0.1,
                "height": 0.2,
            },
            {
                "time": 1.0,
                "x_center": 0.64,
                "y_center": 0.44,
                "width": 0.12,
                "height": 0.2,
            },
        ],
        crop_keyframes=[
            {"time": 0.0, "x_center": 0.5, "y_center": 0.44},
            {"time": 1.0, "x_center": 0.5, "y_center": 0.44},
        ],
        source_width=1920,
        source_height=1080,
    )

    assert result["evaluated"] is True
    assert result["face_inside_safe_zone_ratio"] == 0.5


def test_face_cutoff_detection_works() -> None:
    result = evaluate_face_crop_safety(
        detections=[
            {
                "time": 0.0,
                "x_center": 0.8,
                "y_center": 0.45,
                "width": 0.2,
                "height": 0.2,
            }
        ],
        crop_keyframes=[{"time": 0.0, "x_center": 0.5, "y_center": 0.45}],
        source_width=1920,
        source_height=1080,
    )

    assert result["face_cutoff_detected"] is True
    assert result["face_inside_safe_zone_ratio"] == 0.0


def test_jitter_metric_detects_sudden_jump() -> None:
    metrics = crop_motion_metrics(
        [
            {"time": 0.0, "x_center": 0.5, "y_center": 0.45},
            {"time": 1.0, "x_center": 0.52, "y_center": 0.45},
            {"time": 1.1, "x_center": 0.9, "y_center": 0.45},
        ]
    )

    assert metrics["jitter_score"] > 0.08
    assert metrics["max_crop_shift_per_second"] > 0.22


def test_center_fallback_is_reported_when_no_faces_exist() -> None:
    assert fallback_is_consistent(
        face_tracking_available=False,
        face_count_detected=0,
        center_fallback_used=True,
    )
    assert not fallback_is_consistent(
        face_tracking_available=False,
        face_count_detected=0,
        center_fallback_used=False,
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
    face_plan = {
        "mode": "center_fallback",
        "fallback_reason": "face_detection_unavailable",
        "input_analysis": {"detected_face_count": 0},
        "crop_keyframes": [],
    }
    editing_path.write_text(
        json.dumps(
            {
                "data": {
                    "timelines": [
                        {
                            "clip_id": "clip",
                            "metadata": {"face_tracking_plan": face_plan},
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
                                "face_tracking": {
                                    "applied": False,
                                    "mode": "center_fallback",
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
        "_render_validation_clip",
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
    allowed = tmp_path / "work" / "validation_reports" / "face_tracking_motion"

    path = write_face_motion_report(
        _result(),
        workspace_root=tmp_path,
        report_dir=allowed,
    )

    assert path.is_file()
    assert path.is_relative_to(tmp_path / "work" / "validation_reports")
    with pytest.raises(ValueError, match="work"):
        write_face_motion_report(
            _result(),
            workspace_root=tmp_path,
            report_dir=tmp_path / "reports",
        )


def test_report_stores_no_raw_frames(tmp_path: Path) -> None:
    path = write_face_motion_report(
        _result(frames_sampled=4),
        workspace_root=tmp_path,
        report_dir=tmp_path / "work" / "validation_reports" / "face_tracking_motion",
        details={"numeric_metric": 0.5},
    )
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert report_contains_private_frame_data(payload) is False
    assert "raw_frames" not in payload
    assert "raw_frames" not in payload["face_motion_validation_result_v1"]


def test_synthetic_mode_makes_no_external_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[list[str]] = []

    def capture_command(command: list[str], **_kwargs: Any) -> SimpleNamespace:
        commands.append(command)
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(validator, "_run", capture_command)
    monkeypatch.setattr(
        validator,
        "_render_validation_clip",
        lambda **_kwargs: {
            "render_completed": True,
            "output_mp4_valid": True,
            "filtergraph_contains_motion": True,
            "duration_delta": 0.0,
            "probe": {},
            "errors": [],
            "warnings": [],
        },
    )

    result, _details = validator.run_synthetic_fallback()

    assert result.external_calls_made is False
    assert commands
    assert not any("://" in argument for command in commands for argument in command)


def test_local_mode_requires_explicit_rights_confirmation(tmp_path: Path) -> None:
    video = tmp_path / "rights-cleared.mp4"
    video.write_bytes(b"video")

    resolved, errors = validate_local_face_path(video, rights_confirmed=False)

    assert resolved is None
    assert any("confirm-rights" in error for error in errors)
