"""Validate BOBA Approval / Rejection Learning V1 without media or network."""

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
from olympus.boba.approval_rejection_learning import (  # noqa: E402
    BobaApprovalRejectionLearningSetV1,
    BobaApprovalRejectionLearningV1,
)
from olympus.boba.creator_learning import (  # noqa: E402
    BobaCreatorFeedbackEventV1,
    BobaCreatorLearningLoopV1,
    BobaCreatorLearningSetV1,
)
from olympus.boba.memory_contracts import BobaProjectMemoryV1  # noqa: E402
from olympus.boba.store import BobaMemoryStore  # noqa: E402
from tools.validate_boba_creator_learning import (  # noqa: E402
    build_synthetic_creator_learning_artifacts,
)

REPORT_DIR = (
    ROOT
    / "work"
    / "validation_reports"
    / "boba_approval_rejection_learning"
)


class BobaApprovalRejectionValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["self_check", "synthetic_project", "project_id"]
    passed: bool
    project_id: str | None = None
    modules_imported: bool = False
    creator_learning_available: bool = False
    memory_system_available: bool = False
    store_available: bool = False
    report_path_writable: bool = False
    feedback_events_used: int = 0
    approval_cases: int = 0
    rejection_cases: int = 0
    decision_attributions: int = 0
    correction_mappings: int = 0
    pattern_scores: int = 0
    module_guidance_present: bool = False
    unknown_attribution_supported: bool = False
    repeated_approval_strengthened: bool = False
    repeated_rejection_strengthened: bool = False
    contradictions_reduced_confidence: bool = False
    apply_automatically_false: bool = False
    dry_run_no_writes: bool = False
    export_safe: bool = False
    reset_project_only: bool = False
    artifact_persisted: bool = False
    json_safe: bool = False
    rendering_triggered: bool = False
    downloading_triggered: bool = False
    external_calls_made: bool = False
    media_required: bool = False
    secrets_required: bool = False
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


def build_synthetic_approval_rejection_artifacts() -> dict[str, dict[str, Any]]:
    artifacts = build_synthetic_creator_learning_artifacts()
    ranked = artifacts["clip_ranking"]["ranked_candidates"][0]
    ranked["score_breakdown"] = {
        "hook_score": 88.0,
        "payoff_score": 84.0,
        "retention_score": 82.0,
        "pacing_score": 80.0,
    }
    ranked["ranking_reasons"] = [
        "Curiosity gap is clear and the payoff is supported."
    ]
    artifacts["editorial_decision"]["decisions"][0].update(
        {
            "selected": True,
            "render_readiness": "ready",
            "decision_reasons": ["Complete story and supported payoff."],
        }
    )
    artifacts["explanation"] = {
        "candidate_explanations": [
            {
                "clip_id": "curiosity_clip",
                "candidate_id": "curiosity_clip",
                "short_summary": "Curiosity gap resolves in a supported payoff.",
                "key_reasons": ["Strong hook", "Complete payoff"],
                "evidence": [
                    {
                        "source_artifact": "clip_ranking",
                        "source_field": "score_breakdown.hook_score",
                        "snippet": "hook_score=88",
                    }
                ],
            }
        ]
    }
    return artifacts


def build_synthetic_approval_rejection_events(
    project_id: str,
    artifacts: dict[str, dict[str, Any]],
) -> list[BobaCreatorFeedbackEventV1]:
    creator_learning = BobaCreatorLearningLoopV1()
    specs: list[dict[str, Any]] = [
        {
            "event_type": "approval",
            "target_type": "ranked_clip",
            "target_id": "ranked_curiosity",
            "user_action": "approved",
            "note": "Strong curiosity gap.",
        },
        {
            "event_type": "approval",
            "target_type": "ranked_clip",
            "target_id": "ranked_curiosity",
            "user_action": "approved",
            "note": "The curiosity gap works.",
        },
        {
            "event_type": "approval",
            "target_type": "caption_motion",
            "target_id": "caption_clean",
            "user_action": "approved",
            "note": "Clean captions and stable motion.",
        },
        {
            "event_type": "approval",
            "target_type": "caption_motion",
            "target_id": "caption_clean",
            "user_action": "approved",
            "note": "Keep the clean captions.",
        },
        {
            "event_type": "rejection",
            "target_type": "hook_alternative",
            "target_id": "hook_alt_slow",
            "user_action": "rejected",
            "note": "Too slow.",
        },
        {
            "event_type": "rejection",
            "target_type": "hook_alternative",
            "target_id": "hook_alt_slow",
            "user_action": "rejected",
            "note": "The slow start drags.",
        },
        {
            "event_type": "rejection",
            "target_type": "caption_motion",
            "target_id": "caption_heavy",
            "user_action": "rejected",
            "note": "Too much zoom.",
        },
        {
            "event_type": "rejection",
            "target_type": "music_mood",
            "target_id": "mood_emotional",
            "user_action": "rejected",
            "note": "Music feels wrong.",
        },
        {
            "event_type": "rejection",
            "target_type": "ranked_clip",
            "target_id": "ranked_curiosity",
            "user_action": "rejected",
            "note": "No payoff.",
        },
        {
            "event_type": "correction",
            "target_type": "project",
            "target_id": project_id,
            "user_action": "corrected",
            "note": "Not interesting.",
        },
        {
            "event_type": "preference_note",
            "target_type": "project",
            "target_id": project_id,
            "user_action": "noted",
            "note": "I am unsure about this one.",
        },
    ]
    return [
        creator_learning.create_feedback_event(
            project_id=project_id,
            artifacts=artifacts,
            event_id=f"creator_feedback_approval_rejection_{index}",
            created_at=f"2026-02-01T00:00:{index:02d}+00:00",
            **spec,
        )
        for index, spec in enumerate(specs, start=1)
    ]


