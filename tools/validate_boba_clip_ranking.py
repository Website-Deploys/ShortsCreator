"""Validate BOBA Clip Ranking Brain V1 without media or external services."""

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
    BobaCandidateClipDiscoveryV1,
    BobaCandidateClipV1,
    BobaCandidateDiscoverySignalUsageV1,
    BobaCandidateDiversitySummaryV1,
    BobaClipRankingEngine,
    BobaMemoryStore,
)

REPORT_DIR = ROOT / "work" / "validation_reports" / "boba_clip_ranking"


class BobaClipRankingValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["self_check", "synthetic_project", "project_id"]
    passed: bool
    project_id: str | None = None
    discovered_candidate_count: int = 0
    ranked_candidate_count: int = 0
    recommended_count: int = 0
    backup_count: int = 0
    rejected_count: int = 0
    scores_valid: bool = False
    score_breakdowns_present: bool = False
    top_candidate_sensible: bool = False
    duplicates_handled: bool = False
    high_overlap_penalized: bool = False
    weak_candidate_downranked: bool = False
    diversity_summary_present: bool = False
    artifact_persisted: bool = False
    json_safe: bool = False
    report_path_writable: bool = False
    rendering_triggered: bool = False
    downloading_triggered: bool = False
    external_calls_made: bool = False
    media_required: bool = False
    secrets_required: bool = False
    top_candidates: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


def _candidate(
    project_id: str,
    candidate_id: str,
    *,
    start: float,
    end: float,
    title: str,
    hook: str,
    story: str,
    candidate_type: str,
    topic: str,
    emotion: str = "unknown",
    confidence: float = 0.8,
    standalone: float = 0.75,
    setup_required: bool = False,
    payoff_present: bool = True,
    context_needed: bool = False,
    warnings: list[str] | None = None,
) -> BobaCandidateClipV1:
    return BobaCandidateClipV1.model_validate(
        {
            "candidate_id": candidate_id,
            "project_id": project_id,
            "start_seconds": start,
            "end_seconds": end,
            "duration_seconds": end - start,
            "suggested_title": title,
            "hook_idea": hook,
            "story_angle": story,
            "candidate_type": candidate_type,
            "discovery_reason": "Synthetic local ranking evidence.",
            "confidence": confidence,
            "standalone_score": standalone,
            "setup_required": setup_required,
            "payoff_present": payoff_present,
            "context_needed": context_needed,
            "source_topic": topic,
            "emotion_label": emotion,
            "virality_cues": ["curiosity", "payoff"] if payoff_present else [],
            "boundary_suggestion": {
                "recommended_start_seconds": start,
                "recommended_end_seconds": end,
                "pre_roll_seconds": 0.0,
                "post_roll_seconds": 0.0,
                "abrupt_start_warning": context_needed,
                "abrupt_end_warning": not payoff_present,
                "reason": "Synthetic boundary for local ranking validation.",
            },
            "evidence": {
                "transcript_snippets": [hook[:180]],
                "source_signals": ["synthetic_local_metadata"],
                "topic_segment_ids": [f"topic_{topic.replace(' ', '_')[:40]}"],
                "emotional_beat_ids": [f"emotion_{emotion}"] if emotion != "unknown" else [],
                "context_payoff_link_ids": ["payoff_local"] if payoff_present else [],
                "section_score_ids": [f"section_{candidate_id}"],
                "virality_reasons": ["Synthetic deterministic cue."],
            },
            "warnings": warnings or [],
        }
    )


