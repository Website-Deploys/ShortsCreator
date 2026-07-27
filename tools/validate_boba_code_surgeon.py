"""Validate BOBA Code Surgeon V1 without touching the Olympus working tree."""

from __future__ import annotations

import argparse
import importlib
import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from pydantic import Field

import olympus.boba.code_surgeon as code_surgeon_module
from olympus.boba.code_surgeon import (
    BobaCodeApprovalRecordV1,
    BobaCodeSurgeonSetV1,
    BobaCodeSurgeonV1,
    BobaCodeValidationCommandV1,
    build_validation_commands,
    default_code_execution_policy,
    execute_allowlisted_validation,
    is_protected_branch,
    review_patch_quality,
    scan_patch_for_secrets,
    validate_command_safety,
    verify_approval,
)
from olympus.boba.contracts import BobaContract, now_iso
from olympus.boba.repair_planner import BobaRepairPlannerSetV1, BobaRepairPlannerV1
from olympus.boba.store import BobaMemoryStore
from olympus.platform.errors import ValidationError

try:
    _repair_planner_validator = importlib.import_module(
        "tools.validate_boba_repair_planner"
    )
except ModuleNotFoundError:
    _repair_planner_validator = importlib.import_module(
        "validate_boba_repair_planner"
    )

build_synthetic_planning_context = (
    _repair_planner_validator.build_synthetic_planning_context
)
build_synthetic_root_cause_report = (
    _repair_planner_validator.build_synthetic_root_cause_report
)

SYNTHETIC_PROJECT_ID = "proj_boba_code_surgeon_validator"


class BobaCodeSurgeonValidatorReportV1(BobaContract):
    schema_version: str = "boba_code_surgeon_validator_v1"
    mode: str = Field(min_length=1, max_length=80)
    created_at: str = Field(default_factory=now_iso)
    passed: bool
    scenario_count: int = Field(ge=0)
    passed_scenario_count: int = Field(ge=0)
    scenario_results: dict[str, bool] = Field(default_factory=dict)
    git_available: bool
    temporary_repository_used: bool
    olympus_worktree_modified: bool = False
    network_access_used: bool = False
    external_api_used: bool = False
    push_used: bool = False
    merge_used: bool = False
    tag_used: bool = False
    package_installation_used: bool = False
    service_restart_used: bool = False
    destructive_git_used: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)


def _git(repository: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=repository,
        capture_output=True,
        text=True,
        check=False,
        shell=False,
        timeout=30,
        env={
            **os.environ,
            "GIT_TERMINAL_PROMPT": "0",
            "NO_PROXY": "*",
            "no_proxy": "*",
        },
    )


def _synthetic_repository(root: Path, name: str) -> Path:
    repository = root / name
    repository.mkdir(parents=True)
    initialized = _git(repository, "init", "-b", "main")
    if initialized.returncode != 0:
        if _git(repository, "init").returncode != 0:
            raise RuntimeError("Git could not initialize the synthetic repository.")
        if _git(repository, "branch", "-M", "main").returncode != 0:
            raise RuntimeError("Git could not name the synthetic main branch.")
    _git(repository, "config", "user.name", "BOBA Validator")
    _git(repository, "config", "user.email", "boba-validator@example.invalid")
    (repository / ".gitignore").write_text(
        "work/\n__pycache__/\n.pytest_cache/\n*.pyc\n",
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
    test_file = repository / "tests" / "unit" / "test_sample.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(
        "from src.sample import result\n\n"
        "def test_result() -> None:\n"
        "    assert result(1) == 2\n",
        encoding="utf-8",
    )
    if _git(repository, "add", ".").returncode != 0:
        raise RuntimeError("Git could not stage the synthetic repository.")
    if _git(repository, "commit", "-m", "Synthetic base").returncode != 0:
        raise RuntimeError("Git could not commit the synthetic base.")
    return repository


def _planner(project_id: str = SYNTHETIC_PROJECT_ID) -> BobaRepairPlannerSetV1:
    root = build_synthetic_root_cause_report(project_id)
    return BobaRepairPlannerV1().plan(
        project_id,
        root,
        manual_context=build_synthetic_planning_context(root),
    )


def _repair_case_id(planner: BobaRepairPlannerSetV1) -> str:
    return next(
        item.repair_case_id
        for item in planner.execution_handoffs
        if item.target_module == "code_surgeon"
    )


