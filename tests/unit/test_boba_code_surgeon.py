"""BOBA Code Surgeon V1 policy, isolation, persistence, API, and safety tests."""

from __future__ import annotations

import asyncio
import json
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError
from tools.validate_boba_repair_planner import (
    build_synthetic_planning_context,
    build_synthetic_root_cause_report,
)

import olympus.boba.code_surgeon as code_surgeon_module
from olympus.api.dependencies import boba_integration_provider
from olympus.boba import (
    BobaCodeApprovalRecordV1,
    BobaCodeExecutionPolicyV1,
    BobaCodeIsolatedRunV1,
    BobaCodePatchFileV1,
    BobaCodePatchHunkV1,
    BobaCodePatchProposalV1,
    BobaCodeRepairCaseV1,
    BobaCodeReviewPackageV1,
    BobaCodeRollbackRecordV1,
    BobaCodeSurgeonExecutionHandoffV1,
    BobaCodeSurgeonSetV1,
    BobaCodeSurgeonSignalUsageV1,
    BobaCodeSurgeonSummaryV1,
    BobaCodeSurgeonV1,
    BobaCodeValidationCommandV1,
    BobaCodeValidationResultV1,
    BobaCodeValidationRunV1,
    BobaIntegration,
    BobaMemoryStore,
    BobaRepairPlannerSetV1,
    BobaRepairPlannerV1,
    build_validation_commands,
    calculate_patch_digest,
    default_code_execution_policy,
    execute_allowlisted_validation,
    is_protected_branch,
    review_patch_quality,
    sanitize_repair_branch_name,
    scan_patch_for_secrets,
    validate_command_safety,
    validate_patch_scope,
    verify_approval,
    verify_code_repair_eligibility,
)
from olympus.data.repositories import StorageProjectRepository
from olympus.data.storage.local import LocalStorage
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.platform.errors import ValidationError
from olympus.utils import utc_now

PROJECT_ID = "proj_boba_code_surgeon_test"


def _git(repository: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=repository,
        capture_output=True,
        text=True,
        check=False,
        shell=False,
        timeout=30,
    )


def _repository(tmp_path: Path) -> Path:
    repository = tmp_path / "synthetic-repository"
    repository.mkdir()
    initialized = _git(repository, "init", "-b", "main")
    if initialized.returncode != 0:
        assert _git(repository, "init").returncode == 0
        assert _git(repository, "branch", "-M", "main").returncode == 0
    assert _git(repository, "config", "user.name", "BOBA Test").returncode == 0
    assert (
        _git(repository, "config", "user.email", "boba-test@example.invalid").returncode
        == 0
    )
    (repository / ".gitignore").write_text(
        "work/\n__pycache__/\n*.pyc\n",
        encoding="utf-8",
    )
    source = repository / "src" / "sample.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "def result(value: int) -> int:\n    return value - 1\n",
        encoding="utf-8",
    )
    frontend = repository / "frontend" / "src" / "sample.ts"
    frontend.parent.mkdir(parents=True)
    frontend.write_text("export const result = false;\n", encoding="utf-8")
    assert _git(repository, "add", ".").returncode == 0
    assert _git(repository, "commit", "-m", "Synthetic base").returncode == 0
    return repository


@lru_cache(maxsize=4)
def _planner(project_id: str = PROJECT_ID) -> BobaRepairPlannerSetV1:
    root = build_synthetic_root_cause_report(project_id)
    return BobaRepairPlannerV1().plan(
        project_id,
        root,
        manual_context=build_synthetic_planning_context(root),
    )


def _planner_case_id(planner: BobaRepairPlannerSetV1 | None = None) -> str:
    report = planner or _planner()
    handoff = next(
        item
        for item in report.execution_handoffs
        if item.target_module == "code_surgeon"
    )
    return handoff.repair_case_id


def _python_diff(path: str = "src/sample.py") -> str:
    return (
        f"diff --git a/{path} b/{path}\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        "@@ -1,2 +1,2 @@\n"
        " def result(value: int) -> int:\n"
        "-    return value - 1\n"
        "+    return value + 1\n"
    )


def _new_file_diff(path: str, content: str = "safe = True") -> str:
    return (
        f"diff --git a/{path} b/{path}\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        f"+++ b/{path}\n"
        "@@ -0,0 +1 @@\n"
        f"+{content}\n"
    )


def _proposal(repository: Path) -> tuple[BobaCodeSurgeonV1, BobaCodeSurgeonSetV1]:
    surgeon = BobaCodeSurgeonV1(repository)
    report = surgeon.propose(
        PROJECT_ID,
        _planner(),
        repair_case_id=_planner_case_id(),
        unified_diff=_python_diff(),
        affected_paths=["src/sample.py"],
    )
    assert report.patch_proposals
    return surgeon, report


