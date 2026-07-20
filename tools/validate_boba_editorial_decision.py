"""Validate BOBA Editorial Decision Engine V1 without media or external services."""

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
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from olympus.api.dependencies import boba_integration_provider  # noqa: E402
from olympus.boba import (  # noqa: E402
    BobaBoundarySuggestionV1,
    BobaCandidateClipDiscoveryV1,
    BobaCandidateClipV1,
    BobaCandidateDiscoverySignalUsageV1,
    BobaCandidateDiversitySummaryV1,
    BobaCandidateEvidenceV1,
    BobaClipScoreBreakdownV1,
    BobaEditingInstructionPacketV1,
    BobaEditorialDecisionEngine,
    BobaEditorialDecisionSetV1,
    BobaEditorialRiskReviewV1,
    BobaMemoryStore,
    BobaRankedClipV1,
    BobaRankingDiversitySummaryV1,
    BobaRankingSignalUsageV1,
)
from olympus.boba.clip_ranking import BobaClipRankingV1  # noqa: E402
from olympus.boba.creative_director import BobaCreativeBriefV1  # noqa: E402

REPORT_DIR = ROOT / "work" / "validation_reports" / "boba_editorial_decision"


class BobaEditorialDecisionValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["self_check", "synthetic_project", "project_id"]
    passed: bool
    project_id: str | None = None
    decision_count: int = 0
    selected_count: int = 0
    rejected_count: int = 0
    ready_for_render_count: int = 0
    needs_revision_count: int = 0
    blocked_count: int = 0
    selection_target_valid: bool = False
    blocked_not_selected: bool = False
    rights_risk_handled: bool = False
    music_moods_safe: bool = False
    instruction_packets_present: bool = False
    risk_reviews_present: bool = False
    artifact_persisted: bool = False
    json_safe: bool = False
    report_path_writable: bool = False
    rendering_triggered: bool = False
    downloading_triggered: bool = False
    external_calls_made: bool = False
    media_required: bool = False
    secrets_required: bool = False
    decisions: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


def _breakdown(
    score: float,
    *,
    hook: float = 82.0,
    payoff: float = 82.0,
    context: float = 12.0,
    emotional: float = 65.0,
    pacing: float = 76.0,
    rights: float = 0.0,
    repetition: float = 4.0,
    overlap: float = 0.0,
) -> BobaClipScoreBreakdownV1:
    return BobaClipScoreBreakdownV1(
        hook_score=hook,
        payoff_score=payoff,
        standalone_score=max(0.0, 100.0 - context),
        emotional_score=emotional,
        clarity_score=88.0,
        novelty_score=78.0,
        pacing_score=pacing,
        retention_score=80.0,
        context_risk_score=context,
        repetition_penalty=repetition,
        overlap_penalty=overlap,
        rights_safety_penalty=rights,
        memory_alignment_score=4.0,
        final_score=score,
    )


def _ranked(
    project_id: str,
    candidate_id: str,
    rank: int,
    tier: str,
    score: float,
    *,
    start: float,
    candidate_type: str,
    hook_idea: str,
    story_angle: str,
    topic: str,
    emotion: str = "unknown",
    breakdown: BobaClipScoreBreakdownV1 | None = None,
    warnings: list[str] | None = None,
) -> BobaRankedClipV1:
    priority = {
        "must_make": "immediate",
        "strong_candidate": "high",
        "backup_candidate": "medium",
        "needs_revision": "low",
        "reject": "do_not_produce",
    }[tier]
    return BobaRankedClipV1.model_validate(
        {
            "candidate_id": candidate_id,
            "project_id": project_id,
            "rank": rank,
            "tier": tier,
            "total_score": score,
            "confidence": 0.9 if score >= 70.0 else 0.68,
            "production_priority": priority,
            "score_breakdown": (breakdown or _breakdown(score)).model_dump(
                mode="json"
            ),
            "ranking_reasons": ["Synthetic deterministic ranking evidence."],
            "risk_warnings": warnings or [],
            "improvement_suggestions": [],
            "source_window": {
                "start_seconds": start,
                "end_seconds": start + 32.0,
                "duration_seconds": 32.0,
            },
            "candidate_type": candidate_type,
            "suggested_title": candidate_id.replace("_", " ").title(),
            "hook_idea": hook_idea,
            "story_angle": story_angle,
            "source_topic": topic,
            "emotion_label": emotion,
        }
    )