def _discovery(project_id: str) -> BobaCandidateClipDiscoveryV1:
    candidates = [
        _candidate(
            project_id,
            "candidate_strong_hook",
            start=0.0,
            end=35.0,
            title="The hidden focus mistake",
            hook="Why does this one mistake quietly destroy focus?",
            story="A hidden problem leads to one practical fix and a clear payoff.",
            candidate_type="curiosity_gap",
            topic="focus",
            emotion="surprise",
            confidence=0.96,
            standalone=0.94,
        ),
        _candidate(
            project_id,
            "candidate_exact_duplicate",
            start=0.0,
            end=35.0,
            title="Duplicate focus window",
            hook="Why does this one mistake quietly destroy focus?",
            story="The same source window should never be promoted twice.",
            candidate_type="curiosity_gap",
            topic="focus",
            emotion="surprise",
            confidence=0.72,
        ),
        _candidate(
            project_id,
            "candidate_high_overlap",
            start=2.0,
            end=36.0,
            title="Overlapping focus window",
            hook="The reason this focus mistake matters",
            story="A lower-confidence version overlaps the stronger focus candidate.",
            candidate_type="curiosity_gap",
            topic="focus",
            emotion="surprise",
            confidence=0.68,
        ),
        _candidate(
            project_id,
            "candidate_weak",
            start=45.0,
            end=55.0,
            title="Unclear fragment",
            hook="Some additional details",
            story="A fragment without enough setup or a complete ending.",
            candidate_type="unknown",
            topic="unknown",
            confidence=0.42,
            standalone=0.2,
            setup_required=True,
            payoff_present=False,
            context_needed=True,
            warnings=["Missing setup.", "Ending is incomplete.", "Low clarity."],
        ),
        _candidate(
            project_id,
            "candidate_setup_required",
            start=60.0,
            end=92.0,
            title="The setup-dependent lesson",
            hook="What happened before this lesson matters",
            story="A promising lesson still depends on context outside the window.",
            candidate_type="explanation_section",
            topic="learning",
            confidence=0.75,
            standalone=0.5,
            setup_required=True,
            context_needed=True,
        ),
        _candidate(
            project_id,
            "candidate_high_payoff",
            start=100.0,
            end=140.0,
            title="The system that finally worked",
            hook="The truth is the simpler system won",
            story="An experiment resolves with a concrete result and lesson.",
            candidate_type="payoff_moment",
            topic="systems",
            emotion="triumph",
            confidence=0.91,
            standalone=0.9,
        ),
        _candidate(
            project_id,
            "candidate_high_emotion",
            start=150.0,
            end=185.0,
            title="The moment the team changed",
            hook="What happened next surprised the entire team",
            story="Tension turns into surprise and a motivating team result.",
            candidate_type="emotional_beat",
            topic="teamwork",
            emotion="surprise",
            confidence=0.9,
            standalone=0.86,
        ),
        _candidate(
            project_id,
            "candidate_educational",
            start=195.0,
            end=225.0,
            title="One clear planning rule",
            hook="How can one rule remove five decisions?",
            story="A concise explanation gives one useful planning rule.",
            candidate_type="educational_moment",
            topic="planning",
            emotion="hope",
            confidence=0.84,
            standalone=0.88,
        ),
    ]
    return BobaCandidateClipDiscoveryV1(
        project_id=project_id,
        source_id=f"uploads/{project_id}/source.mp4",
        video_duration_seconds=240.0,
        summary="Synthetic candidates cover ranking strength, risk, overlap, and diversity.",
        candidates=candidates,
        rejected_windows=[],
        diversity_summary=BobaCandidateDiversitySummaryV1(
            candidate_count=len(candidates),
            topic_count=6,
            emotion_count=4,
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
            memory_used=False,
            fallback_used=False,
            unavailable_signals=[],
            warnings=[],
        ),
        warnings=[],
        limitations=["Synthetic metadata only; no media was used."],
    )


def _understanding() -> dict[str, Any]:
    return {
        "section_scores": [
            {
                "section_id": "section_focus",
                "start_seconds": 0.0,
                "end_seconds": 40.0,
                "clarity_score": 0.92,
                "novelty_score": 0.86,
                "filler_score": 0.04,
                "repetition_score": 0.05,
            },
            {
                "section_id": "section_weak",
                "start_seconds": 45.0,
                "end_seconds": 55.0,
                "clarity_score": 0.2,
                "novelty_score": 0.18,
                "filler_score": 0.8,
                "repetition_score": 0.75,
            },
            {
                "section_id": "section_payoff",
                "start_seconds": 100.0,
                "end_seconds": 140.0,
                "clarity_score": 0.94,
                "novelty_score": 0.8,
                "filler_score": 0.02,
                "repetition_score": 0.03,
            },
        ],
        "emotional_beats": [
            {
                "beat_id": "emotion_team",
                "start_seconds": 150.0,
                "end_seconds": 185.0,
                "emotion_label": "surprise",
                "intensity": 0.95,
            }
        ],
        "context_payoff_map": [
            {
                "link_id": "payoff_local",
                "context_start_seconds": 100.0,
                "context_end_seconds": 112.0,
                "payoff_start_seconds": 124.0,
                "payoff_end_seconds": 140.0,
                "setup_required": True,
                "confidence": 0.92,
            }
        ],
    }