def _approval(
    proposal: BobaCodePatchProposalV1,
    *,
    approval_type: str = "isolated_patch_execution",
    base_sha: str | None = None,
    diff_sha: str | None = None,
    scope: list[str] | None = None,
    validation_commands: list[str] | None = None,
    approved: bool = True,
    explicit: bool = True,
    expires: str | None = None,
) -> BobaCodeApprovalRecordV1:
    return BobaCodeApprovalRecordV1(
        approval_id=f"approval_{approval_type}",
        code_repair_case_id=proposal.code_repair_case_id,
        patch_proposal_id=proposal.patch_proposal_id,
        approval_type=approval_type,
        approved=approved,
        approved_by="local-human-reviewer",
        approved_base_commit_sha=base_sha or proposal.base_commit_sha,
        approved_diff_sha256=diff_sha or proposal.diff_sha256,
        approved_scope=scope or [item.path for item in proposal.files],
        approved_validation_commands=validation_commands or ["git_diff_check"],
        approved_special_paths=[],
        approval_expires_at=expires,
        explicit_confirmation=explicit,
    )


def _roundtrip(value: Any, model: Any) -> None:
    assert model.model_validate(value.model_dump(mode="json")) == value


def _project(project_id: str = PROJECT_ID) -> Project:
    timestamp = utc_now()
    return Project(
        id=project_id,
        name="BOBA Code Surgeon V1 Test",
        source_filename="synthetic-source.mp4",
        storage_key=f"uploads/{project_id}/source.mp4",
        size_bytes=12,
        video_format="mp4",
        content_type="video/mp4",
        duration_seconds=120.0,
        width=1920,
        height=1080,
        status=ProjectStatus.ANALYZED,
        created_at=timestamp,
        updated_at=timestamp,
    )


def _integration(
    tmp_path: Path,
    repository: Path,
) -> tuple[BobaIntegration, BobaMemoryStore]:
    storage = LocalStorage(root=str(tmp_path / "storage"))
    store = BobaMemoryStore(tmp_path / "boba", memory_root=tmp_path / "memory")
    asyncio.run(StorageProjectRepository(storage).save(_project()))
    integration = BobaIntegration(storage, store)
    integration.code_surgeon = BobaCodeSurgeonV1(repository)
    return integration, store


def test_001_default_policy_serializes() -> None:
    _roundtrip(default_code_execution_policy(), BobaCodeExecutionPolicyV1)


def test_002_missing_planner_blocks_proposal() -> None:
    result = verify_code_repair_eligibility(None)
    assert result.execution_eligible is False
    assert result.evidence_strength == "insufficient"


def test_003_malformed_planner_blocks_proposal() -> None:
    result = verify_code_repair_eligibility({"broken": True})
    assert result.execution_eligible is False


def test_004_code_handoff_is_eligible() -> None:
    result = verify_code_repair_eligibility(
        _planner(),
        repair_case_id=_planner_case_id(),
        affected_paths=["src/sample.py"],
    )
    assert result.execution_eligible is True
    assert result.evidence_strength == "strong"


