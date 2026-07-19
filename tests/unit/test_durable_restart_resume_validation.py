"""Tests for Durable Restart / Resume Proof V2 validation helpers."""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path
from typing import Any

import pytest
from tools import validate_durable_restart_resume as validator

from olympus.data.repositories import (
    StorageProjectRepository,
    StorageWorkflowRepository,
)
from olympus.data.storage.local import LocalStorage
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.domain.entities.workflow import Job, JobStatus, Workflow, WorkflowStatus
from olympus.utils import utc_now
from olympus.validation.durable_resume import (
    DURABLE_STAGE_ORDER,
    DurableOutputValidationV1,
    DurableRestartResumeResultV1,
    classify_stage_execution,
    compute_stage_execution_counts,
    detect_checkpoint_corruption,
    detect_duplicate_outputs,
    detect_impossible_stage_transitions,
    durable_resume_self_check,
    interruption_plan,
    is_generated_resume_artifact,
    parse_checkpoint_snapshot,
    validate_rendered_output,
    validate_resume_final_payload,
    validate_resume_manifests,
    write_durable_resume_report,
)


def _stage(
    name: str,
    status: str,
    *,
    attempts: int = 0,
    valid: bool | None = None,
    artifact_path: str | None = None,
) -> dict[str, Any]:
    checkpoint: dict[str, Any] = {}
    if valid is not None:
        checkpoint["valid"] = valid
    if artifact_path is not None:
        checkpoint["artifact_path"] = artifact_path
    return {
        "stage": name,
        "engine": name,
        "status": status,
        "attempts": attempts,
        "checkpoint": checkpoint,
        "warnings": [],
        "errors": [],
    }


def _snapshot(stages: list[dict[str, Any]]) -> dict[str, Any]:
    return parse_checkpoint_snapshot(
        {
            "workflow_id": "wf_one",
            "project_id": "proj_one",
            "status": "running",
            "jobs": stages,
        }
    )


def _output(
    clip_id: str,
    storage_key: str,
    checksum: str,
) -> DurableOutputValidationV1:
    return DurableOutputValidationV1(
        clip_id=clip_id,
        storage_key=storage_key,
        exists=True,
        size_bytes=100,
        ffprobe_valid=True,
        checksum=checksum,
        duplicate_of=None,
        partial_detected=False,
    )


def test_validation_contract_serializes() -> None:
    result = DurableRestartResumeResultV1(
        project_id="proj_one",
        mode="interrupt_after_analysis",
        interruption_stage="cognitive",
        interruption_method="checkpoint_boundary",
        outputs=[_output("clip_one", "render/clip_one.mp4", "sha256:one")],
    )

    payload = result.to_dict()

    assert json.loads(json.dumps(payload))["contract_version"] == "1"
    assert payload["outputs"][0]["ffprobe_valid"] is True


def test_self_check_reports_missing_ffmpeg_clearly(tmp_path: Path) -> None:
    def which(binary: str) -> str | None:
        return "C:/tools/ffprobe.exe" if binary == "ffprobe" else None

    result = durable_resume_self_check(
        storage_root=tmp_path / "storage",
        report_dir=tmp_path / "reports",
        which=which,
    )

    assert result["passed"] is False
    assert any("ffmpeg not found" in error for error in result["errors"])


def test_checkpoint_snapshot_parser_works() -> None:
    snapshot = _snapshot(
        [_stage("upload", "completed", attempts=1, valid=True, artifact_path="upload.mp4")]
    )

    assert snapshot["readable"] is True
    assert snapshot["stages"][0]["artifact_path"] == "upload.mp4"
    assert snapshot["stages"][0]["attempts"] == 1


def test_corrupted_checkpoint_detection_works() -> None:
    corrupt_json = parse_checkpoint_snapshot(b"{not-json")
    invalid_completed = _snapshot(
        [_stage("upload", "completed", attempts=1, valid=False)]
    )

    assert corrupt_json["corrupted"] is True
    assert detect_checkpoint_corruption(invalid_completed)


