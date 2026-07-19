"""Focused tests for Analysis Signal Activation V2."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from tools import validate_analysis_signals as validator

from olympus.analysis import (
    AnalysisSignalHealthV1,
    AnalysisSignalState,
    AnalysisSignalStatusV1,
)
from olympus.analysis import (
    availability as availability_module,
)
from olympus.analysis.audio_signals import analyze_pcm_samples
from olympus.analysis.emotion_signals import build_emotion_timeline
from olympus.analysis.signals import build_analysis_signals_v2
from olympus.analysis.speaker_signals import build_speaker_segmentation
from olympus.analysis.visual_signals import (
    build_scene_signal,
    build_shot_signal,
    build_visual_pacing_signal,
    parse_scene_metadata,
)
from olympus.data.storage.local import LocalStorage
from olympus.domain.contracts.editing import EditingStageContext
from olympus.domain.contracts.planning import PlanningStageContext
from olympus.domain.contracts.story import StoryStageContext
from olympus.domain.contracts.virality import ViralityStageContext
from olympus.domain.entities.analysis import (
    Analysis,
    AnalysisStatus,
    StageResult,
    StageStatus,
)
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.utils import utc_now


def _status(
    name: str,
    state: AnalysisSignalState,
    *,
    available: bool,
    confidence: float = 0.5,
) -> AnalysisSignalStatusV1:
    return AnalysisSignalStatusV1(
        signal_name=name,
        available=available,
        status=state,
        confidence=confidence,
        provider="test",
        fallback_used=state is AnalysisSignalState.FALLBACK,
        reason=None if available else "dependency_missing",
    )


def _project() -> Project:
    now = utc_now()
    return Project(
        id="proj_signal_test",
        name="Signal test",
        source_filename="source.mp4",
        storage_key="uploads/test/source.mp4",
        size_bytes=100,
        video_format="mp4",
        content_type="video/mp4",
        duration_seconds=6.0,
        width=320,
        height=180,
        status=ProjectStatus.UPLOADED,
        created_at=now,
        updated_at=now,
    )


def _analysis_with_artifact(artifact: dict[str, Any]) -> Analysis:
    now = utc_now()
    return Analysis(
        project_id="proj_signal_test",
        pipeline_version="2",
        status=AnalysisStatus.COMPLETED,
        created_at=now,
        updated_at=now,
        stages=[
            StageResult(
                stage="signal_health",
                status=StageStatus.COMPLETED,
                version="1",
                data={"analysis_signals_v2": artifact},
            )
        ],
    )


def _optional_artifact(stage_name: str) -> dict[str, Any]:
    stages = {
        stage_name: StageResult(
            stage=stage_name,
            status=StageStatus.UNAVAILABLE,
            reason="Required dependency/model is missing.",
        )
    }
    return build_analysis_signals_v2(
        project_id="proj_signal_test",
        source_id="uploads/test/source.mp4",
        stages=stages,
    )


def test_signal_status_contract_serializes() -> None:
    status = _status("scene_detection", AnalysisSignalState.AVAILABLE, available=True)

    payload = status.to_dict()

    assert payload["signal_name"] == "scene_detection"
    assert payload["status"] == "available"
    assert json.loads(json.dumps(payload))["available"] is True


def test_signal_health_counts_are_correct() -> None:
    health = AnalysisSignalHealthV1.build(
        project_id="proj_signal_test",
        source_id="source",
        signals=[
            _status("one", AnalysisSignalState.AVAILABLE, available=True),
            _status("two", AnalysisSignalState.PARTIAL, available=True),
            _status("three", AnalysisSignalState.FALLBACK, available=True),
            _status("four", AnalysisSignalState.UNAVAILABLE, available=False),
            _status("five", AnalysisSignalState.FAILED, available=False),
        ],
    )

    assert health.total_signals == 5
    assert health.available_count == 1
    assert health.partial_count == 1
    assert health.fallback_count == 1
    assert health.unavailable_count == 1
    assert health.failed_count == 1


def test_unavailable_optional_dependencies_report_honestly(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(availability_module, "module_available", lambda _name: False)
    monkeypatch.setattr(
        availability_module.shutil,
        "which",
        lambda name: f"C:/tools/{name}.exe" if name in {"ffmpeg", "ffprobe"} else None,
    )

    capabilities = availability_module.analysis_capabilities()

    assert capabilities["face_detection"]["available"] is False
    assert capabilities["face_detection"]["reason"] == "dependency_missing"
    assert capabilities["ocr"]["available"] is False
    assert capabilities["speaker_diarization"]["available"] is False


def test_audio_energy_detects_loud_and_quiet_regions() -> None:
    samples = [0.8] * 100 + [0.03] * 100

    result = analyze_pcm_samples(samples, sample_rate=100, window_seconds=0.5)
    labels = [event["label"] for event in result["audio_energy"]["timeline"]["events"]]

    assert "loud" in labels
    assert "quiet" in labels


def test_silence_detection_finds_gap() -> None:
    samples = [0.5] * 100 + [0.0] * 100 + [0.5] * 100

    result = analyze_pcm_samples(samples, sample_rate=100, window_seconds=0.25)
    silence = result["silence"]["timeline"]["events"]

    assert silence
    assert silence[0]["end_seconds"] - silence[0]["start_seconds"] >= 0.9


def test_scene_detection_parses_synthetic_cuts() -> None:
    output = "\n".join(
        [
            "frame:0 pts:24 pts_time:2.000",
            "lavfi.scene_score=0.810000",
            "frame:1 pts:48 pts_time:4.000",
            "lavfi.scene_score=0.760000",
        ]
    )

    boundaries = parse_scene_metadata(output)
    signal = build_scene_signal(boundaries, duration_seconds=6.0)

    assert len(boundaries) == 2
    assert len(signal["scenes"]) == 3


def test_shot_detection_produces_segments() -> None:
    scenes = build_scene_signal(
        [{"time": 2.0, "score": 0.8}, {"time": 4.0, "score": 0.8}],
        duration_seconds=6.0,
    )

    shots = build_shot_signal(scenes, duration_seconds=6.0)

    assert len(shots["shots"]) == 3
    assert shots["shots"][-1]["end"] == 6.0


def test_visual_pacing_is_derived_from_shots() -> None:
    shots = [
        {"id": f"shot_{index}", "start": float(index), "end": float(index + 1)}
        for index in range(6)
    ]

    pacing = build_visual_pacing_signal(shots, duration_seconds=6.0)

    assert pacing["overall_score"] > 0.0
    assert pacing["status"]["status"] == "partial"


def test_speaker_segmentation_uses_transcript_labels() -> None:
    result = build_speaker_segmentation(
        [
            {"start": 0.0, "end": 1.0, "speaker": "speaker_a"},
            {"start": 1.1, "end": 2.0, "speaker": "speaker_b"},
        ]
    )

    assert result is not None
    assert result["diarization_available"] is True
    assert result["speaker_segmentation"]["status"]["status"] == "available"


def test_speaker_fallback_uses_silence_turns() -> None:
    result = build_speaker_segmentation(
        None,
        silence_events=[
            {"start_seconds": 1.0, "end_seconds": 1.5},
            {"start_seconds": 3.0, "end_seconds": 3.5},
        ],
        duration_seconds=5.0,
    )

    assert result is not None
    assert result["diarization_available"] is False
    assert result["speaker_segmentation"]["status"]["status"] == "fallback"
    assert result["timeline"][-1]["end"] == 5.0


def test_emotion_timeline_is_marked_as_heuristic_fallback() -> None:
    result = build_emotion_timeline(
        [{"start": 0.0, "end": 1.0, "text": "Wow, this is amazing!"}],
        audio_energy_events=[{"start_seconds": 0.0, "end_seconds": 1.0, "score": 0.8}],
    )

    assert result is not None
    assert result["emotion_timeline"]["status"]["status"] == "fallback"
    assert result["timeline"][0]["method"] == "transcript_audio_heuristic"


def test_ocr_unavailable_does_not_fake_text() -> None:
    artifact = _optional_artifact("ocr")

    assert artifact["ocr"]["status"]["available"] is False
    assert "text" not in artifact["ocr"]


def test_face_unavailable_does_not_fake_faces() -> None:
    artifact = _optional_artifact("face_detection")

    assert artifact["face_detection"]["status"]["available"] is False
    assert "detections" not in artifact["face_detection"]


def test_object_unavailable_does_not_fake_classes() -> None:
    artifact = _optional_artifact("object_detection")

    assert artifact["object_detection"]["status"]["available"] is False
    assert "objects" not in artifact["object_detection"]


def test_downstream_contexts_tolerate_unavailable_signals(tmp_path: Path) -> None:
    artifact = _optional_artifact("face_detection")
    analysis = _analysis_with_artifact(artifact)
    project = _project()
    storage = LocalStorage(str(tmp_path))
    contexts = [
        StoryStageContext(project=project, storage=storage, analysis=analysis),
        ViralityStageContext(project=project, storage=storage, analysis=analysis),
        PlanningStageContext(project=project, storage=storage, analysis=analysis),
        EditingStageContext(project=project, storage=storage, analysis=analysis),
    ]

    for context in contexts:
        signal = context.cognitive_signal("face_detection")
        assert signal is not None
        assert signal["status"]["available"] is False
        assert context.cognitive_signal("missing_signal") is None


def test_validator_synthetic_mode_writes_report(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    report_root = tmp_path / "work" / "validation_reports"
    report_dir = report_root / "analysis_signals"

    async def fake_synthetic(*, ffmpeg_binary: str = "ffmpeg") -> dict[str, Any]:
        del ffmpeg_binary
        return {
            "mode": "synthetic",
            "passed": True,
            "signal_health": {
                "total_signals": 1,
                "available_count": 1,
                "partial_count": 0,
                "fallback_count": 0,
                "unavailable_count": 0,
                "failed_count": 0,
            },
            "warnings": [],
            "errors": [],
        }

    monkeypatch.setattr(validator, "ROOT", tmp_path)
    monkeypatch.setattr(validator, "run_synthetic", fake_synthetic)

    exit_code = validator.main(["--synthetic", "--report-dir", str(report_dir)])

    assert exit_code == 0
    assert (report_dir / validator.REPORT_NAME).is_file()
    assert (report_dir / validator.SUMMARY_NAME).is_file()


def test_project_inspection_does_not_rerun_analysis(tmp_path: Path) -> None:
    project_id = "proj_existing_signal"
    artifact = _optional_artifact("face_detection")
    artifact_path = (
        tmp_path / "analysis" / project_id / "stages" / "signal_health.json"
    )
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_text(
        json.dumps({"status": "completed", "data": {"analysis_signals_v2": artifact}}),
        encoding="utf-8",
    )

    report = validator.inspect_project(project_id, storage_root=tmp_path)

    assert report["inspection_only"] is True
    assert report["analysis_rerun"] is False
    assert report["artifact_path"] == str(artifact_path)


def test_signal_artifact_stores_no_raw_frames_or_media() -> None:
    artifact = _optional_artifact("object_detection")

    assert validator._contains_forbidden_payload(artifact) is False
    assert validator._contains_forbidden_payload({"raw_frames": [b"frame"]}) is True
    assert not any(
        math.isnan(float(signal["confidence"]))
        for signal in artifact["signal_health"]["signals"]
    )
