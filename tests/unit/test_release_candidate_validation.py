"""Olympus V2 release-candidate decision, evidence, and report tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from olympus.validation.release_candidate import (
    DECISION_NOT_READY,
    DECISION_PASS,
    DECISION_WARN,
    SYSTEM_KEYS,
    TEST_SUITE_KEYS,
    add_blocker,
    add_warning,
    build_release_candidate_report,
    evaluate_release_candidate,
    release_candidate_markdown,
    run_command,
    write_release_candidate_report,
)


def _passing_report(tmp_path: Path, *, mode: str = "full") -> dict[str, Any]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    report = build_release_candidate_report(tmp_path, mode=mode)
    top = report["olympus_v2_release_candidate"]
    top["environment"].update(
        {
            "python_ok": True,
            "ffmpeg_ok": True,
            "ffprobe_ok": True,
            "node_ok": True,
            "npm_ok": True,
            "backend_import_ok": True,
            "backend_running": True,
            "backend_settings_ok": True,
            "frontend_dependencies_ok": True,
            "storage_writable": True,
        }
    )
    for name in TEST_SUITE_KEYS:
        top["test_suites"][name] = {
            "id": name,
            "command": name,
            "passed": True,
            "status": "passed",
            "exit_code": 0,
            "duration_seconds": 0.1,
            "stdout_tail": "passed",
            "stderr_tail": "",
            "warnings": [],
            "errors": [],
        }
    for name in SYSTEM_KEYS:
        top["systems"][name] = {
            "status": "passed",
            "passed": True,
            "evidence_kind": "test",
            "checks": [],
            "warnings": [],
            "errors": [],
        }
    top["systems"]["live_trend_provider_v2"]["live_provider_used"] = True
    top["systems"]["curated_music_library_v2"]["production_assets_available"] = True
    top["systems"]["durable_jobs_v2"]["clip_level_partial_resume"] = True
    top["systems"]["link_ingestion"]["pre_project_download_durable"] = True
    top["end_to_end"]["local_upload_full_pipeline"].update(
        {
            "status": "passed",
            "passed": True,
            "fresh": True,
            "safety_metadata_present": True,
            "upload_metadata_present": True,
            "manual_playback_performed": True,
            "music_audibility_verified": True,
            "real_face_tracking_verified": True,
        }
    )
    top["end_to_end"]["final_mp4_validation"].update(
        {"status": "passed", "passed": True, "fresh": True}
    )
    top["end_to_end"]["durable_resume"].update(
        {"status": "passed", "passed": True, "fresh": True}
    )
    top["end_to_end"]["full_render_long_video"].update(
        {
            "status": "passed",
            "passed": True,
            "fresh": True,
            "duration_evidence_seconds": 1800.0,
        }
    )
    top["end_to_end"]["youtube_link_full_pipeline"].update(
        {
            "status": "passed",
            "passed": True,
            "fresh": True,
            "real_url_used": True,
        }
    )
    top["end_to_end"]["backend_restart_recovery"].update(
        {
            "status": "passed",
            "passed": True,
            "fresh": True,
            "real_process_restart": True,
        }
    )
    top["artifacts"].update(
        {
            "rendered_clip_count": 1,
            "valid_mp4_count": 1,
            "invalid_mp4_count": 0,
            "stale_artifact_warnings": [],
        }
    )
    top["release_notes"].update(
        {
            "docs_complete": True,
            "missing_docs": [],
            "known_limitations": ["Documented limitations exist."],
        }
    )
    return report


def test_decision_pass_release_candidate_with_all_gates(tmp_path: Path) -> None:
    report = evaluate_release_candidate(_passing_report(tmp_path))
    decision = report["olympus_v2_release_candidate"]["decision"]

    assert decision["status"] == DECISION_PASS
    assert decision["release_candidate_ready"] is True
    assert decision["blocker_count"] == 0
    assert decision["warning_count"] == 0


def test_decision_pass_with_noncritical_warning(tmp_path: Path) -> None:
    report = _passing_report(tmp_path)
    add_warning(
        report,
        "MANUAL_FOLLOWUP",
        system="manual_qa",
        title="A non-critical manual follow-up remains.",
        evidence="Automated gates passed.",
        recommended_followup="Perform the documented follow-up.",
    )

    evaluate_release_candidate(report)

    assert report["olympus_v2_release_candidate"]["decision"]["status"] == DECISION_WARN
    assert report["olympus_v2_release_candidate"]["decision"][
        "release_candidate_ready"
    ] is True


def test_decision_not_release_ready_with_blocker(tmp_path: Path) -> None:
    report = _passing_report(tmp_path)
    add_blocker(
        report,
        "CORE_FLOW_BROKEN",
        system="runtime",
        title="Core flow failed.",
        evidence="No render.",
        recommended_fix="Fix the renderer.",
    )

    evaluate_release_candidate(report)

    assert report["olympus_v2_release_candidate"]["decision"]["status"] == DECISION_NOT_READY
    assert report["olympus_v2_release_candidate"]["decision"][
        "release_candidate_ready"
    ] is False


def test_missing_30_plus_video_is_warning_not_claim(tmp_path: Path) -> None:
    report = _passing_report(tmp_path)
    long_render = report["olympus_v2_release_candidate"]["end_to_end"][
        "full_render_long_video"
    ]
    long_render.update(passed=False, duration_evidence_seconds=0.0)

    evaluate_release_candidate(report)
    top = report["olympus_v2_release_candidate"]

    assert top["release_gates"]["real_30_plus_minute_validation"] is False
    assert any(
        warning["id"] == "REAL_30_PLUS_MINUTE_VALIDATION_NOT_RUN"
        for warning in top["warnings"]
    )


def test_missing_backend_warning_or_blocker_depends_on_mode(tmp_path: Path) -> None:
    fast = _passing_report(tmp_path / "fast", mode="fast")
    fast["olympus_v2_release_candidate"]["environment"]["backend_running"] = False
    evaluate_release_candidate(fast)
    assert fast["olympus_v2_release_candidate"]["decision"]["status"] == DECISION_WARN

    runtime = _passing_report(tmp_path / "runtime", mode="runtime_only")
    runtime["olympus_v2_release_candidate"]["environment"]["backend_running"] = False
    evaluate_release_candidate(runtime)
    assert runtime["olympus_v2_release_candidate"]["decision"][
        "status"
    ] == DECISION_NOT_READY
    assert any(
        blocker["id"] == "LOCAL_BACKEND_UNAVAILABLE"
        for blocker in runtime["olympus_v2_release_candidate"]["blockers"]
    )


def test_failed_pytest_is_blocker(tmp_path: Path) -> None:
    report = _passing_report(tmp_path)
    report["olympus_v2_release_candidate"]["test_suites"]["pytest"].update(
        passed=False, status="failed", exit_code=1, stderr_tail="failure"
    )

    evaluate_release_candidate(report)

    assert any(
        blocker["id"] == "TEST_SUITE_PYTEST_FAILED"
        for blocker in report["olympus_v2_release_candidate"]["blockers"]
    )


def test_failed_frontend_build_is_blocker(tmp_path: Path) -> None:
    report = _passing_report(tmp_path)
    report["olympus_v2_release_candidate"]["test_suites"]["frontend_build"].update(
        passed=False, status="failed", exit_code=1, stderr_tail="build failed"
    )

    evaluate_release_candidate(report)

    assert any(
        blocker["id"] == "TEST_SUITE_FRONTEND_BUILD_FAILED"
        for blocker in report["olympus_v2_release_candidate"]["blockers"]
    )


def test_stale_artifact_becomes_warning(tmp_path: Path) -> None:
    report = _passing_report(tmp_path)
    report["olympus_v2_release_candidate"]["artifacts"]["stale_artifact_warnings"] = [
        "old report"
    ]

    evaluate_release_candidate(report)

    assert report["olympus_v2_release_candidate"]["decision"]["status"] == DECISION_WARN
    assert any(
        warning["system"] == "artifacts"
        for warning in report["olympus_v2_release_candidate"]["warnings"]
    )


def test_real_youtube_skip_is_warning(tmp_path: Path) -> None:
    report = _passing_report(tmp_path)
    youtube = report["olympus_v2_release_candidate"]["end_to_end"][
        "youtube_link_full_pipeline"
    ]
    youtube.update(passed=None, real_url_used=False, status="skipped")

    evaluate_release_candidate(report)

    assert any(
        warning["id"] == "REAL_YOUTUBE_LINK_VALIDATION_NOT_RUN"
        for warning in report["olympus_v2_release_candidate"]["warnings"]
    )


def test_report_json_serializes_and_markdown_writes(tmp_path: Path) -> None:
    report = evaluate_release_candidate(_passing_report(tmp_path))

    encoded = json.dumps(report)
    paths = write_release_candidate_report(report, tmp_path / "reports")
    markdown = release_candidate_markdown(report)

    assert json.loads(encoded)["olympus_v2_release_candidate"]["decision"][
        "status"
    ] == DECISION_PASS
    assert Path(paths["json"]).is_file()
    assert Path(paths["markdown"]).is_file()
    assert "PASS_RELEASE_CANDIDATE" in markdown


def test_command_failure_is_captured(tmp_path: Path) -> None:
    result = run_command(
        "planned_failure",
        [sys.executable, "-c", "import sys; print('captured'); sys.exit(7)"],
        cwd=tmp_path,
        timeout_seconds=10,
    )

    assert result["passed"] is False
    assert result["exit_code"] == 7
    assert result["code"] == "COMMAND_FAILED"
    assert "captured" in result["stdout_tail"]


def test_no_false_ready_when_fresh_full_render_missing(tmp_path: Path) -> None:
    report = _passing_report(tmp_path)
    local = report["olympus_v2_release_candidate"]["end_to_end"][
        "local_upload_full_pipeline"
    ]
    local.update(fresh=False, passed=None, status="skipped")

    evaluate_release_candidate(report)

    top = report["olympus_v2_release_candidate"]
    assert top["decision"]["release_candidate_ready"] is False
    assert any(
        blocker["id"] == "FRESH_FULL_PIPELINE_RENDER_MISSING"
        for blocker in top["blockers"]
    )


def test_no_false_30_plus_claim_without_duration_evidence(tmp_path: Path) -> None:
    report = _passing_report(tmp_path)
    long_render = report["olympus_v2_release_candidate"]["end_to_end"][
        "full_render_long_video"
    ]
    long_render.update(passed=True, duration_evidence_seconds=1799.99)

    evaluate_release_candidate(report)

    assert report["olympus_v2_release_candidate"]["release_gates"][
        "real_30_plus_minute_validation"
    ] is False


def test_caption_advisories_and_missing_validator_mode_are_release_warnings(
    tmp_path: Path,
) -> None:
    report = _passing_report(tmp_path)
    top = report["olympus_v2_release_candidate"]
    top["end_to_end"]["local_upload_full_pipeline"][
        "caption_readability_advisories"
    ] = [{"clip_id": "clip_a", "warning_count": 2}]
    top["systems"]["multi_speaker_layout_v2"]["checks"] = [
        {"code": "VALIDATOR_MODE_MISSING"}
    ]

    evaluate_release_candidate(report)

    warning_ids = {warning["id"] for warning in top["warnings"]}
    assert top["decision"]["status"] == DECISION_WARN
    assert "CAPTION_READABILITY_ADVISORIES_REMAIN" in warning_ids
    assert "VALIDATOR_MODE_MISSING_MULTI_SPEAKER_SYNTHETIC" in warning_ids