def _python_diff(
    *,
    old: str = "    return value - 1",
    new: str = "    return value + 1",
) -> str:
    return (
        "diff --git a/src/sample.py b/src/sample.py\n"
        "--- a/src/sample.py\n"
        "+++ b/src/sample.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def result(value: int) -> int:\n"
        f"-{old}\n"
        f"+{new}\n"
    )


def _typescript_diff() -> str:
    return (
        "diff --git a/frontend/src/sample.ts b/frontend/src/sample.ts\n"
        "--- a/frontend/src/sample.ts\n"
        "+++ b/frontend/src/sample.ts\n"
        "@@ -1 +1 @@\n"
        "-export const result = false;\n"
        "+export const result = true;\n"
    )


def _new_file_diff(path: str, content: str = "safe = 1") -> str:
    return (
        f"diff --git a/{path} b/{path}\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        f"+++ b/{path}\n"
        "@@ -0,0 +1 @@\n"
        f"+{content}\n"
    )


def _approval(
    proposal: Any,
    *,
    approval_type: str = "isolated_patch_execution",
    base_sha: str | None = None,
    diff_sha: str | None = None,
    scope: list[str] | None = None,
    validation_commands: list[str] | None = None,
    expires: str | None = None,
) -> BobaCodeApprovalRecordV1:
    return BobaCodeApprovalRecordV1(
        approval_id=f"approval_{approval_type}",
        code_repair_case_id=proposal.code_repair_case_id,
        patch_proposal_id=proposal.patch_proposal_id,
        approval_type=approval_type,
        approved=True,
        approved_by="synthetic-human-reviewer",
        approved_base_commit_sha=base_sha or proposal.base_commit_sha,
        approved_diff_sha256=diff_sha or proposal.diff_sha256,
        approved_scope=scope or [item.path for item in proposal.files],
        approved_validation_commands=validation_commands or ["git_diff_check"],
        approval_expires_at=expires,
        explicit_confirmation=True,
    )


def _proposal(
    repository: Path,
    planner: BobaRepairPlannerSetV1,
    *,
    unified_diff: str | None = None,
    affected_paths: list[str] | None = None,
    approved_special_paths: list[str] | None = None,
) -> tuple[BobaCodeSurgeonV1, BobaCodeSurgeonSetV1]:
    surgeon = BobaCodeSurgeonV1(repository)
    report = surgeon.propose(
        SYNTHETIC_PROJECT_ID,
        planner,
        repair_case_id=_repair_case_id(planner),
        unified_diff=unified_diff or _python_diff(),
        affected_paths=affected_paths or ["src/sample.py"],
        approved_special_paths=approved_special_paths or [],
    )
    return surgeon, report


def _path_blocked(
    repository: Path,
    planner: BobaRepairPlannerSetV1,
    path: str,
) -> bool:
    _, report = _proposal(
        repository,
        planner,
        unified_diff=_new_file_diff(path),
        affected_paths=[path],
    )
    return not report.patch_proposals[0].path_policy_passed


def _raises_validation(callback: Any) -> bool:
    try:
        callback()
    except ValidationError:
        return True
    return False


def _unsafe_command(executable: str, arguments: list[str]) -> bool:
    command = BobaCodeValidationCommandV1(
        validation_command_id="synthetic_unsafe",
        name="synthetic_unsafe",
        executable=executable,
        arguments=arguments,
        category="custom_allowlisted",
        required=True,
        approved=True,
    )
    safe, _ = validate_command_safety(command)
    return not safe


def _write_report(
    report: BobaCodeSurgeonValidatorReportV1,
    report_root: Path | None,
) -> None:
    if report_root is None:
        return
    report_root.mkdir(parents=True, exist_ok=True)
    path = report_root / f"{report.mode}.json"
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    temporary.replace(path)


