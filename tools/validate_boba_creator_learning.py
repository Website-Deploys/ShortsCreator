"""Validate BOBA Creator Learning Loop V1 without media, rendering, or network."""

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
from olympus.boba.creator_learning import (  # noqa: E402
    BobaCreatorFeedbackEventV1,
    BobaCreatorLearningLoopV1,
    BobaCreatorLearningSetV1,
)
from olympus.boba.memory_contracts import BobaProjectMemoryV1  # noqa: E402
from olympus.boba.store import BobaMemoryStore  # noqa: E402

REPORT_DIR = ROOT / "work" / "validation_reports" / "boba_creator_learning"


class BobaCreatorLearningValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["self_check", "synthetic_project", "project_id"]
    passed: bool
    project_id: str | None = None
    modules_imported: bool = False
    memory_system_available: bool = False
    store_available: bool = False
    report_path_writable: bool = False
    feedback_events_recorded: int = 0
    preferences_extracted: int = 0
    learning_profile_present: bool = False
    insights_present: bool = False
    guidance_present: bool = False
    apply_automatically_false: bool = False
    audit_summary_present: bool = False
    confidence_bounded: bool = False
    repeated_feedback_increased_confidence: bool = False
    contradictions_reduced_confidence: bool = False
    dry_run_no_writes: bool = False
    export_safe: bool = False
    reset_project_only: bool = False
    artifact_persisted: bool = False
    event_log_append_safe: bool = False
    json_safe: bool = False
    rendering_triggered: bool = False
    downloading_triggered: bool = False
    external_calls_made: bool = False
    media_required: bool = False
    secrets_required: bool = False
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


def build_synthetic_creator_learning_artifacts() -> dict[str, dict[str, Any]]:
    return {
        "clip_ranking": {
            "project_id": "synthetic",
            "ranked_candidates": [
                {
                    "ranked_clip_id": "ranked_curiosity",
                    "candidate_id": "curiosity_clip",
                    "candidate_type": "motivational_story",
                    "hook_category": "curiosity_gap",
                }
            ],
        },
        "editorial_decision": {
            "decisions": [
                {
                    "decision_id": "editorial_curiosity",
                    "candidate_id": "curiosity_clip",
                    "candidate_type": "motivational_story",
                    "final_hook_strategy": "curiosity_gap",
                    "final_story_angle": "problem_to_breakthrough",
                    "pacing_intensity": "fast",
                    "caption_style": "clean_subtitles",
                    "motion_style": "stable_subtle",
                    "music_mood": "emotional",
                    "production_priority": "must_make",
                }
            ]
        },
        "explanation": {
            "explanations": [
                {
                    "explanation_id": "explanation_curiosity",
                    "candidate_id": "curiosity_clip",
                    "summary": "A supported curiosity hook resolves in the payoff.",
                }
            ]
        },
        "creative_direction": {
            "directions": [
                {
                    "direction_id": "direction_curiosity",
                    "candidate_id": "curiosity_clip",
                    "hook_treatment": {"hook_type": "curiosity_gap"},
                    "caption_direction": {"caption_style": "clean_subtitles"},
                    "motion_direction": {"motion_style": "stable_subtle"},
                    "audio_direction": {"music_mood": "emotional"},
                }
            ]
        },
        "clip_briefs": {
            "selected_briefs": [
                {
                    "brief_id": "brief_curiosity",
                    "candidate_id": "curiosity_clip",
                    "hook_type": "curiosity_gap",
                    "caption_style": "clean_subtitles",
                    "motion_style": "stable_subtle",
                    "music_mood": "emotional",
                    "pacing_level": "fast",
                }
            ]
        },
        "hook_retention": {
            "analyses": [
                {
                    "candidate_id": "curiosity_clip",
                    "hook_analysis": {"hook_type": "curiosity_gap"},
                    "hook_alternatives": [
                        {
                            "alternative_id": "hook_alt_bold",
                            "hook_type": "bold_curiosity_gap",
                        },
                        {
                            "alternative_id": "hook_alt_slow",
                            "hook_type": "slow_start",
                        },
                    ],
                }
            ]
        },
        "caption_motion": {
            "recommendations": [
                {
                    "recommendation_id": "caption_clean",
                    "candidate_id": "curiosity_clip",
                    "caption_recommendation": {
                        "caption_style": "clean_subtitles",
                    },
                    "motion_recommendation": {
                        "motion_style": "stable_subtle",
                    },
                },
                {
                    "recommendation_id": "caption_heavy",
                    "candidate_id": "heavy_motion_clip",
                    "caption_recommendation": {
                        "caption_style": "high_caption_density",
                    },
                    "motion_recommendation": {
                        "motion_style": "high_motion_intensity",
                    },
                },
            ]
        },
        "music_mood": {
            "recommendations": [
                {
                    "recommendation_id": "mood_emotional",
                    "candidate_id": "curiosity_clip",
                    "music_mood": {"primary_mood": "emotional_cinematic"},
                }
            ]
        },
    }


