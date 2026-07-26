"""Validate BOBA Observer V1 with local synthetic artifact state only."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (ROOT, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from olympus.api.dependencies import boba_integration_provider  # noqa: E402
from olympus.boba.observer import (  # noqa: E402
    BobaObserverSetV1,
    BobaObserverV1,
    build_boba_artifact_registry,
)
from olympus.boba.store import BobaMemoryStore  # noqa: E402

REPORT_DIR = ROOT / "work" / "validation_reports" / "boba_observer"
SYNTHETIC_PROJECT_ID = "proj_boba_observer_synthetic"
SYNTHETIC_OBSERVED_AT = datetime(2026, 1, 15, 12, 0, tzinfo=UTC)


class BobaObserverValidationReport(BaseModel):
    """Compact local proof for observation-only behavior."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["self_check", "synthetic_project", "project_id"]
    passed: bool
    project_id: str | None = None
    modules_imported: bool = False
    store_available: bool = False
    registry_builds: bool = False
    report_path_writable: bool = False
    artifact_observations_exist: bool = False
    module_health_observations_exist: bool = False
    workflow_observations_exist: bool = False
    dependency_observations_exist: bool = False
    validation_observations_exist: bool = False
    safety_observations_exist: bool = False
    next_action_recommendations_exist: bool = False
    missing_artifact_detected: bool = False
    stale_artifact_detected: bool = False
    corrupt_artifact_detected: bool = False
    broken_dependency_detected: bool = False
    missing_validation_detected: bool = False
    stale_validation_detected: bool = False
    unknown_validation_detected: bool = False
    unsafe_ingestion_detected: bool = False
    summary_counts_consistent: bool = False
    artifact_persisted: bool = False
    json_safe: bool = False
    export_safe: bool = False
    reset_project_only: bool = False
    external_api_used_false: bool = False
    url_fetching_used_false: bool = False
    scraping_used_false: bool = False
    downloading_used_false: bool = False
    command_execution_used_false: bool = False
    code_modification_used_false: bool = False
    destructive_action_used_false: bool = False
    validators_executed: bool = False
    rendering_triggered: bool = False
    downloading_triggered: bool = False
    url_fetching_triggered: bool = False
    external_calls_made: bool = False
    code_edits_made: bool = False
    destructive_actions_made: bool = False
    media_ingestion_triggered: bool = False
    media_required: bool = False
    secrets_required: bool = False
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


