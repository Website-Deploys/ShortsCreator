"""Self-validation helpers for BOBA Core Brain V1."""

from __future__ import annotations

from typing import Any

from olympus.boba.constitution import get_boba_constitution
from olympus.boba.contracts import BobaValidationResultV1


def validate_constitution() -> list[str]:
    constitution = get_boba_constitution()
    errors: list[str] = []
    if len(constitution.get("principles", [])) < 20:
        errors.append("BOBA constitution is missing required principles.")
    forbidden = " ".join(constitution.get("forbidden_behaviors", [])).lower()
    for required in ("copy", "copyright", "private", "safety", "render", "publish"):
        if required not in forbidden:
            errors.append(f"BOBA constitution lacks forbidden behavior coverage for {required}.")
    if len(constitution.get("explanation_requirements", [])) < 5:
        errors.append("BOBA constitution lacks explanation requirements.")
    return errors


def compact_boba_summary(
    *,
    brain: dict[str, Any] | None = None,
    ranking: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    brain = brain or {}
    ranking = ranking or {}
    policy = policy or {}
    source = brain.get("source_understanding")
    source = source if isinstance(source, dict) else {}
    ranked = ranking.get("ranked_candidates")
    ranked = ranked if isinstance(ranked, list) else []
    top = ranked[0] if ranked and isinstance(ranked[0], dict) else {}
    warnings = [
        *list(source.get("warnings") or []),
        *list(ranking.get("warnings") or []),
        *list(policy.get("warnings") or []),
    ]
    return {
        "brain_version": str(brain.get("version") or "1"),
        "mode": str(brain.get("mode") or "advise"),
        "decisions_present": bool(brain.get("decisions")),
        "ranking_explanation": str(
            top.get("reasons", [""])[0]
            if top.get("reasons")
            else ranking.get("reasoning_summary", "")
        ),
        "editorial_policy_summary": str(policy.get("explanation") or ""),
        "confidence": float(policy.get("confidence") or brain.get("confidence") or 0.0),
        "missing_signals": list(source.get("missing_signals") or []),
        "warnings": list(dict.fromkeys(str(item) for item in warnings if item)),
        "advisory_only": True,
        "applied": False,
    }


def self_check() -> BobaValidationResultV1:
    errors = validate_constitution()
    return BobaValidationResultV1(
        passed=not errors,
        mode="self_check",
        errors=errors,
        warnings=["BOBA Core Brain V1 is advisory and does not execute edits."],
    )
