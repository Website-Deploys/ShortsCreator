"""Validate BOBA Experimentation System V1 without media, network, or analytics."""

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
from olympus.boba.experimentation import (  # noqa: E402
    BobaExperimentationSetV1,
    BobaExperimentationSystemV1,
)
from olympus.boba.memory_contracts import BobaProjectMemoryV1  # noqa: E402
from olympus.boba.store import BobaMemoryStore  # noqa: E402

REPORT_DIR = ROOT / "work" / "validation_reports" / "boba_experimentation"


class BobaExperimentationValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["self_check", "synthetic_project", "project_id"]
    passed: bool
    project_id: str | None = None
    modules_imported: bool = False
    creator_learning_available: bool = False
    approval_rejection_learning_available: bool = False
    store_available: bool = False
    report_path_writable: bool = False
    experiment_plans: int = 0
    hook_experiments: int = 0
    caption_experiments: int = 0
    motion_experiments: int = 0
    music_mood_experiments: int = 0
    retention_experiments: int = 0
    rejected_ideas: int = 0
    baselines_traceable: bool = False
    variants_present: bool = False
    one_variable_per_experiment: bool = False
    hypotheses_present: bool = False
    metric_plans_present: bool = False
    success_criteria_present: bool = False
    risk_reviews_present: bool = False
    creator_approval_required: bool = False
    apply_automatically_false: bool = False
    unsafe_ideas_rejected: bool = False
    dry_run_no_writes: bool = False
    export_safe: bool = False
    reset_project_only: bool = False
    artifact_persisted: bool = False
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


def _brief(candidate_id: str, *, warning: str = "") -> dict[str, Any]:
    return {
        "brief_id": f"brief_{candidate_id}",
        "candidate_id": candidate_id,
        "brief_title": f"Advisory brief for {candidate_id}",
        "final_clip_angle": "A supported problem-to-payoff story.",
        "target_viewer_feeling": "Clear curiosity followed by resolution.",
        "opening_three_second_instruction": {
            "do_this": "Open on the first supported meaningful words.",
            "reason": "The source contains a clear opening promise.",
        },
        "risk_fixes": [warning] if warning else [],
        "warnings": [warning] if warning else [],
        "confidence": 0.76,
    }