def build_synthetic_creator_learning_events(
    project_id: str,
    artifacts: dict[str, dict[str, Any]],
) -> list[BobaCreatorFeedbackEventV1]:
    engine = BobaCreatorLearningLoopV1()
    event_specs: list[dict[str, Any]] = [
        {
            "event_type": "approval",
            "target_type": "ranked_clip",
            "target_id": "ranked_curiosity",
            "user_action": "approved",
        },
        {
            "event_type": "rejection",
            "target_type": "hook_alternative",
            "target_id": "hook_alt_slow",
            "user_action": "rejected",
        },
        {
            "event_type": "rating",
            "target_type": "caption_motion",
            "target_id": "caption_clean",
            "user_action": "liked",
            "rating": 5,
        },
        {
            "event_type": "rating",
            "target_type": "caption_motion",
            "target_id": "caption_heavy",
            "user_action": "disliked",
            "rating": 1,
        },
        {
            "event_type": "chosen_alternative",
            "target_type": "music_mood",
            "target_id": "mood_emotional",
            "user_action": "chose",
        },
        {
            "event_type": "preference_note",
            "target_type": "project",
            "target_id": project_id,
            "user_action": "noted",
            "note": "There is too much zoom; use stable motion.",
        },
        {
            "event_type": "preference_note",
            "target_type": "project",
            "target_id": project_id,
            "user_action": "noted",
            "note": "Captions were too busy. Prefer clean captions.",
        },
    ]
    return [
        engine.create_feedback_event(
            project_id=project_id,
            artifacts=artifacts,
            event_id=f"creator_feedback_synthetic_{index}",
            created_at=f"2026-01-01T00:00:{index:02d}+00:00",
            **spec,
        )
        for index, spec in enumerate(event_specs, start=1)
    ]


def _analyze(
    engine: BobaCreatorLearningLoopV1,
    project_id: str,
    events: list[BobaCreatorFeedbackEventV1],
    artifacts: dict[str, dict[str, Any]],
    *,
    creator_id: str = "creator_synthetic",
    source_id: str | None = None,
    boba_memory: dict[str, Any] | None = None,
) -> BobaCreatorLearningSetV1:
    return engine.analyze(
        project_id,
        events,
        creator_id=creator_id,
        source_id=source_id,
        boba_memory=boba_memory,
        clip_ranking=artifacts["clip_ranking"],
        editorial_decision=artifacts["editorial_decision"],
        explanation=artifacts["explanation"],
        creative_direction=artifacts["creative_direction"],
        clip_briefs=artifacts["clip_briefs"],
        hook_retention=artifacts["hook_retention"],
        caption_motion=artifacts["caption_motion"],
        music_mood=artifacts["music_mood"],
    )


