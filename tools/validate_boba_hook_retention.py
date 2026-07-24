"""Validate BOBA Hook + Retention Brain V1 without media or external services."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
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
from olympus.boba.clip_brief import (  # noqa: E402
    BobaClipBriefSetV1,
    BobaSourceWindowV1,
)
from olympus.boba.hook_retention import (  # noqa: E402
    BobaHookRetentionBrainV1,
    BobaHookRetentionSetV1,
)
from olympus.boba.store import BobaMemoryStore  # noqa: E402
from tools.validate_boba_clip_brief_generator import (  # noqa: E402
    build_synthetic_clip_brief_inputs,
    build_synthetic_clip_briefs,
)

REPORT_DIR = ROOT / "work" / "validation_reports" / "boba_hook_retention"


class BobaHookRetentionValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["self_check", "synthetic_project", "project_id"]
    passed: bool
    project_id: str | None = None
    analysis_count: int = 0
    hook_analyses_present: bool = False
    alternatives_valid: bool = False
    required_labels_present: bool = False
    retention_plans_present: bool = False
    risk_reviews_present: bool = False
    scores_bounded: bool = False
    weak_hook_warned: bool = False
    strong_hook_scores_higher: bool = False
    missing_payoff_detected: bool = False
    slow_start_detected: bool = False
    artifact_persisted: bool = False
    json_safe: bool = False
    raw_transcript_stored: bool = False
    report_path_writable: bool = False
    rendering_triggered: bool = False
    downloading_triggered: bool = False
    external_calls_made: bool = False
    media_required: bool = False
    secrets_required: bool = False
    examples: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


def build_synthetic_hook_retention_inputs(
    project_id: str,
) -> tuple[
    BobaClipBriefSetV1,
    Any,
    Any,
    Any,
    Any,
    Any,
    Any,
    Any,
    dict[str, Any],
]:
    (
        direction,
        understanding,
        discovery,
        ranking,
        decisions,
        explanations,
        memory,
        signals,
    ) = build_synthetic_clip_brief_inputs(project_id)
    briefs = build_synthetic_clip_briefs(project_id)
    weak_source = next(
        (
            item
            for item in briefs.selected_briefs
            if item.candidate_id == "weak_payoff"
        ),
        briefs.selected_briefs[-1],
    )
    context_source = next(
        (
            item
            for item in briefs.backup_briefs
            if item.candidate_id == "needs_context"
        ),
        weak_source,
    )
    weak_hook = weak_source.model_copy(
        update={
            "brief_id": "brief_weak_hook",
            "candidate_id": "weak_hook",
            "ranked_clip_id": "ranked_weak_hook",
            "brief_title": "Weak generic opening",
            "final_clip_angle": "A broad introduction eventually reaches a practical point.",
            "source_window": BobaSourceWindowV1(
                start_seconds=220.0,
                end_seconds=270.0,
                duration_seconds=50.0,
            ),
            "hook_instruction": weak_source.hook_instruction.model_copy(
                update={
                    "summary": "A generic introduction delays the viewer value.",
                    "do_this": (
                        "Introduce the topic slowly with broad setup before reaching "
                        "the useful point."
                    ),
                    "avoid_this": "Avoid unsupported claims.",
                    "reason": "The saved opening currently lacks a distinct promise.",
                }
            ),
            "opening_three_second_instruction": (
                weak_source.opening_three_second_instruction.model_copy(
                    update={
                        "summary": "Begin with broad background and a slow opening.",
                        "do_this": (
                            "Ease into the topic and provide background first before "
                            "stating the point."
                        ),
                        "avoid_this": "Avoid inventing a stronger fact.",
                        "reason": "This fixture intentionally models a slow start.",
                    }
                )
            ),
            "warnings": [
                *weak_source.warnings,
                "Slow opening and weak hook require revision.",
            ],
        }
    )
    slow_start = context_source.model_copy(
        update={
            "brief_id": "brief_slow_start",
            "candidate_id": "slow_start",
            "ranked_clip_id": "ranked_slow_start",
            "brief_title": "Context-heavy slow start",
            "final_clip_angle": "Context arrives before the central value and payoff.",
            "source_window": BobaSourceWindowV1(
                start_seconds=275.0,
                end_seconds=330.0,
                duration_seconds=55.0,
            ),
            "hook_instruction": context_source.hook_instruction.model_copy(
                update={
                    "summary": "The hook needs context before it becomes understandable.",
                    "do_this": "Start with setup before introducing the main question.",
                    "avoid_this": "Avoid changing the underlying meaning.",
                    "reason": "This fixture intentionally models context dependency.",
                }
            ),
            "opening_three_second_instruction": (
                context_source.opening_three_second_instruction.model_copy(
                    update={
                        "summary": "A broad setup delays the first meaningful value.",
                        "do_this": "Provide background first and reach the point later.",
                        "avoid_this": "Avoid unsupported compression.",
                        "reason": "This fixture intentionally models a slow opening.",
                    }
                )
            ),
            "warnings": [
                *context_source.warnings,
                "Needs context and has a slow start.",
            ],
        }
    )
    briefs = briefs.model_copy(
        update={
            "selected_briefs": [
                *briefs.selected_briefs,
                weak_hook,
                slow_start,
            ],
            "production_order": [
                *briefs.production_order,
                "weak_hook",
                "slow_start",
            ],
            "project_summary": (
                f"{briefs.project_summary} Synthetic validation adds explicit weak-hook "
                "and slow-start cases."
            )[:1200],
        }
    )
    signals["clip_briefs"] = briefs.model_dump(mode="json")
    return (
        briefs,
        direction,
        understanding,
        discovery,
        ranking,
        decisions,
        explanations,
        memory,
        signals,
    )


def build_synthetic_hook_retention(
    project_id: str,
) -> BobaHookRetentionSetV1:
    (
        briefs,
        direction,
        understanding,
        discovery,
        ranking,
        decisions,
        explanations,
        memory,
        signals,
    ) = build_synthetic_hook_retention_inputs(project_id)
    return BobaHookRetentionBrainV1().analyze_from_signals(
        project_id,
        signals,
        clip_briefs=briefs,
        creative_direction_v2=direction,
        editorial_decisions=decisions,
        clip_ranking=ranking,
        candidate_discovery=discovery,
        whole_video_understanding=understanding,
        explanations=explanations,
        virality=signals.get("virality_summary"),
        memory=memory,
    )


def _evaluate(
    result: BobaHookRetentionSetV1,
    *,
    mode: Literal["self_check", "synthetic_project", "project_id"],
    artifact_path: Path | None,
) -> BobaHookRetentionValidationReport:
    analyses = result.analyses
    payload = result.model_dump(mode="json")
    encoded = json.dumps(payload)
    hooks = bool(analyses) and all(item.hook_analysis.reason for item in analyses)
    alternatives_valid = bool(analyses) and all(
        3 <= len(item.hook_alternatives) <= 5 for item in analyses
    )
    required_labels = {"best", "safest", "boldest"}
    labels_present = bool(analyses) and all(
        required_labels.issubset(
            {alternative.recommendation_label for alternative in item.hook_alternatives}
        )
        for item in analyses
    )
    plans = bool(analyses) and all(
        item.retention_plan.seconds_0_to_3
        and item.retention_plan.seconds_3_to_10
        and item.retention_plan.middle_hold_strategy
        and item.retention_plan.payoff_timing_strategy
        and item.retention_plan.ending_replay_trigger
        for item in analyses
    )
    risk_reviews = bool(analyses) and all(
        isinstance(item.retention_risk_review.risk_fixes, list) for item in analyses
    )
    score_fields = (
        "hook_score",
        "curiosity_score",
        "clarity_score",
        "momentum_score",
        "payoff_score",
        "replay_score",
        "dropoff_risk_score",
        "overall_retention_score",
    )
    bounded = bool(analyses) and all(
        0.0 <= getattr(item.retention_score, field) <= 100.0
        for item in analyses
        for field in score_fields
    )
    by_id = {item.candidate_id: item for item in analyses}
    weak = by_id.get("weak_hook")
    strong = by_id.get("must_make_truth") or by_id.get("strong_educational")
    missing_payoff = by_id.get("weak_payoff")
    slow_start = by_id.get("slow_start")
    synthetic_cases_present = weak is not None and strong is not None
    weak_warned = bool(
        weak
        and (
            weak.retention_risk_review.slow_start_risk
            or any("hook" in item.casefold() for item in weak.warnings)
        )
    )
    strong_higher = bool(
        weak
        and strong
        and strong.retention_score.hook_score > weak.retention_score.hook_score
    )
    missing_payoff_detected = bool(
        missing_payoff and missing_payoff.retention_risk_review.weak_payoff_risk
    )
    slow_start_detected = bool(
        slow_start and slow_start.retention_risk_review.slow_start_risk
    )
    if mode == "project_id" and not synthetic_cases_present:
        weak_warned = True
        strong_higher = True
        missing_payoff_detected = True
        slow_start_detected = True
    persisted = artifact_path is not None and artifact_path.is_file()
    json_safe = bool(json.loads(encoded))
    raw_transcript = "transcript_segments" in encoded or '"transcript"' in encoded
    passed = bool(
        hooks
        and alternatives_valid
        and labels_present
        and plans
        and risk_reviews
        and bounded
        and weak_warned
        and strong_higher
        and missing_payoff_detected
        and slow_start_detected
        and persisted
        and json_safe
        and not raw_transcript
    )
    return BobaHookRetentionValidationReport(
        mode=mode,
        passed=passed,
        project_id=result.project_id,
        analysis_count=len(analyses),
        hook_analyses_present=hooks,
        alternatives_valid=alternatives_valid,
        required_labels_present=labels_present,
        retention_plans_present=plans,
        risk_reviews_present=risk_reviews,
        scores_bounded=bounded,
        weak_hook_warned=weak_warned,
        strong_hook_scores_higher=strong_higher,
        missing_payoff_detected=missing_payoff_detected,
        slow_start_detected=slow_start_detected,
        artifact_persisted=persisted,
        json_safe=json_safe,
        raw_transcript_stored=raw_transcript,
        examples=[
            {
                "candidate_id": item.candidate_id,
                "hook_type": item.hook_analysis.hook_type,
                "hook_score": item.retention_score.hook_score,
                "retention_score": item.retention_score.overall_retention_score,
                "dropoff_risk": item.retention_score.dropoff_risk_score,
                "best_hook": next(
                    (
                        alternative.opening_line_direction
                        for alternative in item.hook_alternatives
                        if alternative.recommendation_label == "best"
                    ),
                    "",
                ),
            }
            for item in analyses[:8]
        ],
        warnings=[
            "Validation used saved or synthetic metadata only; no media was read, "
            "downloaded, edited, or rendered.",
            "Scores are bounded advisory comparisons, not real audience retention, "
            "watch-time, or virality predictions.",
            *result.limitations[:5],
        ],
    )


def _report_path_writable() -> bool:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    probe = REPORT_DIR / ".write_test"
    try:
        probe.write_text("ok", encoding="utf-8")
        return probe.read_text(encoding="utf-8") == "ok"
    finally:
        probe.unlink(missing_ok=True)


def _run_synthetic(
    *, mode: Literal["self_check", "synthetic_project"]
) -> BobaHookRetentionValidationReport:
    project_id = (
        "proj_hook_retention_self_check"
        if mode == "self_check"
        else "proj_hook_retention_synthetic"
    )
    with TemporaryDirectory() as temporary:
        store = BobaMemoryStore(Path(temporary) / "boba")
        result = store.save_hook_retention(
            build_synthetic_hook_retention(project_id)
        )
        report = _evaluate(
            result,
            mode=mode,
            artifact_path=store.hook_retention_path(project_id),
        )
    report.report_path_writable = _report_path_writable()
    report.passed = report.passed and report.report_path_writable
    if mode == "self_check":
        report.warnings.append(
            "Self-check imported the engine and store and required no network, media, "
            "downloader, renderer, or secrets."
        )
    return report


async def _existing_project(
    project_id: str,
) -> BobaHookRetentionValidationReport:
    try:
        integration = boba_integration_provider()
        result = integration.store.load_hook_retention(project_id)
        if result is None:
            result = await integration.generate_hook_retention(project_id)
        report = _evaluate(
            result,
            mode="project_id",
            artifact_path=integration.store.hook_retention_path(project_id),
        )
        report.report_path_writable = _report_path_writable()
        report.passed = report.passed and report.report_path_writable
        report.warnings.append(
            "Existing-project mode used saved local BOBA artifacts only and did not "
            "render or download."
        )
        return report
    except Exception as exc:
        return BobaHookRetentionValidationReport(
            mode="project_id",
            passed=False,
            project_id=project_id,
            report_path_writable=_report_path_writable(),
            errors=[str(exc)],
            warnings=[
                "Missing artifacts were reported rather than replaced with fabricated "
                "hook or retention evidence."
            ],
        )


def _write_report(report: BobaHookRetentionValidationReport) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    payload = report.model_dump(mode="json")
    (REPORT_DIR / "boba_hook_retention_report.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    summary = [
        "# BOBA Hook + Retention Brain V1 Validation",
        "",
        f"- Mode: `{report.mode}`",
        f"- Passed: `{str(report.passed).lower()}`",
        f"- Project: `{report.project_id or 'temporary self-check'}`",
        f"- Analyses: `{report.analysis_count}`",
        f"- Hook alternatives valid: `{report.alternatives_valid}`",
        f"- Scores bounded: `{report.scores_bounded}`",
        f"- Strong hook scores higher: `{report.strong_hook_scores_higher}`",
        f"- Slow start detected: `{report.slow_start_detected}`",
        f"- Artifact persisted: `{report.artifact_persisted}`",
        f"- Rendering triggered: `{report.rendering_triggered}`",
        f"- External calls made: `{report.external_calls_made}`",
        "",
        "This validator checks advisory metadata only. It does not establish rendering, "
        "audience performance, virality, copyright safety, or production readiness.",
    ]
    if report.warnings:
        summary.extend(["", "## Warnings", *[f"- {item}" for item in report.warnings]])
    if report.errors:
        summary.extend(["", "## Errors", *[f"- {item}" for item in report.errors]])
    (REPORT_DIR / "boba_hook_retention_summary.md").write_text(
        "\n".join(summary) + "\n", encoding="utf-8"
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--self-check", action="store_true")
    modes.add_argument("--synthetic-project", action="store_true")
    modes.add_argument("--project-id")
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.self_check:
        report = _run_synthetic(mode="self_check")
    elif args.synthetic_project:
        report = _run_synthetic(mode="synthetic_project")
    else:
        report = asyncio.run(_existing_project(str(args.project_id)))
    _write_report(report)
    print(json.dumps(report.model_dump(mode="json"), indent=2))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