def _candidate(ranked: BobaRankedClipV1) -> BobaCandidateClipV1:
    start = ranked.source_window["start_seconds"]
    end = ranked.source_window["end_seconds"]
    context_needed = ranked.score_breakdown.context_risk_score >= 50.0
    payoff_present = ranked.score_breakdown.payoff_score >= 55.0
    return BobaCandidateClipV1(
        candidate_id=ranked.candidate_id,
        project_id=ranked.project_id,
        start_seconds=start,
        end_seconds=end,
        duration_seconds=end - start,
        suggested_title=ranked.suggested_title,
        hook_idea=ranked.hook_idea,
        story_angle=ranked.story_angle,
        candidate_type=ranked.candidate_type,
        discovery_reason="Synthetic local editorial-decision evidence.",
        confidence=ranked.confidence,
        standalone_score=ranked.score_breakdown.standalone_score / 100.0,
        setup_required=context_needed,
        payoff_present=payoff_present,
        context_needed=context_needed,
        source_topic=ranked.source_topic,
        emotion_label=ranked.emotion_label,
        virality_cues=["hook", "payoff"] if payoff_present else ["hook"],
        boundary_suggestion=BobaBoundarySuggestionV1(
            recommended_start_seconds=start,
            recommended_end_seconds=end,
            abrupt_start_warning=context_needed,
            abrupt_end_warning=not payoff_present,
            reason="Synthetic local source boundary.",
        ),
        evidence=BobaCandidateEvidenceV1(
            transcript_snippets=[ranked.hook_idea],
            source_signals=["synthetic_local_metadata"],
            topic_segment_ids=[f"topic_{ranked.source_topic}"],
            emotional_beat_ids=[f"emotion_{ranked.emotion_label}"],
            context_payoff_link_ids=["payoff"] if payoff_present else [],
            section_score_ids=[f"section_{ranked.candidate_id}"],
            virality_reasons=["Synthetic deterministic cue."],
        ),
        warnings=list(ranked.risk_warnings),
    )