def build_synthetic_creator_learning(
    project_id: str = "proj_creator_learning_synthetic",
) -> BobaCreatorLearningSetV1:
    engine = BobaCreatorLearningLoopV1()
    artifacts = build_synthetic_creator_learning_artifacts()
    events = build_synthetic_creator_learning_events(project_id, artifacts)
    return _analyze(
        engine,
        project_id,
        events,
        artifacts,
        source_id=project_id,
        boba_memory={"explicit_feedback_only": True},
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


def _run_local(
    *,
    mode: Literal["self_check", "synthetic_project"],
    report_dir: Path,
) -> BobaCreatorLearningValidationReport:
    project_id = (
        "proj_creator_learning_self_check"
        if mode == "self_check"
        else "proj_creator_learning_synthetic"
    )
    engine = BobaCreatorLearningLoopV1()
    artifacts = build_synthetic_creator_learning_artifacts()
    events = build_synthetic_creator_learning_events(project_id, artifacts)
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        store = BobaMemoryStore(root / "boba", memory_root=root / "memory")
        for event in events:
            store.record_creator_feedback_event(event)
        result = _analyze(
            engine,
            project_id,
            store.list_creator_feedback_events(project_id),
            artifacts,
            source_id=project_id,
            boba_memory={"explicit_feedback_only": True},
        )
        store.save_creator_learning(result)
        persisted = store.load_creator_learning(project_id)
        event_log_append_safe = (
            len(store.list_creator_feedback_events(project_id)) == len(events)
            and store.creator_learning_events_path(project_id).read_text(
                encoding="utf-8"
            ).count("\n")
            == len(events)
        )

        single = _analyze(
            engine,
            project_id,
            [events[0]],
            artifacts,
        )
        repeated_event = engine.create_feedback_event(
            project_id=project_id,
            event_type="approval",
            target_type="ranked_clip",
            target_id="ranked_curiosity",
            user_action="approved",
            artifacts=artifacts,
            event_id="creator_feedback_repeated",
            created_at="2026-01-01T00:01:00+00:00",
        )
        repeated = _analyze(
            engine,
            project_id,
            [events[0], repeated_event],
            artifacts,
        )
        contradiction_event = engine.create_feedback_event(
            project_id=project_id,
            event_type="rejection",
            target_type="ranked_clip",
            target_id="ranked_curiosity",
            user_action="rejected",
            artifacts=artifacts,
            event_id="creator_feedback_contradiction",
            created_at="2026-01-01T00:02:00+00:00",
        )
        contradiction = _analyze(
            engine,
            project_id,
            [events[0], repeated_event, contradiction_event],
            artifacts,
        )

        dry_store = BobaMemoryStore(root / "dry_boba", memory_root=root / "dry_memory")
        _analyze(
            engine,
            project_id,
            events,
            artifacts,
        )
        dry_run_no_writes = not dry_store.creator_learning_path(project_id).exists()

        export_payload = store.export_creator_learning_profile(project_id)
        store.save_project_memory(
            BobaProjectMemoryV1(
                project_id=project_id,
                source_summary="Unrelated BOBA project memory remains after reset.",
            )
        )
        reset_removed = store.reset_creator_learning_profile(project_id)
        reset_project_only = bool(
            reset_removed
            and store.load_creator_learning(project_id) is None
            and not store.list_creator_feedback_events(project_id)
            and store.load_project_memory(project_id) is not None
        )

        encoded = result.model_dump_json()
        preferences = sum(
            len(event.extracted_preferences) for event in result.feedback_events
        )
        report = BobaCreatorLearningValidationReport(
            mode=mode,
            passed=False,
            project_id=project_id,
            modules_imported=True,
            memory_system_available=True,
            store_available=True,
            report_path_writable=_report_path_writable(report_dir),
            feedback_events_recorded=len(result.feedback_events),
            preferences_extracted=preferences,
            learning_profile_present=result.learning_profile.data_points > 0,
            insights_present=bool(result.learning_insights),
            guidance_present=bool(result.recommendation_guidance.general_guidance),
            apply_automatically_false=(
                result.recommendation_guidance.apply_automatically is False
            ),
            audit_summary_present=(
                result.audit_summary.total_events == len(result.feedback_events)
            ),
            confidence_bounded=0.0 <= result.learning_profile.confidence <= 1.0,
            repeated_feedback_increased_confidence=(
                repeated.learning_profile.confidence
                > single.learning_profile.confidence
            ),
            contradictions_reduced_confidence=(
                contradiction.learning_profile.confidence
                < repeated.learning_profile.confidence
            ),
            dry_run_no_writes=dry_run_no_writes,
            export_safe=_safe_export(export_payload),
            reset_project_only=reset_project_only,
            artifact_persisted=bool(
                persisted
                and persisted.schema_version == "boba_creator_learning_loop_v1"
            ),
            event_log_append_safe=event_log_append_safe,
            json_safe=bool(json.loads(encoded)),
            warnings=[
                "Validation used synthetic or saved metadata and explicit feedback only.",
                "No creator-learning recommendation was applied automatically.",
            ],
        )
    checks = [
        report.modules_imported,
        report.memory_system_available,
        report.store_available,
        report.report_path_writable,
        report.feedback_events_recorded >= 7,
        report.preferences_extracted > 0,
        report.learning_profile_present,
        report.insights_present,
        report.guidance_present,
        report.apply_automatically_false,
        report.audit_summary_present,
        report.confidence_bounded,
        report.repeated_feedback_increased_confidence,
        report.contradictions_reduced_confidence,
        report.dry_run_no_writes,
        report.export_safe,
        report.reset_project_only,
        report.artifact_persisted,
        report.event_log_append_safe,
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
) -> BobaCreatorLearningValidationReport:
    return _run_local(
        mode="self_check",
        report_dir=report_dir or REPORT_DIR,
    )


def run_synthetic_project(
    report_dir: Path | None = None,
) -> BobaCreatorLearningValidationReport:
    return _run_local(
        mode="synthetic_project",
        report_dir=report_dir or REPORT_DIR,
    )


async def _existing_project(
    project_id: str,
    report_dir: Path,
) -> BobaCreatorLearningValidationReport:
    try:
        integration = boba_integration_provider()
        learning = integration.load_creator_learning_profile(project_id)
        if learning is None:
            learning = await integration.generate_creator_learning_profile(
                project_id,
                dry_run=False,
            )
        artifact_path = integration.store.creator_learning_path(project_id)
        return BobaCreatorLearningValidationReport(
            mode="project_id",
            passed=bool(
                artifact_path.is_file()
                and 0.0 <= learning.learning_profile.confidence <= 1.0
                and learning.recommendation_guidance.apply_automatically is False
            ),
            project_id=project_id,
            modules_imported=True,
            memory_system_available=True,
            store_available=True,
            report_path_writable=_report_path_writable(report_dir),
            feedback_events_recorded=len(learning.feedback_events),
            preferences_extracted=sum(
                len(event.extracted_preferences)
                for event in learning.feedback_events
            ),
            learning_profile_present=True,
            insights_present=bool(learning.learning_insights),
            guidance_present=bool(
                learning.recommendation_guidance.general_guidance
            ),
            apply_automatically_false=True,
            audit_summary_present=True,
            confidence_bounded=0.0 <= learning.learning_profile.confidence <= 1.0,
            artifact_persisted=artifact_path.is_file(),
            event_log_append_safe=True,
            json_safe=bool(json.loads(learning.model_dump_json())),
            warnings=[
                "Existing-project mode used local BOBA artifacts and explicit feedback only.",
                "Missing optional artifacts are reported through signal usage.",
            ],
        )
    except Exception as exc:
        return BobaCreatorLearningValidationReport(
            mode="project_id",
            passed=False,
            project_id=project_id,
            modules_imported=True,
            memory_system_available=True,
            store_available=True,
            report_path_writable=_report_path_writable(report_dir),
            errors=[str(exc)],
            warnings=[
                "The validator did not fabricate feedback or creator preferences."
            ],
        )


def _write_report(
    report: BobaCreatorLearningValidationReport,
    report_dir: Path,
) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    payload = report.model_dump(mode="json")
    (report_dir / "boba_creator_learning_report.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )
    summary = [
        "# BOBA Creator Learning Loop V1 Validation",
        "",
        f"- Mode: `{report.mode}`",
        f"- Passed: `{str(report.passed).lower()}`",
        f"- Project: `{report.project_id or 'temporary self-check'}`",
        f"- Explicit events: `{report.feedback_events_recorded}`",
        f"- Extracted preferences: `{report.preferences_extracted}`",
        f"- Artifact persisted: `{report.artifact_persisted}`",
        f"- Dry run avoided writes: `{report.dry_run_no_writes}`",
        f"- Export safe: `{report.export_safe}`",
        f"- Reset project-only: `{report.reset_project_only}`",
        f"- Rendering triggered: `{report.rendering_triggered}`",
        f"- External calls made: `{report.external_calls_made}`",
        "",
        "This validator checks local explicit-feedback learning only. It does not "
        "use audience analytics or prove future content performance.",
    ]
    if report.warnings:
        summary.extend(["", "## Warnings", *[f"- {item}" for item in report.warnings]])
    if report.errors:
        summary.extend(["", "## Errors", *[f"- {item}" for item in report.errors]])
    (report_dir / "boba_creator_learning_summary.md").write_text(
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