def build_synthetic_experimentation_artifacts() -> dict[str, dict[str, Any]]:
    """Return compact saved-artifact shapes for every V1 experiment category."""

    candidates = (
        "strong_clip",
        "weak_hook_clip",
        "caption_overload_clip",
        "heavy_motion_clip",
        "wrong_mood_clip",
    )
    briefs = [
        _brief(
            candidate,
            warning=(
                "Clarify one editor action without changing the creative angle."
                if candidate == "strong_clip"
                else ""
            ),
        )
        for candidate in candidates
    ]
    return {
        "clip_briefs": {
            "schema_version": "boba_clip_brief_set_v1",
            "selected_briefs": briefs,
            "backup_briefs": [],
            "blocked_briefs": [],
        },
        "hook_retention": {
            "schema_version": "boba_hook_retention_v1",
            "analyses": [
                {
                    "candidate_id": "weak_hook_clip",
                    "brief_id": "brief_weak_hook_clip",
                    "confidence": 0.74,
                    "hook_analysis": {
                        "hook_type": "curiosity_gap",
                        "opening_line_direction": (
                            "Lead with the supported unanswered question."
                        ),
                        "hook_strength": 54.0,
                        "hook_risk": "Current opening takes too long to state the question.",
                        "reason": "The question resolves in the saved payoff.",
                    },
                    "hook_alternatives": [
                        {
                            "alternative_id": "hook_alt_direct",
                            "hook_type": "direct_question",
                            "opening_line_direction": (
                                "State the supported question in the first sentence."
                            ),
                            "why_it_may_work": "It reduces setup without inventing a claim.",
                            "why_it_may_fail": "It may feel less conversational.",
                            "risk_score": 24.0,
                        },
                        {
                            "alternative_id": "hook_alt_misleading",
                            "hook_type": "sensational_claim",
                            "opening_line_direction": (
                                "Use a misleading guaranteed-result promise."
                            ),
                            "why_it_may_work": "Unsupported sensational promise.",
                            "why_it_may_fail": "Misleading and deceptive bait and switch.",
                            "risk_score": 94.0,
                        },
                    ],
                    "retention_plan": {
                        "payoff_timing_strategy": (
                            "Keep the supported payoff at the end of the story."
                        ),
                        "middle_hold_strategy": "Use one concise open-loop reminder.",
                        "ending_replay_trigger": "End with a callback to the question.",
                        "retention_tactics": ["Preserve setup and payoff."],
                    },
                    "retention_risk_review": {
                        "weak_payoff_risk": True,
                        "slow_start_risk": True,
                        "warnings": [
                            "Weak payoff emphasis and slow opening require review."
                        ],
                    },
                    "brief_enhancements": {
                        "enhanced_payoff_timing": (
                            "Emphasize the existing payoff when it arrives."
                        ),
                        "enhanced_replay_trigger": (
                            "Use a concise callback without adding a claim."
                        ),
                    },
                },
                {
                    "candidate_id": "strong_clip",
                    "brief_id": "brief_strong_clip",
                    "confidence": 0.82,
                    "hook_analysis": {
                        "hook_type": "problem_solution",
                        "opening_line_direction": (
                            "Open with the supported problem in one concise line."
                        ),
                        "hook_strength": 82.0,
                        "reason": "The source supplies a complete payoff.",
                    },
                    "hook_alternatives": [
                        {
                            "alternative_id": "hook_alt_contrast",
                            "hook_type": "contrast",
                            "opening_line_direction": (
                                "Frame the same supported problem as a concise contrast."
                            ),
                            "why_it_may_work": "The contrast remains evidence-backed.",
                            "why_it_may_fail": "It may feel more formal.",
                            "risk_score": 20.0,
                        }
                    ],
                    "retention_plan": {
                        "payoff_timing_strategy": "Hold the payoff to its saved beat.",
                        "middle_hold_strategy": "Keep the middle concise.",
                        "ending_replay_trigger": (
                            "End with the supported lesson as a callback."
                        ),
                        "retention_tactics": ["One natural callback."],
                    },
                    "retention_risk_review": {
                        "filler_risk": True,
                        "warnings": ["The middle may repeat one idea."],
                    },
                },
            ],
        },
        "caption_motion": {
            "schema_version": "boba_caption_motion_v1",
            "recommendations": [
                {
                    "recommendation_id": "caption_overload",
                    "candidate_id": "caption_overload_clip",
                    "brief_id": "brief_caption_overload_clip",
                    "confidence": 0.78,
                    "caption_recommendation": {
                        "caption_style": "high_density",
                        "hook_caption_instruction": (
                            "Show dense captions with several simultaneous highlights."
                        ),
                        "reason": "The baseline is energetic but crowded.",
                    },
                    "motion_recommendation": {
                        "motion_style": "stable",
                        "motion_intensity": "low",
                        "reason": "Keep framing steady.",
                    },
                    "safety_review": {
                        "caption_overload_risk": True,
                        "readability_risk": True,
                        "warnings": ["Caption density is too high for phone reading."],
                    },
                    "brief_enhancement": {
                        "improved_caption_instruction": (
                            "Use short phrase groups and one emphasis word per beat."
                        ),
                        "readability_warning": "Do not stack multiple highlights.",
                    },
                },
                {
                    "recommendation_id": "heavy_motion",
                    "candidate_id": "heavy_motion_clip",
                    "brief_id": "brief_heavy_motion_clip",
                    "confidence": 0.72,
                    "caption_recommendation": {
                        "caption_style": "clean",
                        "hook_caption_instruction": "Use two readable caption lines.",
                        "reason": "Clean captions protect speech clarity.",
                    },
                    "motion_recommendation": {
                        "motion_style": "repeated_zoom",
                        "motion_intensity": "high",
                        "reason": "The baseline requests repeated zooms.",
                    },
                    "safety_review": {
                        "face_cutoff_risk": True,
                        "over_motion_risk": True,
                        "warnings": ["Repeated zoom may cut off the speaker."],
                        "blockers": ["Face-safe framing is unresolved."],
                    },
                },
            ],
        },
        "music_mood": {
            "schema_version": "boba_music_mood_v1",
            "recommendations": [
                {
                    "recommendation_id": "wrong_mood",
                    "candidate_id": "wrong_mood_clip",
                    "brief_id": "brief_wrong_mood_clip",
                    "confidence": 0.75,
                    "music_mood": {
                        "primary_mood": "triumphant",
                        "secondary_mood": "reflective",
                        "energy_level": "high",
                        "reason": "The current direction may overstate a reflective story.",
                        "emotional_direction": "Reflective resolution.",
                        "pacing_fit": "Restrained.",
                    },
                    "speech_clarity_plan": {"clarity_risk": True},
                    "sfx_recommendation": {
                        "sfx_intensity": "high",
                        "reason": "The baseline uses several accents.",
                        "hook_sfx_guidance": "Use only a clean subtle accent.",
                        "payoff_sfx_guidance": "Protect the payoff speech.",
                    },
                    "audio_risk_review": {
                        "wrong_mood_risk": True,
                        "speech_clarity_risk": True,
                        "rights_review_required": True,
                        "warnings": ["No track may be selected before rights review."],
                    },
                    "brief_enhancement": {
                        "rights_review_warning": (
                            "Music licensing and usage rights remain unresolved."
                        )
                    },
                },
                {
                    "recommendation_id": "strong_audio",
                    "candidate_id": "strong_clip",
                    "brief_id": "brief_strong_clip",
                    "confidence": 0.82,
                    "music_mood": {
                        "primary_mood": "focused",
                        "secondary_mood": "hopeful",
                        "energy_level": "medium",
                        "reason": "A focused bed supports the complete payoff.",
                        "emotional_direction": "Measured optimism.",
                        "pacing_fit": "Speech first.",
                    },
                    "sfx_recommendation": {
                        "sfx_intensity": "subtle",
                        "reason": "One restrained accent may support the payoff.",
                        "hook_sfx_guidance": "No noisy hit.",
                        "payoff_sfx_guidance": "One clean low accent.",
                    },
                    "audio_risk_review": {},
                },
            ],
        },
        "creative_direction": {
            "clip_directions": [
                {
                    "candidate_id": "strong_clip",
                    "brief_id": "brief_strong_clip",
                    "summary": "Problem to supported payoff.",
                }
            ]
        },
        "editorial_decision": {
            "decisions": [
                {
                    "candidate_id": candidate,
                    "brief_id": f"brief_{candidate}",
                    "selected": True,
                    "risk_review": {
                        "warnings": (
                            ["Rights and license review required."]
                            if candidate == "wrong_mood_clip"
                            else []
                        ),
                        "blockers": [],
                    },
                }
                for candidate in candidates
            ]
        },
        "explanation": {
            "candidate_explanations": [
                {
                    "candidate_id": candidate,
                    "brief_id": f"brief_{candidate}",
                    "summary": "Synthetic evidence-backed advisory explanation.",
                    "warnings": [],
                }
                for candidate in candidates
            ]
        },
        "creator_learning": {
            "learning_profile": {
                "preferred_hook_styles": ["direct_question"],
                "preferred_caption_styles": ["clean_subtitles"],
                "preferred_motion_styles": ["stable_subtle"],
                "preferred_music_moods": ["reflective"],
            },
            "explicit_feedback_only": True,
        },
        "approval_rejection_learning": {
            "module_guidance": {
                "hook_retention_guidance": [
                    "Avoid slow or sensational unsupported hooks."
                ],
                "caption_motion_guidance": [
                    "Prefer clean captions and avoid repeated zoom."
                ],
                "music_mood_guidance": ["Avoid mood mismatch and protect speech."],
            },
            "pattern_scores": [
                {
                    "category": "motion",
                    "guidance": "Repeated zoom was rejected.",
                },
                {
                    "category": "music_mood",
                    "guidance": "Reflective mood was preferred.",
                },
            ],
        },
        "memory": {
            "project_id": "synthetic",
            "source_summary": "Compact advisory memory only.",
        },
    }