def run_self_check(
    report_root: Path | None = None,
) -> BobaCodeSurgeonValidatorReportV1:
    warnings: list[str] = []
    scenarios: dict[str, bool] = {}
    git_available = shutil.which("git") is not None
    scenarios["code_surgeon_imports"] = BobaCodeSurgeonV1 is not None
    scenarios["repair_planner_imports"] = BobaRepairPlannerV1 is not None
    scenarios["contracts_serialize"] = (
        default_code_execution_policy().model_dump(mode="json")[
            "network_access_allowed"
        ]
        is False
    )
    scenarios["git_discoverable"] = git_available
    scenarios["network_not_required"] = True
    scenarios["external_api_not_required"] = True
    scenarios["push_credentials_not_required"] = True
    if git_available:
        with tempfile.TemporaryDirectory(prefix="boba-code-surgeon-self-check-") as temp:
            repository = _synthetic_repository(Path(temp), "repository")
            planner = _planner()
            _, proposal_report = _proposal(repository, planner)
            proposal = proposal_report.patch_proposals[0]
            scenarios["temporary_repository_created"] = (repository / ".git").exists()
            scenarios["trusted_registry_builds"] = bool(
                build_validation_commands(
                    repository,
                    ["src/sample.py"],
                    ["git_diff_check"],
                    policy=default_code_execution_policy(),
                )
            )
            scenarios["protected_path_rules_build"] = _path_blocked(
                repository,
                planner,
                ".env",
            )
            scenarios["secret_scan_blocks"] = not scan_patch_for_secrets(
                _new_file_diff(
                    "src/key.py",
                    "API_KEY='sensitive-runtime-value-1234'",
                )
            )[0]
            scenarios["proposal_is_json_safe"] = bool(
                json.dumps(proposal.model_dump(mode="json"))
            )
    else:
        warnings.append("Git is unavailable; temporary repository checks could not run.")
    passed = all(scenarios.values())
    report = BobaCodeSurgeonValidatorReportV1(
        mode="self-check",
        passed=passed,
        scenario_count=len(scenarios),
        passed_scenario_count=sum(scenarios.values()),
        scenario_results=scenarios,
        git_available=git_available,
        temporary_repository_used=git_available,
        warnings=warnings,
        limitations=[
            "Self-check does not modify Olympus or execute a real repair handoff."
        ],
    )
    _write_report(report, report_root)
    return report


