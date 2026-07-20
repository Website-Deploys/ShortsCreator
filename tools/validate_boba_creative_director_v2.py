"""Validate BOBA Creative Director V2 without media or external services."""

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
from olympus.boba import (  # noqa: E402
    BobaCreativeDirectionSetV2,
    BobaCreativeDirectorV2Engine,
    BobaExplanationEngine,
    BobaMemoryStore,
    BobaProjectMemoryV1,
)
from olympus.boba.clip_discovery import BobaCandidateClipDiscoveryV1  # noqa: E402
from olympus.boba.clip_ranking import BobaClipRankingV1  # noqa: E402
from olympus.boba.editorial_decision import BobaEditorialDecisionSetV1  # noqa: E402
from olympus.boba.explanation import BobaExplanationSetV1  # noqa: E402
from olympus.boba.whole_video import BobaWholeVideoUnderstandingV1  # noqa: E402
from tools.validate_boba_explanation_engine import (  # noqa: E402
    build_synthetic_explanation_inputs,
)

REPORT_DIR = ROOT / "work" / "validation_reports" / "boba_creative_director_v2"


class BobaCreativeDirectorV2ValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["self_check", "synthetic_project", "project_id"]
    passed: bool
    project_id: str | None = None
    project_direction_present: bool = False
    clip_direction_count: int = 0
    opening_plans_present: bool = False
    hook_treatments_present: bool = False
    pacing_maps_present: bool = False
    caption_directions_present: bool = False
    motion_directions_present: bool = False
    audio_mood_only: bool = False
    retention_plans_present: bool = False
    emotional_arcs_present: bool = False
    quality_scores_present: bool = False
    warnings_preserved: bool = False
    limitations_preserved: bool = False
    artifact_persisted: bool = False
    json_safe: bool = False
    raw_transcript_stored: bool = False
    report_path_writable: bool = False
    rendering_triggered: bool = False
    downloading_triggered: bool = False
    external_calls_made: bool = False
    media_required: bool = False
    secrets_required: bool = False
    direction_examples: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


def build_synthetic_creative_direction_inputs(
    project_id: str,
) -> tuple[
    BobaWholeVideoUnderstandingV1,
    BobaCandidateClipDiscoveryV1,
    BobaClipRankingV1,
    BobaEditorialDecisionSetV1,
    BobaExplanationSetV1,
    BobaProjectMemoryV1,
    dict[str, Any],
]:
    understanding, discovery, ranking, decisions, briefs, signals = (
        build_synthetic_explanation_inputs(project_id)
    )
    adjusted = []
    for decision in decisions.decisions:
        if decision.candidate_id == "must_make_truth":
            decision = decision.model_copy(
                update={
                    "final_story_angle": (
                        "A motivating transformation reveals the practical system "
                        "behind the result."
                    ),
                    "final_hook_strategy": "motivational_payoff",
                    "opening_line_direction": (
                        "Lead with the transformation, then reveal the rule that "
                        "made it possible."
                    ),
                    "pacing_intensity": "aggressive",
                    "music_mood": "motivational",
                    "sfx_intensity": "light",
                }
            )
        elif decision.candidate_id == "strong_educational":
            decision = decision.model_copy(
                update={
                    "caption_style": "keyword_highlight",
                    "music_mood": "educational",
                }
            )
        elif decision.candidate_id == "strong_emotional":
            decision = decision.model_copy(
                update={
                    "final_hook_strategy": "emotional_reveal",
                    "caption_style": "emotional_emphasis",
                    "motion_style": "subtle_zoom",
                    "music_mood": "cinematic",
                }
            )
        adjusted.append(decision)
    decisions = decisions.model_copy(update={"decisions": adjusted})
    signals.update(
        {
            "analysis_signals_v2": {
                "speech": {"available": True},
                "visual": {"available": True},
                "face": {"available": True},
                "speaker": {"available": True},
            },
            "transcript_available": True,
            "face_signals_available": True,
            "speaker_signals_available": True,
            "visual_signals_available": True,
            "editorial_decisions": decisions.model_dump(mode="json"),
        }
    )
    memory = BobaProjectMemoryV1(
        project_id=project_id,
        source_summary="Creator prefers clear practical payoffs and restrained motion.",
        main_topics=["systems", "education", "teamwork"],
        selected_clip_ids=list(decisions.selected_clip_ids),
        known_limitations=["Synthetic local metadata only."],
    )
    explanations = BobaExplanationEngine().explain_from_signals(
        project_id,
        signals,
        whole_video_understanding=understanding,
        candidate_discovery=discovery,
        clip_ranking=ranking,
        editorial_decisions=decisions,
        creative_briefs=briefs,
        memory=memory,
    )
    signals["explanations"] = explanations.model_dump(mode="json")
    return (
        understanding,
        discovery,
        ranking,
        decisions,
        explanations,
        memory,
        signals,
    )