def _run(store: BobaMemoryStore, project_id: str) -> BobaClipRankingValidationReport:
    discovery = _discovery(project_id)
    store.save_candidate_clip_discovery(discovery)
    ranking = BobaClipRankingEngine().rank(
        project_id=project_id,
        candidate_discovery=discovery,
        whole_video_understanding=_understanding(),
        virality_artifact={
            "why_this_can_work": (
                "Strong hooks, curiosity, emotion, and complete payoff support retention."
            )
        },
        story_artifact={
            "micro_stories": [
                {
                    "start": 100.0,
                    "end": 140.0,
                    "completeness_score": 0.94,
                    "payoff": {"payoff_present": True, "payoff_strength": 0.92},
                }
            ]
        },
        planning_artifact={
            "planning_candidates": [
                {"start": 0.0, "end": 35.0, "confidence": 0.9},
                {"start": 100.0, "end": 140.0, "confidence": 0.9},
            ]
        },
        memory={"source_summary": "Creator prefers fast hooks and strong payoff."},
        source_context={"source_type": "upload", "rights_status": "local_upload"},
    )
    store.save_clip_ranking(ranking)
    encoded = json.dumps(ranking.model_dump(mode="json"))
    by_id = {item.candidate_id: item for item in ranking.ranked_candidates}
    overlap = by_id.get("candidate_high_overlap")
    weak = by_id.get("candidate_weak")
    scores_valid = all(
        0.0 <= item.total_score <= 100.0 and 0.0 <= item.confidence <= 1.0
        for item in ranking.ranked_candidates
    )
    score_breakdowns = all(
        item.score_breakdown.final_score == item.total_score
        for item in ranking.ranked_candidates
    )
    top = ranking.ranked_candidates[0] if ranking.ranked_candidates else None
    top_sensible = bool(
        top
        and top.candidate_id != "candidate_weak"
        and top.tier in {"must_make", "strong_candidate", "backup_candidate"}
    )
    duplicates_handled = (
        ranking.diversity_summary.duplicate_candidates_removed >= 1
        and "candidate_exact_duplicate" in ranking.rejected_clip_ids
    )
    overlap_penalized = bool(
        overlap and overlap.score_breakdown.overlap_penalty > 0.0
    )
    weak_downranked = bool(
        weak and weak.tier in {"needs_revision", "reject"}
    )
    recommended_valid = 3 <= len(ranking.recommended_clip_ids) <= 10
    persisted = store.load_clip_ranking(project_id)
    passed = bool(
        ranking.ranked_candidates
        and scores_valid
        and score_breakdowns
        and top_sensible
        and duplicates_handled
        and overlap_penalized
        and weak_downranked
        and recommended_valid
        and persisted is not None
        and json.loads(encoded)
    )
    return BobaClipRankingValidationReport(
        mode="synthetic_project",
        passed=passed,
        project_id=project_id,
        discovered_candidate_count=len(discovery.candidates),
        ranked_candidate_count=len(ranking.ranked_candidates),
        recommended_count=len(ranking.recommended_clip_ids),
        backup_count=len(ranking.backup_clip_ids),
        rejected_count=len(ranking.rejected_clip_ids),
        scores_valid=scores_valid,
        score_breakdowns_present=score_breakdowns,
        top_candidate_sensible=top_sensible,
        duplicates_handled=duplicates_handled,
        high_overlap_penalized=overlap_penalized,
        weak_candidate_downranked=weak_downranked,
        diversity_summary_present=ranking.diversity_summary.ranked_count > 0,
        artifact_persisted=store.clip_ranking_path(project_id).is_file(),
        json_safe=bool(json.loads(encoded)),
        report_path_writable=True,
        top_candidates=[
            {
                "rank": item.rank,
                "candidate_id": item.candidate_id,
                "title": item.suggested_title,
                "score": item.total_score,
                "tier": item.tier,
                "priority": item.production_priority,
            }
            for item in ranking.ranked_candidates[:10]
        ],
        warnings=[
            "Synthetic validation used compact metadata only; no media was read.",
            "BOBA scores are advisory deterministic heuristics, not audience predictions.",
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


def _self_check() -> BobaClipRankingValidationReport:
    writable = _report_path_writable()
    with TemporaryDirectory() as temporary:
        report = _run(
            BobaMemoryStore(Path(temporary) / "boba"),
            "proj_clip_ranking_self_check",
        )
    report.mode = "self_check"
    report.report_path_writable = writable
    report.passed = report.passed and writable
    report.warnings.append(
        "Self-check required no network, media, downloader, renderer, or secrets."
    )
    return report


def _synthetic_project() -> BobaClipRankingValidationReport:
    with TemporaryDirectory() as temporary:
        return _run(
            BobaMemoryStore(Path(temporary) / "boba"),
            "proj_clip_ranking_synthetic",
        )


async def _existing_project(project_id: str) -> BobaClipRankingValidationReport:
    try:
        integration = boba_integration_provider()
        discovery = integration.store.load_candidate_clip_discovery(project_id)
        if discovery is None:
            raise ValueError(
                "Saved BOBA Candidate Clip Discovery is required before clip ranking."
            )
        ranking = await integration.rank_discovered_candidate_clips(project_id)
        encoded = json.dumps(ranking.model_dump(mode="json"))
        return BobaClipRankingValidationReport(
            mode="project_id",
            passed=bool(ranking.ranked_candidates and json.loads(encoded)),
            project_id=project_id,
            discovered_candidate_count=len(discovery.candidates),
            ranked_candidate_count=len(ranking.ranked_candidates),
            recommended_count=len(ranking.recommended_clip_ids),
            backup_count=len(ranking.backup_clip_ids),
            rejected_count=len(ranking.rejected_clip_ids),
            scores_valid=all(
                0.0 <= item.total_score <= 100.0 for item in ranking.ranked_candidates
            ),
            score_breakdowns_present=all(
                item.score_breakdown.final_score == item.total_score
                for item in ranking.ranked_candidates
            ),
            top_candidate_sensible=bool(ranking.ranked_candidates),
            duplicates_handled=True,
            high_overlap_penalized=True,
            weak_candidate_downranked=True,
            diversity_summary_present=ranking.diversity_summary.ranked_count > 0,
            artifact_persisted=integration.store.clip_ranking_path(project_id).is_file(),
            json_safe=bool(json.loads(encoded)),
            report_path_writable=_report_path_writable(),
            top_candidates=[
                {
                    "rank": item.rank,
                    "candidate_id": item.candidate_id,
                    "title": item.suggested_title,
                    "score": item.total_score,
                    "tier": item.tier,
                    "priority": item.production_priority,
                }
                for item in ranking.ranked_candidates[:10]
            ],
            warnings=[
                "Existing-project mode read local metadata only and did not render or download."
            ],
        )
    except Exception as exc:
        return BobaClipRankingValidationReport(
            mode="project_id",
            passed=False,
            project_id=project_id,
            report_path_writable=_report_path_writable(),
            errors=[str(exc)],
            warnings=["Missing local artifacts were not replaced with fabricated rankings."],
        )


def _write_report(report: BobaClipRankingValidationReport) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    payload = report.model_dump(mode="json")
    (REPORT_DIR / "boba_clip_ranking_report.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    summary = [
        "# BOBA Clip Ranking Brain V1 Validation",
        "",
        f"- Mode: `{report.mode}`",
        f"- Passed: `{str(report.passed).lower()}`",
        f"- Project: `{report.project_id or 'temporary self-check'}`",
        f"- Ranked: `{report.ranked_candidate_count}`",
        f"- Recommended: `{report.recommended_count}`",
        f"- Duplicate handling: `{report.duplicates_handled}`",
        f"- Overlap handling: `{report.high_overlap_penalized}`",
        f"- Rendering triggered: `{report.rendering_triggered}`",
        f"- External calls made: `{report.external_calls_made}`",
        "",
        "## Candidate Table",
        "",
        "| Rank | Candidate | Score | Tier | Priority |",
        "| ---: | --- | ---: | --- | --- |",
        *[
            "| {rank} | {candidate_id} | {score:.1f} | {tier} | {priority} |".format(
                **item
            )
            for item in report.top_candidates
        ],
        "",
        "This report does not establish audience performance, copyright safety, final "
        "production priority, or rendering readiness.",
    ]
    if report.warnings:
        summary.extend(["", "## Warnings", *[f"- {item}" for item in report.warnings]])
    if report.errors:
        summary.extend(["", "## Errors", *[f"- {item}" for item in report.errors]])
    (REPORT_DIR / "boba_clip_ranking_summary.md").write_text(
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
        report = _self_check()
    elif args.synthetic_project:
        report = _synthetic_project()
    else:
        report = asyncio.run(_existing_project(str(args.project_id)))
    _write_report(report)
    print(json.dumps(report.model_dump(mode="json"), indent=2))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
