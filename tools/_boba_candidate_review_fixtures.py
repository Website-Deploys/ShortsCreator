"""Synthetic canonical BOBA records built through the real owning contracts.

Shared by the Candidate Review validator and its unit tests so both exercise
the same genuine module contracts rather than hand-written dictionaries.
"""

from __future__ import annotations

from typing import Any

from olympus.boba.clip_discovery import (
    BobaBoundarySuggestionV1,
    BobaCandidateClipDiscoveryV1,
    BobaCandidateClipV1,
    BobaCandidateDiscoverySignalUsageV1,
    BobaCandidateDiversitySummaryV1,
    BobaCandidateEvidenceV1,
)
from olympus.boba.clip_ranking import (
    BobaClipRankingV1,
    BobaClipScoreBreakdownV1,
    BobaRankedClipV1,
    BobaRankingDiversitySummaryV1,
    BobaRankingSignalUsageV1,
    BobaRejectedRankCandidateV1,
)
from olympus.boba.store import BobaMemoryStore


def synthetic_candidate(
    candidate_id: str,
    project_id: str,
    start: float,
    end: float,
    *,
    confidence: float = 0.81,
    standalone: float = 0.72,
    warnings: list[str] | None = None,
) -> BobaCandidateClipV1:
    return BobaCandidateClipV1(
        candidate_id=candidate_id,
        project_id=project_id,
        start_seconds=start,
        end_seconds=end,
        duration_seconds=round(end - start, 3),
        suggested_title=f"Candidate {candidate_id}",
        hook_idea="A concrete hook line.",
        story_angle="A concrete story angle.",
        candidate_type="hook_moment",
        discovery_reason="Strong hook detected in the transcript.",
        confidence=confidence,
        standalone_score=standalone,
        setup_required=False,
        payoff_present=True,
        context_needed=False,
        source_topic="topic",
        emotion_label="curious",
        virality_cues=["clear hook"],
        boundary_suggestion=BobaBoundarySuggestionV1(
            recommended_start_seconds=start,
            recommended_end_seconds=end,
            reason="Clean sentence boundary.",
        ),
        evidence=BobaCandidateEvidenceV1(
            transcript_snippets=["The exact transcript line for this candidate."],
            source_signals=["transcript"],
            topic_segment_ids=[f"seg_{candidate_id}"],
        ),
        warnings=warnings or [],
    )


def synthetic_discovery(
    project_id: str, candidates: list[BobaCandidateClipV1]
) -> BobaCandidateClipDiscoveryV1:
    return BobaCandidateClipDiscoveryV1(
        project_id=project_id,
        source_id="synthetic_source",
        video_duration_seconds=600.0,
        summary="Synthetic candidate discovery record.",
        candidates=candidates,
        diversity_summary=BobaCandidateDiversitySummaryV1(
            candidate_count=len(candidates), topic_count=1, emotion_count=1
        ),
        signal_usage=BobaCandidateDiscoverySignalUsageV1(
            whole_video_understanding_used=True,
            transcript_used=True,
            analysis_signals_used=True,
            story_used=False,
            virality_used=False,
            planning_used=False,
            memory_used=False,
            fallback_used=False,
        ),
    )


def _breakdown(final: float) -> BobaClipScoreBreakdownV1:
    return BobaClipScoreBreakdownV1(
        hook_score=80.0,
        payoff_score=70.0,
        standalone_score=72.0,
        emotional_score=61.0,
        clarity_score=77.0,
        novelty_score=55.0,
        pacing_score=68.0,
        retention_score=73.0,
        context_risk_score=12.0,
        repetition_penalty=5.0,
        overlap_penalty=8.0,
        rights_safety_penalty=0.0,
        memory_alignment_score=50.0,
        final_score=final,
    )


def synthetic_ranked(
    candidate_id: str,
    project_id: str,
    rank: int,
    total: float,
    start: float,
    end: float,
    *,
    tier: str = "strong_candidate",
) -> BobaRankedClipV1:
    return BobaRankedClipV1(
        candidate_id=candidate_id,
        project_id=project_id,
        rank=rank,
        tier=tier,
        total_score=total,
        confidence=0.8,
        production_priority="high",
        score_breakdown=_breakdown(total),
        ranking_reasons=["Clear hook and payoff."],
        source_window={"start_seconds": start, "end_seconds": end},
        candidate_type="hook_moment",
        suggested_title=f"Candidate {candidate_id}",
        hook_idea="A concrete hook line.",
        story_angle="A concrete story angle.",
    )