def build_synthetic_inputs(
    project_id: str,
) -> tuple[
    BobaClipRankingV1,
    BobaCandidateClipDiscoveryV1,
    list[BobaCreativeBriefV1],
]:
    ranked = [
        _ranked(
            project_id,
            "must_make_truth",
            1,
            "must_make",
            92.0,
            start=0.0,
            candidate_type="controversial_moment",
            hook_idea="The truth about why this system finally works",
            story_angle="A hidden problem resolves into one practical system.",
            topic="systems",
        ),
        _ranked(
            project_id,
            "strong_educational",
            2,
            "strong_candidate",
            84.0,
            start=40.0,
            candidate_type="educational_moment",
            hook_idea="How one rule removes five bad decisions",
            story_angle="Teach one clear rule and its immediate benefit.",
            topic="education",
        ),
        _ranked(
            project_id,
            "strong_emotional",
            3,
            "strong_candidate",
            81.0,
            start=80.0,
            candidate_type="emotional_beat",
            hook_idea="The emotional reveal changed the entire team",
            story_angle="Build tension before a motivating team reveal.",
            topic="teamwork",
            emotion="triumph",
            breakdown=_breakdown(81.0, emotional=94.0, pacing=86.0),
        ),
        _ranked(
            project_id,
            "backup_practical",
            4,
            "backup_candidate",
            66.0,
            start=120.0,
            candidate_type="explanation_section",
            hook_idea="Why this practical step matters",
            story_angle="Explain one useful practical step.",
            topic="process",
        ),
        _ranked(
            project_id,
            "needs_context",
            5,
            "needs_revision",
            52.0,
            start=160.0,
            candidate_type="story_turn",
            hook_idea="Then the result changed",
            story_angle="A promising turn still depends on earlier context.",
            topic="story",
            breakdown=_breakdown(52.0, hook=50.0, context=68.0),
            warnings=["Missing setup before this source window."],
        ),
        _ranked(
            project_id,
            "reject_fragment",
            6,
            "reject",
            31.0,
            start=200.0,
            candidate_type="unknown",
            hook_idea="Additional details",
            story_angle="An incomplete fragment without a standalone ending.",
            topic="unknown",
            breakdown=_breakdown(31.0, hook=30.0, payoff=28.0, context=88.0),
        ),
        _ranked(
            project_id,
            "rights_risk",
            7,
            "strong_candidate",
            78.0,
            start=240.0,
            candidate_type="hook_moment",
            hook_idea="Why this external moment seems compelling",
            story_angle="A strong moment cannot proceed without rights review.",
            topic="rights",
            breakdown=_breakdown(78.0, rights=95.0),
            warnings=["Source rights are not confirmed."],
        ),
        _ranked(
            project_id,
            "weak_payoff",
            8,
            "strong_candidate",
            74.0,
            start=280.0,
            candidate_type="curiosity_gap",
            hook_idea="Why does this surprising problem happen?",
            story_angle="A strong opening still needs its complete payoff.",
            topic="curiosity",
            breakdown=_breakdown(74.0, payoff=34.0),
            warnings=["The source window ends before a confirmed payoff."],
        ),
    ]
    candidates = [_candidate(item) for item in ranked]
    discovery = BobaCandidateClipDiscoveryV1(
        project_id=project_id,
        source_id=f"uploads/{project_id}/source.mp4",
        video_duration_seconds=340.0,
        summary="Synthetic candidates cover editorial selection, direction, and risk.",
        candidates=candidates,
        rejected_windows=[],
        diversity_summary=BobaCandidateDiversitySummaryV1(
            candidate_count=len(candidates),
            topic_count=len({item.source_topic for item in candidates}),
            emotion_count=len({item.emotion_label for item in candidates}),
            candidate_types=list(dict.fromkeys(item.candidate_type for item in candidates)),
            duplicate_windows_removed=0,
            high_overlap_windows_removed=0,
            warnings=[],
        ),
        signal_usage=BobaCandidateDiscoverySignalUsageV1(
            whole_video_understanding_used=True,
            transcript_used=True,
            analysis_signals_used=True,
            story_used=True,
            virality_used=True,
            planning_used=True,
            memory_used=True,
            fallback_used=False,
            unavailable_signals=[],
            warnings=[],
        ),
        warnings=[],
        limitations=["Synthetic metadata only; no media was used."],
    )
    ranking = BobaClipRankingV1(
        project_id=project_id,
        source_id=discovery.source_id,
        summary="Synthetic ranked candidates for editorial-decision validation.",
        ranked_candidates=ranked,
        recommended_clip_ids=[item.candidate_id for item in ranked[:3]],
        backup_clip_ids=["backup_practical"],
        rejected_clip_ids=["reject_fragment"],
        rejected_candidates=[],
        diversity_summary=BobaRankingDiversitySummaryV1(
            ranked_count=len(ranked),
            recommended_count=3,
            topic_count=8,
            emotion_count=3,
            candidate_type_count=8,
            overlap_penalties_applied=0,
            duplicate_candidates_removed=0,
            diversity_warnings=[],
        ),
        signal_usage=BobaRankingSignalUsageV1(
            candidate_discovery_used=True,
            whole_video_understanding_used=True,
            virality_used=True,
            story_used=True,
            planning_used=True,
            memory_used=True,
            fallback_used=False,
            unavailable_signals=[],
            warnings=[],
        ),
        warnings=[],
        limitations=["Synthetic deterministic ranking metadata."],
    )
    briefs = [
        BobaCreativeBriefV1(
            clip_id="strong_emotional",
            project_id=project_id,
            target_emotion="triumph",
            hook_type="emotional_reveal",
            curiosity_trigger="Hold the team result until the source-supported reveal.",
            story_angle="Tension resolves into a motivating team payoff.",
            recommended_duration_seconds=32.0,
            pacing_level="fast",
            caption_style="emotional emphasis",
            motion_style="punch in",
            music_mood="emotional",
            editing_notes=["Preserve the final resolving phrase."],
            risk_warnings=[],
            why_it_may_work="The emotional turn and payoff are both present in the source.",
            whole_video_understanding_used=True,
            understanding_guidance=["Protect the payoff."],
        )
    ]
    return ranking, discovery, briefs