def test_impossible_stage_transition_detection_works() -> None:
    before = _snapshot([_stage("upload", "completed", attempts=1, valid=True)])
    after = _snapshot([_stage("upload", "pending", attempts=1)])

    errors = detect_impossible_stage_transitions(before, after)

    assert any("regressed" in error for error in errors)


def test_stage_execution_counts_compute_correctly() -> None:
    snapshot = _snapshot(
        [
            _stage("upload", "completed", attempts=1, valid=True),
            _stage("cognitive", "running", attempts=2),
        ]
    )

    counts = compute_stage_execution_counts(snapshot)

    assert counts["upload"] == 1
    assert counts["cognitive"] == 2
    assert counts["optimization"] == 0


def test_reused_and_rerun_stage_lists_compute_correctly() -> None:
    before = _snapshot(
        [
            _stage("upload", "completed", attempts=1, valid=True),
            _stage("cognitive", "running", attempts=1),
        ]
    )
    after = _snapshot(
        [
            _stage("upload", "completed", attempts=1, valid=True),
            _stage("cognitive", "completed", attempts=2, valid=True),
        ]
    )

    result = classify_stage_execution(before, after)

    assert result["reused"] == ["upload"]
    assert result["rerun"] == ["cognitive"]


def test_partial_zero_byte_mp4_is_rejected(tmp_path: Path) -> None:
    output_path = tmp_path / "clip.mp4"
    output_path.write_bytes(b"")

    result = validate_rendered_output(
        clip_id="clip_one",
        storage_key="render/clip.mp4",
        path=output_path,
        probe_function=lambda _path: {"passed": True},
    )

    assert result.partial_detected is True
    assert result.ffprobe_valid is False
    assert any("zero bytes" in error for error in result.errors)


def test_ffprobe_invalid_mp4_is_rejected(tmp_path: Path) -> None:
    output_path = tmp_path / "clip.mp4"
    output_path.write_bytes(b"not-an-mp4")

    result = validate_rendered_output(
        clip_id="clip_one",
        storage_key="render/clip.mp4",
        path=output_path,
        probe_function=lambda _path: {"passed": False, "errors": ["invalid data"]},
    )

    assert result.partial_detected is True
    assert any("FFprobe" in error for error in result.errors)


def test_duplicate_storage_key_detection_works() -> None:
    result = detect_duplicate_outputs(
        [
            _output("clip_one", "render/same.mp4", "sha256:one"),
            _output("clip_two", "render/same.mp4", "sha256:two"),
        ]
    )

    assert result["detected"] is True
    assert result["storage_key_duplicates"][0]["duplicate_of"] == "clip_one"


def test_duplicate_checksum_detection_works() -> None:
    result = detect_duplicate_outputs(
        [
            _output("clip_one", "render/one.mp4", "sha256:same"),
            _output("clip_two", "render/two.mp4", "sha256:same"),
        ]
    )

    assert result["detected"] is True
    assert result["checksum_duplicates"][0]["duplicate_of"] == "clip_one"


def test_missing_render_manifest_fails() -> None:
    result = validate_resume_manifests(
        render_manifest_present=False,
        optimization_manifest_present=True,
    )

    assert result["passed"] is False
    assert "Canonical render manifest is missing." in result["errors"]


def test_missing_optimization_manifest_fails() -> None:
    result = validate_resume_manifests(
        render_manifest_present=True,
        optimization_manifest_present=False,
    )

    assert result["passed"] is False
    assert "Optimization manifest is missing." in result["errors"]


def test_final_payload_missing_clips_fails() -> None:
    result = validate_resume_final_payload({"manifest": {"renders": []}})

    assert result["passed"] is False
    assert result["clip_count"] == 0


def test_interrupt_after_analysis_plan_uses_checkpoint_boundary() -> None:
    plan = interruption_plan(interrupt_after="analysis", interrupt_during=None)

    assert plan["valid"] is True
    assert plan["stage"] == "cognitive"
    assert plan["trigger"] == "job_completed"


