"""Validate BOBA Output Quality Reviewer V1 with offline read-only fixtures."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal

from pydantic import Field

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for import_path in (ROOT, SRC):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from olympus.boba import output_quality_reviewer as quality  # noqa: E402
from olympus.boba.contracts import BobaContract, now_iso  # noqa: E402
from olympus.boba.output_quality_reviewer import (  # noqa: E402
    BobaCreativeQualityAssessmentV1,
    BobaCreativeQualityDimensionV1,
    BobaOutputAcceptanceDecisionV1,
    BobaOutputBaselineComparisonV1,
    BobaOutputQualityHandoffV1,
    BobaOutputQualityIssueV1,
    BobaOutputQualityRegressionV1,
    BobaOutputQualityReviewerSetV1,
    BobaOutputQualityReviewerV1,
    BobaOutputQualitySignalUsageV1,
    BobaOutputReviewModeV1,
    BobaOutputReviewSourceTypeV1,
    BobaReviewedOutputArtifactV1,
    BobaTechnicalQualityAssessmentV1,
    BobaTechnicalQualityCheckV1,
    build_creative_quality_dimensions,
    build_human_review_package,
    build_output_quality_handoffs,
    build_read_only_quality_validator_registry,
    compare_output_to_baseline,
    make_output_acceptance_decision,
    validate_caption_events,
)
from olympus.boba.store import BobaMemoryStore  # noqa: E402

REPORT_ROOT = (
    ROOT / "work" / "validation_reports" / "boba_output_quality_reviewer"
)
SYNTHETIC_PROJECT_ID = "proj_boba_output_quality_reviewer_synthetic"
CASE_ID = "quality_validator_case"


class BobaOutputQualityReviewerValidatorReportV1(BobaContract):
    """Compact, JSON-safe Output Quality Reviewer validation proof."""

    schema_version: Literal["boba_output_quality_reviewer_validator_v1"] = (
        "boba_output_quality_reviewer_validator_v1"
    )
    mode: Literal["self_check", "synthetic_project", "project_id"]
    created_at: str = Field(default_factory=now_iso)
    passed: bool
    project_id: str | None = None
    scenario_count: int = Field(default=0, ge=0)
    passed_scenario_count: int = Field(default=0, ge=0)
    scenario_results: dict[str, bool] = Field(default_factory=dict)
    ffprobe_available: bool
    ffmpeg_available: bool
    generated_fixture_only: bool = True
    output_modified: Literal[False] = False
    source_media_modified: Literal[False] = False
    workflow_resumed: Literal[False] = False
    rendering_used_by_reviewer: Literal[False] = False
    fallback_execution_used: Literal[False] = False
    network_access_used: Literal[False] = False
    external_api_used: Literal[False] = False
    upload_used: Literal[False] = False
    publication_used: Literal[False] = False
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)
    errors: list[str] = Field(default_factory=list, max_length=64)


def _write_report(
    report: BobaOutputQualityReviewerValidatorReportV1,
    report_root: Path,
) -> None:
    report_root.mkdir(parents=True, exist_ok=True)
    payload = report.model_dump_json(indent=2)
    (report_root / "latest.json").write_text(payload + "\n", encoding="utf-8")


def _status(
    report: BobaOutputQualityReviewerSetV1,
    category: str,
) -> str:
    assessment = report.technical_assessments[-1]
    return next(
        (
            item.status
            for item in assessment.checks
            if item.category == category
        ),
        "missing",
    )


def _dimension_status(
    assessment: BobaCreativeQualityAssessmentV1,
    dimension: str,
) -> str:
    return next(
        (
            item.status
            for item in assessment.dimensions
            if item.dimension == dimension
        ),
        "missing",
    )


def _technical(
    *,
    eligible: bool = True,
    failed: list[str] | None = None,
    unavailable: list[str] | None = None,
    checks: list[BobaTechnicalQualityCheckV1] | None = None,
) -> BobaTechnicalQualityAssessmentV1:
    failures = failed or []
    unavailable_checks = unavailable or []
    return BobaTechnicalQualityAssessmentV1(
        technical_assessment_id="technical_validator",
        review_case_id=CASE_ID,
        checks=checks or [],
        technical_score=1.0 if eligible else 0.2,
        required_checks_passed=eligible
        and not failures
        and not unavailable_checks,
        failed_required_checks=failures,
        unavailable_required_checks=unavailable_checks,
        technical_acceptance_eligible=eligible
        and not failures
        and not unavailable_checks,
    )


def _check(
    category: str,
    status: str,
    *,
    required: bool = True,
) -> BobaTechnicalQualityCheckV1:
    return BobaTechnicalQualityCheckV1(
        technical_check_id=f"check_{category}_{status}",
        review_case_id=CASE_ID,
        category=category,
        name=category.replace("_", " "),
        required=required,
        status=status,
        observed_value=status,
        expected_value="passed",
        blocks_acceptance=required and status in {"failed", "unavailable"},
        failure_summary=(
            f"{category} failed." if status in {"failed", "unavailable"} else ""
        ),
    )


def _dimension(
    name: str,
    status: str = "acceptable",
    *,
    blocking: bool = False,
    human: bool = False,
) -> BobaCreativeQualityDimensionV1:
    return BobaCreativeQualityDimensionV1(
        creative_dimension_id=f"dimension_{name}",
        review_case_id=CASE_ID,
        dimension=name,
        status=status,
        score=0.8 if status in {"strong", "acceptable"} else 0.2,
        requires_human_review=human,
        blocking=blocking,
    )


def _creative(
    *,
    eligible: bool = True,
    human: bool = False,
    dimensions: list[BobaCreativeQualityDimensionV1] | None = None,
) -> BobaCreativeQualityAssessmentV1:
    return BobaCreativeQualityAssessmentV1(
        creative_assessment_id="creative_validator",
        review_case_id=CASE_ID,
        dimensions=dimensions or [],
        creative_score=0.8 if eligible else 0.2,
        evidence_coverage=0.9 if eligible else 0.3,
        creative_acceptance_eligible=eligible,
        human_review_required=human,
        subjective_uncertainty=["Human judgment is required."] if human else [],
    )


def _decision(
    *,
    rights_status: str = "owned",
    safety_status: str = "passed",
    technical: BobaTechnicalQualityAssessmentV1 | None = None,
    creative: BobaCreativeQualityAssessmentV1 | None = None,
    comparison: BobaOutputBaselineComparisonV1 | None = None,
    regressions: list[BobaOutputQualityRegressionV1] | None = None,
    baseline_required: bool = False,
) -> BobaOutputAcceptanceDecisionV1:
    return make_output_acceptance_decision(
        review_case_id=CASE_ID,
        rights_status=rights_status,
        safety_status=safety_status,
        technical=technical or _technical(),
        creative=creative or _creative(),
        comparison=comparison,
        regressions=regressions or [],
        issues=[],
        baseline_required=baseline_required,
    )


def _artifact(
    *,
    artifact_id: str,
    reference: str,
    width: int = 320,
    height: int = 568,
    duration: float = 1.0,
    frame_rate: float = 24.0,
    audio: bool = True,
    captions: bool = False,
    checksum: str = "sha256:same",
) -> BobaReviewedOutputArtifactV1:
    return BobaReviewedOutputArtifactV1(
        output_artifact_id=artifact_id,
        project_id=SYNTHETIC_PROJECT_ID,
        clip_id="clip_validator",
        sanitized_artifact_reference=reference,
        artifact_type="video",
        expected_source_window={"start_seconds": 2.0, "end_seconds": 3.0},
        expected_duration_seconds=duration,
        expected_resolution={"width": width, "height": height},
        expected_frame_rate=frame_rate,
        expected_audio=audio,
        expected_captions=captions,
        checksum=checksum,
        file_size_bytes=100,
        rights_status="owned",
    )


def _resolved(
    *,
    artifact_id: str,
    reference: str,
    width: int = 320,
    height: int = 568,
    duration: float = 1.0,
    frame_rate: float = 24.0,
    audio: bool = True,
    captions: bool = False,
    hook: str = "acceptable",
    story: str = "acceptable",
    payoff: str = "acceptable",
    checksum: str = "sha256:same",
) -> quality.ResolvedReviewedOutputV1:
    artifact = _artifact(
        artifact_id=artifact_id,
        reference=reference,
        width=width,
        height=height,
        duration=duration,
        frame_rate=frame_rate,
        audio=audio,
        captions=captions,
        checksum=checksum,
    )
    metadata = {
        "manifest_entry": {
            "storage_key": reference,
            "width": width,
            "height": height,
            "duration": duration,
            "fps": frame_rate,
            "has_audio": audio,
            "subtitles_included": captions,
            "video_codec": "h264",
            "audio_codec": "aac" if audio else None,
            "container": "mp4",
        },
        "actual_source_window": {"start_seconds": 2.0, "end_seconds": 3.0},
        "sync_validation": {"passed": True},
        "caption_timing_status": "passed",
        "framing_status": "passed",
        "story_completeness_status": story,
        "hook_status": hook,
        "payoff_status": payoff,
        "pacing_status": "acceptable",
        "motion_status": "acceptable",
        "music_fit_status": "acceptable",
    }
    return quality.ResolvedReviewedOutputV1(
        artifact=artifact,
        path=Path(reference),
        metadata=metadata,
        source_type="normal_render",
        path_scope="storage",
    )


def _compare(
    baseline: quality.ResolvedReviewedOutputV1,
    reviewed: quality.ResolvedReviewedOutputV1,
    *,
    creative: BobaCreativeQualityAssessmentV1 | None = None,
) -> tuple[BobaOutputBaselineComparisonV1, list[BobaOutputQualityRegressionV1]]:
    collector = quality._EvidenceCollector(
        review_case_id=CASE_ID,
        output_reference=reviewed.artifact.sanitized_artifact_reference,
    )
    return compare_output_to_baseline(
        review_case_id=CASE_ID,
        reviewed=reviewed,
        baseline=baseline,
        technical=_technical(),
        creative=creative
        or _creative(
            dimensions=[
                _dimension("story_completeness"),
                _dimension("hook_strength"),
                _dimension("payoff_preservation"),
                _dimension("pacing"),
                _dimension("motion_balance"),
                _dimension("music_mood_fit"),
            ]
        ),
        collector=collector,
        comparison_basis="manual_baseline",
        non_negotiable_requirements=[],
    )


def _run_fixture_command(command: list[str]) -> bool:
    completed = subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=False,
        shell=False,
        timeout=60,
    )
    return completed.returncode == 0


def _create_media_fixtures(
    root: Path,
    *,
    ffmpeg_binary: str,
) -> dict[str, Path]:
    fixture_root = root / "storage_data" / "render" / SYNTHETIC_PROJECT_ID / "run"
    fixture_root.mkdir(parents=True)
    audio_video = fixture_root / "valid-av.mp4"
    video_only = fixture_root / "video-only.mp4"
    audio_only = fixture_root / "audio-only.m4a"
    common = [
        ffmpeg_binary,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-y",
        "-threads",
        "1",
        "-filter_threads",
        "1",
    ]
    av_ok = _run_fixture_command(
        [
            *common,
            "-f",
            "lavfi",
            "-i",
            "color=c=0x23324a:s=320x568:r=24:d=1",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=1",
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-t",
            "1",
            "-c:v",
            "mpeg4",
            "-q:v",
            "5",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-ar",
            "48000",
            "-ac",
            "1",
            str(audio_video),
        ]
    )
    video_ok = _run_fixture_command(
        [
            *common,
            "-f",
            "lavfi",
            "-i",
            "color=c=0x23324a:s=320x568:r=24:d=1",
            "-t",
            "1",
            "-c:v",
            "mpeg4",
            "-q:v",
            "5",
            "-pix_fmt",
            "yuv420p",
            str(video_only),
        ]
    )
    audio_ok = _run_fixture_command(
        [
            *common,
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=1",
            "-t",
            "1",
            "-c:a",
            "aac",
            "-ar",
            "48000",
            "-ac",
            "1",
            str(audio_only),
        ]
    )
    if not all((av_ok, video_ok, audio_ok)):
        return {}
    return {
        "audio_video": audio_video,
        "video_only": video_only,
        "audio_only": audio_only,
    }


def _known_media(
    path: Path,
    storage_root: Path,
    *,
    expected_duration: float = 1.0,
    expected_width: int = 320,
    expected_height: int = 568,
    expected_fps: float = 24.0,
    expected_audio: bool = True,
    expected_captions: bool = False,
    artifact_type: str = "video",
    source_window: tuple[float, float] = (2.0, 3.0),
    actual_window: tuple[float, float] = (2.0, 3.0),
    frame_count: int | None = None,
    audio_sample_rate: int = 48000,
    audio_channels: int = 1,
    sync_delta: float = 0.0,
    **extra: Any,
) -> dict[str, Any]:
    reference = path.resolve().relative_to(storage_root.resolve()).as_posix()
    checksum = (
        "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        if path.is_file()
        else ""
    )
    manifest_entry = {
        "storage_key": reference,
        "checksum": checksum,
        "duration": 1.0,
        "width": 320,
        "height": 568,
        "fps": 24.0,
        "frame_count": frame_count,
        "has_audio": path.name != "video-only.mp4",
        "subtitles_included": expected_captions,
        "video_codec": None if path.suffix == ".m4a" else "mpeg4",
        "audio_codec": None if path.name == "video-only.mp4" else "aac",
        "audio_sample_rate": audio_sample_rate,
        "audio_channels": audio_channels,
        "container": "mp4",
        "metadata": {
            "sync_validation": {
                "passed": abs(sync_delta) <= 0.15,
                "actual_video_duration": 1.0,
                "actual_audio_duration": 1.0 + sync_delta,
                "actual_video_start_time": 0.0,
                "actual_audio_start_time": 0.0,
            }
        },
    }
    return {
        "artifact_id": f"artifact_{path.stem}_{len(extra)}",
        "project_id": SYNTHETIC_PROJECT_ID,
        "reference": reference,
        "path_scope": "storage",
        "artifact_type": artifact_type,
        "source_type": "normal_render",
        "expected_checksum": checksum,
        "expected_duration_seconds": expected_duration,
        "expected_resolution": {
            "width": expected_width,
            "height": expected_height,
        },
        "expected_frame_rate": expected_fps,
        "expected_audio": expected_audio,
        "expected_captions": expected_captions,
        "expected_audio_sample_rate": audio_sample_rate,
        "expected_audio_channels": audio_channels,
        "expected_source_window": {
            "start_seconds": source_window[0],
            "end_seconds": source_window[1],
        },
        "actual_source_window": {
            "start_seconds": actual_window[0],
            "end_seconds": actual_window[1],
        },
        "manifest_entry": manifest_entry,
        **extra,
    }


def _review(
    reviewer: BobaOutputQualityReviewerV1,
    artifact: dict[str, Any],
    *,
    mode: BobaOutputReviewModeV1 = "artifact_only",
    rights: str = "owned",
    safety: str = "passed",
    creative_artifacts: dict[str, Any] | None = None,
    validation_artifacts: dict[str, Any] | None = None,
    required_quality_properties: list[str] | None = None,
) -> BobaOutputQualityReviewerSetV1:
    return reviewer.review(
        project_id=SYNTHETIC_PROJECT_ID,
        output_reference=str(artifact["reference"]),
        known_output_artifacts=[artifact],
        source_id=SYNTHETIC_PROJECT_ID,
        source_media_reference=f"uploads/{SYNTHETIC_PROJECT_ID}/source.mp4",
        review_mode=mode,
        rights_status=rights,
        safety_status=safety,
        creative_artifacts=creative_artifacts or {},
        validation_artifacts=validation_artifacts or {},
        required_quality_properties=required_quality_properties or [],
    )


def _creative_review(
    artifacts: dict[str, Any],
    *,
    technical: BobaTechnicalQualityAssessmentV1 | None = None,
    expected_captions: bool = False,
) -> BobaCreativeQualityAssessmentV1:
    collector = quality._EvidenceCollector(
        review_case_id=CASE_ID,
        output_reference="render/output.mp4",
    )
    return build_creative_quality_dimensions(
        review_case_id=CASE_ID,
        artifact=_artifact(
            artifact_id="creative_artifact",
            reference="render/output.mp4",
            captions=expected_captions,
        ),
        technical=technical or _technical(),
        creative_artifacts=artifacts,
        collector=collector,
        signal_usage=BobaOutputQualitySignalUsageV1(),
    )


def run_self_check(
    report_root: Path = REPORT_ROOT,
) -> BobaOutputQualityReviewerValidatorReportV1:
    registry = build_read_only_quality_validator_registry()
    scenarios: dict[str, bool] = {}
    errors: list[str] = []
    try:
        with TemporaryDirectory(prefix="boba-output-quality-self-check-") as raw:
            root = Path(raw)
            evidence = root / "evidence"
            evidence.mkdir()
            probe_available = registry["ffprobe_media"].available
            decode_available = registry["ffmpeg_decode"].available
            contract = BobaOutputQualityReviewerSetV1(
                project_id=SYNTHETIC_PROJECT_ID,
                source_id=SYNTHETIC_PROJECT_ID,
            )
            scenarios = {
                "reviewer_imports": BobaOutputQualityReviewerV1 is not None,
                "tool_recovery_imports": (
                    __import__("olympus.boba.tool_recovery") is not None
                ),
                "contracts_serialize": bool(
                    json.dumps(contract.model_dump(mode="json"))
                ),
                "read_only_registry_builds": set(registry)
                == {
                    "ffprobe_media",
                    "ffmpeg_decode",
                    "checksum",
                    "json_schema",
                    "caption_timing",
                    "face_motion_artifact",
                    "multi_speaker_artifact",
                },
                "ffprobe_availability_detected_honestly": (
                    probe_available == bool(shutil.which("ffprobe"))
                ),
                "ffmpeg_availability_detected_honestly": (
                    decode_available == bool(shutil.which("ffmpeg"))
                ),
                "temporary_evidence_workspace_writable": (
                    evidence.is_dir() and evidence.resolve().is_relative_to(root)
                ),
                "network_not_required": True,
                "output_modification_not_required": True,
                "source_media_not_required": True,
                "rendering_not_required": True,
                "workflow_resume_not_required": True,
            }
    except Exception as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
    report = BobaOutputQualityReviewerValidatorReportV1(
        mode="self_check",
        passed=bool(scenarios) and all(scenarios.values()) and not errors,
        scenario_count=len(scenarios),
        passed_scenario_count=sum(scenarios.values()),
        scenario_results=scenarios,
        ffprobe_available=registry["ffprobe_media"].available,
        ffmpeg_available=registry["ffmpeg_decode"].available,
        limitations=[
            "Self-check validates contracts and local capability discovery only."
        ],
        errors=errors,
    )
    _write_report(report, report_root)
    return report


def run_synthetic_project(
    report_root: Path = REPORT_ROOT,
) -> BobaOutputQualityReviewerValidatorReportV1:
    registry = build_read_only_quality_validator_registry()
    ffprobe_available = registry["ffprobe_media"].available
    ffmpeg_available = registry["ffmpeg_decode"].available
    scenarios: dict[str, bool] = {}
    errors: list[str] = []
    warnings: list[str] = []
    try:
        with TemporaryDirectory(prefix="boba-output-quality-synthetic-") as raw:
            root = Path(raw)
            storage_root = root / "storage_data"
            reviewer = BobaOutputQualityReviewerV1(
                root,
                storage_root=storage_root,
                evidence_root=root / "evidence",
            )
            media = (
                _create_media_fixtures(
                    root,
                    ffmpeg_binary=str(registry["ffmpeg_decode"].executable),
                )
                if ffmpeg_available
                else {}
            )
            if not (ffprobe_available and media):
                warnings.append(
                    "FFmpeg/FFprobe media fixtures are unavailable; media scenarios "
                    "remain false rather than being reported as fake passes."
                )

            invalid_path = (
                storage_root
                / "render"
                / SYNTHETIC_PROJECT_ID
                / "run"
                / "invalid.mp4"
            )
            invalid_path.parent.mkdir(parents=True, exist_ok=True)
            invalid_path.write_bytes(b"not a media container")
            empty_path = invalid_path.with_name("empty.mp4")
            empty_path.write_bytes(b"")
            missing_path = invalid_path.with_name("missing.mp4")

            real_reports: dict[str, BobaOutputQualityReviewerSetV1] = {}
            if media and ffprobe_available:
                av = media["audio_video"]
                video_only = media["video_only"]
                audio_only = media["audio_only"]
                real_reports["valid"] = _review(
                    reviewer,
                    _known_media(av, storage_root),
                    mode="local_technical_review",
                    validation_artifacts={
                        "duplicate_segment_detected": False,
                        "missing_segment_detected": False,
                    },
                )
                real_reports["missing_video"] = _review(
                    reviewer,
                    _known_media(
                        audio_only,
                        storage_root,
                        artifact_type="video",
                    ),
                    mode="local_technical_review",
                )
                real_reports["missing_audio"] = _review(
                    reviewer,
                    _known_media(
                        video_only,
                        storage_root,
                        expected_audio=True,
                    ),
                    mode="local_technical_review",
                )
                real_reports["unexpected_audio"] = _review(
                    reviewer,
                    _known_media(
                        av,
                        storage_root,
                        expected_audio=False,
                    ),
                    mode="local_technical_review",
                )
                real_reports["short"] = _review(
                    reviewer,
                    _known_media(av, storage_root, expected_duration=2.0),
                    mode="local_technical_review",
                )
                real_reports["long"] = _review(
                    reviewer,
                    _known_media(av, storage_root, expected_duration=0.5),
                    mode="local_technical_review",
                )
                real_reports["lower_resolution"] = _review(
                    reviewer,
                    _known_media(
                        av,
                        storage_root,
                        expected_width=1080,
                        expected_height=1920,
                    ),
                    mode="local_technical_review",
                )
                real_reports["wrong_aspect"] = _review(
                    reviewer,
                    _known_media(
                        av,
                        storage_root,
                        expected_width=320,
                        expected_height=320,
                    ),
                    mode="local_technical_review",
                )
                real_reports["lower_fps"] = _review(
                    reviewer,
                    _known_media(av, storage_root, expected_fps=30.0),
                    mode="local_technical_review",
                )
                real_reports["channel_mismatch"] = _review(
                    reviewer,
                    _known_media(
                        av,
                        storage_root,
                        audio_channels=2,
                    ),
                    mode="local_technical_review",
                )
                real_reports["invalid"] = _review(
                    reviewer,
                    _known_media(invalid_path, storage_root),
                    mode="local_technical_review",
                )
            missing_report = _review(
                reviewer,
                _known_media(missing_path, storage_root),
            )
            empty_report = _review(
                reviewer,
                _known_media(empty_path, storage_root),
            )

            saved_path = invalid_path.with_name("saved-evidence.mp4")
            saved_path.write_bytes(b"artifact-only media bytes")
            saved = _known_media(saved_path, storage_root)
            saved["manifest_entry"]["video_codec"] = "h264"
            saved["manifest_entry"]["audio_codec"] = "aac"
            saved["manifest_entry"]["frame_count"] = 24
            artifact_report = _review(reviewer, saved)
            frame_anomaly_artifact = json.loads(json.dumps(saved))
            frame_anomaly_artifact["artifact_id"] = "frame_anomaly"
            frame_anomaly_artifact["manifest_entry"]["frame_count"] = 500
            frame_anomaly_report = _review(reviewer, frame_anomaly_artifact)
            sync_fail_artifact = json.loads(json.dumps(saved))
            sync_fail_artifact["artifact_id"] = "sync_fail"
            sync_fail_artifact["manifest_entry"]["metadata"][
                "sync_validation"
            ]["actual_audio_duration"] = 1.5
            sync_fail_report = _review(reviewer, sync_fail_artifact)
            window_fail_artifact = json.loads(json.dumps(saved))
            window_fail_artifact["artifact_id"] = "window_fail"
            window_fail_artifact["actual_source_window"] = {
                "start_seconds": 2.5,
                "end_seconds": 3.5,
            }
            window_fail_report = _review(reviewer, window_fail_artifact)
            truncation_artifact = json.loads(json.dumps(saved))
            truncation_artifact["artifact_id"] = "truncation"
            truncation_report = _review(
                reviewer,
                truncation_artifact,
                validation_artifacts={"truncation_detected": True},
            )
            duplicate_report = _review(
                reviewer,
                saved,
                validation_artifacts={"duplicate_segment_detected": True},
                required_quality_properties=["No duplicate segment"],
            )
            missing_segment_report = _review(
                reviewer,
                saved,
                validation_artifacts={"missing_segment_detected": True},
                required_quality_properties=["No required segment is missing"],
            )
            caption_artifact = json.loads(json.dumps(saved))
            caption_artifact["artifact_id"] = "caption_valid"
            caption_artifact["expected_captions"] = True
            caption_artifact["manifest_entry"]["subtitles_included"] = True
            caption_valid = _review(
                reviewer,
                caption_artifact,
                validation_artifacts={
                    "caption_events": [
                        {"start": 0.0, "end": 0.45, "text": "Opening"},
                        {"start": 0.5, "end": 0.95, "text": "Payoff"},
                    ]
                },
            )
            caption_missing = _review(
                reviewer,
                {
                    **caption_artifact,
                    "artifact_id": "caption_missing",
                    "manifest_entry": {
                        **caption_artifact["manifest_entry"],
                        "subtitles_included": False,
                    },
                },
            )
            caption_outside = _review(
                reviewer,
                {**caption_artifact, "artifact_id": "caption_outside"},
                validation_artifacts={
                    "caption_events": [
                        {"start": 0.5, "end": 1.5, "text": "Too late"}
                    ]
                },
            )
            caption_nonmonotonic = validate_caption_events(
                [
                    {"start": 0.5, "end": 0.8, "text": "Second"},
                    {"start": 0.0, "end": 0.4, "text": "First"},
                ],
                clip_duration_seconds=1.0,
            )
            caption_overlap = validate_caption_events(
                [
                    {"start": 0.0, "end": 0.7, "text": "First"},
                    {"start": 0.5, "end": 0.9, "text": "Second"},
                ],
                clip_duration_seconds=1.0,
            )

            face_pass_artifact = json.loads(json.dumps(saved))
            face_pass_artifact["artifact_id"] = "face_pass"
            face_pass_artifact["face_tracking_applied"] = True
            face_pass = _review(
                reviewer,
                face_pass_artifact,
                validation_artifacts={
                    "face_motion_validation": {
                        "passed": True,
                        "face_crop_safety_evaluated": True,
                        "face_cutoff_detected": False,
                    }
                },
            )
            face_fail = _review(
                reviewer,
                {**face_pass_artifact, "artifact_id": "face_fail"},
                validation_artifacts={
                    "face_motion_validation": {
                        "passed": False,
                        "face_crop_safety_evaluated": True,
                        "face_cutoff_detected": True,
                    }
                },
            )
            face_unknown = _review(
                reviewer,
                {**face_pass_artifact, "artifact_id": "face_unknown"},
            )
            multi_pass_artifact = json.loads(json.dumps(saved))
            multi_pass_artifact["artifact_id"] = "multi_pass"
            multi_pass_artifact["layout_strategy"] = "two_speaker_stack"
            multi_pass = _review(
                reviewer,
                multi_pass_artifact,
                validation_artifacts={
                    "multi_speaker_validation": {
                        "passed": True,
                        "layout_strategy": "two_speaker_stack",
                        "subject_region_safety_evaluated": True,
                    }
                },
            )
            multi_unknown = _review(
                reviewer,
                {**multi_pass_artifact, "artifact_id": "multi_unknown"},
            )

            strong_hook = _creative_review(
                {
                    "hook_retention": {
                        "hook_score": 0.9,
                        "hook_line": "This one mistake changes everything.",
                        "reasoning": "Specific opening curiosity gap.",
                    }
                }
            )
            weak_hook = _creative_review(
                {"hook_retention": {"hook_score": 0.2, "weak_hook": True}}
            )
            unavailable_hook = _creative_review({})
            complete_story = _creative_review(
                {
                    "boundary_quality": {
                        "completeness_score": 0.9,
                        "payoff_present": True,
                        "payoff_time": 2.9,
                        "payoff_score": 0.85,
                        "pacing_score": 0.8,
                        "abrupt_end_risk": 0.1,
                    }
                }
            )
            missing_payoff = _creative_review(
                {
                    "boundary_quality": {
                        "completeness_score": 0.2,
                        "payoff_present": False,
                    }
                }
            )
            abrupt_story = _creative_review(
                {
                    "boundary_quality": {
                        "pacing_score": 0.8,
                        "abrupt_end_risk": 0.9,
                    }
                }
            )
            pacing_uncertain = _creative_review({})
            caption_readable = _creative_review(
                {
                    "render_metadata": {
                        "caption_readability_validation": {"passed": True}
                    }
                },
                technical=_technical(
                    checks=[
                        _check("caption_presence", "passed"),
                        _check("caption_timing", "passed"),
                        _check("caption_bounds", "passed"),
                    ]
                ),
                expected_captions=True,
            )
            caption_uncertain = _creative_review(
                {},
                expected_captions=True,
            )
            motion_overload = _creative_review(
                {"caption_motion": {"motion_overload": True}}
            )
            music_present = _creative_review(
                {
                    "music_mood": {
                        "mood": "hopeful",
                        "should_use_music": True,
                    },
                    "render_metadata": {
                        "music_mixed": True,
                        "music_validation": {
                            "mixed": True,
                            "audible": True,
                            "speech_clarity_passed": True,
                        },
                    },
                }
            )
            music_unavailable = _creative_review(
                {
                    "music_mood": {
                        "mood": "hopeful",
                        "should_use_music": True,
                    }
                }
            )
            repetition = _creative_review(
                {"boundary_quality": {"duplicate_risk": 0.95}}
            )

            baseline = _resolved(
                artifact_id="baseline",
                reference="render/baseline.mp4",
            )
            equivalent_output = _resolved(
                artifact_id="equivalent",
                reference="render/equivalent.mp4",
            )
            equivalent_comparison, equivalent_regressions = _compare(
                baseline,
                equivalent_output,
            )
            resolution_comparison, resolution_regressions = _compare(
                baseline,
                _resolved(
                    artifact_id="low_resolution",
                    reference="render/low-resolution.mp4",
                    width=240,
                    height=426,
                ),
            )
            audio_comparison, audio_regressions = _compare(
                baseline,
                _resolved(
                    artifact_id="missing_audio",
                    reference="render/missing-audio.mp4",
                    audio=False,
                ),
            )
            timing_comparison, timing_regressions = _compare(
                baseline,
                _resolved(
                    artifact_id="timing",
                    reference="render/timing.mp4",
                    duration=0.5,
                ),
            )
            hook_comparison, hook_regressions = _compare(
                _resolved(
                    artifact_id="baseline_hook",
                    reference="render/baseline-hook.mp4",
                    hook="strong",
                ),
                _resolved(
                    artifact_id="weak_hook",
                    reference="render/weak-hook.mp4",
                    hook="weak",
                ),
                creative=_creative(
                    dimensions=[
                        _dimension("story_completeness"),
                        _dimension("hook_strength", "weak"),
                        _dimension("payoff_preservation"),
                        _dimension("pacing"),
                        _dimension("motion_balance"),
                        _dimension("music_mood_fit"),
                    ]
                ),
            )
            minor_regression = BobaOutputQualityRegressionV1(
                quality_regression_id="minor_regression",
                review_case_id=CASE_ID,
                category="music_fit",
                baseline_value="acceptable",
                reviewed_value="weak",
                severity="minor",
                non_negotiable=False,
                disclosed=True,
                approved=True,
                acceptance_impact="disclose",
                recommended_action="Disclose for human approval.",
            )
            non_negotiable_regression = BobaOutputQualityRegressionV1(
                quality_regression_id="non_negotiable",
                review_case_id=CASE_ID,
                category="source_window",
                baseline_value="preserved",
                reviewed_value="changed",
                severity="critical",
                non_negotiable=True,
                acceptance_impact="reject",
                recommended_action="Reject.",
            )
            technical_failure = _decision(
                technical=_technical(eligible=False, failed=["decode"])
            )
            quality_failure = _decision(
                creative=_creative(
                    eligible=False,
                    dimensions=[
                        _dimension(
                            "payoff_preservation",
                            "failed",
                            blocking=True,
                        )
                    ],
                )
            )
            regression_failure = _decision(
                comparison=BobaOutputBaselineComparisonV1(
                    baseline_comparison_id="comparison_failure",
                    review_case_id=CASE_ID,
                    baseline_artifact_id="baseline",
                    reviewed_artifact_id="reviewed",
                    comparison_basis="manual_baseline",
                    non_negotiable_regressions=["source_window"],
                    equivalent_for_required_capability=False,
                ),
                regressions=[non_negotiable_regression],
                baseline_required=True,
            )
            creative_uncertain_decision = _decision(
                creative=_creative(eligible=False, human=True)
            )
            rights_unknown_decision = _decision(rights_status="unknown")
            rights_blocked_decision = _decision(rights_status="blocked")
            safety_blocked_decision = _decision(safety_status="blocked")
            required_unavailable_decision = _decision(
                technical=_technical(
                    eligible=False,
                    unavailable=["ffprobe_media"],
                )
            )
            optional_unavailable = _technical(
                checks=[
                    _check(
                        "subject_visibility",
                        "unavailable",
                        required=False,
                    )
                ]
            )
            accepted_decision = _decision()
            limitation_decision = _decision(
                comparison=BobaOutputBaselineComparisonV1(
                    baseline_comparison_id="comparison_minor",
                    review_case_id=CASE_ID,
                    baseline_artifact_id="baseline",
                    reviewed_artifact_id="reviewed",
                    comparison_basis="manual_baseline",
                    equivalent_for_required_capability=True,
                ),
                regressions=[minor_regression],
                baseline_required=True,
            )
            human_package = build_human_review_package(
                review_case_id=CASE_ID,
                artifact=_artifact(
                    artifact_id="reviewed",
                    reference="render/reviewed.mp4",
                ),
                baseline=None,
                technical=_technical(),
                creative=_creative(eligible=False, human=True),
                comparison=None,
                decision=creative_uncertain_decision,
            )

            handoff_decisions: dict[
                str,
                tuple[
                    BobaOutputAcceptanceDecisionV1,
                    BobaOutputReviewSourceTypeV1,
                    list[BobaOutputQualityIssueV1],
                ],
            ] = {
                "tool_recovery": (
                    BobaOutputAcceptanceDecisionV1(
                        acceptance_decision_id="decision_tool_recovery",
                        review_case_id=CASE_ID,
                        decision="rejected_technical",
                        decision_summary="Recovery output failed.",
                    ),
                    "tool_recovery_output",
                    [],
                ),
                "repair_planner": (
                    quality_failure,
                    "normal_render",
                    [],
                ),
                "root_cause": (
                    technical_failure,
                    "normal_render",
                    [],
                ),
                "validator": (
                    required_unavailable_decision,
                    "normal_render",
                    [],
                ),
                "workflow": (
                    accepted_decision,
                    "normal_render",
                    [],
                ),
                "safety": (
                    safety_blocked_decision,
                    "normal_render",
                    [],
                ),
                "human": (
                    creative_uncertain_decision,
                    "normal_render",
                    [],
                ),
            }
            handoffs: dict[str, list[BobaOutputQualityHandoffV1]] = {
                name: build_output_quality_handoffs(
                    review_case_id=CASE_ID,
                    source_type=source_type,
                    decision=decision,
                    technical=(
                        _technical(eligible=False, failed=["decode"])
                        if name in {"tool_recovery", "root_cause"}
                        else _technical(
                            eligible=False,
                            unavailable=["ffprobe_media"],
                        )
                        if name == "validator"
                        else _technical()
                    ),
                    issues=issues,
                )
                for name, (decision, source_type, issues) in handoff_decisions.items()
            }

            output_before = saved_path.read_bytes()
            source_path = storage_root / "uploads" / SYNTHETIC_PROJECT_ID / "source.mp4"
            source_path.parent.mkdir(parents=True)
            source_path.write_bytes(b"synthetic source remains unchanged")
            source_before = source_path.read_bytes()
            signals = artifact_report.signal_usage

            valid = real_reports.get("valid")
            invalid = real_reports.get("invalid")
            scenarios = {
                "01_valid_video_and_audio_output": bool(
                    valid
                    and valid.technical_assessments[-1].technical_acceptance_eligible
                    and _status(valid, "video_stream") == "passed"
                    and _status(valid, "audio_stream") == "passed"
                ),
                "02_missing_output": _status(missing_report, "artifact_exists")
                == "failed",
                "03_empty_output": _status(empty_report, "artifact_non_empty")
                == "failed",
                "04_invalid_container": bool(
                    invalid and _status(invalid, "media_probe") == "failed"
                ),
                "05_decode_failure": bool(
                    invalid and _status(invalid, "decode") == "failed"
                ),
                "06_missing_video_stream": bool(
                    real_reports.get("missing_video")
                    and _status(real_reports["missing_video"], "video_stream")
                    == "failed"
                ),
                "07_missing_required_audio": bool(
                    real_reports.get("missing_audio")
                    and _status(real_reports["missing_audio"], "audio_presence")
                    == "failed"
                ),
                "08_unexpected_audio_when_disallowed": bool(
                    real_reports.get("unexpected_audio")
                    and _status(real_reports["unexpected_audio"], "audio_presence")
                    == "failed"
                ),
                "09_correct_duration": bool(
                    valid and _status(valid, "duration") == "passed"
                ),
                "10_short_duration": bool(
                    real_reports.get("short")
                    and _status(real_reports["short"], "duration") == "failed"
                ),
                "11_long_duration": bool(
                    real_reports.get("long")
                    and _status(real_reports["long"], "duration") == "failed"
                ),
                "12_correct_resolution": bool(
                    valid and _status(valid, "resolution") == "passed"
                ),
                "13_lower_resolution": bool(
                    real_reports.get("lower_resolution")
                    and _status(real_reports["lower_resolution"], "resolution")
                    == "failed"
                ),
                "14_incorrect_aspect_ratio": bool(
                    real_reports.get("wrong_aspect")
                    and _status(real_reports["wrong_aspect"], "aspect_ratio")
                    == "failed"
                ),
                "15_correct_frame_rate": bool(
                    valid and _status(valid, "frame_rate") == "passed"
                ),
                "16_lower_frame_rate": bool(
                    real_reports.get("lower_fps")
                    and _status(real_reports["lower_fps"], "frame_rate")
                    == "failed"
                ),
                "17_frame_count_mismatch": _status(
                    frame_anomaly_report, "frame_count"
                )
                == "degraded",
                "18_correct_audio_sample_rate": bool(
                    valid and _status(valid, "audio_sample_rate") == "passed"
                ),
                "19_missing_audio_channel": bool(
                    real_reports.get("channel_mismatch")
                    and _status(
                        real_reports["channel_mismatch"],
                        "audio_channels",
                    )
                    == "failed"
                ),
                "20_audio_video_sync_pass": bool(
                    valid and _status(valid, "audio_video_sync") == "passed"
                ),
                "21_audio_video_sync_failure": _status(
                    sync_fail_report, "audio_video_sync"
                )
                == "failed",
                "22_source_window_pass": _status(
                    artifact_report, "source_window"
                )
                == "passed",
                "23_source_window_mismatch": _status(
                    window_fail_report, "source_window"
                )
                == "failed",
                "24_unexpected_truncation": _status(
                    truncation_report, "truncation"
                )
                == "failed",
                "25_duplicate_segment": _status(
                    duplicate_report, "duplicate_segment"
                )
                == "failed",
                "26_missing_segment": _status(
                    missing_segment_report, "missing_segment"
                )
                == "failed",
                "27_caption_present": _status(
                    caption_valid, "caption_presence"
                )
                == "passed",
                "28_required_caption_missing": _status(
                    caption_missing, "caption_presence"
                )
                == "failed",
                "29_caption_outside_clip_bounds": _status(
                    caption_outside, "caption_bounds"
                )
                == "failed",
                "30_non_monotonic_caption_timing": (
                    caption_nonmonotonic["passed"] is False
                    and caption_nonmonotonic["monotonic"] is False
                ),
                "31_caption_overlap_corruption": (
                    caption_overlap["passed"] is False
                    and caption_overlap["overlap_corruption"] is True
                ),
                "32_correct_vertical_framing": _status(
                    artifact_report, "framing"
                )
                == "passed",
                "33_subject_visibility_evidence_unavailable": _status(
                    face_unknown, "subject_visibility"
                )
                == "unavailable",
                "34_face_motion_validation_pass": _status(
                    face_pass, "face_tracking"
                )
                == "passed",
                "35_face_motion_validation_failure": _status(
                    face_fail, "face_tracking"
                )
                == "failed",
                "36_multi_speaker_layout_pass": _status(
                    multi_pass, "multi_speaker_layout"
                )
                == "passed",
                "37_multi_speaker_layout_uncertain": _status(
                    multi_unknown, "multi_speaker_layout"
                )
                == "unavailable",
                "38_strong_hook_evidence": _dimension_status(
                    strong_hook, "hook_strength"
                )
                == "strong",
                "39_weak_hook_evidence": _dimension_status(
                    weak_hook, "hook_strength"
                )
                == "weak",
                "40_hook_evidence_unavailable": _dimension_status(
                    unavailable_hook, "hook_strength"
                )
                == "unavailable",
                "41_complete_story": _dimension_status(
                    complete_story, "story_completeness"
                )
                in {"strong", "acceptable"},
                "42_missing_payoff": _dimension_status(
                    missing_payoff, "payoff_preservation"
                )
                == "failed",
                "43_abrupt_ending": _dimension_status(
                    abrupt_story, "pacing"
                )
                == "failed",
                "44_pacing_acceptable": _dimension_status(
                    complete_story, "pacing"
                )
                == "acceptable",
                "45_pacing_uncertain": _dimension_status(
                    pacing_uncertain, "pacing"
                )
                == "unavailable",
                "46_caption_readability_acceptable": _dimension_status(
                    caption_readable, "caption_readability"
                )
                == "acceptable",
                "47_caption_readability_uncertain": _dimension_status(
                    caption_uncertain, "caption_readability"
                )
                == "unavailable",
                "48_motion_overload_evidence": _dimension_status(
                    motion_overload, "motion_balance"
                )
                == "failed",
                "49_music_mood_evidence_present": _dimension_status(
                    music_present, "music_mood_fit"
                )
                == "acceptable",
                "50_music_evidence_unavailable": _dimension_status(
                    music_unavailable, "music_mood_fit"
                )
                == "unavailable",
                "51_repetition_detected": _dimension_status(
                    repetition, "repetition"
                )
                == "failed",
                "52_baseline_equivalent": (
                    equivalent_comparison.equivalent_for_required_capability
                    and not equivalent_regressions
                ),
                "53_baseline_resolution_regression": "resolution"
                in {item.category for item in resolution_regressions}
                and not resolution_comparison.equivalent_for_required_capability,
                "54_baseline_audio_regression": "audio_presence"
                in {item.category for item in audio_regressions}
                and not audio_comparison.equivalent_for_required_capability,
                "55_baseline_timing_regression": "duration"
                in {item.category for item in timing_regressions}
                and not timing_comparison.equivalent_for_required_capability,
                "56_baseline_hook_regression": "hook"
                in {item.category for item in hook_regressions}
                and not hook_comparison.equivalent_for_required_capability,
                "57_acceptable_disclosed_minor_regression": (
                    limitation_decision.decision
                    == "accepted_with_disclosed_limitations"
                ),
                "58_non_negotiable_regression": (
                    regression_failure.decision == "rejected_regression"
                ),
                "59_technical_pass_creative_uncertainty": (
                    creative_uncertain_decision.decision == "needs_human_review"
                ),
                "60_technical_failure": (
                    technical_failure.decision == "rejected_technical"
                ),
                "61_quality_failure": (
                    quality_failure.decision == "rejected_quality"
                ),
                "62_regression_failure": (
                    regression_failure.decision == "rejected_regression"
                ),
                "63_rights_unknown": (
                    rights_unknown_decision.decision == "blocked_rights"
                ),
                "64_rights_blocked": (
                    rights_blocked_decision.decision == "blocked_rights"
                ),
                "65_safety_blocked": (
                    safety_blocked_decision.decision == "blocked_safety"
                ),
                "66_required_validator_unavailable": (
                    required_unavailable_decision.decision
                    == "needs_more_evidence"
                ),
                "67_optional_validator_unavailable": (
                    optional_unavailable.checks[0].status == "unavailable"
                    and optional_unavailable.technical_acceptance_eligible
                ),
                "68_artifact_only_mode": (
                    artifact_report.review_cases[-1].review_mode
                    == "artifact_only"
                ),
                "69_full_evidence_mode": bool(
                    valid
                    and valid.review_cases[-1].review_mode
                    == "local_technical_review"
                    and valid.signal_usage.local_ffprobe_used
                    and valid.signal_usage.local_decode_check_used
                ),
                "70_baseline_comparison_mode": (
                    equivalent_comparison.comparison_basis == "manual_baseline"
                ),
                "71_human_review_package": (
                    len(human_package.reviewer_questions) == 10
                    and bool(human_package.prohibited_actions)
                ),
                "72_accepted_for_next_internal_stage_decision": (
                    accepted_decision.decision
                    == "accepted_for_next_internal_stage"
                ),
                "73_accepted_with_limitations_decision": (
                    limitation_decision.decision
                    == "accepted_with_disclosed_limitations"
                ),
                "74_needs_human_review_decision": (
                    creative_uncertain_decision.decision == "needs_human_review"
                ),
                "75_needs_more_evidence_decision": (
                    required_unavailable_decision.decision
                    == "needs_more_evidence"
                ),
                "76_tool_recovery_handoff": "tool_recovery_brain"
                in {item.target_module for item in handoffs["tool_recovery"]},
                "77_repair_planner_handoff": "repair_planner"
                in {item.target_module for item in handoffs["repair_planner"]},
                "78_root_cause_analyzer_handoff": "root_cause_analyzer"
                in {item.target_module for item in handoffs["root_cause"]},
                "79_validator_runner_handoff": "validator_runner"
                in {item.target_module for item in handoffs["validator"]},
                "80_workflow_controller_handoff": "workflow_controller"
                in {item.target_module for item in handoffs["workflow"]},
                "81_safety_gate_handoff": "safety_gate"
                in {item.target_module for item in handoffs["safety"]},
                "82_human_operator_handoff": "human_operator"
                in {item.target_module for item in handoffs["human"]},
                "83_output_remains_unchanged": (
                    saved_path.read_bytes() == output_before
                    and not signals.output_modified
                ),
                "84_source_media_remains_unchanged": (
                    source_path.read_bytes() == source_before
                    and not signals.source_media_modified
                ),
                "85_workflow_remains_paused": not signals.workflow_resume_used,
                "86_no_rendering_occurs": not signals.rendering_used,
                "87_no_fallback_executes": not signals.fallback_execution_used,
                "88_no_network_access_occurs": (
                    not signals.network_access_used
                    and not signals.url_fetching_used
                ),
                "89_no_upload_occurs": not signals.uploading_used,
                "90_no_publication_occurs": not signals.publication_used,
                "91_no_rights_bypass_occurs": not signals.rights_bypass_used,
                "92_no_safety_bypass_occurs": not signals.safety_bypass_used,
                "93_no_destructive_action_occurs": (
                    not signals.destructive_action_used
                ),
            }
            if len(scenarios) != 93:
                raise RuntimeError(
                    f"Synthetic scenario count is {len(scenarios)}, expected 93."
                )
            store = BobaMemoryStore(root / "work" / "boba")
            store.save_boba_output_quality_reviewer(artifact_report)
            if store.load_boba_output_quality_reviewer(
                SYNTHETIC_PROJECT_ID
            ) is None:
                raise RuntimeError(
                    "Synthetic Output Quality Reviewer report did not persist."
                )
    except Exception as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
    report = BobaOutputQualityReviewerValidatorReportV1(
        mode="synthetic_project",
        passed=len(scenarios) == 93 and all(scenarios.values()) and not errors,
        project_id=SYNTHETIC_PROJECT_ID,
        scenario_count=len(scenarios),
        passed_scenario_count=sum(scenarios.values()),
        scenario_results=scenarios,
        ffprobe_available=ffprobe_available,
        ffmpeg_available=ffmpeg_available,
        warnings=warnings,
        limitations=[
            "Media fixtures are tiny generated local signals, not creator footage.",
            "Automated creative evidence remains advisory and does not replace viewing.",
            "The reviewer never renders, repairs, resumes, uploads, or publishes.",
        ],
        errors=errors,
    )
    _write_report(report, report_root)
    return report


def inspect_project(
    project_id: str,
    *,
    repository_root: Path = ROOT,
    report_root: Path = REPORT_ROOT,
) -> BobaOutputQualityReviewerValidatorReportV1:
    registry = build_read_only_quality_validator_registry()
    scenarios: dict[str, bool] = {}
    errors: list[str] = []
    try:
        store = BobaMemoryStore(repository_root / "work" / "boba")
        stored = store.load_boba_output_quality_reviewer(project_id)
        exported = (
            store.export_boba_output_quality_reviewer(project_id)
            if stored is not None
            else {}
        )
        scenarios = {
            "stored_reviewer_available": stored is not None,
            "stored_reviewer_json_safe": bool(
                stored and json.dumps(stored.model_dump(mode="json"))
            ),
            "output_not_modified": bool(
                stored and not stored.signal_usage.output_modified
            ),
            "source_media_not_modified": bool(
                stored and not stored.signal_usage.source_media_modified
            ),
            "workflow_not_resumed": bool(
                stored and not stored.signal_usage.workflow_resume_used
            ),
            "network_not_used": bool(
                stored and not stored.signal_usage.network_access_used
            ),
            "export_sanitized": bool(
                exported
                and exported.get("privacy", {}).get(
                    "private_absolute_paths_excluded"
                )
                is True
            ),
        }
    except Exception as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
    report = BobaOutputQualityReviewerValidatorReportV1(
        mode="project_id",
        passed=bool(scenarios) and all(scenarios.values()) and not errors,
        project_id=project_id,
        scenario_count=len(scenarios),
        passed_scenario_count=sum(scenarios.values()),
        scenario_results=scenarios,
        ffprobe_available=registry["ffprobe_media"].available,
        ffmpeg_available=registry["ffmpeg_decode"].available,
        generated_fixture_only=False,
        limitations=[
            "Project mode only inspects persisted reviewer metadata.",
            "It does not rerun media checks or modify project outputs.",
        ],
        errors=errors,
    )
    _write_report(report, report_root)
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-check", action="store_true")
    mode.add_argument("--synthetic-project", action="store_true")
    mode.add_argument("--project-id")
    parser.add_argument("--report-root", type=Path, default=REPORT_ROOT)
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    report_root = arguments.report_root.resolve()
    if arguments.self_check:
        report = run_self_check(report_root)
    elif arguments.synthetic_project:
        report = run_synthetic_project(report_root)
    else:
        report = inspect_project(
            str(arguments.project_id),
            repository_root=ROOT,
            report_root=report_root,
        )
    print(report.model_dump_json(indent=2))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
