"""Deterministic editorial explanations over existing Olympus signals."""

from __future__ import annotations

from typing import Any

from olympus.boba.contracts import BobaReasoningV1


def _number(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _reasoning(
    summary: str,
    *,
    evidence: list[str],
    tradeoffs: list[str],
    rejected: list[str],
    risks: list[str],
    confidence: float,
) -> dict[str, Any]:
    user = summary
    if risks:
        user += f" Main risk: {risks[0]}"
    return {
        **BobaReasoningV1(
            summary=summary,
            evidence=evidence,
            tradeoffs=tradeoffs,
            rejected_options=rejected,
            risks=risks,
            explanation_for_user=user,
        ).model_dump(mode="json"),
        "confidence": round(_number(confidence), 3),
    }


def explain_clip_selection(candidate: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    hook = _number(candidate.get("hook_strength") or candidate.get("hook"))
    story = _number(candidate.get("story_completeness") or candidate.get("story"))
    payoff = _number(candidate.get("payoff_strength") or candidate.get("payoff"))
    duplicate = _number(candidate.get("duplicate_risk"))
    evidence = [
        f"Hook strength {hook:.2f}",
        f"Story completeness {story:.2f}",
        f"Payoff strength {payoff:.2f}",
        f"Duplicate risk {duplicate:.2f}",
    ]
    risks = [str(item) for item in context.get("missing_signals", []) if item]
    if candidate.get("boundary_risk"):
        risks.append("The proposed boundary may cut speech or payoff context.")
    summary = (
        "I recommend this clip because it combines a clear opening, a sufficiently complete "
        "story, and a usable payoff without duplicating a stronger range."
    )
    return _reasoning(
        summary,
        evidence=evidence,
        tradeoffs=["A stronger hook cannot compensate for a missing payoff."],
        rejected=[str(item) for item in candidate.get("rejected_options", [])],
        risks=risks,
        confidence=(hook + story + payoff + (1.0 - duplicate)) / 4,
    )

def explain_clip_rejection(candidate: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    payoff = _number(candidate.get("payoff_strength") or candidate.get("payoff"))
    context_need = _number(candidate.get("context_requirement"))
    duplicate = _number(candidate.get("duplicate_risk"))
    reasons: list[str] = []
    if payoff < 0.4:
        reasons.append("the payoff is weak or missing")
    if context_need > 0.55:
        reasons.append("it requires too much outside context")
    if duplicate > 0.5:
        reasons.append("it overlaps a stronger candidate")
    reasons = reasons or ["its combined editorial evidence is weaker than selected options"]
    summary = "I would not prioritize this clip because " + ", ".join(reasons) + "."
    return _reasoning(
        summary,
        evidence=[f"Payoff {payoff:.2f}", f"Context requirement {context_need:.2f}"],
        tradeoffs=["It may still be usable after boundary or context repair."],
        rejected=[],
        risks=[str(item) for item in context.get("missing_signals", []) if item],
        confidence=max(0.35, (1.0 - payoff + context_need + duplicate) / 3),
    )


def explain_candidate_comparison(
    candidate_a: dict[str, Any],
    candidate_b: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    score_a = _number(candidate_a.get("overall_recommendation") or candidate_a.get("score"))
    score_b = _number(candidate_b.get("overall_recommendation") or candidate_b.get("score"))
    winner = candidate_a if score_a >= score_b else candidate_b
    loser = candidate_b if winner is candidate_a else candidate_a
    winner_id = winner.get("candidate_id") or "the stronger candidate"
    loser_id = loser.get("candidate_id") or "the alternative"
    summary = f"I prefer {winner_id} over {loser_id} based on the combined editorial evidence."
    return _reasoning(
        summary,
        evidence=[f"Candidate A {score_a:.2f}", f"Candidate B {score_b:.2f}"],
        tradeoffs=["Close scores should remain advisory rather than forced."],
        rejected=[str(loser_id)],
        risks=[str(item) for item in context.get("missing_signals", []) if item],
        confidence=0.5 + abs(score_a - score_b) / 2,
    )


def explain_editorial_policy(
    clip: dict[str, Any], policy: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    pacing = str(policy.get("pacing") or "balanced")
    summary = (
        f"I recommend {pacing} pacing while preserving the hook, spoken meaning, and final payoff."
    )
    return _reasoning(
        summary,
        evidence=[
            f"Story shape: {clip.get('story_shape') or 'unknown'}",
            f"Hook type: {clip.get('hook_type') or 'unknown'}",
        ],
        tradeoffs=["More motion is not automatically more engaging."],
        rejected=[],
        risks=[str(item) for item in context.get("missing_signals", []) if item],
        confidence=_number(policy.get("confidence") or 0.6),
    )


def explain_metadata_choice(metadata: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    return _reasoning(
        "The metadata should describe the real hook and payoff without copied or inflated claims.",
        evidence=[f"Title style: {metadata.get('title_style') or 'clear'}"],
        tradeoffs=["Curiosity wording must remain faithful to the clip."],
        rejected=["Copied creator wording", "Guaranteed outcome claims"],
        risks=[str(item) for item in context.get("missing_signals", []) if item],
        confidence=0.7,
    )


def explain_safety_warning(safety: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    status = str(safety.get("status") or safety.get("risk_level") or "unknown")
    return _reasoning(
        f"Safety status is {status}; BOBA cannot establish copyright clearance or override review.",
        evidence=[str(item) for item in safety.get("warnings", [])][:8],
        tradeoffs=["A downloadable source is not proof of publishing rights."],
        rejected=["Override safety blocker"],
        risks=[str(item) for item in context.get("missing_signals", []) if item],
        confidence=0.75 if status != "unknown" else 0.35,
    )


def summarize_project_understanding(signals: dict[str, Any]) -> dict[str, Any]:
    missing = [str(item) for item in signals.get("missing_signals", []) if item]
    topics = [str(item) for item in signals.get("main_topics", []) if item][:6]
    summary = (
        f"BOBA found {len(topics)} topic signal(s) and {len(missing)} missing signal(s). "
        "This understanding is advisory and derived only from persisted Olympus artifacts."
    )
    return _reasoning(
        summary,
        evidence=[f"Topic: {item}" for item in topics],
        tradeoffs=["Missing visual or transcript signals reduce confidence."],
        rejected=[],
        risks=missing,
        confidence=max(0.1, min(0.9, 0.75 - 0.08 * len(missing))),
    )