def _decide(project_id: str) -> BobaEditorialDecisionSetV1:
    ranking, discovery, briefs = build_synthetic_inputs(project_id)
    return BobaEditorialDecisionEngine().decide(
        project_id=project_id,
        clip_ranking=ranking,
        candidate_discovery=discovery,
        whole_video_understanding={
            "section_scores": [
                {
                    "start_seconds": 80.0,
                    "end_seconds": 112.0,
                    "energy_score": 0.9,
                }
            ],
            "emotional_beats": [
                {
                    "start_seconds": 80.0,
                    "end_seconds": 112.0,
                    "intensity": 0.95,
                }
            ],
        },
        creative_briefs=briefs,
        analysis_artifact={"confidence": 0.9, "signals": ["speech", "visual"]},
        story_artifact={
            "micro_stories": [
                {
                    "start": 0.0,
                    "end": 32.0,
                    "story_summary": "A hidden problem resolves into one useful system.",
                }
            ]
        },
        virality_artifact={"hook_score": 0.9, "retention_score": 0.82},
        planning_artifact={
            "selected_plans": [{"start": 0.0, "end": 32.0, "confidence": 0.9}]
        },
        editing_artifact={"timelines": []},
        memory={"source_summary": "Creator prefers keyword captions and stable motion."},
        source_context={
            "source_type": "upload",
            "external_source": False,
            "rights_status": "local_upload",
            "transcript_available": True,
            "face_signals_available": True,
            "speaker_signals_available": True,
            "visual_signals_available": True,
        },
    )