def build_synthetic_creative_direction(
    project_id: str,
) -> BobaCreativeDirectionSetV2:
    (
        understanding,
        discovery,
        ranking,
        decisions,
        explanations,
        memory,
        signals,
    ) = build_synthetic_creative_direction_inputs(project_id)
    return BobaCreativeDirectorV2Engine().direct_from_signals(
        project_id,
        signals,
        editorial_decisions=decisions,
        clip_ranking=ranking,
        candidate_discovery=discovery,
        whole_video_understanding=understanding,
        explanations=explanations,
        memory=memory,
    )


def _evaluate(
    direction: BobaCreativeDirectionSetV2,
    *,
    mode: Literal["self_check", "synthetic_project", "project_id"],
    artifact_path: Path | None,
) -> BobaCreativeDirectorV2ValidationReport:
    payload = direction.model_dump(mode="json")
    encoded = json.dumps(payload)
    clips = direction.clip_directions
    project_present = bool(
        direction.project_direction.overall_style
        and direction.project_direction.pacing_philosophy
        and direction.project_direction.audio_philosophy
    )
    opening = bool(clips) and all(
        item.opening_three_second_plan.what_viewer_sees_first
        and item.opening_three_second_plan.caption_implication
        and item.opening_three_second_plan.curiosity_gap
        for item in clips
    )
    hooks = bool(clips) and all(
        item.hook_treatment.opening_line_direction
        and item.hook_treatment.pattern_interrupt
        for item in clips
    )
    pacing = bool(clips) and all(
        item.pacing_map.first_3_seconds and item.pacing_map.payoff_section
        for item in clips
    )
    captions = bool(clips) and all(
        item.caption_direction.style and item.caption_direction.rhythm for item in clips
    )
    motion = bool(clips) and all(
        item.motion_direction.style and item.motion_direction.stable_moments
        for item in clips
    )
    audio = bool(clips) and all(
        set(item.audio_direction.model_dump(mode="json"))
        == {
            "music_mood",
            "sfx_intensity",
            "ducking_guidance",
            "silence_notes",
            "speech_clarity_notes",
            "warnings",
        }
        and "/" not in item.audio_direction.music_mood
        and "\\" not in item.audio_direction.music_mood
        for item in clips
    )
    retention = bool(clips) and all(
        item.retention_plan.opening_hook and item.retention_plan.payoff_delivery
        for item in clips
    )
    emotional = bool(clips) and all(
        item.emotional_arc.starting_emotion and item.emotional_arc.payoff_emotion
        for item in clips
    )
    quality = bool(clips) and all(
        0.0 <= item.creative_quality_score.overall_confidence <= 100.0
        for item in clips
    )
    persisted = artifact_path is not None and artifact_path.is_file()
    json_safe = bool(json.loads(encoded))
    raw_transcript_stored = "transcript_segments" in encoded
    warnings_preserved = bool(direction.warnings) or any(
        item.warnings
        or item.motion_direction.safety_warnings
        or item.audio_direction.warnings
        for item in clips
    )
    limitations_preserved = bool(direction.limitations)
    passed = bool(
        project_present
        and clips
        and opening
        and hooks
        and pacing
        and captions
        and motion
        and audio
        and retention
        and emotional
        and quality
        and persisted
        and json_safe
        and not raw_transcript_stored
    )
    return BobaCreativeDirectorV2ValidationReport(
        mode=mode,
        passed=passed,
        project_id=direction.project_id,
        project_direction_present=project_present,
        clip_direction_count=len(clips),
        opening_plans_present=opening,
        hook_treatments_present=hooks,
        pacing_maps_present=pacing,
        caption_directions_present=captions,
        motion_directions_present=motion,
        audio_mood_only=audio,
        retention_plans_present=retention,
        emotional_arcs_present=emotional,
        quality_scores_present=quality,
        warnings_preserved=warnings_preserved,
        limitations_preserved=limitations_preserved,
        artifact_persisted=persisted,
        json_safe=json_safe,
        raw_transcript_stored=raw_transcript_stored,
        direction_examples=[
            {
                "candidate_id": item.candidate_id,
                "hook_type": item.hook_treatment.hook_type,
                "pacing": item.pacing_map.pacing_intensity,
                "caption_style": item.caption_direction.style,
                "motion_style": item.motion_direction.style,
                "music_mood": item.audio_direction.music_mood,
                "quality": item.creative_quality_score.overall_confidence,
            }
            for item in clips[:8]
        ],
        warnings=[
            "Validation used bounded local metadata only; no media was read, "
            "edited, downloaded, or rendered.",
            "Creative quality scores are advisory and do not predict audience performance.",
            *direction.limitations[:4],
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
) -> BobaCreativeDirectorV2ValidationReport:
    project_id = (
        "proj_creative_director_v2_self_check"
        if mode == "self_check"
        else "proj_creative_director_v2_synthetic"
    )
    with TemporaryDirectory() as temporary:
        store = BobaMemoryStore(Path(temporary) / "boba")
        direction = store.save_creative_direction_v2(
            build_synthetic_creative_direction(project_id)
        )
        report = _evaluate(
            direction,
            mode=mode,
            artifact_path=store.creative_direction_v2_path(project_id),
        )
    report.report_path_writable = _report_path_writable()
    report.passed = report.passed and report.report_path_writable
    if mode == "self_check":
        report.warnings.append(
            "Self-check required no network, media, downloader, renderer, or secrets."
        )
    return report


async def _existing_project(
    project_id: str,
) -> BobaCreativeDirectorV2ValidationReport:
    try:
        integration = boba_integration_provider()
        direction = integration.store.load_creative_direction_v2(project_id)
        if direction is None:
            direction = await integration.generate_creative_direction_v2(project_id)
        report = _evaluate(
            direction,
            mode="project_id",
            artifact_path=integration.store.creative_direction_v2_path(project_id),
        )
        report.report_path_writable = _report_path_writable()
        report.passed = report.passed and report.report_path_writable
        report.warnings.append(
            "Existing-project mode used saved local BOBA artifacts only and did not "
            "render or download."
        )
        return report
    except Exception as exc:
        return BobaCreativeDirectorV2ValidationReport(
            mode="project_id",
            passed=False,
            project_id=project_id,
            report_path_writable=_report_path_writable(),
            errors=[str(exc)],
            warnings=[
                "Missing artifacts were reported rather than replaced with "
                "fabricated creative evidence."
            ],
        )


def _write_report(report: BobaCreativeDirectorV2ValidationReport) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    payload = report.model_dump(mode="json")
    (REPORT_DIR / "boba_creative_director_v2_report.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    summary = [
        "# BOBA Creative Director V2 Validation",
        "",
        f"- Mode: `{report.mode}`",
        f"- Passed: `{str(report.passed).lower()}`",
        f"- Project: `{report.project_id or 'temporary self-check'}`",
        f"- Clip directions: `{report.clip_direction_count}`",
        f"- Opening plans present: `{report.opening_plans_present}`",
        f"- Audio mood only: `{report.audio_mood_only}`",
        f"- Artifact persisted: `{report.artifact_persisted}`",
        f"- Rendering triggered: `{report.rendering_triggered}`",
        f"- External calls made: `{report.external_calls_made}`",
        "",
        "This validator checks advisory metadata only. It does not establish rendering, "
        "copyright safety, production readiness, or audience performance.",
    ]
    if report.warnings:
        summary.extend(["", "## Warnings", *[f"- {item}" for item in report.warnings]])
    if report.errors:
        summary.extend(["", "## Errors", *[f"- {item}" for item in report.errors]])
    (REPORT_DIR / "boba_creative_director_v2_summary.md").write_text(
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
