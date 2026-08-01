"""Isolated fixed-command execution for the BOBA Validator Runner V1."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path
from typing import Any

from olympus.boba.code_surgeon import (
    BobaCodeValidationCommandV1,
    validate_command_safety,
)
from olympus.boba.validator_runner import (
    _DEFAULT_CAPTURE_BYTES,
    _FRONTEND_SCRIPTS,
    _OWNED_PROCESS_LOCK,
    _OWNED_PROCESSES,
    _SHELL_TOKEN,
    _URL,
    BobaValidationCheckStatusV1,
    BobaValidationInputBindingV1,
    BobaValidationPlanCheckV1,
    BobaValidationResourceBudgetV1,
    _AdapterOutcome,
    _bounded_file_tail,
    _protected_tree_digest,
    _sanitized_process_environment,
)
from olympus.boba.validator_runner_runtime import (
    BobaValidatorRunnerV1 as _MediaValidatorRunnerV1,
)
from olympus.platform.errors import ValidationError


class BobaValidatorRunnerV1(_MediaValidatorRunnerV1):
    """Validator Runner with bounded, cancellable, isolated code checks."""

    def _execute_code_adapter(
        self,
        check: BobaValidationPlanCheckV1,
        bindings: Sequence[BobaValidationInputBindingV1],
        workspace: Path,
        budget: BobaValidationResourceBudgetV1,
        process_key: str,
    ) -> _AdapterOutcome:
        code_root = self._code_workspace(bindings)
        command, working_directory, category = self._fixed_code_command(
            check.validator_id,
            code_root,
        )
        command_contract = BobaCodeValidationCommandV1(
            validation_command_id=f"validator_runner:{check.validator_id}",
            name=check.validator_id,
            executable=command[0],
            arguments=command[1:],
            working_directory_scope=(
                working_directory.relative_to(code_root).as_posix()
                if working_directory != code_root
                else "."
            ),
            category=category,
            required=check.required,
            approved=True,
            timeout_seconds=min(
                check.timeout_seconds,
                budget.maximum_single_check_duration_seconds,
            ),
            network_forbidden=True,
            shell_used=False,
            expected_exit_codes=[0],
            output_limit_bytes=min(
                budget.maximum_capture_bytes_per_stream,
                _DEFAULT_CAPTURE_BYTES,
            ),
        )
        safe, reason = validate_command_safety(command_contract)
        if not safe:
            raise ValidationError(
                "The fixed code command failed Code Surgeon safety review.",
                details={"reason": reason},
            )
        before_digest = _protected_tree_digest(code_root)
        process = self._run_owned_process(
            process_key=process_key,
            command=command,
            working_directory=working_directory,
            temp_root=workspace,
            timeout_seconds=command_contract.timeout_seconds,
            capture_bytes=command_contract.output_limit_bytes,
        )
        after_digest = _protected_tree_digest(code_root)
        protected_unchanged = before_digest == after_digest
        status: BobaValidationCheckStatusV1
        if process["cancelled"]:
            status = "cancelled"
        elif process["timed_out"]:
            status = "timed_out"
        elif process["exit_code"] == 0 and protected_unchanged:
            status = "passed"
        elif not protected_unchanged:
            status = "errored"
        else:
            status = "failed"
        failed = []
        if process["exit_code"] != 0:
            failed.append("exit_code_zero")
        if not protected_unchanged:
            failed.append("protected_source_unchanged")
        return _AdapterOutcome(
            status=status,
            summary=(
                f"Fixed isolated check {check.validator_id} passed."
                if status == "passed"
                else f"Fixed isolated check {check.validator_id} did not pass."
            ),
            assertion_results={
                "exit_code_zero": process["exit_code"] == 0,
                "protected_source_unchanged": protected_unchanged,
                "shell_unused": True,
                "network_not_requested": True,
            },
            measured_values={
                "exit_code": process["exit_code"],
                "timed_out": process["timed_out"],
                "cancelled": process["cancelled"],
                "duration_seconds": process["duration_seconds"],
                "protected_digest_before": before_digest,
                "protected_digest_after": after_digest,
            },
            expected_values={
                "exit_code": 0,
                "protected_source_unchanged": True,
            },
            failed_assertions=failed,
            unavailable_assertions=[],
            source_type=(
                "frontend_runner"
                if check.validator_id in _FRONTEND_SCRIPTS
                else "test_runner"
                if "pytest" in check.validator_id
                else "code_static_check"
            ),
            confidence=1.0,
            stdout=str(process["stdout"]),
            stderr=str(process["stderr"]),
            output_truncated=bool(process["output_truncated"]),
            exit_code=(
                int(process["exit_code"])
                if process["exit_code"] is not None
                else None
            ),
            owned_child_terminated=bool(process["owned_child_terminated"]),
            limitations=[
                (
                    "V1 uses a sanitized environment and proxy denial but does "
                    "not claim an operating-system network sandbox."
                )
            ],
        )

    def _fixed_code_command(
        self,
        validator_id: str,
        code_root: Path,
    ) -> tuple[list[str], Path, str]:
        python_commands: dict[str, tuple[list[str], str]] = {
            "python.ruff": (
                [sys.executable, "-m", "ruff", "check", "src", "tests", "tools"],
                "lint",
            ),
            "python.mypy": (
                [sys.executable, "-m", "mypy", "src"],
                "typecheck",
            ),
            "python.pytest_focused": (
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "tests/unit/test_boba_validator_runner.py",
                ],
                "unit_test",
            ),
            "python.pytest_regression": (
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "tests/unit/test_boba_core.py",
                    "tests/unit/test_boba_memory.py",
                    "tests/unit/test_boba_integration_layer.py",
                    "tests/unit/test_boba_safety_gate.py",
                    "tests/unit/test_boba_autopilot_controller.py",
                    "tests/unit/test_boba_workflow_controller.py",
                    "tests/unit/test_boba_validator_runner.py",
                ],
                "regression",
            ),
        }
        if validator_id in python_commands:
            command, category = python_commands[validator_id]
            return command, code_root, category
        if validator_id in _FRONTEND_SCRIPTS:
            npm = shutil.which("npm")
            if npm is None:
                raise ValidationError("The fixed npm executable is unavailable.")
            frontend = (code_root / "frontend").resolve()
            if not frontend.is_dir() or code_root not in frontend.parents:
                raise ValidationError(
                    "The isolated frontend workspace is unavailable."
                )
            script = _FRONTEND_SCRIPTS[validator_id]
            category = "build" if script == "build" else "frontend"
            return [npm, "run", script], frontend, category
        raise ValidationError("No fixed code command exists for this validator.")

    def _run_owned_process(
        self,
        *,
        process_key: str,
        command: Sequence[str],
        working_directory: Path,
        temp_root: Path,
        timeout_seconds: int,
        capture_bytes: int,
    ) -> dict[str, Any]:
        if not command or _SHELL_TOKEN.search(" ".join(command)):
            raise ValidationError("Unsafe process command shape was rejected.")
        if any(_URL.match(argument.strip()) for argument in command):
            raise ValidationError("Network and URL process arguments are blocked.")
        temp_root.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        timed_out = False
        cancelled = False
        terminated = False
        exit_code: int | None = None
        creation_flags = (
            int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if os.name == "nt"
            else 0
        )
        with (
            tempfile.TemporaryFile(
                prefix="boba-validator-stdout-",
                dir=temp_root,
            ) as stdout,
            tempfile.TemporaryFile(
                prefix="boba-validator-stderr-",
                dir=temp_root,
            ) as stderr,
        ):
            try:
                process = subprocess.Popen(
                    list(command),
                    stdin=subprocess.DEVNULL,
                    stdout=stdout,
                    stderr=stderr,
                    shell=False,
                    cwd=working_directory,
                    env=_sanitized_process_environment(temp_root),
                    creationflags=creation_flags,
                )
            except OSError as exc:
                stderr.write(str(exc).encode("utf-8", "replace"))
                process = None
            if process is not None:
                with _OWNED_PROCESS_LOCK:
                    if process_key in _OWNED_PROCESSES:
                        with suppress(OSError):
                            process.terminate()
                        raise ValidationError(
                            "A duplicate runner-owned process key was rejected."
                        )
                    _OWNED_PROCESSES[process_key] = process
                try:
                    while process.poll() is None:
                        if time.monotonic() - started >= timeout_seconds:
                            timed_out = True
                            break
                        project_id, validation_run_id, _check_run_id = (
                            process_key.split(":", 2)
                        )
                        current = self.store.load_boba_validator_runner(project_id)
                        active_run = (
                            next(
                                (
                                    item
                                    for item in current.validation_runs
                                    if item.validation_run_id == validation_run_id
                                ),
                                None,
                            )
                            if current
                            else None
                        )
                        if active_run and active_run.cancellation_requested:
                            cancelled = True
                            break
                        time.sleep(0.05)
                    if (timed_out or cancelled) and process.poll() is None:
                        with suppress(OSError):
                            process.terminate()
                            terminated = True
                        try:
                            process.wait(timeout=2.0)
                        except subprocess.TimeoutExpired:
                            with suppress(OSError):
                                process.kill()
                                terminated = True
                            with suppress(subprocess.TimeoutExpired):
                                process.wait(timeout=2.0)
                    exit_code = process.poll()
                finally:
                    with _OWNED_PROCESS_LOCK:
                        _OWNED_PROCESSES.pop(process_key, None)
            stdout_text, stdout_truncated = _bounded_file_tail(
                stdout,
                capture_bytes,
            )
            stderr_text, stderr_truncated = _bounded_file_tail(
                stderr,
                capture_bytes,
            )
        return {
            "exit_code": exit_code,
            "timed_out": timed_out,
            "cancelled": cancelled,
            "duration_seconds": round(
                max(0.0, time.monotonic() - started),
                3,
            ),
            "stdout": stdout_text,
            "stderr": stderr_text,
            "output_truncated": stdout_truncated or stderr_truncated,
            "owned_child_terminated": terminated,
        }


__all__ = ["BobaValidatorRunnerV1"]