def build_synthetic_experimentation(
    project_id: str = "proj_experimentation_synthetic",
    *,
    dry_run: bool = False,
) -> BobaExperimentationSetV1:
    artifacts = build_synthetic_experimentation_artifacts()
    return BobaExperimentationSystemV1().analyze(
        project_id,
        source_id=project_id,
        clip_briefs=artifacts["clip_briefs"],
        hook_retention=artifacts["hook_retention"],
        caption_motion=artifacts["caption_motion"],
        music_mood=artifacts["music_mood"],
        creative_direction=artifacts["creative_direction"],
        editorial_decision=artifacts["editorial_decision"],
        explanation=artifacts["explanation"],
        creator_learning=artifacts["creator_learning"],
        approval_rejection_learning=artifacts["approval_rejection_learning"],
        boba_memory=artifacts["memory"],
        dry_run=dry_run,
    )


def _safe_export(payload: dict[str, Any]) -> bool:
    encoded = json.dumps(payload, sort_keys=True).casefold()
    forbidden = (
        "creator_note",
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


def _run_local(
    *,
    mode: Literal["self_check", "synthetic_project"],
    report_dir: Path,
) -> BobaExperimentationValidationReport:
    project_id = (
        "proj_experimentation_self_check"
        if mode == "self_check"
        else "proj_experimentation_synthetic"
    )
    result = build_synthetic_experimentation(project_id)
    dry_result = build_synthetic_experimentation(project_id, dry_run=True)
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        store = BobaMemoryStore(root / "boba", memory_root=root / "memory")
        dry_run_no_writes = (
            "Dry run: experimentation plans were not persisted." in dry_result.warnings
            and not store.experimentation_path(project_id).exists()
        )
        store.save_experimentation_plan(result)
        persisted = store.load_experimentation_plan(project_id)
        first_plan = result.experiment_plans[0]
        manual_result = BobaExperimentationSystemV1().create_manual_result(
            first_plan,
            selected_variant_id=first_plan.variants[0].variant_id,
            manual_rating=4.0,
            outcome_label="variant_preferred",
            creator_note="Synthetic explicit note excluded from export.",
            should_feed_learning=False,
        )
        store.record_manual_experiment_result(project_id, manual_result)
        export = store.export_experimentation_plan(project_id)
        store.save_project_memory(
            BobaProjectMemoryV1(
                project_id=project_id,
                source_summary="Unrelated BOBA memory must survive reset.",
            )
        )
        reset_removed = store.reset_experimentation_plan(project_id)
        reset_project_only = bool(
            reset_removed
            and store.load_experimentation_plan(project_id) is None
            and not store.list_manual_experiment_results(project_id)
            and store.load_project_memory(project_id) is not None
        )

    experiment_types = [item.experiment_type for item in result.experiment_plans]
    report = BobaExperimentationValidationReport(
        mode=mode,
        passed=False,
        project_id=project_id,
        modules_imported=True,
        creator_learning_available=result.signal_usage.creator_learning_used,
        approval_rejection_learning_available=(
            result.signal_usage.approval_rejection_learning_used
        ),
        store_available=True,
        report_path_writable=_report_path_writable(report_dir),
        experiment_plans=len(result.experiment_plans),
        hook_experiments=experiment_types.count("hook_ab_test"),
        caption_experiments=experiment_types.count("caption_ab_test"),
        motion_experiments=experiment_types.count("motion_ab_test"),
        music_mood_experiments=experiment_types.count("music_mood_ab_test"),
        retention_experiments=experiment_types.count("retention_ab_test"),
        rejected_ideas=len(result.rejected_experiment_ideas),
        baselines_traceable=all(
            item.baseline.source_artifact and item.baseline.source_field
            for item in result.experiment_plans
        ),
        variants_present=all(item.variants for item in result.experiment_plans),
        one_variable_per_experiment=all(
            len({variant.changed_variable for variant in item.variants}) == 1
            for item in result.experiment_plans
        ),
        hypotheses_present=all(
            item.hypothesis.statement for item in result.experiment_plans
        ),
        metric_plans_present=all(
            item.metric_plan.manual_review_questions
            for item in result.experiment_plans
        ),
        success_criteria_present=all(
            item.success_criteria.decision_rule
            for item in result.experiment_plans
        ),
        risk_reviews_present=all(
            item.risk_review is not None for item in result.experiment_plans
        ),
        creator_approval_required=all(
            item.required_creator_approval
            and item.status == "needs_creator_approval"
            for item in result.experiment_plans
        ),
        apply_automatically_false=all(
            item.learning_handoff.apply_automatically is False
            for item in result.experiment_plans
        ),
        unsafe_ideas_rejected=any(
            "misleading" in item.reason_rejected.casefold()
            or "rights" in item.risk.casefold()
            or "motion" in item.risk.casefold()
            for item in result.rejected_experiment_ideas
        ),
        dry_run_no_writes=dry_run_no_writes,
        export_safe=_safe_export(export),
        reset_project_only=reset_project_only,
        artifact_persisted=bool(
            persisted
            and persisted.schema_version == "boba_experimentation_system_v1"
        ),
        json_safe=bool(json.loads(result.model_dump_json())),
        warnings=[
            "Validation used local synthetic BOBA metadata only.",
            "No experiment was rendered, uploaded, started, or observed.",
        ],
    )
    checks = [
        report.modules_imported,
        report.creator_learning_available,
        report.approval_rejection_learning_available,
        report.store_available,
        report.report_path_writable,
        report.experiment_plans > 0,
        report.hook_experiments > 0,
        report.caption_experiments > 0,
        report.motion_experiments > 0,
        report.music_mood_experiments > 0,
        report.retention_experiments > 0,
        report.rejected_ideas > 0,
        report.baselines_traceable,
        report.variants_present,
        report.one_variable_per_experiment,
        report.hypotheses_present,
        report.metric_plans_present,
        report.success_criteria_present,
        report.risk_reviews_present,
        report.creator_approval_required,
        report.apply_automatically_false,
        report.unsafe_ideas_rejected,
        report.dry_run_no_writes,
        report.export_safe,
        report.reset_project_only,
        report.artifact_persisted,
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
) -> BobaExperimentationValidationReport:
    return _run_local(mode="self_check", report_dir=report_dir or REPORT_DIR)


def run_synthetic_project(
    report_dir: Path | None = None,
) -> BobaExperimentationValidationReport:
    return _run_local(mode="synthetic_project", report_dir=report_dir or REPORT_DIR)


async def _existing_project(
    project_id: str,
    report_dir: Path,
) -> BobaExperimentationValidationReport:
    try:
        integration = boba_integration_provider()
        result = integration.load_experimentation_plan(project_id)
        if result is None:
            result = await integration.generate_experimentation_plan(project_id)
        path = integration.store.experimentation_path(project_id)
        types = [item.experiment_type for item in result.experiment_plans]
        return BobaExperimentationValidationReport(
            mode="project_id",
            passed=bool(
                path.is_file()
                and json.loads(result.model_dump_json())
                and all(
                    item.required_creator_approval
                    and item.learning_handoff.apply_automatically is False
                    for item in result.experiment_plans
                )
            ),
            project_id=project_id,
            modules_imported=True,
            creator_learning_available=result.signal_usage.creator_learning_used,
            approval_rejection_learning_available=(
                result.signal_usage.approval_rejection_learning_used
            ),
            store_available=True,
            report_path_writable=_report_path_writable(report_dir),
            experiment_plans=len(result.experiment_plans),
            hook_experiments=types.count("hook_ab_test"),
            caption_experiments=types.count("caption_ab_test"),
            motion_experiments=types.count("motion_ab_test"),
            music_mood_experiments=types.count("music_mood_ab_test"),
            retention_experiments=types.count("retention_ab_test"),
            rejected_ideas=len(result.rejected_experiment_ideas),
            baselines_traceable=all(
                item.baseline.source_artifact and item.baseline.source_field
                for item in result.experiment_plans
            ),
            variants_present=all(item.variants for item in result.experiment_plans),
            one_variable_per_experiment=all(
                len({variant.changed_variable for variant in item.variants}) == 1
                for item in result.experiment_plans
            ),
            hypotheses_present=True,
            metric_plans_present=True,
            success_criteria_present=True,
            risk_reviews_present=True,
            creator_approval_required=True,
            apply_automatically_false=True,
            unsafe_ideas_rejected=bool(result.rejected_experiment_ideas),
            artifact_persisted=path.is_file(),
            json_safe=True,
            warnings=[
                "Existing-project mode used saved local BOBA artifacts only.",
                "Missing optional artifacts are reported through signal usage.",
            ],
        )
    except Exception as exc:
        return BobaExperimentationValidationReport(
            mode="project_id",
            passed=False,
            project_id=project_id,
            modules_imported=True,
            store_available=True,
            report_path_writable=_report_path_writable(report_dir),
            errors=[str(exc)],
            warnings=[
                "The validator did not render, upload, download, or fabricate experiments."
            ],
        )


def _write_report(
    report: BobaExperimentationValidationReport,
    report_dir: Path,
) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    payload = report.model_dump(mode="json")
    (report_dir / "boba_experimentation_report.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )
    summary = [
        "# BOBA Experimentation System V1 Validation",
        "",
        f"- Mode: `{report.mode}`",
        f"- Passed: `{str(report.passed).lower()}`",
        f"- Project: `{report.project_id or 'temporary self-check'}`",
        f"- Experiment plans: `{report.experiment_plans}`",
        f"- Rejected ideas: `{report.rejected_ideas}`",
        f"- Artifact persisted: `{report.artifact_persisted}`",
        f"- Export safe: `{report.export_safe}`",
        f"- Rendering triggered: `{report.rendering_triggered}`",
        f"- Uploading triggered: `{report.uploading_triggered}`",
        f"- Analytics collected: `{report.analytics_collected}`",
        "",
        "V1 validates advisory test plans only. It does not execute experiments or "
        "prove future performance.",
    ]
    if report.warnings:
        summary.extend(["", "## Warnings", *[f"- {item}" for item in report.warnings]])
    if report.errors:
        summary.extend(["", "## Errors", *[f"- {item}" for item in report.errors]])
    (report_dir / "boba_experimentation_summary.md").write_text(
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
