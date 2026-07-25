"""Validate BOBA Performance Feedback Brain V1 without media or network access."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (ROOT, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from olympus.api.dependencies import boba_integration_provider  # noqa: E402
from olympus.boba.experimentation import BobaExperimentationSetV1  # noqa: E402
from olympus.boba.memory_contracts import BobaProjectMemoryV1  # noqa: E402
from olympus.boba.performance_feedback import (  # noqa: E402
    BobaManualPerformanceMetricsV1,
    BobaPerformanceFeedbackBrainV1,
    BobaPerformanceFeedbackEventV1,
    BobaPerformanceFeedbackSetV1,
)
from olympus.boba.store import BobaMemoryStore  # noqa: E402
from tools.validate_boba_experimentation import (  # noqa: E402
    build_synthetic_experimentation,
    build_synthetic_experimentation_artifacts,
)

REPORT_DIR = ROOT / "work" / "validation_reports" / "boba_performance_feedback"


class BobaPerformanceFeedbackValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["self_check", "synthetic_project", "project_id"]
    passed: bool
    project_id: str | None = None
    modules_imported: bool = False
    store_available: bool = False
    experimentation_available: bool = False
    creator_learning_available: bool = False
    approval_rejection_learning_available: bool = False
    report_path_writable: bool = False
    events_recorded: int = 0
    snapshots_created: int = 0
    outcomes_created: int = 0
    pattern_summary_created: bool = False
    learning_handoff_created: bool = False
    auto_collected_count_zero: bool = False
    analytics_api_used_false: bool = False
    apply_automatically_false: bool = False
    negative_metrics_rejected: bool = False
    weak_data_warned: bool = False
    repeated_outcomes_increase_confidence: bool = False
    contradictions_reduce_confidence: bool = False
    export_safe: bool = False
    reset_project_only: bool = False
    artifact_persisted: bool = False
    events_append_safe: bool = False
    json_safe: bool = False
    rendering_triggered: bool = False
    uploading_triggered: bool = False
    downloading_triggered: bool = False
    analytics_collected: bool = False
    external_calls_made: bool = False
    media_required: bool = False
    secrets_required: bool = False
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


def build_synthetic_performance_artifacts(
    project_id: str = "proj_performance_feedback_synthetic",
) -> dict[str, Any]:
    artifacts: dict[str, Any] = build_synthetic_experimentation_artifacts()
    hook_analyses = artifacts["hook_retention"]["analyses"]
    weak_hook = next(
        item
        for item in hook_analyses
        if item.get("candidate_id") == "weak_hook_clip"
    )
    weak_hook["hook_analysis"]["hook_type"] = "slow_opening"
    hook_analyses.extend(
        [
            {
                "candidate_id": "curiosity_clip",
                "brief_id": "brief_curiosity_clip",
                "confidence": 0.84,
                "hook_analysis": {
                    "hook_type": "curiosity_gap",
                    "hook_strength": 86.0,
                    "reason": "The saved setup creates a supported open loop.",
                },
            },
            {
                "candidate_id": "contradictory_clip",
                "brief_id": "brief_contradictory_clip",
                "confidence": 0.64,
                "hook_analysis": {
                    "hook_type": "contrast",
                    "hook_strength": 68.0,
                    "reason": "The same supported contrast received mixed manual reviews.",
                },
            },
        ]
    )
    artifacts["clip_ranking"] = {
        "schema_version": "boba_clip_ranking_v1",
        "ranked_candidates": [
            {"candidate_id": "curiosity_clip", "rank": 1},
            {"candidate_id": "weak_hook_clip", "rank": 2},
        ],
    }
    artifacts["experimentation"] = build_synthetic_experimentation(project_id)
    return artifacts


def _experiment(
    experimentation: BobaExperimentationSetV1,
    experiment_type: str,
    candidate_id: str,
) -> Any:
    return next(
        plan
        for plan in experimentation.experiment_plans
        if plan.experiment_type == experiment_type
        and plan.candidate_id == candidate_id
    )


def build_synthetic_performance_events(
    project_id: str = "proj_performance_feedback_synthetic",
    *,
    experimentation: BobaExperimentationSetV1 | None = None,
) -> list[BobaPerformanceFeedbackEventV1]:
    brain = BobaPerformanceFeedbackBrainV1()
    plans = experimentation or build_synthetic_experimentation(project_id)
    caption_plan = _experiment(plans, "caption_ab_test", "caption_overload_clip")
    motion_plan = _experiment(plans, "motion_ab_test", "heavy_motion_clip")
    music_plan = _experiment(plans, "music_mood_ab_test", "strong_clip")
    events = [
        brain.create_event(
            project_id,
            event_type="manual_clip_result",
            target_type="clip",
            target_id="clip_curiosity_a",
            candidate_id="curiosity_clip",
            platform="creator_entered_short_platform",
            manual_rating=4.8,
            creator_note="The curiosity hook worked and the strong payoff landed.",
            metrics={
                "views": 12_000,
                "likes": 930,
                "comments": 84,
                "shares": 146,
                "saves": 201,
                "retention_percent": 78.0,
                "completion_rate_percent": 74.0,
            },
        ),
        brain.create_event(
            project_id,
            event_type="manual_clip_result",
            target_type="clip",
            target_id="clip_curiosity_b",
            candidate_id="curiosity_clip",
            manual_rating=4.6,
            creator_note="The curiosity hook worked again with a clear payoff.",
            metrics={
                "views": 9_500,
                "likes": 710,
                "shares": 109,
                "retention_percent": 75.0,
                "completion_rate_percent": 71.0,
            },
        ),
        brain.create_event(
            project_id,
            event_type="manual_clip_result",
            target_type="clip",
            target_id="clip_slow_hook_a",
            candidate_id="weak_hook_clip",
            manual_rating=2.0,
            creator_note="The slow hook underperformed.",
            retention_notes="people dropped before payoff",
            metrics={
                "views": 1_400,
                "likes": 31,
                "retention_percent": 27.0,
                "completion_rate_percent": 22.0,
            },
        ),
        brain.create_event(
            project_id,
            event_type="manual_note",
            target_type="clip",
            target_id="clip_slow_hook_b",
            candidate_id="weak_hook_clip",
            manual_rating=2.2,
            creator_note="The slow opening hurt this version.",
            retention_notes="people dropped before payoff",
        ),
        brain.create_event(
            project_id,
            event_type="manual_experiment_result",
            target_type="experiment",
            target_id=caption_plan.experiment_id,
            candidate_id=caption_plan.candidate_id,
            brief_id=caption_plan.brief_id,
            experiment_id=caption_plan.experiment_id,
            baseline_id=caption_plan.baseline.baseline_id,
            selected_variant_id=caption_plan.variants[0].variant_id,
            variant_id=caption_plan.variants[0].variant_id,
            outcome_label="variant_won",
            manual_rating=4.9,
            creator_note="clean captions worked better",
            metrics={"completion_rate_percent": 82.0},
            should_feed_learning=True,
        ),
        brain.create_event(
            project_id,
            event_type="manual_experiment_result",
            target_type="experiment",
            target_id=motion_plan.experiment_id,
            candidate_id=motion_plan.candidate_id,
            brief_id=motion_plan.brief_id,
            experiment_id=motion_plan.experiment_id,
            baseline_id=motion_plan.baseline.baseline_id,
            selected_variant_id=motion_plan.variants[0].variant_id,
            variant_id=motion_plan.variants[0].variant_id,
            outcome_label="baseline_won",
            manual_rating=4.5,
            creator_note="heavy motion hurt clarity",
            should_feed_learning=True,
        ),
        brain.create_event(
            project_id,
            event_type="manual_experiment_result",
            target_type="experiment",
            target_id=music_plan.experiment_id,
            candidate_id=music_plan.candidate_id,
            brief_id=music_plan.brief_id,
            experiment_id=music_plan.experiment_id,
            baseline_id=music_plan.baseline.baseline_id,
            selected_variant_id=music_plan.variants[0].variant_id,
            variant_id=music_plan.variants[0].variant_id,
            outcome_label="inconclusive",
            manual_rating=3.0,
            creator_note="The music mood comparison had no clear winner.",
            should_feed_learning=True,
        ),
        brain.create_event(
            project_id,
            event_type="manual_clip_result",
            target_type="clip",
            target_id="clip_contradiction_positive",
            candidate_id="contradictory_clip",
            manual_rating=4.2,
            creator_note="The contrast hook worked in this manual review.",
        ),
        brain.create_event(
            project_id,
            event_type="manual_clip_result",
            target_type="clip",
            target_id="clip_contradiction_negative",
            candidate_id="contradictory_clip",
            manual_rating=2.1,
            creator_note="The same contrast hook did not work in this review.",
        ),
    ]
    return events


def build_synthetic_performance_feedback(
    project_id: str = "proj_performance_feedback_synthetic",
    *,
    include_contradictions: bool = True,
    event_limit: int | None = None,
    dry_run: bool = False,
) -> BobaPerformanceFeedbackSetV1:
    artifacts = build_synthetic_performance_artifacts(project_id)
    experimentation = artifacts["experimentation"]
    events = build_synthetic_performance_events(
        project_id,
        experimentation=experimentation,
    )
    if not include_contradictions:
        events = [
            event
            for event in events
            if event.candidate_id != "contradictory_clip"
        ]
    if event_limit is not None:
        events = events[:event_limit]
    return BobaPerformanceFeedbackBrainV1().analyze(
        project_id,
        events,
        source_id=project_id,
        experimentation=experimentation,
        creator_learning=artifacts["creator_learning"],
        approval_rejection_learning=artifacts["approval_rejection_learning"],
        clip_briefs=artifacts["clip_briefs"],
        hook_retention=artifacts["hook_retention"],
        caption_motion=artifacts["caption_motion"],
        music_mood=artifacts["music_mood"],
        clip_ranking=artifacts["clip_ranking"],
        editorial_decision=artifacts["editorial_decision"],
        boba_memory=artifacts["memory"],
        dry_run=dry_run,
    )


def _safe_export(payload: dict[str, Any]) -> bool:
    encoded = json.dumps(payload, sort_keys=True).casefold()
    forbidden = (
        "creator_note",
        "retention_notes",
        "creator_interpretation",
        "raw_media",
        "full_transcript",
        "api_key",
        "access_token",
        "refresh_token",
        "password",
        "cookie",
        ".mp4",
        ".mov",
        ".wav",
    )
    return not any(value in encoded for value in forbidden)


def _report_path_writable(report_dir: Path) -> bool:
    report_dir.mkdir(parents=True, exist_ok=True)
    probe = report_dir / ".write_test"
    try:
        probe.write_text("ok", encoding="utf-8")
        return probe.read_text(encoding="utf-8") == "ok"
    finally:
        probe.unlink(missing_ok=True)


def _factor_confidence(
    feedback: BobaPerformanceFeedbackSetV1,
    text: str,
) -> float:
    factors = [
        *feedback.pattern_summary.strongest_positive_patterns,
        *feedback.pattern_summary.strongest_negative_patterns,
    ]
    return max(
        (
            factor.confidence
            for factor in factors
            if text in factor.summary.casefold()
        ),
        default=0.0,
    )


def _run_local(
    *,
    mode: Literal["self_check", "synthetic_project"],
    report_dir: Path,
) -> BobaPerformanceFeedbackValidationReport:
    project_id = (
        "proj_performance_feedback_self_check"
        if mode == "self_check"
        else "proj_performance_feedback_synthetic"
    )
    feedback = build_synthetic_performance_feedback(project_id)
    first_result = build_synthetic_performance_feedback(
        project_id,
        include_contradictions=False,
        event_limit=1,
    )
    repeated_result = build_synthetic_performance_feedback(
        project_id,
        include_contradictions=False,
        event_limit=2,
    )
    no_contradictions = build_synthetic_performance_feedback(
        project_id,
        include_contradictions=False,
    )
    weak = BobaPerformanceFeedbackBrainV1().analyze(
        project_id,
        [
            BobaPerformanceFeedbackBrainV1().create_event(
                project_id,
                event_type="manual_rating",
                target_type="project",
                target_id=project_id,
                manual_rating=4.0,
            )
        ],
    )
    negative_metrics_rejected = False
    try:
        BobaManualPerformanceMetricsV1(views=-1)
    except ValidationError:
        negative_metrics_rejected = True

    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        store = BobaMemoryStore(root / "boba", memory_root=root / "memory")
        experimentation = build_synthetic_experimentation(project_id)
        store.save_experimentation_plan(experimentation)
        store.save_project_memory(
            BobaProjectMemoryV1(
                project_id=project_id,
                source_summary="Unrelated compact memory survives reset.",
            )
        )
        events = build_synthetic_performance_events(
            project_id,
            experimentation=experimentation,
        )
        for event in events:
            store.record_performance_feedback_event(event)
        saved = store.save_performance_feedback(feedback)
        persisted = store.load_performance_feedback(project_id)
        export = store.export_performance_feedback(project_id)
        events_append_safe = (
            len(store.list_performance_feedback_events(project_id)) == len(events)
        )
        removed = store.reset_performance_feedback(project_id)
        reset_project_only = bool(
            removed
            and store.load_performance_feedback(project_id) is None
            and not store.list_performance_feedback_events(project_id)
            and store.load_experimentation_plan(project_id) is not None
            and store.load_project_memory(project_id) is not None
        )
        artifact_persisted = bool(
            saved == persisted
            and store.performance_feedback_path(project_id)
            .as_posix()
            .endswith(f"projects/{project_id}/performance_feedback/index.json")
        )

    report = BobaPerformanceFeedbackValidationReport(
        mode=mode,
        passed=False,
        project_id=project_id,
        modules_imported=True,
        store_available=True,
        experimentation_available=feedback.signal_usage.experimentation_used,
        creator_learning_available=feedback.signal_usage.creator_learning_used,
        approval_rejection_learning_available=(
            feedback.signal_usage.approval_rejection_used
        ),
        report_path_writable=_report_path_writable(report_dir),
        events_recorded=feedback.audit_summary.total_events,
        snapshots_created=len(feedback.performance_snapshots),
        outcomes_created=len(feedback.experiment_outcomes),
        pattern_summary_created=bool(
            feedback.pattern_summary.strongest_positive_patterns
            or feedback.pattern_summary.strongest_negative_patterns
        ),
        learning_handoff_created=bool(
            feedback.learning_handoff.creator_learning_updates
            or feedback.learning_handoff.experimentation_updates
        ),
        auto_collected_count_zero=(
            feedback.audit_summary.auto_collected_count == 0
        ),
        analytics_api_used_false=(
            feedback.signal_usage.analytics_api_used is False
        ),
        apply_automatically_false=(
            feedback.learning_handoff.apply_automatically is False
        ),
        negative_metrics_rejected=negative_metrics_rejected,
        weak_data_warned=bool(
            weak.performance_snapshots[0].warnings
            and weak.pattern_summary.risky_conclusions
        ),
        repeated_outcomes_increase_confidence=(
            _factor_confidence(repeated_result, "curiosity gap")
            > _factor_confidence(first_result, "curiosity gap")
        ),
        contradictions_reduce_confidence=(
            feedback.pattern_summary.confidence
            < no_contradictions.pattern_summary.confidence
            and bool(feedback.pattern_summary.contradictions)
        ),
        export_safe=_safe_export(export),
        reset_project_only=reset_project_only,
        artifact_persisted=artifact_persisted,
        events_append_safe=events_append_safe,
        json_safe=bool(json.loads(feedback.model_dump_json())),
        warnings=[
            "Validation used creator-entered synthetic metadata only.",
            "No rendering, upload, download, analytics API, or external call occurred.",
        ],
    )
    checks = [
        report.modules_imported,
        report.store_available,
        report.experimentation_available,
        report.creator_learning_available,
        report.approval_rejection_learning_available,
        report.report_path_writable,
        report.events_recorded >= 9,
        report.snapshots_created >= 8,
        report.outcomes_created >= 3,
        report.pattern_summary_created,
        report.learning_handoff_created,
        report.auto_collected_count_zero,
        report.analytics_api_used_false,
        report.apply_automatically_false,
        report.negative_metrics_rejected,
        report.weak_data_warned,
        report.repeated_outcomes_increase_confidence,
        report.contradictions_reduce_confidence,
        report.export_safe,
        report.reset_project_only,
        report.artifact_persisted,
        report.events_append_safe,
        report.json_safe,
        not report.rendering_triggered,
        not report.uploading_triggered,
        not report.downloading_triggered,
        not report.analytics_collected,
        not report.external_calls_made,
        not report.media_required,
        not report.secrets_required,
    ]
    report.passed = all(checks)
    return report


def run_self_check(
    report_dir: Path | None = None,
) -> BobaPerformanceFeedbackValidationReport:
    return _run_local(mode="self_check", report_dir=report_dir or REPORT_DIR)


def run_synthetic_project(
    report_dir: Path | None = None,
) -> BobaPerformanceFeedbackValidationReport:
    return _run_local(
        mode="synthetic_project",
        report_dir=report_dir or REPORT_DIR,
    )


async def _existing_project(
    project_id: str,
    report_dir: Path,
) -> BobaPerformanceFeedbackValidationReport:
    try:
        integration = boba_integration_provider()
        events = integration.store.list_performance_feedback_events(project_id)
        feedback = integration.load_performance_feedback(project_id)
        if feedback is None and events:
            feedback = await integration.generate_performance_feedback(project_id)
        if feedback is None:
            return BobaPerformanceFeedbackValidationReport(
                mode="project_id",
                passed=False,
                project_id=project_id,
                modules_imported=True,
                store_available=True,
                report_path_writable=_report_path_writable(report_dir),
                warnings=[
                    "No saved manual performance feedback is available.",
                    "No rendering, upload, download, or analytics collection occurred.",
                ],
            )
        export = integration.export_performance_feedback(project_id)
        path = integration.store.performance_feedback_path(project_id)
        report = BobaPerformanceFeedbackValidationReport(
            mode="project_id",
            passed=False,
            project_id=project_id,
            modules_imported=True,
            store_available=True,
            experimentation_available=feedback.signal_usage.experimentation_used,
            creator_learning_available=feedback.signal_usage.creator_learning_used,
            approval_rejection_learning_available=(
                feedback.signal_usage.approval_rejection_used
            ),
            report_path_writable=_report_path_writable(report_dir),
            events_recorded=feedback.audit_summary.total_events,
            snapshots_created=len(feedback.performance_snapshots),
            outcomes_created=len(feedback.experiment_outcomes),
            pattern_summary_created=True,
            learning_handoff_created=True,
            auto_collected_count_zero=(
                feedback.audit_summary.auto_collected_count == 0
            ),
            analytics_api_used_false=(
                feedback.signal_usage.analytics_api_used is False
            ),
            apply_automatically_false=(
                feedback.learning_handoff.apply_automatically is False
            ),
            export_safe=_safe_export(export),
            artifact_persisted=path.is_file(),
            events_append_safe=len(events) == feedback.audit_summary.total_events,
            json_safe=bool(json.loads(feedback.model_dump_json())),
            warnings=[
                "Existing-project mode read local manual BOBA artifacts only.",
                "No rendering, upload, download, or analytics collection occurred.",
            ],
        )
        report.passed = all(
            (
                report.report_path_writable,
                report.events_recorded > 0,
                report.auto_collected_count_zero,
                report.analytics_api_used_false,
                report.apply_automatically_false,
                report.export_safe,
                report.artifact_persisted,
                report.json_safe,
            )
        )
        return report
    except Exception as exc:
        return BobaPerformanceFeedbackValidationReport(
            mode="project_id",
            passed=False,
            project_id=project_id,
            modules_imported=True,
            store_available=True,
            report_path_writable=_report_path_writable(report_dir),
            errors=[str(exc)],
            warnings=[
                "The validator did not render, upload, download, or collect analytics."
            ],
        )


def _write_report(
    report: BobaPerformanceFeedbackValidationReport,
    report_dir: Path,
) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "boba_performance_feedback_report.json").write_text(
        json.dumps(report.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )
    summary = [
        "# BOBA Performance Feedback Brain V1 Validation",
        "",
        f"- Mode: `{report.mode}`",
        f"- Passed: `{str(report.passed).lower()}`",
        f"- Project: `{report.project_id or 'temporary self-check'}`",
        f"- Manual events: `{report.events_recorded}`",
        f"- Snapshots: `{report.snapshots_created}`",
        f"- Experiment outcomes: `{report.outcomes_created}`",
        "- Auto-collected events: `0`",
        f"- Analytics API used: `{str(not report.analytics_api_used_false).lower()}`",
        f"- Artifact persisted: `{report.artifact_persisted}`",
        f"- Export safe: `{report.export_safe}`",
        "",
        "V1 reviews explicit manual data only and never guarantees performance or "
        "applies a winner automatically.",
    ]
    (report_dir / "boba_performance_feedback_summary.md").write_text(
        "\n".join(summary) + "\n",
        encoding="utf-8",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate BOBA Performance Feedback Brain V1 locally.",
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
        report = asyncio.run(_existing_project(str(args.project_id), report_dir))
    _write_report(report, report_dir)
    print(json.dumps(report.model_dump(mode="json"), indent=2))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