def _evaluate(
    decisions: BobaEditorialDecisionSetV1,
    *,
    mode: Literal["self_check", "synthetic_project", "project_id"],
    artifact_path: Path | None,
    strict_selection: bool,
) -> BobaEditorialDecisionValidationReport:
    encoded = json.dumps(decisions.model_dump(mode="json"))
    blocked = [item for item in decisions.decisions if item.render_readiness == "blocked"]
    rights = next(
        (item for item in decisions.decisions if item.candidate_id == "rights_risk"),
        None,
    )
    moods = {
        "none",
        "motivational",
        "emotional",
        "suspense",
        "energetic",
        "calm",
        "funny",
        "cinematic",
        "educational",
    }
    selection_target_valid = len(decisions.selected_clip_ids) <= 10 and (
        len(decisions.selected_clip_ids) >= 3 if strict_selection else True
    )
    blocked_not_selected = all(not item.selected for item in blocked)
    rights_handled = rights is None or rights.render_readiness in {
        "needs_revision",
        "blocked",
    }
    music_safe = all(
        item.music_mood in moods
        and "/" not in item.music_mood
        and "\\" not in item.music_mood
        for item in decisions.decisions
    )
    packets = all(
        isinstance(item.editing_instruction_packet, BobaEditingInstructionPacketV1)
        and item.editing_instruction_packet.hook_instruction
        and item.editing_instruction_packet.cut_instruction
        and item.editing_instruction_packet.caption_instruction
        and item.editing_instruction_packet.motion_instruction
        and item.editing_instruction_packet.audio_instruction
        and item.editing_instruction_packet.pacing_instruction
        for item in decisions.decisions
    )
    risks = all(
        isinstance(item.risk_review, BobaEditorialRiskReviewV1)
        for item in decisions.decisions
    )
    persisted = artifact_path is not None and artifact_path.is_file()
    passed = bool(
        decisions.decisions
        and (decisions.selected_clip_ids or not strict_selection)
        and selection_target_valid
        and blocked_not_selected
        and rights_handled
        and music_safe
        and packets
        and risks
        and persisted
        and json.loads(encoded)
    )
    return BobaEditorialDecisionValidationReport(
        mode=mode,
        passed=passed,
        project_id=decisions.project_id,
        decision_count=len(decisions.decisions),
        selected_count=len(decisions.selected_clip_ids),
        rejected_count=len(decisions.rejected_clip_ids),
        ready_for_render_count=decisions.risk_summary.ready_for_render_count,
        needs_revision_count=decisions.risk_summary.needs_revision_count,
        blocked_count=decisions.risk_summary.blocked_count,
        selection_target_valid=selection_target_valid,
        blocked_not_selected=blocked_not_selected,
        rights_risk_handled=rights_handled,
        music_moods_safe=music_safe,
        instruction_packets_present=bool(packets),
        risk_reviews_present=risks,
        artifact_persisted=persisted,
        json_safe=bool(json.loads(encoded)),
        report_path_writable=True,
        decisions=[
            {
                "rank": item.rank,
                "candidate_id": item.candidate_id,
                "selected": item.selected,
                "readiness": item.render_readiness,
                "priority": item.production_priority,
                "hook": item.final_hook_strategy,
                "pacing": item.pacing_intensity,
                "captions": item.caption_style,
                "motion": item.motion_style,
                "music_mood": item.music_mood,
                "sfx_intensity": item.sfx_intensity,
            }
            for item in decisions.decisions[:10]
        ],
        warnings=[
            "Validation used compact local metadata only; no media was read or rendered.",
            "Editorial readiness is advisory and does not prove rendering or audience performance.",
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
    *,
    mode: Literal["self_check", "synthetic_project"],
) -> BobaEditorialDecisionValidationReport:
    project_id = (
        "proj_editorial_decision_self_check"
        if mode == "self_check"
        else "proj_editorial_decision_synthetic"
    )
    with TemporaryDirectory() as temporary:
        store = BobaMemoryStore(Path(temporary) / "boba")
        decisions = store.save_editorial_decisions(_decide(project_id))
        report = _evaluate(
            decisions,
            mode=mode,
            artifact_path=store.editorial_decision_path(project_id),
            strict_selection=True,
        )
    report.report_path_writable = _report_path_writable()
    report.passed = report.passed and report.report_path_writable
    if mode == "self_check":
        report.warnings.append(
            "Self-check required no network, media, downloader, renderer, or secrets."
        )
    return report


async def _existing_project(project_id: str) -> BobaEditorialDecisionValidationReport:
    try:
        integration = boba_integration_provider()
        ranking = integration.store.load_clip_ranking(project_id)
        if ranking is None:
            raise ValueError(
                "Saved BOBA Clip Ranking is required before editorial decisions."
            )
        decisions = integration.store.load_editorial_decisions(project_id)
        if decisions is None:
            decisions = await integration.generate_editorial_decisions(project_id)
        report = _evaluate(
            decisions,
            mode="project_id",
            artifact_path=integration.store.editorial_decision_path(project_id),
            strict_selection=False,
        )
        report.report_path_writable = _report_path_writable()
        report.passed = report.passed and report.report_path_writable
        report.warnings.append(
            "Existing-project mode used saved local metadata only and did not render or download."
        )
        return report
    except Exception as exc:
        return BobaEditorialDecisionValidationReport(
            mode="project_id",
            passed=False,
            project_id=project_id,
            report_path_writable=_report_path_writable(),
            errors=[str(exc)],
            warnings=["Missing artifacts were not replaced with fabricated decisions."],
        )


def _write_report(report: BobaEditorialDecisionValidationReport) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    payload = report.model_dump(mode="json")
    (REPORT_DIR / "boba_editorial_decision_report.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    summary = [
        "# BOBA Editorial Decision Engine V1 Validation",
        "",
        f"- Mode: `{report.mode}`",
        f"- Passed: `{str(report.passed).lower()}`",
        f"- Project: `{report.project_id or 'temporary self-check'}`",
        f"- Decisions: `{report.decision_count}`",
        f"- Selected: `{report.selected_count}`",
        f"- Ready / revision / blocked: `{report.ready_for_render_count}` / "
        f"`{report.needs_revision_count}` / `{report.blocked_count}`",
        f"- Artifact persisted: `{report.artifact_persisted}`",
        f"- Rendering triggered: `{report.rendering_triggered}`",
        f"- External calls made: `{report.external_calls_made}`",
        "",
        "## Decision Table",
        "",
        "| Rank | Candidate | Selected | Readiness | Hook | Pacing | Music mood |",
        "| ---: | --- | --- | --- | --- | --- | --- |",
        *[
            "| {rank} | {candidate_id} | {selected} | {readiness} | {hook} | "
            "{pacing} | {music_mood} |".format(**item)
            for item in report.decisions
        ],
        "",
        "This report does not establish copyright safety, rendering success, production "
        "readiness, or audience performance.",
    ]
    if report.warnings:
        summary.extend(["", "## Warnings", *[f"- {item}" for item in report.warnings]])
    if report.errors:
        summary.extend(["", "## Errors", *[f"- {item}" for item in report.errors]])
    (REPORT_DIR / "boba_editorial_decision_summary.md").write_text(
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
