"""Stable JSON-safe contracts for Copyright / Safety Checker V2."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, TypedDict

CHECKER_VERSION = "2"
COPYRIGHT_SAFETY_DISCLAIMER = "This is a technical risk assessment, not legal advice."


class RiskLevel(StrEnum):
    """Calibrated component and aggregate risk levels."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


class UploadReadiness(StrEnum):
    """Technical readiness language that never promises platform approval."""

    READY_WITH_LOW_RISK = "ready_with_low_risk"
    NEEDS_MANUAL_REVIEW = "needs_manual_review"
    NOT_READY = "not_ready"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


class CopyrightSafetyReport(TypedDict):
    """Top-level report persisted on rendered clips and emitted by the CLI."""

    report_id: str
    project_id: str | None
    clip_id: str | None
    created_at: str
    checker_version: str
    overall: dict[str, Any]
    source_video: dict[str, Any]
    music: dict[str, Any]
    sfx: dict[str, Any]
    visual_assets: dict[str, Any]
    captions_text: dict[str, Any]
    final_output: dict[str, Any]
    platform_readiness: dict[str, Any]
    manual_review: dict[str, Any]
    result: dict[str, Any]


RISK_PRIORITY: dict[str, int] = {
    RiskLevel.LOW.value: 0,
    RiskLevel.UNKNOWN.value: 1,
    RiskLevel.MEDIUM.value: 2,
    RiskLevel.HIGH.value: 3,
    RiskLevel.BLOCKED.value: 4,
}

BASE_MANUAL_REVIEW_CHECKLIST = (
    "Confirm you own or have permission to use the source video.",
    "Confirm every music license allows use on the intended platform.",
    "Confirm all required attribution text is included when publishing.",
    "Confirm SFX, overlays, templates, logos, and footage have documented provenance.",
    "Confirm captions, titles, and descriptions do not copy another creator's script.",
    "Confirm the edit is not misleading, impersonating someone, private, or restricted.",
)