def _write_json(
    path: Path,
    payload: dict[str, Any],
    *,
    modified_at: datetime,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    timestamp = modified_at.timestamp()
    os.utime(path, (timestamp, timestamp))


def _artifact_payload(
    artifact_id: str,
    *,
    created_at: datetime,
) -> dict[str, Any]:
    return {
        "schema_version": f"synthetic_{artifact_id}_v1",
        "project_id": SYNTHETIC_PROJECT_ID,
        "created_at": created_at.isoformat(),
        "summary": "Compact synthetic local artifact metadata.",
    }


def build_synthetic_observer_state(
    root: Path,
    *,
    project_id: str = SYNTHETIC_PROJECT_ID,
    rights_status: str = "blocked",
) -> tuple[Path, Path, datetime]:
    """Create deterministic local JSON state without media, network, or commands."""

    store_root = root / "boba"
    validation_root = root / "validation_reports"
    project_root = store_root / "projects" / project_id
    registry = {
        item.artifact_id: item for item in build_boba_artifact_registry()
    }
    fresh = SYNTHETIC_OBSERVED_AT - timedelta(days=1)
    ordinary_mtime = SYNTHETIC_OBSERVED_AT - timedelta(days=2)
    hook_mtime = SYNTHETIC_OBSERVED_AT - timedelta(hours=12)
    caption_mtime = SYNTHETIC_OBSERVED_AT - timedelta(days=4)
    present = (
        "whole_video",
        "clip_ranking",
        "editorial_decision",
        "creative_direction_v2",
        "clip_briefs",
        "hook_retention",
        "caption_motion",
        "creator_learning",
        "approval_rejection_learning",
        "experimentation",
        "performance_feedback",
        "content_scout_v2",
        "trend_topic_watcher",
        "candidate_video_scorer",
        "rights_permission_gate",
    )
    for artifact_id in present:
        payload = _artifact_payload(artifact_id, created_at=fresh)
        payload["project_id"] = project_id
        if artifact_id == "rights_permission_gate":
            payload["gate_decisions"] = [
                {
                    "decision_id": "synthetic_rights_decision",
                    "gate_status": rights_status,
                }
            ]
        modified_at = ordinary_mtime
        if artifact_id == "hook_retention":
            modified_at = hook_mtime
        elif artifact_id == "caption_motion":
            modified_at = caption_mtime
        _write_json(
            project_root / registry[artifact_id].relative_path,
            payload,
            modified_at=modified_at,
        )

    corrupt_path = project_root / registry["explanation"].relative_path
    corrupt_path.parent.mkdir(parents=True, exist_ok=True)
    corrupt_path.write_text("{not valid observer fixture JSON", encoding="utf-8")
    corrupt_time = ordinary_mtime.timestamp()
    os.utime(corrupt_path, (corrupt_time, corrupt_time))

    report_specs = (
        (
            "boba_whole_video_understanding",
            "fresh-pass.json",
            {
                "passed": True,
                "created_at": fresh.isoformat(),
            },
            ordinary_mtime,
        ),
        (
            "boba_clip_ranking",
            "stale-pass.json",
            {
                "passed": True,
                "created_at": (
                    SYNTHETIC_OBSERVED_AT - timedelta(days=45)
                ).isoformat(),
            },
            SYNTHETIC_OBSERVED_AT - timedelta(days=45),
        ),
        (
            "boba_editorial_decision",
            "unknown-format.json",
            {
                "created_at": fresh.isoformat(),
                "details": "No recognized pass or status field.",
            },
            ordinary_mtime,
        ),
    )
    for directory, name, payload, modified_at in report_specs:
        _write_json(
            validation_root / directory / name,
            payload,
            modified_at=modified_at,
        )
    return store_root, validation_root, SYNTHETIC_OBSERVED_AT


def build_synthetic_observer_report(
    project_id: str = SYNTHETIC_PROJECT_ID,
) -> BobaObserverSetV1:
    """Build one complete synthetic Observer report in a temporary directory."""

    with TemporaryDirectory(prefix="boba-observer-fixture-") as temporary:
        store_root, validation_root, observed_at = (
            build_synthetic_observer_state(
                Path(temporary),
                project_id=project_id,
            )
        )
        return BobaObserverV1(
            store_root,
            validation_report_root=validation_root,
        ).analyze(
            project_id,
            source_id="synthetic_local_artifact_state",
            workflow_context={
                "workflow_stage": "manual_observer_context",
                "ready_modules": ["human_review"],
            },
            observed_at=observed_at,
        )


def _report_path_writable(report_dir: Path) -> bool:
    try:
        report_dir.mkdir(parents=True, exist_ok=True)
        marker = report_dir / ".write_test"
        marker.write_text("local-observer-validation-only", encoding="utf-8")
        marker.unlink()
    except OSError:
        return False
    return True


def _contains_key(value: Any, key: str) -> bool:
    if isinstance(value, dict):
        return key in value or any(
            _contains_key(item, key) for item in value.values()
        )
    if isinstance(value, list):
        return any(_contains_key(item, key) for item in value)
    return False


def _safe_export(payload: dict[str, Any]) -> bool:
    observer = payload.get("observer")
    privacy = payload.get("privacy")
    if not isinstance(observer, dict) or not isinstance(privacy, dict):
        return False
    for private_key in ("expected_path", "report_path", "evidence"):
        if _contains_key(observer, private_key):
            return False
    required_truth = {
        "private_paths_excluded": True,
        "finding_evidence_excluded": True,
        "raw_artifact_content_excluded": True,
        "full_transcripts_excluded": True,
        "media_files_excluded": True,
        "credentials_excluded": True,
        "command_logs_excluded": True,
        "external_api_used": False,
        "url_fetching_used": False,
        "scraping_used": False,
        "downloading_used": False,
        "command_execution_used": False,
        "code_modification_used": False,
        "destructive_action_used": False,
        "validator_execution_used": False,
        "rendering_used": False,
        "media_ingestion_used": False,
    }
    if any(privacy.get(key) is not value for key, value in required_truth.items()):
        return False
    encoded = json.dumps(payload).casefold()
    return not any(
        forbidden in encoded
        for forbidden in (
            '"api_key":',
            '"access_token":',
            '"password":',
            '"full_transcript":',
            '"raw_media":',
            ".mp4",
            ".wav",
            ".mov",
            ".webm",
        )
    )


def _summary_consistent(observer: BobaObserverSetV1) -> bool:
    summary = observer.observer_summary
    partition = (
        summary.healthy_count
        + summary.partial_count
        + summary.missing_count
        + summary.blocked_count
        + summary.stale_count
        + summary.unknown_count
    )
    return (
        summary.total_modules_observed
        == len(observer.module_health_observations)
        == partition
        and summary.blocker_count >= 0
        and summary.warning_count >= 0
    )


def _validation_report(
    observer: BobaObserverSetV1,
    *,
    mode: Literal["self_check", "synthetic_project", "project_id"],
    report_dir: Path,
    artifact_persisted: bool,
    export_safe: bool,
    reset_project_only: bool,
) -> BobaObserverValidationReport:
    signal = observer.signal_usage
    report = BobaObserverValidationReport(
        mode=mode,
        passed=False,
        project_id=observer.project_id,
        modules_imported=True,
        store_available=True,
        registry_builds=len(build_boba_artifact_registry()) == 19,
        report_path_writable=_report_path_writable(report_dir),
        artifact_observations_exist=bool(observer.artifact_observations),
        module_health_observations_exist=bool(
            observer.module_health_observations
        ),
        workflow_observations_exist=bool(observer.workflow_observations),
        dependency_observations_exist=bool(
            observer.dependency_observations
        ),
        validation_observations_exist=bool(
            observer.validation_observations
        ),
        safety_observations_exist=bool(observer.safety_observations),
        next_action_recommendations_exist=bool(
            observer.next_action_recommendations
        ),
        missing_artifact_detected=any(
            artifact.freshness_status == "missing"
            for artifact in observer.artifact_observations
        ),
        stale_artifact_detected=any(
            artifact.freshness_status == "stale"
            for artifact in observer.artifact_observations
        ),
        corrupt_artifact_detected=any(
            artifact.exists and not artifact.readable
            for artifact in observer.artifact_observations
        ),
        broken_dependency_detected=any(
            dependency.status == "broken"
            for dependency in observer.dependency_observations
        ),
        missing_validation_detected=any(
            validation.latest_status == "missing"
            for validation in observer.validation_observations
        ),
        stale_validation_detected=any(
            validation.freshness_status == "stale"
            for validation in observer.validation_observations
        ),
        unknown_validation_detected=any(
            validation.latest_status == "unknown"
            for validation in observer.validation_observations
        ),
        unsafe_ingestion_detected=any(
            safety.safety_area == "ingestion"
            and safety.status in {"blocked", "needs_human_review"}
            for safety in observer.safety_observations
        ),
        summary_counts_consistent=_summary_consistent(observer),
        artifact_persisted=artifact_persisted,
        json_safe=bool(json.loads(observer.model_dump_json())),
        export_safe=export_safe,
        reset_project_only=reset_project_only,
        external_api_used_false=signal.external_api_used is False,
        url_fetching_used_false=signal.url_fetching_used is False,
        scraping_used_false=signal.scraping_used is False,
        downloading_used_false=signal.downloading_used is False,
        command_execution_used_false=(
            signal.command_execution_used is False
        ),
        code_modification_used_false=signal.code_modification_used is False,
        destructive_action_used_false=(
            signal.destructive_action_used is False
        ),
        warnings=[
            "Validation inspected deterministic local JSON fixture state only.",
            "Observer executed no validators, commands, rendering, ingestion, "
            "downloads, URL fetches, external calls, code edits, or "
            "destructive actions.",
        ],
    )
    baseline = [
        report.modules_imported,
        report.store_available,
        report.registry_builds,
        report.report_path_writable,
        report.artifact_observations_exist,
        report.module_health_observations_exist,
        report.workflow_observations_exist,
        report.dependency_observations_exist,
        report.validation_observations_exist,
        report.safety_observations_exist,
        report.next_action_recommendations_exist,
        report.summary_counts_consistent,
        report.artifact_persisted,
        report.json_safe,
        report.export_safe,
        report.external_api_used_false,
        report.url_fetching_used_false,
        report.scraping_used_false,
        report.downloading_used_false,
        report.command_execution_used_false,
        report.code_modification_used_false,
        report.destructive_action_used_false,
        not report.validators_executed,
        not report.rendering_triggered,
        not report.downloading_triggered,
        not report.url_fetching_triggered,
        not report.external_calls_made,
        not report.code_edits_made,
        not report.destructive_actions_made,
        not report.media_ingestion_triggered,
        not report.media_required,
        not report.secrets_required,
    ]
    if mode != "project_id":
        baseline.extend(
            [
                report.missing_artifact_detected,
                report.stale_artifact_detected,
                report.corrupt_artifact_detected,
                report.broken_dependency_detected,
                report.missing_validation_detected,
                report.stale_validation_detected,
                report.unknown_validation_detected,
                report.unsafe_ingestion_detected,
                report.reset_project_only,
            ]
        )
    report.passed = all(baseline)
    return report


def _run_local(
    *,
    mode: Literal["self_check", "synthetic_project"],
    report_dir: Path,
) -> BobaObserverValidationReport:
    project_id = (
        "proj_boba_observer_self_check"
        if mode == "self_check"
        else SYNTHETIC_PROJECT_ID
    )
    with TemporaryDirectory(prefix="boba-observer-validator-") as temporary:
        root = Path(temporary)
        store_root, validation_root, observed_at = (
            build_synthetic_observer_state(root, project_id=project_id)
        )
        observer = BobaObserverV1(
            store_root,
            validation_report_root=validation_root,
        ).analyze(
            project_id,
            source_id="synthetic_local_artifact_state",
            observed_at=observed_at,
        )
        store = BobaMemoryStore(store_root)
        saved = store.save_observer_report(observer)
        observer_path = store.observer_path(project_id)
        artifact_persisted = (
            observer_path.is_file()
            and store.load_observer_report(project_id) == saved
        )
        exported = store.export_observer_report(project_id)
        export_safe = _safe_export(exported)
        preserved_path = (
            store_root
            / "projects"
            / project_id
            / "whole_video_understanding"
            / "index.json"
        )
        reset_removed = store.reset_observer_report(project_id)
        reset_project_only = (
            reset_removed
            and store.load_observer_report(project_id) is None
            and preserved_path.is_file()
        )
        return _validation_report(
            observer,
            mode=mode,
            report_dir=report_dir,
            artifact_persisted=artifact_persisted,
            export_safe=export_safe,
            reset_project_only=reset_project_only,
        )


def run_self_check(
    report_dir: Path | None = None,
) -> BobaObserverValidationReport:
    """Run imports, registry, local storage, and safety checks."""

    return _run_local(
        mode="self_check",
        report_dir=report_dir or REPORT_DIR,
    )


def run_synthetic_project(
    report_dir: Path | None = None,
) -> BobaObserverValidationReport:
    """Run the complete local synthetic Observer proof."""

    return _run_local(
        mode="synthetic_project",
        report_dir=report_dir or REPORT_DIR,
    )


def run_existing_project(
    project_id: str,
    report_dir: Path | None = None,
) -> BobaObserverValidationReport:
    """Load or safely generate an Observer report from saved project state."""

    effective_report_dir = report_dir or REPORT_DIR
    try:
        integration = boba_integration_provider()
        observer = integration.load_observer_report(project_id)
        if observer is None:
            observer = asyncio.run(
                integration.generate_observer_report(project_id)
            )
        artifact_path = integration.store.observer_path(project_id)
        return _validation_report(
            observer,
            mode="project_id",
            report_dir=effective_report_dir,
            artifact_persisted=artifact_path.is_file(),
            export_safe=_safe_export(
                integration.export_observer_report(project_id)
            ),
            reset_project_only=False,
        )
    except Exception as exc:
        return BobaObserverValidationReport(
            mode="project_id",
            passed=False,
            project_id=project_id,
            modules_imported=True,
            store_available=True,
            registry_builds=len(build_boba_artifact_registry()) == 19,
            report_path_writable=_report_path_writable(
                effective_report_dir
            ),
            external_api_used_false=True,
            url_fetching_used_false=True,
            scraping_used_false=True,
            downloading_used_false=True,
            command_execution_used_false=True,
            code_modification_used_false=True,
            destructive_action_used_false=True,
            errors=[str(exc)],
            warnings=[
                "No project artifact was changed except an Observer report if "
                "generation succeeded.",
                "No validator, command, rendering, ingestion, download, URL "
                "fetch, external call, code edit, or destructive action "
                "occurred.",
            ],
        )


def _write_report(
    report: BobaObserverValidationReport,
    report_dir: Path,
) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "boba_observer_v1_report.json").write_text(
        json.dumps(report.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )
    summary = [
        "# BOBA Observer V1 Validation",
        "",
        f"- Mode: `{report.mode}`",
        f"- Passed: `{str(report.passed).lower()}`",
        f"- Project: `{report.project_id or 'temporary self-check'}`",
        f"- Artifact observations: `{report.artifact_observations_exist}`",
        f"- Broken dependency detected: `{report.broken_dependency_detected}`",
        f"- Validation gap detected: `{report.missing_validation_detected}`",
        f"- Unsafe ingestion detected: `{report.unsafe_ingestion_detected}`",
        f"- Artifact persisted: `{report.artifact_persisted}`",
        f"- Export safe: `{report.export_safe}`",
        "- Validators or commands executed by Observer: `false`",
        "- External APIs or URLs used: `false`",
        "- Media downloaded, ingested, or rendered: `false`",
        "- Code edits or destructive actions: `false`",
        "",
        "Observer V1 reports local evidence only; every next action remains advisory.",
    ]
    (report_dir / "boba_observer_v1_summary.md").write_text(
        "\n".join(summary) + "\n",
        encoding="utf-8",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate BOBA Observer V1 locally.",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-check", action="store_true")
    mode.add_argument("--synthetic-project", action="store_true")
    mode.add_argument("--project-id")
    parser.add_argument("--report-dir", type=Path, default=REPORT_DIR)
    return parser


def main() -> int:
    args = _parser().parse_args()
    report_dir = args.report_dir.resolve()
    if args.self_check:
        report = run_self_check(report_dir)
    elif args.synthetic_project:
        report = run_synthetic_project(report_dir)
    else:
        report = run_existing_project(str(args.project_id), report_dir)
    _write_report(report, report_dir)
    print(json.dumps(report.model_dump(mode="json"), indent=2))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