def synthetic_ranking(
    project_id: str,
    ranked: list[BobaRankedClipV1],
    *,
    recommended: list[str] | None = None,
    rejected: list[str] | None = None,
) -> BobaClipRankingV1:
    return BobaClipRankingV1(
        project_id=project_id,
        source_id="synthetic_source",
        summary="Synthetic clip ranking record.",
        ranked_candidates=ranked,
        recommended_clip_ids=recommended or [],
        rejected_clip_ids=rejected or [],
        rejected_candidates=[
            BobaRejectedRankCandidateV1(
                candidate_id=item, reason="Overlaps a stronger candidate.", score=20.0
            )
            for item in (rejected or [])
        ],
        diversity_summary=BobaRankingDiversitySummaryV1(ranked_count=len(ranked)),
        signal_usage=BobaRankingSignalUsageV1(
            candidate_discovery_used=True,
            whole_video_understanding_used=True,
            virality_used=False,
            story_used=False,
            planning_used=False,
            memory_used=False,
            fallback_used=False,
        ),
    )


def seed_project(
    store: BobaMemoryStore,
    project_id: str,
    *,
    windows: list[tuple[str, float, float]] | None = None,
    with_ranking: bool = True,
    with_editorial: bool = True,
    recommended: list[str] | None = None,
    rejected: list[str] | None = None,
    selected: list[str] | None = None,
) -> dict[str, Any]:
    """Persist canonical records for a synthetic candidate-review project."""
    rows = windows or [
        ("cand_a", 10.0, 40.0),
        ("cand_b", 35.0, 65.0),
        ("cand_c", 10.0, 40.0),
        ("cand_d", 200.0, 220.0),
    ]
    candidates = [
        synthetic_candidate(cid, project_id, start, end) for cid, start, end in rows
    ]
    store.save_candidate_clip_discovery(synthetic_discovery(project_id, candidates))
    if with_ranking:
        ranked = [
            synthetic_ranked(
                cid, project_id, index + 1, 90.0 - index * 10.0, start, end
            )
            for index, (cid, start, end) in enumerate(rows)
            if cid not in (rejected or [])
        ]
        store.save_clip_ranking(
            synthetic_ranking(
                project_id, ranked, recommended=recommended, rejected=rejected
            )
        )
    if with_editorial:
        _seed_editorial(store, project_id, rows, selected or [])
    return {"windows": rows}


def _seed_editorial(
    store: BobaMemoryStore,
    project_id: str,
    rows: list[tuple[str, float, float]],
    selected: list[str],
) -> None:
    from olympus.boba.editorial_decision import (
        BobaEditingInstructionPacketV1,
        BobaEditorialDecisionSetV1,
        BobaEditorialDecisionV1,
        BobaEditorialRiskReviewV1,
        BobaEditorialRiskSummaryV1,
        BobaEditorialSignalUsageV1,
    )

    decisions = [
        BobaEditorialDecisionV1(
            candidate_id=cid,
            ranked_clip_id=cid,
            project_id=project_id,
            rank=index + 1,
            ranking_score=90.0 - index * 10.0,
            ranking_tier="strong_candidate",
            suggested_title=f"Candidate {cid}",
            candidate_type="hook_moment",
            source_window={"start_seconds": start, "end_seconds": end},
            selected=cid in selected,
            render_readiness="ready_for_render",
            render_readiness_reason="All required evidence is present.",
            production_priority="high",
            final_story_angle="A concrete story angle.",
            final_hook_strategy="curiosity_gap",
            opening_line_direction="Open on the strongest claim.",
            pacing_intensity="moderate",
            caption_style="bold_hook_captions",
            motion_style="subtle_zoom",
            music_mood="motivational",
            sfx_intensity="light",
            editing_instruction_packet=BobaEditingInstructionPacketV1(
                hook_instruction="Open on the strongest claim.",
                cut_instruction="Cut on the sentence boundary.",
                caption_instruction="Bold centred captions.",
                motion_instruction="Subtle zoom only.",
                audio_instruction="Keep dialogue dominant.",
                pacing_instruction="Hold a medium pace.",
                retention_instruction="Restate the hook at the midpoint.",
                risk_instruction="Do not imply any guarantee.",
            ),
            risk_review=BobaEditorialRiskReviewV1(
                weak_hook=False,
                missing_context=False,
                weak_payoff=False,
                filler_risk=False,
                duplicate_risk=False,
                rights_risk=False,
                audio_risk=False,
                visual_layout_risk=False,
                unavailable_signal_risk=False,
            ),
            decision_reasons=["Strong hook with a clear payoff."],
            confidence=0.77,
        )
        for index, (cid, start, end) in enumerate(rows)
    ]
    store.save_editorial_decisions(
        BobaEditorialDecisionSetV1(
            project_id=project_id,
            source_id="synthetic_source",
            summary="Synthetic editorial decision record.",
            selected_clip_ids=list(selected),
            rejected_clip_ids=[],
            production_order=list(selected),
            decisions=decisions,
            risk_summary=BobaEditorialRiskSummaryV1(selected_count=len(selected)),
            signal_usage=BobaEditorialSignalUsageV1(
                clip_ranking_used=True,
                candidate_discovery_used=True,
                whole_video_understanding_used=True,
                creative_briefs_used=False,
                analysis_signals_used=True,
                story_used=False,
                virality_used=False,
                planning_used=False,
                memory_used=False,
                fallback_used=False,
            ),
        )
    )