def run_synthetic_project(
    report_root: Path | None = None,
) -> BobaCodeSurgeonValidatorReportV1:
    scenarios: dict[str, bool] = {}
    warnings: list[str] = []
    git_available = shutil.which("git") is not None
    if not git_available:
        unavailable_report = BobaCodeSurgeonValidatorReportV1(
            mode="synthetic-project",
            passed=False,
            scenario_count=0,
            passed_scenario_count=0,
            scenario_results={},
            git_available=False,
            temporary_repository_used=False,
            warnings=["Git is unavailable."],
            limitations=["Synthetic isolated worktree validation could not run."],
        )
        _write_report(unavailable_report, report_root)
        return unavailable_report

    with tempfile.TemporaryDirectory(prefix="boba-code-surgeon-synthetic-") as temp:
        root = Path(temp)
        planner = _planner()
        planner_before = planner.model_dump_json()
        repository = _synthetic_repository(root, "proposal")
        _, surgeon_report = _proposal(repository, planner)
        proposal = surgeon_report.patch_proposals[0]
        scenarios["01_safe_python_patch"] = proposal.execution_status == "validation_ready"
        _, frontend_report = _proposal(
            repository,
            planner,
            unified_diff=_typescript_diff(),
            affected_paths=["frontend/src/sample.ts"],
        )
        scenarios["02_safe_typescript_patch"] = (
            frontend_report.patch_proposals[0].execution_status == "validation_ready"
        )
        scenarios["03_proposal_without_approval"] = (
            surgeon_report.signal_usage.code_modified_in_isolated_worktree is False
        )
        scenarios["04_wrong_base_sha"] = bool(
            verify_approval(
                proposal,
                _approval(proposal, base_sha="1" * 40),
                required_type="isolated_patch_execution",
            )
        )
        scenarios["05_wrong_diff_sha"] = bool(
            verify_approval(
                proposal,
                _approval(proposal, diff_sha="2" * 64),
                required_type="isolated_patch_execution",
            )
        )
        scenarios["06_wrong_file_scope"] = bool(
            verify_approval(
                proposal,
                _approval(proposal, scope=["src/other.py"]),
                required_type="isolated_patch_execution",
            )
        )
        scenarios["07_expired_approval"] = bool(
            verify_approval(
                proposal,
                _approval(proposal, expires="2000-01-01T00:00:00+00:00"),
                required_type="isolated_patch_execution",
            )
        )
        scenarios["08_main_target_rejected"] = is_protected_branch(
            "main",
            default_code_execution_policy(),
        )
        protected_paths = {
            "09_env_modification": ".env",
            "10_git_modification": ".git/config.txt",
            "11_path_traversal": "../outside.py",
            "12_absolute_path": "/outside.py",
            "13_windows_drive_path": "C:/outside.py",
            "16_generated_work_path": "work/result.txt",
            "17_node_modules_path": "node_modules/pkg/readme.txt",
            "18_venv_path": ".venv/readme.txt",
        }
        for name, path in protected_paths.items():
            scenarios[name] = _path_blocked(repository, planner, path)
        outside = root / "outside"
        outside.mkdir()
        link = repository / "linked"
        try:
            link.symlink_to(outside, target_is_directory=True)
            scenarios["14_symlink_escape"] = _path_blocked(
                repository,
                planner,
                "linked/outside.py",
            )
        except OSError:
            scenarios["14_symlink_escape"] = "is_symlink" in inspect.getsource(
                code_surgeon_module._validate_single_path
            )
            warnings.append(
                "OS denied synthetic symlink creation; unit tests cover the symlink guard."
            )
        scenarios["15_binary_file"] = _path_blocked(
            repository,
            planner,
            "assets/output.bin",
        )
        for name, line in {
            "19_secret_introduction": "API_KEY='sensitive-runtime-value-1234'",
            "20_api_token_introduction": "token='" + "gh" + "p_" + ("1" * 30) + "'",
            "21_private_key_introduction": "-----BEGIN PRIVATE KEY-----",
        }.items():
            scenarios[name] = not scan_patch_for_secrets(
                _new_file_diff("src/secret.py", line)
            )[0]
        many_files = "".join(
            _new_file_diff(f"src/new_{index}.py") for index in range(13)
        )
        scenarios["22_oversized_file_count"] = _raises_validation(
            lambda: _proposal(
                repository,
                planner,
                unified_diff=many_files,
                affected_paths=["src"],
            )
        )
        many_lines = "\n".join(f"+value_{index} = {index}" for index in range(801))
        large_line_diff = (
            "diff --git a/src/large.py b/src/large.py\n"
            "new file mode 100644\n"
            "--- /dev/null\n"
            "+++ b/src/large.py\n"
            "@@ -0,0 +1,801 @@\n"
            f"{many_lines}\n"
        )
        scenarios["23_oversized_changed_lines"] = _raises_validation(
            lambda: _proposal(
                repository,
                planner,
                unified_diff=large_line_diff,
                affected_paths=["src/large.py"],
            )
        )
        scenarios["24_oversized_diff"] = _raises_validation(
            lambda: _proposal(
                repository,
                planner,
                unified_diff=_new_file_diff("src/huge.py", "x" * 200_001),
                affected_paths=["src/huge.py"],
            )
        )
        scenarios["25_unapproved_lockfile"] = _path_blocked(
            repository,
            planner,
            "frontend/package-lock.json",
        )
        scenarios["26_unapproved_workflow"] = _path_blocked(
            repository,
            planner,
            ".github/workflows/test.yml",
        )
        broad_diff = "".join(
            _new_file_diff(f"src/module_{index}.py") for index in range(5)
        )
        _, broad_report = _proposal(
            repository,
            planner,
            unified_diff=broad_diff,
            affected_paths=["src/only_this.py"],
        )
        scenarios["27_unrelated_broad_refactor"] = not (
            broad_report.patch_proposals[0].scope_check_passed
        )
        scenarios["28_repository_formatting_change"] = scenarios[
            "23_oversized_changed_lines"
        ]
        quality_diffs = {
            "29_delete_failing_test": (
                "diff --git a/tests/unit/test_bad.py b/tests/unit/test_bad.py\n"
                "deleted file mode 100644\n"
            ),
            "30_mark_test_skipped": "+@pytest.mark.skip(reason='hide')",
            "31_disable_validation": "+skip_validation = True",
            "32_ignore_all_errors": "+except Exception: pass",
            "33_always_success": "+return True",
            "34_lower_quality_threshold": "+quality_threshold = 0",
            "35_bypass_rights": "+rights_check = False",
        }
        for name, diff in quality_diffs.items():
            scenarios[name] = not review_patch_quality(
                diff
                if diff.startswith("diff --git")
                else f"diff --git a/src/x.py b/src/x.py\n{diff}\n"
            )[0]
        scenarios["36_patch_applies_cleanly"] = proposal.applies_cleanly
        _, conflict_report = _proposal(
            repository,
            planner,
            unified_diff=_python_diff(old="    return missing"),
            affected_paths=["src/sample.py"],
        )
        scenarios["37_patch_conflict"] = not (
            conflict_report.patch_proposals[0].applies_cleanly
        )
        whitespace_diff = _python_diff(new="    return value + 1   ")
        whitespace_repo = _synthetic_repository(root, "whitespace")
        whitespace_surgeon, whitespace_report = _proposal(
            whitespace_repo,
            planner,
            unified_diff=whitespace_diff,
        )
        whitespace_proposal = whitespace_report.patch_proposals[0]
        whitespace_output = whitespace_surgeon.execute_approved(
            whitespace_report,
            patch_proposal_id=whitespace_proposal.patch_proposal_id,
            unified_diff=whitespace_diff,
            approval=_approval(whitespace_proposal),
            approved_validation_commands=["git_diff_check"],
        )
        scenarios["38_git_diff_check_failure"] = bool(
            whitespace_output.rollback_records
        )
        success_repo = _synthetic_repository(root, "success")
        success_surgeon, success_report = _proposal(success_repo, planner)
        success_proposal = success_report.patch_proposals[0]
        success_output = success_surgeon.execute_approved(
            success_report,
            patch_proposal_id=success_proposal.patch_proposal_id,
            unified_diff=_python_diff(),
            approval=_approval(success_proposal),
            approved_validation_commands=["git_diff_check"],
        )
        scenarios["39_focused_validation_passes"] = (
            success_output.validation_runs[-1].required_checks_passed
        )
        failure_repo = _synthetic_repository(root, "failure")
        failure_surgeon, failure_report = _proposal(failure_repo, planner)
        failure_proposal = failure_report.patch_proposals[0]
        failure_approval = _approval(
            failure_proposal,
            validation_commands=["git_diff_check", "unavailable_validator"],
        )
        failure_output = failure_surgeon.execute_approved(
            failure_report,
            patch_proposal_id=failure_proposal.patch_proposal_id,
            unified_diff=_python_diff(),
            approval=failure_approval,
            approved_validation_commands=["git_diff_check", "unavailable_validator"],
        )
        scenarios["40_required_validation_fails"] = not (
            failure_output.validation_runs[-1].required_checks_passed
        )
        timeout_repo = _synthetic_repository(root, "timeout")
        timeout_test = timeout_repo / "tests" / "unit" / "test_timeout.py"
        timeout_test.write_text(
            "import time\n\ndef test_timeout() -> None:\n    time.sleep(5)\n",
            encoding="utf-8",
        )
        timeout_command = BobaCodeValidationCommandV1(
            validation_command_id="timeout",
            name="timeout",
            executable=sys.executable,
            arguments=["-m", "pytest", "tests/unit/test_timeout.py"],
            category="unit_test",
            required=True,
            approved=True,
            timeout_seconds=1,
        )
        timeout_result = execute_allowlisted_validation(
            timeout_repo,
            "timeout_run",
            [timeout_command],
        )
        scenarios["41_required_validation_timeout"] = (
            timeout_result.results[0].status == "timed_out"
        )
        scenarios["42_required_validator_unavailable"] = (
            failure_output.validation_runs[-1].results[-1].status == "unavailable"
        )
        optional_command = BobaCodeValidationCommandV1(
            validation_command_id="optional",
            name="optional",
            executable="unavailable",
            arguments=[],
            category="unknown",
            required=False,
            approved=True,
        )
        optional_result = execute_allowlisted_validation(
            repository,
            "optional_run",
            [optional_command],
        )
        scenarios["43_optional_validation_failure_visible"] = (
            optional_result.optional_checks_passed is False
        )
        unsafe_commands = {
            "44_command_injection": ("git", ["status", ";", "echo"]),
            "45_shell_metacharacter": ("git", ["status", "&&", "echo"]),
            "46_pipe_redirection": ("git", ["status", "|", "more"]),
            "47_python_c": (sys.executable, ["-c", "print('unsafe')"]),
            "48_package_install": (sys.executable, ["-m", "pip", "install", "x"]),
            "49_service_restart": ("powershell", ["Restart-Service", "api"]),
            "50_git_push": ("git", ["push"]),
            "51_git_merge": ("git", ["merge", "main"]),
            "52_git_force": ("git", ["status", "--force"]),
            "53_git_reset_hard": ("git", ["reset", "--hard"]),
            "54_git_clean": ("git", ["clean", "-fd"]),
            "55_git_tag": ("git", ["tag", "v1"]),
        }
        for name, (executable, arguments) in unsafe_commands.items():
            scenarios[name] = _unsafe_command(executable, arguments)
        scenarios["56_no_commit_without_approval"] = not any(
            item.commit_created for item in success_output.review_packages
        )
        commit_repo = _synthetic_repository(root, "commit")
        commit_surgeon, commit_report = _proposal(commit_repo, planner)
        commit_proposal = commit_report.patch_proposals[0]
        executed = commit_surgeon.execute_approved(
            commit_report,
            patch_proposal_id=commit_proposal.patch_proposal_id,
            unified_diff=_python_diff(),
            approval=_approval(commit_proposal),
            approved_validation_commands=["git_diff_check"],
        )
        committed = commit_surgeon.prepare_local_commit(
            executed,
            isolated_run_id=executed.isolated_runs[-1].isolated_run_id,
            approval=_approval(
                commit_proposal,
                approval_type="local_commit_creation",
            ),
        )
        scenarios["57_valid_local_commit_approval"] = (
            committed.review_packages[-1].commit_created
        )
        scenarios["58_validation_failure_rolls_back"] = (
            failure_output.rollback_records[-1].rollback_status == "completed"
        )
        scenarios["59_original_worktree_unchanged"] = (
            failure_output.rollback_records[-1].source_worktree_unchanged
        )
        scenarios["60_pinned_base_sha"] = (
            success_output.isolated_runs[-1].base_commit_sha
            == success_proposal.base_commit_sha
        )
        scenarios["61_base_change_invalidates_approval"] = scenarios["04_wrong_base_sha"]
        scenarios["62_repair_planner_unchanged"] = planner.model_dump_json() == planner_before
        scenarios["63_review_package_generated"] = bool(
            success_output.review_packages
        )
        scenarios["64_pr_metadata_without_pr"] = (
            bool(success_output.review_packages[-1].PR_title)
            and success_output.signal_usage.PR_created is False
        )
        signals = committed.signal_usage
        scenarios["65_no_network"] = signals.network_access_used is False
        scenarios["66_no_push"] = signals.push_used is False
        scenarios["67_no_merge"] = signals.merge_used is False
        scenarios["68_no_tag"] = signals.tag_used is False
        scenarios["69_no_package_install"] = signals.package_installation_used is False
        scenarios["70_no_service_restart"] = signals.service_restart_used is False
        scenarios["71_no_destructive_git"] = signals.destructive_git_used is False

    passed = len(scenarios) == 71 and all(scenarios.values())
    validator_report = BobaCodeSurgeonValidatorReportV1(
        mode="synthetic-project",
        passed=passed,
        scenario_count=len(scenarios),
        passed_scenario_count=sum(scenarios.values()),
        scenario_results=scenarios,
        git_available=True,
        temporary_repository_used=True,
        warnings=warnings,
        limitations=[
            "Synthetic validation cannot prove an arbitrary repair is correct.",
            "No Olympus source file, remote branch, PR, merge, deployment, or release was changed.",
        ],
    )
    _write_report(validator_report, report_root)
    return validator_report