def test_interrupt_after_editing_plan_uses_checkpoint_boundary() -> None:
    plan = interruption_plan(interrupt_after="editing", interrupt_during=None)

    assert plan["valid"] is True
    assert plan["stage"] == "editing"
    assert "boundary" in plan["method"]


def test_interrupt_during_rendering_plan_uses_runner_gate() -> None:
    plan = interruption_plan(interrupt_after=None, interrupt_during="rendering")

    assert plan["valid"] is True
    assert plan["stage"] == "rendering"
    assert "before_ffmpeg" in plan["method"]


@pytest.mark.asyncio
async def test_project_id_mode_does_not_mutate_checkpoints(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage_root = tmp_path / "storage"
    storage = LocalStorage(root=str(storage_root))
    now = utc_now()
    project = Project(
        id="proj_inspect",
        name="Inspection",
        source_filename="source.mp4",
        storage_key="uploads/proj_inspect/source.mp4",
        size_bytes=100,
        video_format="mp4",
        content_type="video/mp4",
        duration_seconds=60.0,
        width=640,
        height=360,
        status=ProjectStatus.PROCESSING,
        created_at=now,
        updated_at=now,
    )
    jobs = [
        Job(
            job_id=f"job_{stage}",
            workflow_id="wf_inspect",
            project_id=project.id,
            engine=stage,
            stage=stage,
            status=JobStatus.PENDING,
            created_at=now,
        )
        for stage in DURABLE_STAGE_ORDER
    ]
    workflow = Workflow(
        workflow_id="wf_inspect",
        project_id=project.id,
        status=WorkflowStatus.PAUSED,
        created_at=now,
        updated_at=now,
        jobs=jobs,
    )
    await StorageProjectRepository(storage).save(project)
    await StorageWorkflowRepository(storage).save(workflow)
    workflow_key = "workflow/proj_inspect/workflow.json"
    before = await storage.get(workflow_key)

    async def evidence(**_kwargs: Any) -> dict[str, Any]:
        return {
            "inspection": {"passed": True},
            "render_manifest_present": True,
            "optimization_manifest_present": True,
            "outputs": [],
            "accepted_mp4_count": 1,
            "duplicate": {"detected": False},
            "partial_outputs_detected": False,
            "final_payload_valid": True,
            "warnings": [],
            "errors": [],
        }

    monkeypatch.setattr(validator, "_final_evidence", evidence)
    args = Namespace(
        project_id=project.id,
        storage_root=storage_root,
        ffprobe_binary="ffprobe",
    )

    await validator.inspect_existing_project(args)

    assert await storage.get(workflow_key) == before


def test_report_writes_under_work_validation_reports_only(tmp_path: Path) -> None:
    report_dir = tmp_path / "work" / "validation_reports" / "durable"
    result = DurableRestartResumeResultV1(
        project_id="proj_one",
        mode="interrupt_after_analysis",
        interruption_stage="cognitive",
        interruption_method="checkpoint_boundary",
    )

    paths = write_durable_resume_report(
        result,
        report_dir,
        workspace_root=tmp_path,
    )

    assert Path(paths["json"]).is_file()
    assert Path(paths["summary"]).is_file()
    assert Path(paths["json"]).is_relative_to(tmp_path / "work" / "validation_reports")


def test_generated_media_and_reports_are_never_publishable() -> None:
    assert is_generated_resume_artifact("work/validation_reports/report.json") is True
    assert is_generated_resume_artifact("storage_data/render/clip.mp4") is True
    assert is_generated_resume_artifact("frontend/node_modules/package/file.js") is True
    assert is_generated_resume_artifact("src/olympus/validation/durable_resume.py") is False


def test_synthetic_runs_use_isolated_recovery_storage(tmp_path: Path) -> None:
    first = validator.isolated_synthetic_storage_root(
        tmp_path,
        "interrupt_after_analysis",
        run_id="one",
    )
    second = validator.isolated_synthetic_storage_root(
        tmp_path,
        "interrupt_after_analysis",
        run_id="two",
    )

    assert first != second
    assert first.is_relative_to(tmp_path / "validation" / "durable_restart_resume")