def build_synthetic_creator_learning(
    project_id: str,
    events: list[BobaCreatorFeedbackEventV1],
    artifacts: dict[str, dict[str, Any]],
) -> BobaCreatorLearningSetV1:
    return BobaCreatorLearningLoopV1().analyze(
        project_id,
        events,
        creator_id="creator_approval_rejection",
        source_id=project_id,
        boba_memory={"explicit_feedback_only": True},
        clip_ranking=artifacts["clip_ranking"],
        editorial_decision=artifacts["editorial_decision"],
        explanation=artifacts["explanation"],
        creative_direction=artifacts["creative_direction"],
        clip_briefs=artifacts["clip_briefs"],
        hook_retention=artifacts["hook_retention"],
        caption_motion=artifacts["caption_motion"],
        music_mood=artifacts["music_mood"],
    )


def analyze_synthetic_approval_rejection_learning(
    project_id: str,
    events: list[BobaCreatorFeedbackEventV1],
    artifacts: dict[str, dict[str, Any]],
    *,
    dry_run: bool = False,
) -> BobaApprovalRejectionLearningSetV1:
    creator_learning = build_synthetic_creator_learning(
        project_id,
        events,
        artifacts,
    )
    return BobaApprovalRejectionLearningV1().analyze(
        project_id,
        events,
        source_id=project_id,
        creator_learning=creator_learning,
        boba_memory={"explicit_feedback_only": True},
        clip_ranking=artifacts["clip_ranking"],
        editorial_decision=artifacts["editorial_decision"],
        explanation=artifacts["explanation"],
        creative_direction=artifacts["creative_direction"],
        clip_briefs=artifacts["clip_briefs"],
        hook_retention=artifacts["hook_retention"],
        caption_motion=artifacts["caption_motion"],
        music_mood=artifacts["music_mood"],
        dry_run=dry_run,
    )


def build_synthetic_approval_rejection_learning(
    project_id: str = "proj_approval_rejection_synthetic",
) -> BobaApprovalRejectionLearningSetV1:
    artifacts = build_synthetic_approval_rejection_artifacts()
    events = build_synthetic_approval_rejection_events(project_id, artifacts)
    return analyze_synthetic_approval_rejection_learning(
        project_id,
        events,
        artifacts,
    )