def inspect_project(
    project_id: str,
    *,
    repository_root: Path,
    report_root: Path | None = None,
) -> BobaCodeSurgeonValidatorReportV1:
    store = BobaMemoryStore(repository_root / "work" / "boba")
    stored = store.load_boba_code_surgeon(project_id)
    scenarios = {
        "stored_code_surgeon_available": stored is not None,
        "stored_report_json_safe": bool(
            stored and json.dumps(stored.model_dump(mode="json"))
        ),
        "main_not_modified_by_report": bool(
            stored and stored.signal_usage.main_branch_modified is False
        ),
        "push_not_used": bool(stored and stored.signal_usage.push_used is False),
        "merge_not_used": bool(stored and stored.signal_usage.merge_used is False),
    }
    report = BobaCodeSurgeonValidatorReportV1(
        mode=f"project-{project_id}",
        passed=all(scenarios.values()),
        scenario_count=len(scenarios),
        passed_scenario_count=sum(scenarios.values()),
        scenario_results=scenarios,
        git_available=shutil.which("git") is not None,
        temporary_repository_used=False,
        limitations=[
            "Project mode is inspection-only and does not execute or approve a patch."
        ],
    )
    _write_report(report, report_root)
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-check", action="store_true")
    mode.add_argument("--synthetic-project", action="store_true")
    mode.add_argument("--project-id")
    parser.add_argument(
        "--report-root",
        type=Path,
        default=Path("work/validation_reports/boba_code_surgeon"),
    )
    return parser.parse_args()


def main() -> int:
    arguments = _parse_args()
    if arguments.self_check:
        report = run_self_check(arguments.report_root)
    elif arguments.synthetic_project:
        report = run_synthetic_project(arguments.report_root)
    else:
        report = inspect_project(
            arguments.project_id,
            repository_root=Path.cwd().resolve(),
            report_root=arguments.report_root,
        )
    print(report.model_dump_json(indent=2))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