def test_005_proposal_only_does_not_modify_repository(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    before = (repository / "src" / "sample.py").read_text(encoding="utf-8")
    _, report = _proposal(repository)
    after = (repository / "src" / "sample.py").read_text(encoding="utf-8")
    assert before == after
    assert report.signal_usage.code_modified_in_isolated_worktree is False


def test_006_patch_digest_is_stable() -> None:
    assert calculate_patch_digest(_python_diff()) == calculate_patch_digest(
        _python_diff()
    )


def test_007_valid_proposal_is_reviewable(tmp_path: Path) -> None:
    _, report = _proposal(_repository(tmp_path))
    proposal = report.patch_proposals[0]
    assert proposal.execution_status == "validation_ready"
    assert proposal.applies_cleanly is True
    assert proposal.secret_scan_passed is True


def test_008_changed_patch_invalidates_approval(tmp_path: Path) -> None:
    _, report = _proposal(_repository(tmp_path))
    proposal = report.patch_proposals[0]
    approval = _approval(proposal, diff_sha="0" * 64)
    assert "Approval diff SHA does not match." in verify_approval(
        proposal,
        approval,
        required_type="isolated_patch_execution",
    )


def test_009_changed_base_invalidates_approval(tmp_path: Path) -> None:
    _, report = _proposal(_repository(tmp_path))
    proposal = report.patch_proposals[0]
    approval = _approval(proposal, base_sha="1" * 40)
    assert "Approval base SHA does not match." in verify_approval(
        proposal,
        approval,
        required_type="isolated_patch_execution",
    )


def test_010_wrong_scope_invalidates_approval(tmp_path: Path) -> None:
    _, report = _proposal(_repository(tmp_path))
    proposal = report.patch_proposals[0]
    approval = _approval(proposal, scope=["src/other.py"])
    assert "Approval path scope does not exactly match the patch." in verify_approval(
        proposal,
        approval,
        required_type="isolated_patch_execution",
    )


def test_011_expired_approval_is_rejected(tmp_path: Path) -> None:
    _, report = _proposal(_repository(tmp_path))
    proposal = report.patch_proposals[0]
    approval = _approval(proposal, expires="2000-01-01T00:00:00+00:00")
    assert "Approval has expired." in verify_approval(
        proposal,
        approval,
        required_type="isolated_patch_execution",
    )


def test_012_execution_requires_explicit_approval(tmp_path: Path) -> None:
    surgeon, report = _proposal(_repository(tmp_path))
    proposal = report.patch_proposals[0]
    updated = surgeon.execute_approved(
        report,
        patch_proposal_id=proposal.patch_proposal_id,
        unified_diff=_python_diff(),
        approval=_approval(proposal, explicit=False),
        approved_validation_commands=["git_diff_check"],
    )
    assert updated.isolated_runs[-1].run_status == "blocked"
    assert updated.signal_usage.isolated_worktree_used is False


def test_012b_blocked_proposal_cannot_execute(tmp_path: Path) -> None:
    surgeon, report = _proposal(_repository(tmp_path))
    proposal = report.patch_proposals[0]
    proposal.execution_status = "blocked"
    updated = surgeon.execute_approved(
        report,
        patch_proposal_id=proposal.patch_proposal_id,
        unified_diff=_python_diff(),
        approval=_approval(proposal),
        approved_validation_commands=["git_diff_check"],
    )
    run = updated.isolated_runs[-1]
    assert run.run_status == "blocked"
    assert "not eligible" in (run.stop_reason or "")
    assert run.worktree_created is False


def test_013_approved_patch_runs_in_isolated_worktree(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    surgeon, report = _proposal(repository)
    proposal = report.patch_proposals[0]
    updated = surgeon.execute_approved(
        report,
        patch_proposal_id=proposal.patch_proposal_id,
        unified_diff=_python_diff(),
        approval=_approval(proposal),
        approved_validation_commands=["git_diff_check"],
    )
    run = updated.isolated_runs[-1]
    assert run.run_status == "validation_passed"
    assert run.worktree_created is True
    assert (repository / "src" / "sample.py").read_text(encoding="utf-8").endswith(
        "return value - 1\n"
    )


def test_014_required_validator_failure_rolls_back(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    surgeon, report = _proposal(repository)
    proposal = report.patch_proposals[0]
    approval = _approval(
        proposal,
        validation_commands=["git_diff_check", "missing_validator"],
    )
    updated = surgeon.execute_approved(
        report,
        patch_proposal_id=proposal.patch_proposal_id,
        unified_diff=_python_diff(),
        approval=approval,
        approved_validation_commands=["git_diff_check", "missing_validator"],
    )
    assert updated.validation_runs[-1].required_checks_passed is False
    assert updated.rollback_records[-1].rollback_status == "completed"
    assert updated.rollback_records[-1].source_worktree_unchanged is True


def test_015_local_commit_requires_separate_approval(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    surgeon, report = _proposal(repository)
    proposal = report.patch_proposals[0]
    updated = surgeon.execute_approved(
        report,
        patch_proposal_id=proposal.patch_proposal_id,
        unified_diff=_python_diff(),
        approval=_approval(proposal),
        approved_validation_commands=["git_diff_check"],
    )
    run = updated.isolated_runs[-1]
    with pytest.raises(ValidationError):
        surgeon.prepare_local_commit(
            updated,
            isolated_run_id=run.isolated_run_id,
            approval=_approval(proposal),
        )


def test_016_separate_commit_approval_creates_local_commit(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    surgeon, report = _proposal(repository)
    proposal = report.patch_proposals[0]
    updated = surgeon.execute_approved(
        report,
        patch_proposal_id=proposal.patch_proposal_id,
        unified_diff=_python_diff(),
        approval=_approval(proposal),
        approved_validation_commands=["git_diff_check"],
    )
    run = updated.isolated_runs[-1]
    committed = surgeon.prepare_local_commit(
        updated,
        isolated_run_id=run.isolated_run_id,
        approval=_approval(proposal, approval_type="local_commit_creation"),
    )
    review = committed.review_packages[-1]
    assert review.commit_created is True
    assert len(review.local_commit_sha) == 40
    assert committed.signal_usage.push_used is False
    assert committed.signal_usage.PR_created is False


def test_017_persistence_roundtrip_and_patch_storage(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    _, report = _proposal(repository)
    proposal = report.patch_proposals[0]
    store = BobaMemoryStore(tmp_path / "boba")
    store.save_boba_code_surgeon(
        report,
        unified_diff=_python_diff(),
        patch_proposal_id=proposal.patch_proposal_id,
    )
    assert store.load_boba_code_surgeon(PROJECT_ID) is not None
    assert (
        store.load_boba_code_surgeon_patch(PROJECT_ID, proposal.patch_proposal_id)
        == _python_diff()
    )


def test_018_export_excludes_full_diff_and_private_paths(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    _, report = _proposal(repository)
    proposal = report.patch_proposals[0]
    store = BobaMemoryStore(tmp_path / "boba")
    store.save_boba_code_surgeon(
        report,
        unified_diff=_python_diff(),
        patch_proposal_id=proposal.patch_proposal_id,
    )
    payload = store.export_boba_code_surgeon(PROJECT_ID)
    encoded = json.dumps(payload)
    assert "return False" not in encoded
    assert str(tmp_path) not in encoded
    assert payload["privacy"]["full_unified_diffs_excluded"] is True


def test_019_reset_removes_only_code_surgeon_metadata(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    _, report = _proposal(repository)
    store = BobaMemoryStore(tmp_path / "boba")
    store.save_boba_repair_planner(_planner())
    store.save_boba_code_surgeon(report)
    assert store.reset_boba_code_surgeon(PROJECT_ID) is True
    assert store.load_boba_code_surgeon(PROJECT_ID) is None
    assert store.load_boba_repair_planner(PROJECT_ID) is not None


def test_020_malformed_prior_report_degrades_safely(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    path = store.code_surgeon_path(PROJECT_ID)
    path.parent.mkdir(parents=True)
    path.write_text("{broken", encoding="utf-8")
    assert store.load_boba_code_surgeon(PROJECT_ID) is None


def test_021_required_skipped_check_does_not_pass(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    command = BobaCodeValidationCommandV1(
        validation_command_id="git_diff_check",
        name="git_diff_check",
        executable="git",
        arguments=["diff", "--check"],
        category="git_diff_check",
        required=True,
        approved=False,
    )
    result = execute_allowlisted_validation(repository, "run_skipped", [command])
    assert result.required_checks_passed is False
    assert result.results[0].status == "skipped"


def test_022_output_is_bounded_and_redacted(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    command = BobaCodeValidationCommandV1(
        validation_command_id="status",
        name="status",
        executable="git",
        arguments=["status", "--short"],
        category="custom_allowlisted",
        required=True,
        approved=True,
        output_limit_bytes=1_024,
    )
    result = execute_allowlisted_validation(repository, "run_status", [command])
    assert result.results[0].status == "passed"
    assert result.results[0].secrets_redacted is True


def test_023_trusted_registry_uses_argument_lists(tmp_path: Path) -> None:
    commands = build_validation_commands(
        _repository(tmp_path),
        ["src/sample.py"],
        ["git_diff_check", "python_compile"],
        policy=default_code_execution_policy(),
    )
    assert commands
    assert all(item.shell_used is False for item in commands)
    assert all(isinstance(item.arguments, list) for item in commands)


def test_024_protected_branch_policy() -> None:
    policy = default_code_execution_policy()
    assert is_protected_branch("main", policy) is True
    assert is_protected_branch("release/v1", policy) is True
    assert is_protected_branch("boba-repair/project/case-fix", policy) is False


def test_025_review_package_is_never_merge_ready(tmp_path: Path) -> None:
    _, report = _proposal(_repository(tmp_path))
    review = report.review_packages[0]
    assert review.ready_for_merge is False
    assert review.ready_for_manual_push is False
    assert "did not push" in " ".join(review.warnings).lower()


@pytest.mark.parametrize(
    "path",
    [
        "src/new.py",
        "src/new.pyi",
        "frontend/src/new.ts",
        "frontend/src/new.tsx",
        "frontend/src/new.js",
        "frontend/src/new.jsx",
        "config/new.json",
        "config/new.toml",
        "config/new.yaml",
        "config/new.yml",
        "docs/new.md",
        "styles/new.css",
        "styles/new.scss",
        "templates/new.html",
        "queries/new.sql",
        "notes/new.txt",
    ],
)
def test_026_allowed_text_extensions_are_not_path_blocked(
    tmp_path: Path,
    path: str,
) -> None:
    repository = _repository(tmp_path)
    report = BobaCodeSurgeonV1(repository).propose(
        PROJECT_ID,
        _planner(),
        repair_case_id=_planner_case_id(),
        unified_diff=_new_file_diff(path),
        affected_paths=[path],
    )
    assert report.patch_proposals[0].path_policy_passed is True


@pytest.mark.parametrize(
    "path",
    [
        ".git/config.txt",
        ".env",
        ".env.local",
        "secrets/key.txt",
        "credentials/token.txt",
        "private_keys/key.txt",
        "work/report.txt",
        "storage_data/report.txt",
        "media/readme.txt",
        "uploads/readme.txt",
        "downloads/readme.txt",
        "node_modules/pkg/readme.txt",
        "frontend/node_modules/pkg/readme.txt",
        "frontend/.next/cache.txt",
        ".venv/readme.txt",
        "dist/output.txt",
        "build/output.txt",
        "__pycache__/output.txt",
        ".pytest_cache/output.txt",
        ".mypy_cache/output.txt",
        ".ruff_cache/output.txt",
        "validation_reports/output.txt",
    ],
)
def test_027_protected_or_generated_paths_are_rejected(
    tmp_path: Path,
    path: str,
) -> None:
    repository = _repository(tmp_path)
    report = BobaCodeSurgeonV1(repository).propose(
        PROJECT_ID,
        _planner(),
        repair_case_id=_planner_case_id(),
        unified_diff=_new_file_diff(path),
        affected_paths=[path],
    )
    assert report.patch_proposals[0].path_policy_passed is False


@pytest.mark.parametrize(
    "path",
    [
        "assets/video.mp4",
        "assets/video.mov",
        "assets/video.mkv",
        "assets/video.webm",
        "assets/audio.wav",
        "assets/audio.mp3",
        "assets/image.png",
        "assets/image.jpg",
        "assets/image.jpeg",
        "assets/image.gif",
        "assets/document.pdf",
        "assets/archive.zip",
        "bin/tool.exe",
        "bin/tool.dll",
        "bin/tool.so",
        "data/state.db",
        "data/state.sqlite",
        "data/state.sqlite3",
    ],
)
def test_028_binary_media_and_database_paths_are_rejected(
    tmp_path: Path,
    path: str,
) -> None:
    repository = _repository(tmp_path)
    report = BobaCodeSurgeonV1(repository).propose(
        PROJECT_ID,
        _planner(),
        repair_case_id=_planner_case_id(),
        unified_diff=_new_file_diff(path),
        affected_paths=[path],
    )
    assert report.patch_proposals[0].path_policy_passed is False


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("API_KEY='sensitive-runtime-value-1234'", False),
        ("password='super-secret-password-value'", False),
        ("token='" + "gh" + "p_" + ("1" * 30) + "'", False),
        ("key='" + "AK" + "IA" + "ABCDEFGHIJKLMNOP'", False),
        ("auth='eyJabcdefghijk.abcdefghijk.abcdefghijk'", False),
        ("url='postgres://admin:secret-password@localhost/db'", False),
        ("-----BEGIN PRIVATE KEY-----", False),
        ("API_KEY='test-placeholder-value'", True),
        ("password='example-password'", True),
        ("safe_value = 'ordinary configuration'", True),
    ],
)
def test_029_secret_scanner_is_conservative(line: str, expected: bool) -> None:
    passed, findings = scan_patch_for_secrets(_new_file_diff("src/new.py", line))
    assert passed is expected
    assert all("super-secret-password-value" not in item for item in findings)


@pytest.mark.parametrize(
    ("executable", "arguments"),
    [
        ("git", ["push", "origin", "branch"]),
        ("git", ["merge", "main"]),
        ("git", ["rebase", "main"]),
        ("git", ["reset", "--hard"]),
        ("git", ["clean", "-fd"]),
        ("git", ["tag", "v1"]),
        ("git", ["pull"]),
        ("git", ["remote", "add", "x", "url"]),
        ("git", ["status", "--force"]),
        ("python", ["-c", "print('unsafe')"]),
        ("python", ["-m", "pip", "install", "package"]),
        ("npm", ["install"]),
        ("npm", ["run", "lint", "&&", "shutdown"]),
        ("git", ["status", "|", "more"]),
        ("git", ["status", ">", "out.txt"]),
        ("git", ["status", ";", "echo"]),
        ("git", ["status", "||", "echo"]),
        ("git", ["status", "$(whoami)"]),
        ("curl", ["https://example.invalid"]),
        ("powershell", ["Restart-Service", "api"]),
        ("cmd.exe", ["/c", "echo unsafe"]),
        ("bash", ["-c", "echo unsafe"]),
    ],
)
def test_030_untrusted_commands_are_rejected(
    executable: str,
    arguments: list[str],
) -> None:
    command = BobaCodeValidationCommandV1(
        validation_command_id="unsafe",
        name="unsafe",
        executable=executable,
        arguments=arguments,
        category="custom_allowlisted",
        required=True,
        approved=True,
    )
    safe, reason = validate_command_safety(command)
    assert safe is False
    assert reason


@pytest.mark.parametrize(
    "value",
    [
        "Project Name",
        "../project",
        "project@{bad}",
        "project.lock",
        "project;shutdown",
        "project|pipe",
        "project:drive",
        "project\\windows",
        "PROJECT_UPPER",
        "project..dots",
        "",
        "a" * 400,
    ],
)
def test_031_repair_branch_components_are_sanitized(value: str) -> None:
    branch = sanitize_repair_branch_name(value, value, value)
    assert branch.startswith("boba-repair/")
    assert ".." not in branch
    assert "@{" not in branch
    assert not branch.endswith(".lock")
    assert len(branch) <= 230


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("+@pytest.mark.skip(reason='hide failure')", False),
        ("+pytest.skip('hide failure')", False),
        ("+except Exception: pass", False),
        ("+return True", False),
        ("+skip_validation = True", False),
        ("+rights_check = False", False),
        ("+print('debug')", True),
        ("+value = result", True),
    ],
)
def test_032_patch_quality_review_blocks_suspicious_fixes(
    line: str,
    expected: bool,
) -> None:
    passed, _ = review_patch_quality(f"diff --git a/x.py b/x.py\n{line}\n")
    assert passed is expected


def test_033_path_traversal_scope_is_rejected() -> None:
    passed, warnings = validate_patch_scope(["../outside.py"], ["src"])
    assert passed is False
    assert warnings


def test_034_absolute_path_diff_is_rejected(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    report = BobaCodeSurgeonV1(repository).propose(
        PROJECT_ID,
        _planner(),
        repair_case_id=_planner_case_id(),
        unified_diff=_new_file_diff("C:/outside.py"),
        affected_paths=["C:/outside.py"],
    )
    assert report.patch_proposals[0].path_policy_passed is False


def test_035_unc_path_diff_is_rejected(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    report = BobaCodeSurgeonV1(repository).propose(
        PROJECT_ID,
        _planner(),
        repair_case_id=_planner_case_id(),
        unified_diff=_new_file_diff("//server/share/outside.py"),
        affected_paths=["//server/share/outside.py"],
    )
    assert report.patch_proposals[0].path_policy_passed is False


def test_035b_symlink_escape_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(tmp_path)
    link_path = repository / "src" / "escape"
    outside = tmp_path / "outside"
    outside.mkdir()
    path_class = type(repository)
    original_exists = path_class.exists
    original_is_symlink = path_class.is_symlink
    original_resolve = path_class.resolve

    def fake_exists(path: Any) -> bool:
        if path == link_path:
            return True
        return original_exists(path)

    def fake_is_symlink(path: Any) -> bool:
        if path == link_path:
            return True
        return original_is_symlink(path)

    def fake_resolve(path: Any, *args: Any, **kwargs: Any) -> Path:
        if path == link_path:
            return original_resolve(outside)
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(path_class, "exists", fake_exists)
    monkeypatch.setattr(path_class, "is_symlink", fake_is_symlink)
    monkeypatch.setattr(path_class, "resolve", fake_resolve)
    passed, _, _, warnings = code_surgeon_module._validate_single_path(
        "src/escape/new.py",
        repository_root=repository,
        policy=default_code_execution_policy(),
    )
    assert passed is False
    assert "symlink escapes repository root" in warnings


def test_036_shell_true_is_not_valid_contract() -> None:
    with pytest.raises(PydanticValidationError):
        BobaCodeValidationCommandV1(
            validation_command_id="bad",
            name="bad",
            executable="git",
            arguments=["status"],
            category="custom_allowlisted",
            approved=True,
            shell_used=True,
        )


def test_037_all_signal_prohibitions_default_false(tmp_path: Path) -> None:
    _, report = _proposal(_repository(tmp_path))
    signals = report.signal_usage
    assert signals.main_branch_modified is False
    assert signals.push_used is False
    assert signals.PR_created is False
    assert signals.merge_used is False
    assert signals.tag_used is False
    assert signals.external_api_used is False
    assert signals.network_access_used is False
    assert signals.package_installation_used is False
    assert signals.service_restart_used is False
    assert signals.destructive_git_used is False


def test_038_contracts_roundtrip(tmp_path: Path) -> None:
    surgeon, report = _proposal(_repository(tmp_path))
    proposal = report.patch_proposals[0]
    approval = _approval(proposal)
    run = BobaCodeIsolatedRunV1(
        isolated_run_id="run_roundtrip",
        patch_proposal_id=proposal.patch_proposal_id,
        mode="proposal_only",
        base_branch="main",
        base_commit_sha=proposal.base_commit_sha,
        repair_branch=proposal.proposed_branch,
        run_status="not_started",
    )
    command = build_validation_commands(
        surgeon.repository_root,
        ["src/sample.py"],
        ["git_diff_check"],
        policy=default_code_execution_policy(),
    )[0]
    result = BobaCodeValidationResultV1(
        validation_result_id="result_roundtrip",
        validation_command_id=command.validation_command_id,
        name=command.name,
        status="passed",
        exit_code=0,
    )
    validation = BobaCodeValidationRunV1(
        validation_run_id="validation_roundtrip",
        isolated_run_id=run.isolated_run_id,
        commands=[command],
        results=[result],
        required_checks_passed=True,
        optional_checks_passed=True,
        acceptance_criteria_met=True,
    )
    rollback = BobaCodeRollbackRecordV1(
        rollback_record_id="rollback_roundtrip",
        isolated_run_id=run.isolated_run_id,
        rollback_trigger="Not required.",
        rollback_status="not_required",
    )
    models = [
        (report.repair_cases[0], BobaCodeRepairCaseV1),
        (proposal.files[0], BobaCodePatchFileV1),
        (proposal.hunks[0], BobaCodePatchHunkV1),
        (proposal, BobaCodePatchProposalV1),
        (approval, BobaCodeApprovalRecordV1),
        (run, BobaCodeIsolatedRunV1),
        (command, BobaCodeValidationCommandV1),
        (result, BobaCodeValidationResultV1),
        (validation, BobaCodeValidationRunV1),
        (rollback, BobaCodeRollbackRecordV1),
        (report.review_packages[0], BobaCodeReviewPackageV1),
        (report.execution_handoffs[0], BobaCodeSurgeonExecutionHandoffV1),
        (report.surgeon_summary, BobaCodeSurgeonSummaryV1),
        (report.signal_usage, BobaCodeSurgeonSignalUsageV1),
        (report, BobaCodeSurgeonSetV1),
    ]
    for value, model in models:
        _roundtrip(value, model)


def test_039_api_propose_get_export_and_reset(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    integration, store = _integration(tmp_path, repository)
    store.save_boba_repair_planner(_planner())
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    body = {
        "repair_case_id": _planner_case_id(),
        "unified_diff": _python_diff(),
        "affected_paths": ["src/sample.py"],
    }
    with TestClient(app) as client:
        proposed = client.post(
            f"/api/v1/boba/projects/{PROJECT_ID}/code-surgeon/propose",
            json=body,
        )
        loaded = client.get(
            f"/api/v1/boba/projects/{PROJECT_ID}/code-surgeon"
        )
        exported = client.get(
            f"/api/v1/boba/projects/{PROJECT_ID}/code-surgeon/export"
        )
        reset = client.delete(
            f"/api/v1/boba/projects/{PROJECT_ID}/code-surgeon"
        )
    assert proposed.status_code == 200, proposed.text
    assert loaded.status_code == 200, loaded.text
    assert exported.status_code == 200, exported.text
    assert reset.status_code == 200, reset.text
    assert reset.json()["repair_planner_removed"] is False
    assert store.load_boba_repair_planner(PROJECT_ID) is not None


def test_040_api_execute_rejects_stale_approval(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    integration, store = _integration(tmp_path, repository)
    store.save_boba_repair_planner(_planner())
    report = asyncio.run(
        integration.generate_boba_code_surgeon_proposal(
            PROJECT_ID,
            repair_case_id=_planner_case_id(),
            unified_diff=_python_diff(),
            affected_paths=["src/sample.py"],
        )
    )
    proposal = report.patch_proposals[0]
    approval = _approval(proposal, base_sha="1" * 40)
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/boba/projects/{PROJECT_ID}/code-surgeon/execute-approved",
            json={
                "patch_proposal_id": proposal.patch_proposal_id,
                "approval": approval.model_dump(mode="json"),
                "approved_validation_commands": ["git_diff_check"],
            },
        )
    assert response.status_code == 200, response.text
    assert response.json()["isolated_runs"][-1]["run_status"] == "blocked"


def test_041_deterministic_template_is_supported(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    surgeon = BobaCodeSurgeonV1(repository)
    report = surgeon.propose(
        PROJECT_ID,
        _planner(),
        repair_case_id=_planner_case_id(),
        deterministic_template_identifier="exact_text_replacement_v1",
        template_parameters={
            "path": "src/sample.py",
            "old_text": "return value - 1",
            "new_text": "return value + 1",
        },
        affected_paths=["src/sample.py"],
    )
    assert report.patch_proposals[0].proposal_source == "deterministic_template"
    assert surgeon.last_proposed_diff


def test_042_unsupported_template_is_rejected(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    with pytest.raises(ValidationError):
        BobaCodeSurgeonV1(repository).propose(
            PROJECT_ID,
            _planner(),
            repair_case_id=_planner_case_id(),
            deterministic_template_identifier="arbitrary_ai_patch",
        )


def test_043_file_count_limit_is_enforced(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    diff = "".join(_new_file_diff(f"src/new_{index}.py") for index in range(13))
    with pytest.raises(ValidationError):
        BobaCodeSurgeonV1(repository).propose(
            PROJECT_ID,
            _planner(),
            repair_case_id=_planner_case_id(),
            unified_diff=diff,
            affected_paths=["src"],
        )


def test_044_changed_line_limit_is_enforced(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    content = "\n".join(f"+value_{index} = {index}" for index in range(801))
    diff = (
        "diff --git a/src/large.py b/src/large.py\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/src/large.py\n"
        "@@ -0,0 +1,801 @@\n"
        f"{content}\n"
    )
    with pytest.raises(ValidationError):
        BobaCodeSurgeonV1(repository).propose(
            PROJECT_ID,
            _planner(),
            repair_case_id=_planner_case_id(),
            unified_diff=diff,
            affected_paths=["src/large.py"],
        )


def test_045_diff_size_limit_is_enforced(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    oversized = _new_file_diff("src/large.py", "x" * 200_001)
    with pytest.raises(ValidationError):
        BobaCodeSurgeonV1(repository).propose(
            PROJECT_ID,
            _planner(),
            repair_case_id=_planner_case_id(),
            unified_diff=oversized,
            affected_paths=["src/large.py"],
        )


def test_046_unapproved_workflow_change_is_blocked(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    path = ".github/workflows/test.yml"
    report = BobaCodeSurgeonV1(repository).propose(
        PROJECT_ID,
        _planner(),
        repair_case_id=_planner_case_id(),
        unified_diff=_new_file_diff(path, "name: test"),
        affected_paths=[path],
    )
    proposal = report.patch_proposals[0]
    assert proposal.workflow_change_detected is True
    assert proposal.path_policy_passed is False


def test_047_unapproved_dependency_change_is_blocked(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    path = "pyproject.toml"
    report = BobaCodeSurgeonV1(repository).propose(
        PROJECT_ID,
        _planner(),
        repair_case_id=_planner_case_id(),
        unified_diff=_new_file_diff(path, "[project]"),
        affected_paths=[path],
    )
    proposal = report.patch_proposals[0]
    assert proposal.dependency_change_detected is True
    assert proposal.path_policy_passed is False


def test_048_review_package_generates_pr_metadata_only(tmp_path: Path) -> None:
    _, report = _proposal(_repository(tmp_path))
    review = report.review_packages[0]
    assert review.PR_title
    assert review.PR_body
    assert report.signal_usage.PR_created is False


def test_049_original_repair_planner_is_unchanged(tmp_path: Path) -> None:
    planner = _planner().model_copy(deep=True)
    before = planner.model_dump_json()
    BobaCodeSurgeonV1(_repository(tmp_path)).propose(
        PROJECT_ID,
        planner,
        repair_case_id=_planner_case_id(planner),
        unified_diff=_python_diff(),
        affected_paths=["src/sample.py"],
    )
    assert planner.model_dump_json() == before


def test_050_no_generated_outputs_are_tracked_by_policy() -> None:
    policy = default_code_execution_policy()
    assert "work" in policy.protected_paths
    assert "storage_data" in policy.protected_paths
    assert "media" in policy.protected_paths
    assert "node_modules" in policy.protected_paths
    assert ".venv" in policy.protected_paths
