"""Fast contract and classification tests for final Olympus V2 release validation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tools import validate_final_release as validator

from olympus.validation.release import (
    FINAL_VERDICT_BLOCKED,
    FINAL_VERDICT_INCOMPLETE,
    FINAL_VERDICT_PASS,
    READINESS_READY,
    FinalReleaseValidationResultV1,
    ValidatorResultV1,
    contains_raw_media_path,
    duration_summary,
    evaluate_final_release,
    final_release_markdown,
    frontend_script_status,
    generated_artifacts_staged,
    missing_validator_result,
    optional_provider_limitations,
    relative_report_path,
    standard_proof_limitations,
    write_final_release_report,
)


def _validator_result(
    name: str = "required_check",
    *,
    status: str = "passed",
    required: bool = True,
    blocker_on_failure: bool = True,
    duration_seconds: float = 1.25,
) -> ValidatorResultV1:
    return ValidatorResultV1(
        name=name,
        command=["python", "validator.py"],
        status=status,
        duration_seconds=duration_seconds,
        report_path=None,
        required=required,
        blocker_on_failure=blocker_on_failure,
        summary=f"{name} {status}",
        errors=["failure"] if status == "failed" else [],
    )


def test_final_release_contract_serializes() -> None:
    result = FinalReleaseValidationResultV1(
        git_commit="abc123",
        git_branch="validation/test",
        validators=[_validator_result()],
    )

    payload = result.to_dict()

    assert json.loads(json.dumps(payload))["git_commit"] == "abc123"
    assert payload["validators"][0]["name"] == "required_check"


def test_validator_result_contract_serializes() -> None:
    result = _validator_result(duration_seconds=2.5)

    payload = result.to_dict()

    assert json.loads(json.dumps(payload))["duration_seconds"] == 2.5
    assert payload["status"] == "passed"


def test_blocker_classification_works() -> None:
    result = FinalReleaseValidationResultV1(validators=[_validator_result(status="failed")])

    evaluate_final_release(result, required_validator_names=["required_check"])

    assert result.final_verdict == FINAL_VERDICT_BLOCKED
    assert any("required_check" in blocker for blocker in result.blockers)


def test_limitation_classification_works() -> None:
    result = FinalReleaseValidationResultV1(
        validators=[_validator_result()],
        limitations=["Synthetic footage only."],
    )

    evaluate_final_release(result, required_validator_names=["required_check"])

    assert result.final_verdict == FINAL_VERDICT_PASS
    assert result.limitations == ["Synthetic footage only."]


def test_final_verdict_pass_internal_rc_when_required_passes() -> None:
    result = FinalReleaseValidationResultV1(
        validators=[_validator_result("one"), _validator_result("two")]
    )

    evaluate_final_release(result, required_validator_names=["one", "two"])

    assert result.final_verdict == FINAL_VERDICT_PASS
    assert result.release_readiness == READINESS_READY


def test_final_verdict_blocked_when_blocker_exists() -> None:
    result = FinalReleaseValidationResultV1(
        validators=[_validator_result()], blockers=["A manifest is missing."]
    )

    evaluate_final_release(result, required_validator_names=["required_check"])

    assert result.final_verdict == FINAL_VERDICT_BLOCKED


def test_final_verdict_incomplete_when_required_validator_skipped() -> None:
    result = FinalReleaseValidationResultV1(
        validators=[_validator_result(status="skipped")]
    )

    evaluate_final_release(result, required_validator_names=["required_check"])

    assert result.final_verdict == FINAL_VERDICT_INCOMPLETE
    assert not result.blockers


def test_missing_validator_command_becomes_blocker() -> None:
    missing = missing_validator_result(
        "missing_validator",
        ["python", "tools/missing_validator.py"],
    )
    result = FinalReleaseValidationResultV1(validators=[missing])

    evaluate_final_release(result, required_validator_names=["missing_validator"])

    assert result.final_verdict == FINAL_VERDICT_BLOCKED
    assert "missing" in result.blockers[0].lower()


def test_missing_frontend_script_gives_clear_result(tmp_path: Path) -> None:
    package = tmp_path / "package.json"
    package.write_text(json.dumps({"scripts": {"build": "next build"}}), encoding="utf-8")

    status = frontend_script_status(package, ["build", "test"])

    assert status["passed"] is False
    assert status["missing_scripts"] == ["test"]
    assert status["errors"] == ["Missing frontend npm script: test"]


def test_report_paths_stay_under_validation_root(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    valid = workspace / "work" / "validation_reports" / "final_release" / "report.json"
    valid.parent.mkdir(parents=True)

    assert relative_report_path(valid, workspace) == (
        "work/validation_reports/final_release/report.json"
    )
    with pytest.raises(ValueError, match="Report path must stay"):
        relative_report_path(workspace / "report.json", workspace)


def test_generated_reports_are_not_staged() -> None:
    staged = generated_artifacts_staged(
        [
            "src/olympus/validation/release.py",
            "work/validation_reports/final_release/final_release_report.json",
            "frontend/.next/cache/data.bin",
        ]
    )

    assert staged == [
        "frontend/.next/cache/data.bin",
        "work/validation_reports/final_release/final_release_report.json",
    ]


def test_validator_duration_summary_works() -> None:
    results = [
        _validator_result("one", duration_seconds=1.0),
        _validator_result("two", duration_seconds=3.5),
        _validator_result("three", status="skipped", duration_seconds=0.0),
    ]

    summary = duration_summary(results)

    assert summary["total_seconds"] == 4.5
    assert summary["longest_validator"] == "two"
    assert summary["skipped_count"] == 1


def test_summary_markdown_renders_key_sections() -> None:
    result = FinalReleaseValidationResultV1(
        git_commit="abc123",
        git_branch="validation/test",
        validators=[_validator_result()],
        blockers=["Example blocker"],
        limitations=["Example limitation"],
    )

    markdown = final_release_markdown(result)

    for heading in (
        "## Environment",
        "## Backend",
        "## Frontend",
        "## Validators",
        "## MP4 / Render Proof",
        "## Long-Video Proof",
        "## Durable Resume Proof",
        "## Blockers",
        "## Limitations",
        "## Final Verdict",
    ):
        assert heading in markdown


def test_optional_provider_absence_becomes_limitation_when_honest() -> None:
    limitations = optional_provider_limitations(
        {
            "cv2": {
                "available": False,
                "required": False,
                "feature": "local computer vision",
            },
            "required_provider": {
                "available": False,
                "required": True,
                "feature": "required proof",
            },
        }
    )

    assert len(limitations) == 1
    assert "cv2" in limitations[0]


def test_real_face_proof_absence_does_not_block_internal_rc() -> None:
    result = FinalReleaseValidationResultV1(
        validators=[_validator_result()],
        limitations=standard_proof_limitations(),
    )

    evaluate_final_release(result, required_validator_names=["required_check"])

    assert result.final_verdict == FINAL_VERDICT_PASS
    assert any("real face" in limitation.lower() for limitation in result.limitations)


def test_music_quality_absence_is_limitation_without_required_audio_validator() -> None:
    result = FinalReleaseValidationResultV1(
        validators=[_validator_result()],
        limitations=standard_proof_limitations(),
    )

    evaluate_final_release(result, required_validator_names=["required_check"])

    assert result.final_verdict == FINAL_VERDICT_PASS
    assert any("music quality" in limitation.lower() for limitation in result.limitations)


def test_no_raw_media_paths_are_embedded_in_final_report(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    result = FinalReleaseValidationResultV1(
        artifacts={"source_path": "D:/private/creator/source.mp4"}
    )

    assert contains_raw_media_path(result.to_dict()) is True
    with pytest.raises(ValueError, match="raw media paths"):
        write_final_release_report(
            result,
            workspace / "work" / "validation_reports" / "final_release",
            workspace_root=workspace,
        )


def test_git_dirty_state_is_reported_clearly(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_git_lines(_root: Path, *arguments: str) -> list[str]:
        if arguments[:2] == ("status", "--porcelain=v1"):
            return [" M src/olympus/validation/release.py"]
        return []

    monkeypatch.setattr(validator, "_git_lines", fake_git_lines)

    state = validator._git_state(Path("D:/Olympus"))

    assert state["dirty"] is True
    assert state["status_entries"] == [" M src/olympus/validation/release.py"]
    assert state["staged_generated_paths"] == []