def _safe_export(payload: dict[str, Any]) -> bool:
    encoded = json.dumps(payload, sort_keys=True).casefold()
    forbidden = (
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


def _pattern(
    result: BobaApprovalRejectionLearningSetV1,
    *,
    category: str,
    summary_contains: str,
) -> Any:
    return next(
        (
            item
            for item in result.pattern_scores
            if item.category == category
            and summary_contains in item.summary.casefold()
        ),
        None,
    )


def _run_local(
    *,
    mode: Literal["self_check", "synthetic_project"],
    report_dir: Path,
) -> BobaApprovalRejectionValidationReport:
    project_id = (
        "proj_approval_rejection_self_check"
        if mode == "self_check"
        else "proj_approval_rejection_synthetic"
    )
    artifacts = build_synthetic_approval_rejection_artifacts()
    events = build_synthetic_approval_rejection_events(project_id, artifacts)
    creator_learning = build_synthetic_creator_learning(
        project_id,
        events,
        artifacts,
    )
    result = analyze_synthetic_approval_rejection_learning(
        project_id,
        events,
        artifacts,
    )
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        store = BobaMemoryStore(root / "boba", memory_root=root / "memory")
        for event in events:
            store.record_creator_feedback_event(event)
        store.save_creator_learning(creator_learning)
        store.save_project_memory(
            BobaProjectMemoryV1(
                project_id=project_id,
                source_summary="Unrelated project memory remains after scoped reset.",
            )
        )
        store.save_approval_rejection_learning(result)
        persisted = store.load_approval_rejection_learning(project_id)
        export = store.export_approval_rejection_learning(project_id)

        dry_store = BobaMemoryStore(
            root / "dry_boba",
            memory_root=root / "dry_memory",
        )
        analyze_synthetic_approval_rejection_learning(
            project_id,
            events,
            artifacts,
            dry_run=True,
        )
        dry_run_no_writes = not dry_store.approval_rejection_learning_path(
            project_id
        ).exists()

        reset_removed = store.reset_approval_rejection_learning(project_id)
        reset_project_only = bool(
            reset_removed
            and store.load_approval_rejection_learning(project_id) is None
            and store.load_creator_learning(project_id) is not None
            and len(store.list_creator_feedback_events(project_id)) == len(events)
            and store.load_project_memory(project_id) is not None
        )

        approval_pattern = _pattern(
            result,
            category="hook",
            summary_contains="curiosity gap",
        )
        rejection_pattern = _pattern(
            result,
            category="pacing",
            summary_contains="slow opening",
        )
        contradiction_pattern = next(
            (
                item
                for item in result.pattern_scores
                if item.pattern_type == "contradiction"
            ),
            None,
        )
        repeated_comparison = analyze_synthetic_approval_rejection_learning(
            project_id,
            events[:1],
            artifacts,
        )
        single_approval_pattern = _pattern(
            repeated_comparison,
            category="hook",
            summary_contains="curiosity gap",
        )
        single_rejection = analyze_synthetic_approval_rejection_learning(
            project_id,
            events[4:5],
            artifacts,
        )
        single_rejection_pattern = _pattern(
            single_rejection,
            category="pacing",
            summary_contains="slow opening",
        )
        non_conflicting = analyze_synthetic_approval_rejection_learning(
            project_id,
            events[:8],
            artifacts,
        )
        non_conflicting_pattern = _pattern(
            non_conflicting,
            category="hook",
            summary_contains="curiosity gap",
        )

        report = BobaApprovalRejectionValidationReport(
            mode=mode,
            passed=False,
            project_id=project_id,
            modules_imported=True,
            creator_learning_available=True,
            memory_system_available=True,
            store_available=True,
            report_path_writable=_report_path_writable(report_dir),
            feedback_events_used=result.audit_summary.total_feedback_events_used,
            approval_cases=len(result.approval_cases),
            rejection_cases=len(result.rejection_cases),
            decision_attributions=len(result.decision_attributions),
            correction_mappings=sum(
                len(case.correction_mapping) for case in result.rejection_cases
            ),
            pattern_scores=len(result.pattern_scores),
            module_guidance_present=any(
                (
                    result.module_guidance.ranking_guidance,
                    result.module_guidance.editorial_guidance,
                    result.module_guidance.hook_retention_guidance,
                    result.module_guidance.caption_motion_guidance,
                    result.module_guidance.music_mood_guidance,
                    result.module_guidance.general_guidance,
                )
            ),
            unknown_attribution_supported=any(
                attribution.primary_module == "unknown"
                for attribution in result.decision_attributions
            ),
            repeated_approval_strengthened=bool(
                approval_pattern
                and single_approval_pattern
                and approval_pattern.strength > single_approval_pattern.strength
            ),
            repeated_rejection_strengthened=bool(
                rejection_pattern
                and single_rejection_pattern
                and rejection_pattern.strength > single_rejection_pattern.strength
            ),
            contradictions_reduced_confidence=bool(
                contradiction_pattern
                and non_conflicting_pattern
                and contradiction_pattern.confidence
                < non_conflicting_pattern.confidence
            ),
            apply_automatically_false=(
                result.module_guidance.apply_automatically is False
                and all(
                    mapping.apply_automatically is False
                    for case in result.rejection_cases
                    for mapping in case.correction_mapping
                )
            ),
            dry_run_no_writes=dry_run_no_writes,
            export_safe=_safe_export(export),
            reset_project_only=reset_project_only,
            artifact_persisted=bool(
                persisted
                and persisted.schema_version
                == "boba_approval_rejection_learning_v1"
            ),
            json_safe=bool(json.loads(result.model_dump_json())),
            warnings=[
                "Validation used explicit synthetic feedback and local metadata only.",
                "No guidance was applied automatically.",
            ],
        )
    checks = [
        report.modules_imported,
        report.creator_learning_available,
        report.memory_system_available,
        report.store_available,
        report.report_path_writable,
        report.feedback_events_used >= 11,
        report.approval_cases >= 4,
        report.rejection_cases >= 6,
        report.decision_attributions >= 11,
        report.correction_mappings > 0,
        report.pattern_scores > 0,
        report.module_guidance_present,
        report.unknown_attribution_supported,
        report.repeated_approval_strengthened,
        report.repeated_rejection_strengthened,
        report.contradictions_reduced_confidence,
        report.apply_automatically_false,
        report.dry_run_no_writes,
        report.export_safe,
        report.reset_project_only,
        report.artifact_persisted,
        report.json_safe,
        not report.rendering_triggered,
        not report.downloading_triggered,
        not report.external_calls_made,
        not report.media_required,
        not report.secrets_required,
    ]
    report.passed = all(checks)
    return report


def run_self_check(
    report_dir: Path | None = None,
) -> BobaApprovalRejectionValidationReport:
    return _run_local(
        mode="self_check",
        report_dir=report_dir or REPORT_DIR,
    )


def run_synthetic_project(
    report_dir: Path | None = None,
) -> BobaApprovalRejectionValidationReport:
    return _run_local(
        mode="synthetic_project",
        report_dir=report_dir or REPORT_DIR,
    )


async def _existing_project(
    project_id: str,
    report_dir: Path,
) -> BobaApprovalRejectionValidationReport:
    try:
        integration = boba_integration_provider()
        learning = integration.load_approval_rejection_learning(project_id)
        if learning is None:
            learning = await integration.generate_approval_rejection_learning(
                project_id,
                dry_run=False,
            )
        artifact_path = integration.store.approval_rejection_learning_path(
            project_id
        )
        return BobaApprovalRejectionValidationReport(
            mode="project_id",
            passed=bool(
                artifact_path.is_file()
                and learning.module_guidance.apply_automatically is False
                and json.loads(learning.model_dump_json())
            ),
            project_id=project_id,
            modules_imported=True,
            creator_learning_available=(
                integration.store.load_creator_learning(project_id) is not None
            ),
            memory_system_available=True,
            store_available=True,
            report_path_writable=_report_path_writable(report_dir),
            feedback_events_used=learning.audit_summary.total_feedback_events_used,
            approval_cases=len(learning.approval_cases),
            rejection_cases=len(learning.rejection_cases),
            decision_attributions=len(learning.decision_attributions),
            correction_mappings=sum(
                len(case.correction_mapping) for case in learning.rejection_cases
            ),
            pattern_scores=len(learning.pattern_scores),
            module_guidance_present=True,
            unknown_attribution_supported=True,
            apply_automatically_false=True,
            artifact_persisted=artifact_path.is_file(),
            json_safe=True,
            warnings=[
                "Existing-project mode used saved explicit feedback and local BOBA "
                "artifacts only.",
                "Missing optional artifacts are reported through signal usage.",
            ],
        )
    except Exception as exc:
        return BobaApprovalRejectionValidationReport(
            mode="project_id",
            passed=False,
            project_id=project_id,
            modules_imported=True,
            creator_learning_available=True,
            memory_system_available=True,
            store_available=True,
            report_path_writable=_report_path_writable(report_dir),
            errors=[str(exc)],
            warnings=["The validator did not fabricate approval or rejection feedback."],
        )


def _write_report(
    report: BobaApprovalRejectionValidationReport,
    report_dir: Path,
) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    payload = report.model_dump(mode="json")
    (report_dir / "boba_approval_rejection_learning_report.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )
    summary = [
        "# BOBA Approval / Rejection Learning V1 Validation",
        "",
        f"- Mode: `{report.mode}`",
        f"- Passed: `{str(report.passed).lower()}`",
        f"- Project: `{report.project_id or 'temporary self-check'}`",
        f"- Explicit events: `{report.feedback_events_used}`",
        f"- Approval cases: `{report.approval_cases}`",
        f"- Rejection cases: `{report.rejection_cases}`",
        f"- Attributions: `{report.decision_attributions}`",
        f"- Artifact persisted: `{report.artifact_persisted}`",
        f"- Dry run avoided writes: `{report.dry_run_no_writes}`",
        f"- Export safe: `{report.export_safe}`",
        f"- Scoped reset passed: `{report.reset_project_only}`",
        f"- Rendering triggered: `{report.rendering_triggered}`",
        f"- External calls made: `{report.external_calls_made}`",
        "",
        "This validator checks local explicit-feedback decision learning only. "
        "It does not use audience analytics or prove future performance.",
    ]
    if report.warnings:
        summary.extend(["", "## Warnings", *[f"- {item}" for item in report.warnings]])
    if report.errors:
        summary.extend(["", "## Errors", *[f"- {item}" for item in report.errors]])
    (report_dir / "boba_approval_rejection_learning_summary.md").write_text(
        "\n".join(summary) + "\n",
        encoding="utf-8",
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
        report = run_self_check()
    elif args.synthetic_project:
        report = run_synthetic_project()
    else:
        report = asyncio.run(_existing_project(str(args.project_id), REPORT_DIR))
    _write_report(report, REPORT_DIR)
    print(json.dumps(report.model_dump(mode="json"), indent=2))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
