"""Conservative metadata-only rights and permission review for BOBA."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from hashlib import sha256
from typing import Any, Literal, TypeAlias
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator

from olympus.boba.contracts import BobaContract, now_iso
from olympus.platform.errors import ValidationError

BobaDeclaredRightsStatusV1 = Literal[
    "owned",
    "licensed",
    "permission_granted",
    "permission_needed",
    "unknown",
    "blocked",
    "public_domain_claimed",
    "fair_use_claimed",
]
BobaRightsGateStatusV1 = Literal[
    "ready_for_human_review",
    "needs_permission",
    "needs_rights_review",
    "blocked",
    "insufficient_information",
]
BobaPermissionChecklistCategoryV1 = Literal[
    "ownership",
    "license",
    "permission",
    "platform_terms",
    "third_party_content",
    "music_audio",
    "people_privacy",
    "source_quality",
    "final_approval",
]
BobaPermissionChecklistStatusV1 = Literal[
    "passed",
    "warning",
    "blocked",
    "unknown",
    "not_applicable",
]
BobaOverallRightsRiskV1 = Literal[
    "low",
    "medium",
    "high",
    "blocked",
    "unknown",
]
BobaIngestionPrecheckStatusV1 = Literal[
    "eligible_for_manual_ingestion_review",
    "permission_required_before_review",
    "rights_review_required_before_review",
    "blocked",
    "insufficient_information",
]
BobaAllowedNextStepV1 = Literal[
    "human_review_only",
    "seek_permission",
    "add_rights_evidence",
    "do_not_process",
    "blocked",
]
ArtifactValue: TypeAlias = Mapping[str, Any] | BaseModel | None

_SPACE = re.compile(r"\s+")
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_MAX_SNIPPET_CHARS = 300
_RIGHTS_ALIASES: dict[str, BobaDeclaredRightsStatusV1] = {
    "owned": "owned",
    "user_owned": "owned",
    "creator_owned": "owned",
    "licensed": "licensed",
    "license_confirmed": "licensed",
    "permission_granted": "permission_granted",
    "permission_confirmed": "permission_granted",
    "permission_needed": "permission_needed",
    "needs_permission": "permission_needed",
    "unknown": "unknown",
    "unverified": "unknown",
    "blocked": "blocked",
    "not_allowed": "blocked",
    "permission_denied": "blocked",
    "public_domain_claimed": "public_domain_claimed",
    "public_domain": "public_domain_claimed",
    "fair_use_claimed": "fair_use_claimed",
    "fair_use": "fair_use_claimed",
}
_BLOCK_TERMS = {
    "blocked",
    "do not process",
    "do not use",
    "not allowed",
    "permission denied",
    "prohibited",
    "rights denied",
}
_CONFLICT_TERMS = {
    "conflicting",
    "not confirmed",
    "permission needed",
    "rights unknown",
    "status unknown",
    "unverified",
}
_THIRD_PARTY_TERMS = {
    "archive footage",
    "copyrighted clip",
    "guest clip",
    "reused footage",
    "stock footage",
    "third party",
    "third-party",
}
_MUSIC_AUDIO_TERMS = {
    "audio rights",
    "background music",
    "copyrighted music",
    "licensed music",
    "music",
    "song",
    "soundtrack",
}
_PEOPLE_PRIVACY_TERMS = {
    "face",
    "faces",
    "guest",
    "interview",
    "minor",
    "people",
    "person",
    "privacy",
    "release",
}
_COPYRIGHT_TERMS = {
    "copyright",
    "copyrighted",
    "fair use",
    "public domain",
    "republication",
    "third party",
    "third-party",
}
_PLATFORM_TERMS = {
    "instagram",
    "platform",
    "shorts",
    "tiktok",
    "youtube",
}


def _text(value: Any, *, maximum: int = 800) -> str:
    return _SPACE.sub(" ", str(value or "")).strip()[:maximum]


def _dict(value: ArtifactValue | Any) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list | tuple) else []


def _clamp(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 4)


def _stable_id(prefix: str, *values: str) -> str:
    digest = sha256("|".join(values).encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


def _unique(
    values: Sequence[Any],
    *,
    limit: int = 32,
    maximum: int = 700,
) -> list[str]:
    return list(
        dict.fromkeys(
            item
            for value in values
            if (item := _text(value, maximum=maximum))
        )
    )[:limit]


def _contains_any(text: str, terms: set[str]) -> bool:
    lowered = text.casefold()
    return any(term in lowered for term in terms)


class BobaRightsEvidenceSnippetV1(BobaContract):
    evidence_id: str = Field(min_length=1, max_length=128)
    source_artifact: str = Field(min_length=1, max_length=160)
    source_field: str = Field(min_length=1, max_length=120)
    snippet: str = Field(min_length=1, max_length=_MAX_SNIPPET_CHARS)
    confidence: float = Field(ge=0.0, le=1.0)
    usage_warning: str = Field(min_length=1, max_length=500)


class BobaRightsReviewedItemV1(BobaContract):
    review_item_id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=128)
    candidate_video_id: str = Field(default="", max_length=128)
    source_item_id: str = Field(default="", max_length=128)
    title: str = Field(default="", max_length=300)
    source_label: str = Field(default="", max_length=160)
    source_reference: str = Field(default="", max_length=300)
    source_url: str | None = Field(default=None, max_length=2_048)
    declared_rights_status: BobaDeclaredRightsStatusV1 = "unknown"
    permission_notes: str = Field(default="", max_length=600)
    license_notes: str = Field(default="", max_length=600)
    ownership_notes: str = Field(default="", max_length=600)
    platform_source_notes: str = Field(default="", max_length=600)
    source_artifact_refs: list[str] = Field(default_factory=list, max_length=32)
    evidence_snippets: list[BobaRightsEvidenceSnippetV1] = Field(
        default_factory=list,
        max_length=32,
    )
    missing_evidence: list[str] = Field(default_factory=list, max_length=32)
    warnings: list[str] = Field(default_factory=list, max_length=32)
    limitations: list[str] = Field(default_factory=list, max_length=32)

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(
                "source_url must be an absolute HTTP or HTTPS reference"
            )
        return value


class BobaRightsGateDecisionV1(BobaContract):
    decision_id: str = Field(min_length=1, max_length=128)
    review_item_id: str = Field(min_length=1, max_length=128)
    candidate_video_id: str = Field(default="", max_length=128)
    gate_status: BobaRightsGateStatusV1
    allow_human_review: bool
    allow_future_ingestion_precheck: bool
    requires_permission: bool
    requires_rights_review: bool
    blocked: bool
    decision_reason: str = Field(min_length=1, max_length=900)
    required_human_checks: list[str] = Field(
        default_factory=list,
        max_length=32,
    )
    confidence: float = Field(ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list, max_length=32)
    limitations: list[str] = Field(default_factory=list, max_length=32)


class BobaPermissionChecklistItemV1(BobaContract):
    item_id: str = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=240)
    category: BobaPermissionChecklistCategoryV1
    status: BobaPermissionChecklistStatusV1
    required: bool
    reason: str = Field(min_length=1, max_length=600)
    human_action: str = Field(min_length=1, max_length=600)


class BobaPermissionChecklistV1(BobaContract):
    checklist_id: str = Field(min_length=1, max_length=128)
    review_item_id: str = Field(min_length=1, max_length=128)
    ownership_confirmed: bool
    license_confirmed: bool
    permission_granted: bool
    permission_evidence_reference_present: bool
    platform_terms_review_needed: bool
    third_party_content_review_needed: bool
    music_audio_rights_review_needed: bool
    people_privacy_release_review_needed: bool
    source_quality_review_needed: bool
    final_human_approval_required: bool
    checklist_items: list[BobaPermissionChecklistItemV1] = Field(
        default_factory=list,
        max_length=16,
    )
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaRightsRiskReviewV1(BobaContract):
    risk_review_id: str = Field(min_length=1, max_length=128)
    review_item_id: str = Field(min_length=1, max_length=128)
    unknown_rights_risk: bool
    third_party_media_risk: bool
    music_audio_rights_risk: bool
    platform_terms_risk: bool
    privacy_release_risk: bool
    source_ambiguity_risk: bool
    copyrighted_source_material_risk: bool
    permission_evidence_missing_risk: bool
    overall_rights_risk: BobaOverallRightsRiskV1
    blockers: list[str] = Field(default_factory=list, max_length=32)
    warnings: list[str] = Field(default_factory=list, max_length=32)
    fixes: list[str] = Field(default_factory=list, max_length=32)


class BobaFutureIngestionHandoffV1(BobaContract):
    handoff_id: str = Field(min_length=1, max_length=128)
    review_item_id: str = Field(min_length=1, max_length=128)
    candidate_video_id: str = Field(default="", max_length=128)
    ingestion_precheck_status: BobaIngestionPrecheckStatusV1
    allowed_next_step: BobaAllowedNextStepV1
    required_before_ingestion: list[str] = Field(
        default_factory=list,
        max_length=32,
    )
    blocked_reason: str = Field(default="", max_length=700)
    apply_automatically: Literal[False] = False
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaRightsSummaryV1(BobaContract):
    total_reviewed: int = Field(default=0, ge=0)
    ready_for_human_review_count: int = Field(default=0, ge=0)
    needs_permission_count: int = Field(default=0, ge=0)
    needs_rights_review_count: int = Field(default=0, ge=0)
    blocked_count: int = Field(default=0, ge=0)
    insufficient_information_count: int = Field(default=0, ge=0)
    common_risks: list[str] = Field(default_factory=list, max_length=32)
    rights_status_breakdown: dict[str, int] = Field(default_factory=dict)
    human_review_notes: list[str] = Field(default_factory=list, max_length=32)
    limitations: list[str] = Field(default_factory=list, max_length=32)


class BobaRightsPermissionSignalUsageV1(BobaContract):
    candidate_video_scorer_used: bool = False
    content_scout_used: bool = False
    research_brain_used: bool = False
    trend_topic_watcher_used: bool = False
    clip_briefs_used: bool = False
    music_mood_used: bool = False
    memory_used: bool = False
    manual_input_used: bool = False
    external_api_used: Literal[False] = False
    url_fetching_used: Literal[False] = False
    scraping_used: Literal[False] = False
    downloading_used: Literal[False] = False
    media_ingestion_used: Literal[False] = False
    legal_validation_used: Literal[False] = False
    fallback_used: bool = False
    unavailable_signals: list[str] = Field(default_factory=list, max_length=32)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaRightsPermissionGateSetV1(BobaContract):
    schema_version: Literal[
        "boba_rights_permission_gate_v1"
    ] = "boba_rights_permission_gate_v1"
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(min_length=1, max_length=512)
    created_at: str = Field(default_factory=now_iso)
    reviewed_items: list[BobaRightsReviewedItemV1] = Field(
        default_factory=list,
        max_length=5_000,
    )
    gate_decisions: list[BobaRightsGateDecisionV1] = Field(
        default_factory=list,
        max_length=5_000,
    )
    permission_checklists: list[BobaPermissionChecklistV1] = Field(
        default_factory=list,
        max_length=5_000,
    )
    risk_reviews: list[BobaRightsRiskReviewV1] = Field(
        default_factory=list,
        max_length=5_000,
    )
    future_ingestion_handoffs: list[BobaFutureIngestionHandoffV1] = Field(
        default_factory=list,
        max_length=5_000,
    )
    rights_summary: BobaRightsSummaryV1
    signal_usage: BobaRightsPermissionSignalUsageV1
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)


def normalize_rights_status(
    value: Any,
) -> tuple[BobaDeclaredRightsStatusV1, list[str]]:
    """Normalize one user-provided status without treating claims as proof."""

    raw = _text(value, maximum=80).casefold()
    normalized = re.sub(r"[^a-z0-9]+", "_", raw).strip("_")
    if not normalized:
        return "unknown", [
            "Rights status was not provided and remains unknown."
        ]
    resolved = _RIGHTS_ALIASES.get(normalized)
    if resolved is None:
        return "unknown", [
            f"Unsupported rights status '{_text(value, maximum=80)}' became unknown."
        ]
    warnings: list[str] = []
    if resolved == "public_domain_claimed":
        warnings.append(
            "Public-domain status is a user-provided claim, not verified proof."
        )
    if resolved == "fair_use_claimed":
        warnings.append(
            "Fair-use status is a user-provided claim and requires human legal review."
        )
    return resolved, warnings


def _evidence_snippet(
    *,
    review_item_id: str,
    source_artifact: str,
    source_field: str,
    snippet: Any,
    confidence: float,
) -> BobaRightsEvidenceSnippetV1 | None:
    compact = _text(snippet, maximum=_MAX_SNIPPET_CHARS)
    if not compact:
        return None
    return BobaRightsEvidenceSnippetV1(
        evidence_id=_stable_id(
            "rights_evidence",
            review_item_id,
            source_artifact,
            source_field,
            compact,
        ),
        source_artifact=source_artifact,
        source_field=source_field,
        snippet=compact,
        confidence=_clamp(confidence),
        usage_warning=(
            "Compact user-provided metadata only; this snippet is not legal "
            "validation or proof of ownership, license validity, or permission."
        ),
    )


def _infer_status_from_notes(value: Any) -> BobaDeclaredRightsStatusV1:
    text = _text(value, maximum=1_500).casefold()
    if _contains_any(text, _BLOCK_TERMS):
        return "blocked"
    if "permission granted" in text or "permission confirmed" in text:
        return "permission_granted"
    if "permission needed" in text or "seek permission" in text:
        return "permission_needed"
    if "licensed" in text or "license confirmed" in text:
        return "licensed"
    if "owned" in text or "creator-owned" in text:
        return "owned"
    if "public domain" in text:
        return "public_domain_claimed"
    if "fair use" in text:
        return "fair_use_claimed"
    return "unknown"


def _normalize_review_item(
    raw: Mapping[str, Any],
    *,
    project_id: str,
    source_label: str,
    source_artifact: str,
    item_index: int,
) -> BobaRightsReviewedItemV1:
    title = _text(raw.get("title") or raw.get("name"), maximum=300)
    candidate_video_id = _text(
        raw.get("candidate_video_id") or raw.get("candidate_id"),
        maximum=128,
    )
    source_item_id = _text(
        raw.get("source_item_id")
        or raw.get("item_id")
        or raw.get("research_source_id")
        or raw.get("topic_id"),
        maximum=128,
    )
    source_reference = _text(
        raw.get("source_reference") or raw.get("reference"),
        maximum=300,
    )
    source_url_raw = _text(
        raw.get("source_url") or raw.get("url"),
        maximum=2_048,
    )
    warnings: list[str] = []
    source_url: str | None = None
    if source_url_raw:
        parsed = urlparse(source_url_raw)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            source_url = source_url_raw
        else:
            source_reference = source_reference or _text(
                source_url_raw,
                maximum=300,
            )
            warnings.append(
                "Invalid source URL was retained only as a compact reference."
            )
    explicit_status = raw.get("declared_rights_status")
    if explicit_status in (None, ""):
        explicit_status = raw.get("rights_status")
    status, status_warnings = normalize_rights_status(explicit_status)
    warnings.extend(status_warnings)
    permission_notes = _text(
        raw.get("permission_notes"),
        maximum=600,
    )
    license_notes = _text(
        raw.get("license_notes") or raw.get("licensing_notes"),
        maximum=600,
    )
    ownership_notes = _text(
        raw.get("ownership_notes"),
        maximum=600,
    )
    platform_source_notes = _text(
        raw.get("platform_source_notes")
        or raw.get("platform_notes")
        or raw.get("source_notes"),
        maximum=600,
    )
    effective_source_label = _text(
        raw.get("source_label") or raw.get("source") or source_label,
        maximum=160,
    )
    supplied_review_id = _text(
        raw.get("review_item_id"),
        maximum=128,
    )
    identity = (
        candidate_video_id
        or source_item_id
        or source_reference
        or title
        or str(item_index)
    )
    review_item_id = (
        supplied_review_id
        if _SAFE_ID.fullmatch(supplied_review_id)
        else _stable_id(
            "rights_review_item",
            project_id,
            source_artifact,
            identity,
        )
    )
    evidence: list[BobaRightsEvidenceSnippetV1] = []
    note_fields = (
        ("permission_notes", permission_notes),
        ("license_notes", license_notes),
        ("ownership_notes", ownership_notes),
        ("platform_source_notes", platform_source_notes),
    )
    for source_field, note in note_fields:
        snippet = _evidence_snippet(
            review_item_id=review_item_id,
            source_artifact=source_artifact,
            source_field=source_field,
            snippet=note,
            confidence=0.55,
        )
        if snippet is not None:
            evidence.append(snippet)
    for source_field in ("tags", "topic_tags", "categories"):
        raw_values = raw.get(source_field)
        if isinstance(raw_values, list | tuple):
            compact_value = ", ".join(
                _text(value, maximum=80)
                for value in raw_values[:20]
                if _text(value, maximum=80)
            )
        else:
            compact_value = _text(raw_values, maximum=_MAX_SNIPPET_CHARS)
        snippet = _evidence_snippet(
            review_item_id=review_item_id,
            source_artifact=source_artifact,
            source_field=source_field,
            snippet=compact_value,
            confidence=0.4,
        )
        if snippet is not None:
            evidence.append(snippet)
    for evidence_index, raw_evidence in enumerate(
        _list(raw.get("evidence_snippets") or raw.get("rights_evidence"))
    ):
        if isinstance(raw_evidence, Mapping):
            snippet_value = raw_evidence.get("snippet") or raw_evidence.get(
                "note"
            )
            source_field = _text(
                raw_evidence.get("source_field") or "user_evidence",
                maximum=120,
            )
            confidence_value = raw_evidence.get("confidence")
            confidence = (
                float(confidence_value)
                if isinstance(confidence_value, int | float)
                else 0.5
            )
        else:
            snippet_value = raw_evidence
            source_field = f"user_evidence_{evidence_index + 1}"
            confidence = 0.5
        snippet = _evidence_snippet(
            review_item_id=review_item_id,
            source_artifact=source_artifact,
            source_field=source_field,
            snippet=snippet_value,
            confidence=confidence,
        )
        if snippet is not None:
            evidence.append(snippet)
    missing: list[str] = []
    if explicit_status in (None, ""):
        missing.append("Declared rights status was not provided.")
    if not (
        title
        or candidate_video_id
        or source_item_id
        or source_reference
        or source_url
    ):
        missing.append(
            "Source title, candidate ID, item ID, URL, or reference was not provided."
        )
    if status == "owned" and not ownership_notes and not evidence:
        missing.append("Ownership note or compact evidence reference is missing.")
    if status == "licensed" and not license_notes:
        missing.append("License note or compact evidence reference is missing.")
    if status == "permission_granted" and not permission_notes:
        missing.append(
            "Permission-granted status lacks a compact permission note or reference."
        )
    if status in {"permission_needed", "unknown"}:
        missing.append("Acceptable ownership, license, or permission evidence is missing.")
    if status in {"public_domain_claimed", "fair_use_claimed"} and not evidence:
        missing.append("Claim evidence or review reference is missing.")
    if not (
        title
        or candidate_video_id
        or source_item_id
        or permission_notes
        or license_notes
        or ownership_notes
        or platform_source_notes
    ):
        raise ValidationError(
            "Rights review item requires source identity or compact rights notes.",
            details={"item_index": item_index},
        )
    refs = _unique(
        [
            *_list(raw.get("source_artifact_refs")),
            f"{source_artifact}:{identity}",
        ],
        limit=32,
        maximum=200,
    )
    return BobaRightsReviewedItemV1(
        review_item_id=review_item_id,
        project_id=project_id,
        candidate_video_id=candidate_video_id,
        source_item_id=source_item_id,
        title=title,
        source_label=effective_source_label,
        source_reference=source_reference,
        source_url=source_url,
        declared_rights_status=status,
        permission_notes=permission_notes,
        license_notes=license_notes,
        ownership_notes=ownership_notes,
        platform_source_notes=platform_source_notes,
        source_artifact_refs=refs,
        evidence_snippets=evidence[:32],
        missing_evidence=_unique(missing, limit=32, maximum=500),
        warnings=_unique(
            [
                *warnings,
                "Source URLs and references were preserved as text and were not fetched.",
                "Declared rights states and notes were not legally validated.",
            ],
            limit=32,
            maximum=500,
        ),
        limitations=[
            "This item contains compact local/user-provided metadata only.",
            "BOBA did not inspect media or validate ownership, licenses, permission, or fair use.",
            "No decision confirms copyright safety or replaces human review.",
        ],
    )


def _item_text(item: BobaRightsReviewedItemV1) -> str:
    return " ".join(
        [
            item.title,
            item.source_label,
            item.source_reference,
            item.permission_notes,
            item.license_notes,
            item.ownership_notes,
            item.platform_source_notes,
            *[snippet.snippet for snippet in item.evidence_snippets],
            *item.warnings,
        ]
    )


def _has_note_for_status(item: BobaRightsReviewedItemV1) -> bool:
    if item.declared_rights_status == "owned":
        return bool(item.ownership_notes)
    if item.declared_rights_status == "licensed":
        return bool(item.license_notes)
    if item.declared_rights_status == "permission_granted":
        return bool(item.permission_notes)
    return False


def _has_source_identity(item: BobaRightsReviewedItemV1) -> bool:
    return bool(
        item.title
        or item.candidate_video_id
        or item.source_item_id
        or item.source_reference
        or item.source_url
    )


def _has_conflict(item: BobaRightsReviewedItemV1) -> bool:
    text = _item_text(item)
    if _contains_any(text, _BLOCK_TERMS):
        return item.declared_rights_status != "blocked"
    if item.declared_rights_status in {
        "owned",
        "licensed",
        "permission_granted",
    }:
        return _contains_any(text, _CONFLICT_TERMS)
    return False


def build_rights_risk_review(
    item: BobaRightsReviewedItemV1,
    *,
    research_warnings: Sequence[str] = (),
    trend_warnings: Sequence[str] = (),
    clip_brief_warnings: Sequence[str] = (),
    music_mood_warnings: Sequence[str] = (),
) -> BobaRightsRiskReviewV1:
    """Build a bounded risk review from supplied metadata and saved warnings."""

    combined = " ".join(
        [
            _item_text(item),
            *research_warnings,
            *trend_warnings,
            *clip_brief_warnings,
            *music_mood_warnings,
        ]
    )
    blocked_note = _contains_any(_item_text(item), _BLOCK_TERMS)
    unknown = item.declared_rights_status in {
        "unknown",
        "public_domain_claimed",
        "fair_use_claimed",
    }
    third_party = _contains_any(combined, _THIRD_PARTY_TERMS)
    music_audio = bool(music_mood_warnings) or _contains_any(
        combined,
        _MUSIC_AUDIO_TERMS,
    )
    platform = bool(
        item.source_url or item.platform_source_notes
    ) or _contains_any(combined, _PLATFORM_TERMS)
    privacy = _contains_any(combined, _PEOPLE_PRIVACY_TERMS)
    ambiguity = (
        not _has_source_identity(item)
        or _has_conflict(item)
        or any("source title" in value.casefold() for value in item.missing_evidence)
    )
    copyrighted = (
        item.declared_rights_status
        in {"public_domain_claimed", "fair_use_claimed"}
        or _contains_any(combined, _COPYRIGHT_TERMS)
        or bool(research_warnings)
    )
    permission_missing = (
        item.declared_rights_status
        in {
            "permission_needed",
            "unknown",
            "public_domain_claimed",
            "fair_use_claimed",
        }
        or (
            item.declared_rights_status
            in {"owned", "licensed", "permission_granted"}
            and not _has_note_for_status(item)
        )
    )
    blockers: list[str] = []
    if item.declared_rights_status == "blocked" or blocked_note:
        blockers.append(
            "Declared status or compact notes explicitly block processing."
        )
    if _has_conflict(item):
        blockers.append(
            "Declared status conflicts with compact rights or permission notes."
        )
    risk_count = sum(
        (
            unknown,
            third_party,
            music_audio,
            platform,
            privacy,
            ambiguity,
            copyrighted,
            permission_missing,
        )
    )
    if item.declared_rights_status == "blocked" or blocked_note:
        overall: BobaOverallRightsRiskV1 = "blocked"
    elif not _has_source_identity(item):
        overall = "unknown"
    elif (
        unknown
        or item.declared_rights_status == "permission_needed"
        or risk_count >= 4
    ):
        overall = "high"
    elif risk_count:
        overall = "medium"
    else:
        overall = "low"
    warnings = [
        "Risk flags are conservative metadata cues, not legal conclusions.",
        "BOBA did not inspect the media or validate any legal document.",
    ]
    if unknown:
        warnings.append("Unknown or claimed rights are never treated as safe.")
    if music_audio:
        warnings.append(
            "Music and audio rights require separate human verification."
        )
    fixes: list[str] = [
        "Record a compact ownership, license, or permission reference.",
        "Review the actual source and intended use before any processing.",
        "Obtain final explicit human approval.",
    ]
    if platform:
        fixes.append("Review applicable platform and source terms.")
    if third_party:
        fixes.append("Identify and review every third-party media element.")
    if music_audio:
        fixes.append("Verify music, audio, and SFX rights separately.")
    if privacy:
        fixes.append("Review privacy, consent, and release needs for people.")
    if ambiguity:
        fixes.append("Resolve source identity or conflicting notes.")
    return BobaRightsRiskReviewV1(
        risk_review_id=_stable_id(
            "rights_risk_review",
            item.review_item_id,
        ),
        review_item_id=item.review_item_id,
        unknown_rights_risk=unknown,
        third_party_media_risk=third_party,
        music_audio_rights_risk=music_audio,
        platform_terms_risk=platform,
        privacy_release_risk=privacy,
        source_ambiguity_risk=ambiguity,
        copyrighted_source_material_risk=copyrighted,
        permission_evidence_missing_risk=permission_missing,
        overall_rights_risk=overall,
        blockers=_unique(blockers, limit=32, maximum=600),
        warnings=_unique(warnings, limit=32, maximum=600),
        fixes=_unique(fixes, limit=32, maximum=600),
    )


def _checklist_item(
    item: BobaRightsReviewedItemV1,
    *,
    category: BobaPermissionChecklistCategoryV1,
    label: str,
    status: BobaPermissionChecklistStatusV1,
    required: bool,
    reason: str,
    human_action: str,
) -> BobaPermissionChecklistItemV1:
    return BobaPermissionChecklistItemV1(
        item_id=_stable_id(
            "rights_check",
            item.review_item_id,
            category,
        ),
        label=label,
        category=category,
        status=status,
        required=required,
        reason=reason,
        human_action=human_action,
    )


def build_permission_checklist(
    item: BobaRightsReviewedItemV1,
    risk: BobaRightsRiskReviewV1 | None = None,
) -> BobaPermissionChecklistV1:
    """Build the required per-item human permission checklist."""

    effective_risk = risk or build_rights_risk_review(item)
    ownership_confirmed = (
        item.declared_rights_status == "owned" and bool(item.ownership_notes)
    )
    license_confirmed = (
        item.declared_rights_status == "licensed" and bool(item.license_notes)
    )
    permission_granted = (
        item.declared_rights_status == "permission_granted"
        and bool(item.permission_notes)
    )
    evidence_present = bool(
        item.permission_notes
        or item.license_notes
        or item.ownership_notes
        or item.evidence_snippets
    )
    blocked = effective_risk.overall_rights_risk == "blocked"
    ownership_status: BobaPermissionChecklistStatusV1 = (
        "passed"
        if ownership_confirmed
        else (
            "unknown"
            if item.declared_rights_status in {"owned", "unknown"}
            else "not_applicable"
        )
    )
    license_status: BobaPermissionChecklistStatusV1 = (
        "passed"
        if license_confirmed
        else (
            "unknown"
            if item.declared_rights_status
            in {"licensed", "public_domain_claimed", "fair_use_claimed"}
            else "not_applicable"
        )
    )
    permission_status: BobaPermissionChecklistStatusV1 = (
        "blocked"
        if blocked
        else (
            "passed"
            if permission_granted
            else (
                "warning"
                if item.declared_rights_status == "permission_needed"
                else "unknown"
            )
        )
    )
    checklist_items = [
        _checklist_item(
            item,
            category="ownership",
            label="Ownership declaration and compact reference reviewed",
            status=ownership_status,
            required=item.declared_rights_status in {"owned", "unknown"},
            reason=(
                "An ownership note exists."
                if ownership_confirmed
                else "Ownership is not established by the available metadata."
            ),
            human_action="Confirm ownership and intended-use scope independently.",
        ),
        _checklist_item(
            item,
            category="license",
            label="License scope and compact reference reviewed",
            status=license_status,
            required=item.declared_rights_status
            in {"licensed", "public_domain_claimed", "fair_use_claimed"},
            reason=(
                "A compact license note exists."
                if license_confirmed
                else "License validity and scope remain unverified."
            ),
            human_action="Review the license or claimed exception with a qualified human.",
        ),
        _checklist_item(
            item,
            category="permission",
            label="Permission and evidence reference reviewed",
            status=permission_status,
            required=item.declared_rights_status
            in {"permission_granted", "permission_needed", "unknown"},
            reason=(
                "A compact permission note exists."
                if permission_granted
                else "Permission is missing, blocked, or unverified."
            ),
            human_action="Obtain and record sufficient permission before processing.",
        ),
        _checklist_item(
            item,
            category="platform_terms",
            label="Platform and source terms reviewed",
            status=(
                "warning"
                if effective_risk.platform_terms_risk
                else "not_applicable"
            ),
            required=effective_risk.platform_terms_risk,
            reason=(
                "Platform/source metadata is present."
                if effective_risk.platform_terms_risk
                else "No platform-specific cue was supplied."
            ),
            human_action="Review applicable platform and source terms.",
        ),
        _checklist_item(
            item,
            category="third_party_content",
            label="Third-party media elements reviewed",
            status=(
                "warning"
                if effective_risk.third_party_media_risk
                else "unknown"
            ),
            required=True,
            reason=(
                "Third-party media cues were detected."
                if effective_risk.third_party_media_risk
                else "Metadata cannot prove the absence of third-party media."
            ),
            human_action="Inspect the source and verify each third-party element.",
        ),
        _checklist_item(
            item,
            category="music_audio",
            label="Music, audio, and SFX rights reviewed",
            status=(
                "warning"
                if effective_risk.music_audio_rights_risk
                else "unknown"
            ),
            required=True,
            reason=(
                "Audio-rights warnings or cues are present."
                if effective_risk.music_audio_rights_risk
                else "Metadata cannot prove audio-rights readiness."
            ),
            human_action="Verify source audio, music, and SFX rights separately.",
        ),
        _checklist_item(
            item,
            category="people_privacy",
            label="People, privacy, consent, and release needs reviewed",
            status=(
                "warning"
                if effective_risk.privacy_release_risk
                else "not_applicable"
            ),
            required=effective_risk.privacy_release_risk,
            reason=(
                "People or privacy cues are present."
                if effective_risk.privacy_release_risk
                else "No people/privacy cue was supplied."
            ),
            human_action="Review consent, privacy, and release needs when relevant.",
        ),
        _checklist_item(
            item,
            category="source_quality",
            label="Source identity and evidence quality reviewed",
            status=(
                "warning"
                if effective_risk.source_ambiguity_risk
                else "passed"
            ),
            required=True,
            reason=(
                "Source identity or notes are ambiguous."
                if effective_risk.source_ambiguity_risk
                else "A compact source identity is present."
            ),
            human_action="Confirm the exact source and resolve conflicting notes.",
        ),
        _checklist_item(
            item,
            category="final_approval",
            label="Final human approval recorded",
            status="blocked" if blocked else "unknown",
            required=True,
            reason="V1 never grants final approval automatically.",
            human_action="A qualified human must approve or reject future processing.",
        ),
    ]
    return BobaPermissionChecklistV1(
        checklist_id=_stable_id(
            "permission_checklist",
            item.review_item_id,
        ),
        review_item_id=item.review_item_id,
        ownership_confirmed=ownership_confirmed,
        license_confirmed=license_confirmed,
        permission_granted=permission_granted,
        permission_evidence_reference_present=evidence_present,
        platform_terms_review_needed=effective_risk.platform_terms_risk,
        third_party_content_review_needed=(
            effective_risk.third_party_media_risk
        ),
        music_audio_rights_review_needed=(
            effective_risk.music_audio_rights_risk
        ),
        people_privacy_release_review_needed=(
            effective_risk.privacy_release_risk
        ),
        source_quality_review_needed=effective_risk.source_ambiguity_risk,
        final_human_approval_required=True,
        checklist_items=checklist_items,
        warnings=[
            "Checklist passes reflect user-provided notes only, not legal validation.",
            "Final human approval is always required.",
        ],
    )


def _gate_decision(
    item: BobaRightsReviewedItemV1,
    risk: BobaRightsRiskReviewV1,
) -> BobaRightsGateDecisionV1:
    status = item.declared_rights_status
    has_identity = _has_source_identity(item)
    has_conflict = _has_conflict(item)
    blocked_note = _contains_any(_item_text(item), _BLOCK_TERMS)
    if status == "blocked" or blocked_note:
        gate_status: BobaRightsGateStatusV1 = "blocked"
        reason = (
            "Declared status or compact notes explicitly block processing."
        )
    elif not has_identity:
        gate_status = "insufficient_information"
        reason = (
            "Source identity evidence is insufficient for a rights decision."
        )
    elif has_conflict:
        gate_status = "needs_rights_review"
        reason = (
            "Declared status conflicts with compact rights or permission notes."
        )
    elif status == "permission_needed":
        gate_status = "needs_permission"
        reason = "Permission is explicitly required before any future processing."
    elif status in {
        "unknown",
        "public_domain_claimed",
        "fair_use_claimed",
    }:
        gate_status = "needs_rights_review"
        reason = (
            "Unknown or claimed rights require qualified human review and evidence."
        )
    elif status in {"owned", "licensed", "permission_granted"} and not (
        _has_note_for_status(item)
    ):
        gate_status = "needs_rights_review"
        reason = (
            "The declared reviewable status lacks its required compact note or reference."
        )
    else:
        gate_status = "ready_for_human_review"
        reason = (
            "User-provided status and compact notes permit human source review only; "
            "they do not authorize ingestion or confirm copyright safety."
        )
    blocked = gate_status == "blocked"
    allow_human_review = not blocked
    allow_ingestion_precheck = gate_status == "ready_for_human_review"
    confidence = 0.28
    confidence += 0.12 if has_identity else 0.0
    confidence += 0.1 if item.source_reference or item.source_url else 0.0
    confidence += min(0.16, len(item.evidence_snippets) * 0.04)
    confidence += 0.2 if _has_note_for_status(item) else 0.0
    confidence += 0.08 if status not in {"unknown"} else 0.0
    confidence -= 0.24 if has_conflict else 0.0
    confidence -= 0.18 if not has_identity else 0.0
    if status in {"public_domain_claimed", "fair_use_claimed"}:
        confidence = min(confidence, 0.55)
    required_checks = [
        "Review the exact source and intended use.",
        "Confirm ownership, license scope, or explicit permission.",
        "Review platform/source terms and third-party elements.",
        "Review music/audio rights and people/privacy needs.",
        "Record final explicit human approval.",
    ]
    if gate_status == "needs_permission":
        required_checks.insert(0, "Obtain and record sufficient permission.")
    if gate_status in {
        "needs_rights_review",
        "insufficient_information",
    }:
        required_checks.insert(0, "Add compact rights evidence or references.")
    return BobaRightsGateDecisionV1(
        decision_id=_stable_id(
            "rights_gate_decision",
            item.review_item_id,
        ),
        review_item_id=item.review_item_id,
        candidate_video_id=item.candidate_video_id,
        gate_status=gate_status,
        allow_human_review=allow_human_review,
        allow_future_ingestion_precheck=allow_ingestion_precheck,
        requires_permission=gate_status == "needs_permission",
        requires_rights_review=gate_status
        in {"needs_rights_review", "insufficient_information"},
        blocked=blocked,
        decision_reason=reason,
        required_human_checks=required_checks,
        confidence=_clamp(confidence),
        warnings=[
            "This gate is advisory metadata review and is not legal advice.",
            "No decision confirms copyright safety, ownership, license validity, or fair use.",
        ],
        limitations=[
            "BOBA did not fetch, download, inspect, ingest, or render media.",
            "The gate cannot validate legal documents or platform permissions.",
        ],
    )


def build_future_ingestion_handoff(
    item: BobaRightsReviewedItemV1,
    decision: BobaRightsGateDecisionV1,
) -> BobaFutureIngestionHandoffV1:
    """Build a non-automatic handoff that never authorizes processing."""

    mapping: dict[
        BobaRightsGateStatusV1,
        tuple[BobaIngestionPrecheckStatusV1, BobaAllowedNextStepV1, str],
    ] = {
        "ready_for_human_review": (
            "eligible_for_manual_ingestion_review",
            "human_review_only",
            "",
        ),
        "needs_permission": (
            "permission_required_before_review",
            "seek_permission",
            "Permission is required before any future ingestion review.",
        ),
        "needs_rights_review": (
            "rights_review_required_before_review",
            "add_rights_evidence",
            "Rights evidence and human review are required.",
        ),
        "blocked": (
            "blocked",
            "do_not_process",
            "Declared status or notes block processing.",
        ),
        "insufficient_information": (
            "insufficient_information",
            "add_rights_evidence",
            "Source identity or rights evidence is insufficient.",
        ),
    }
    precheck, next_step, blocked_reason = mapping[decision.gate_status]
    return BobaFutureIngestionHandoffV1(
        handoff_id=_stable_id(
            "future_ingestion_handoff",
            item.review_item_id,
        ),
        review_item_id=item.review_item_id,
        candidate_video_id=item.candidate_video_id,
        ingestion_precheck_status=precheck,
        allowed_next_step=next_step,
        required_before_ingestion=[
            "A human reviews the actual source.",
            "Acceptable ownership, license, or permission evidence is confirmed.",
            "Platform, third-party, music/audio, and privacy risks are reviewed.",
            "Final explicit human approval is recorded.",
        ],
        blocked_reason=blocked_reason,
        apply_automatically=False,
        warnings=[
            "This handoff does not ingest, fetch, download, upload, or render media.",
            "Eligibility means manual review only and is not legal clearance.",
        ],
    )


def _artifact_warnings(
    artifact: ArtifactValue,
    *,
    keys: Sequence[str],
) -> list[str]:
    payload = _dict(artifact)
    values: list[str] = []
    stack: list[Any] = [payload]
    while stack and len(values) < 100:
        current = stack.pop()
        if isinstance(current, Mapping):
            for key, value in current.items():
                if key in keys:
                    if isinstance(value, str):
                        values.append(_text(value, maximum=600))
                    elif isinstance(value, list | tuple):
                        values.extend(
                            _text(item, maximum=600)
                            for item in value
                            if isinstance(item, str)
                        )
                elif isinstance(value, Mapping | list | tuple):
                    stack.append(value)
        elif isinstance(current, list | tuple):
            stack.extend(current)
    return _unique(values, limit=64, maximum=600)


def _candidate_rows(
    artifact: ArtifactValue,
) -> list[dict[str, Any]]:
    payload = _dict(artifact)
    rights_by_id: dict[str, dict[str, Any]] = {}
    for scored in _list(payload.get("scored_candidates")):
        if not isinstance(scored, Mapping):
            continue
        candidate = _dict(scored.get("candidate_video"))
        candidate_id = _text(
            candidate.get("candidate_video_id"),
            maximum=128,
        )
        rights_by_id[candidate_id] = _dict(scored.get("rights_review"))
    rows: list[dict[str, Any]] = []
    for candidate in _list(payload.get("candidate_videos")):
        if not isinstance(candidate, Mapping):
            continue
        candidate_id = _text(
            candidate.get("candidate_video_id"),
            maximum=128,
        )
        rights = rights_by_id.get(candidate_id, {})
        status = candidate.get("rights_status")
        notes = _text(candidate.get("permission_notes"), maximum=600)
        rows.append(
            {
                **dict(candidate),
                "declared_rights_status": status,
                "ownership_notes": notes if status == "owned" else "",
                "license_notes": notes if status == "licensed" else "",
                "permission_notes": notes,
                "evidence_snippets": [
                    {
                        "source_field": "candidate_rights_review",
                        "snippet": rights.get("reason"),
                        "confidence": 0.55,
                    }
                ],
            }
        )
    return rows


def _scout_rows(artifact: ArtifactValue) -> list[dict[str, Any]]:
    payload = _dict(artifact)
    rows: list[dict[str, Any]] = []
    for item in _list(payload.get("scout_items")):
        if not isinstance(item, Mapping):
            continue
        status = item.get("rights_status")
        notes = _text(item.get("permission_notes"), maximum=600)
        rows.append(
            {
                **dict(item),
                "source_item_id": item.get("item_id"),
                "declared_rights_status": status,
                "ownership_notes": notes if status == "owned" else "",
                "license_notes": notes if status == "licensed" else "",
                "permission_notes": notes,
            }
        )
    return rows


def _research_rows(artifact: ArtifactValue) -> list[dict[str, Any]]:
    payload = _dict(artifact)
    rows: list[dict[str, Any]] = []
    safety = _dict(payload.get("safety_review"))
    safety_warnings = _unique(
        [
            *_list(safety.get("rights_usage_warnings")),
            *_list(safety.get("copyrighted_content_warnings")),
            *_list(safety.get("blockers")),
        ],
        limit=16,
        maximum=300,
    )
    for source in _list(payload.get("research_sources")):
        if not isinstance(source, Mapping):
            continue
        rights_notes = _text(
            source.get("rights_usage_notes"),
            maximum=600,
        )
        status = _infer_status_from_notes(rights_notes)
        rows.append(
            {
                "source_item_id": source.get("research_source_id"),
                "title": source.get("title"),
                "source_label": source.get("source_label")
                or "research_brain",
                "source_reference": source.get("research_source_id"),
                "declared_rights_status": status,
                "ownership_notes": rights_notes if status == "owned" else "",
                "license_notes": rights_notes if status == "licensed" else "",
                "permission_notes": (
                    rights_notes
                    if status in {"permission_granted", "permission_needed"}
                    else ""
                ),
                "platform_source_notes": source.get(
                    "author_or_source_name"
                ),
                "evidence_snippets": [
                    {
                        "source_field": "rights_usage_notes",
                        "snippet": rights_notes,
                        "confidence": 0.45,
                    },
                    *[
                        {
                            "source_field": "research_safety_warning",
                            "snippet": warning,
                            "confidence": 0.35,
                        }
                        for warning in safety_warnings[:4]
                    ],
                ],
            }
        )
    return rows


def _trend_rows(artifact: ArtifactValue) -> list[dict[str, Any]]:
    payload = _dict(artifact)
    rows: list[dict[str, Any]] = []
    for snapshot in _list(payload.get("topic_snapshots")):
        if not isinstance(snapshot, Mapping):
            continue
        label = _text(
            snapshot.get("source_label"),
            maximum=160,
        ) or "trend_topic_watcher"
        platform = _text(
            snapshot.get("platform_label"),
            maximum=300,
        )
        for topic in _list(snapshot.get("topics")):
            if not isinstance(topic, Mapping):
                continue
            rights_note = _text(
                topic.get("rights_safety_note"),
                maximum=600,
            )
            if not rights_note:
                continue
            status = _infer_status_from_notes(rights_note)
            rows.append(
                {
                    "source_item_id": topic.get("topic_id"),
                    "title": topic.get("topic"),
                    "source_label": label,
                    "source_reference": topic.get("topic_id"),
                    "declared_rights_status": status,
                    "ownership_notes": rights_note
                    if status == "owned"
                    else "",
                    "license_notes": rights_note
                    if status == "licensed"
                    else "",
                    "permission_notes": rights_note
                    if status
                    in {"permission_granted", "permission_needed"}
                    else "",
                    "platform_source_notes": platform,
                    "evidence_snippets": [
                        {
                            "source_field": "rights_safety_note",
                            "snippet": rights_note,
                            "confidence": 0.4,
                        }
                    ],
                }
            )
    return rows


def _collect_rows(
    rows: Sequence[Any],
    *,
    project_id: str,
    source_label: str,
    source_artifact: str,
) -> tuple[list[BobaRightsReviewedItemV1], list[str]]:
    reviewed: list[BobaRightsReviewedItemV1] = []
    rejected: list[str] = []
    for item_index, raw in enumerate(rows):
        if not isinstance(raw, Mapping):
            rejected.append(f"Item {item_index + 1} was not an object.")
            continue
        try:
            reviewed.append(
                _normalize_review_item(
                    raw,
                    project_id=project_id,
                    source_label=source_label,
                    source_artifact=source_artifact,
                    item_index=item_index,
                )
            )
        except (ValidationError, ValueError) as exc:
            rejected.append(
                f"Item {item_index + 1}: {_text(exc, maximum=500)}"
            )
    return reviewed, rejected


def _deduplicate_items(
    items: Sequence[BobaRightsReviewedItemV1],
) -> list[BobaRightsReviewedItemV1]:
    deduplicated: list[BobaRightsReviewedItemV1] = []
    seen: set[tuple[str, str, str]] = set()
    for item in items:
        key = (
            item.candidate_video_id.casefold(),
            item.source_item_id.casefold(),
            (
                item.source_reference.casefold()
                or item.title.casefold()
                or item.review_item_id
            ),
        )
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(item)
    return deduplicated


def _summary(
    items: Sequence[BobaRightsReviewedItemV1],
    decisions: Sequence[BobaRightsGateDecisionV1],
    risks: Sequence[BobaRightsRiskReviewV1],
) -> BobaRightsSummaryV1:
    statuses = Counter(item.declared_rights_status for item in items)
    gates = Counter(decision.gate_status for decision in decisions)
    common_risks: list[str] = []
    risk_counts = {
        "Unknown or claimed rights": sum(
            risk.unknown_rights_risk for risk in risks
        ),
        "Third-party media": sum(
            risk.third_party_media_risk for risk in risks
        ),
        "Music/audio rights": sum(
            risk.music_audio_rights_risk for risk in risks
        ),
        "Platform terms": sum(risk.platform_terms_risk for risk in risks),
        "People/privacy releases": sum(
            risk.privacy_release_risk for risk in risks
        ),
        "Source ambiguity": sum(
            risk.source_ambiguity_risk for risk in risks
        ),
        "Copyrighted source material": sum(
            risk.copyrighted_source_material_risk for risk in risks
        ),
        "Missing permission evidence": sum(
            risk.permission_evidence_missing_risk for risk in risks
        ),
    }
    for label, count in sorted(
        risk_counts.items(),
        key=lambda item: (item[1], item[0]),
        reverse=True,
    ):
        if count:
            common_risks.append(f"{label}: {count} item(s).")
    return BobaRightsSummaryV1(
        total_reviewed=len(items),
        ready_for_human_review_count=gates["ready_for_human_review"],
        needs_permission_count=gates["needs_permission"],
        needs_rights_review_count=gates["needs_rights_review"],
        blocked_count=gates["blocked"],
        insufficient_information_count=gates["insufficient_information"],
        common_risks=common_risks[:32],
        rights_status_breakdown=dict(sorted(statuses.items())),
        human_review_notes=[
            "Review the actual source and intended use.",
            "Unknown or claimed rights are never safe or ingestion-ready.",
            "Ready status permits human review only, never automatic ingestion.",
            "A qualified human must record final approval.",
        ],
        limitations=[
            "Counts reflect local/user-provided metadata, not legal validation.",
            "The gate does not confirm ownership, license validity, permission, "
            "fair use, or public-domain status.",
        ],
    )


class BobaRightsPermissionGateV1:
    """Review compact rights metadata without network or media access."""

    def analyze(
        self,
        project_id: str,
        *,
        source_id: str | None = None,
        manual_items: Sequence[Mapping[str, Any]] = (),
        source_label: str = "manual",
        candidate_video_scorer: ArtifactValue = None,
        content_scout: ArtifactValue = None,
        research_brain: ArtifactValue = None,
        trend_topic_watcher: ArtifactValue = None,
        clip_briefs: ArtifactValue = None,
        music_mood: ArtifactValue = None,
        boba_memory: ArtifactValue = None,
        dry_run: bool = False,
    ) -> BobaRightsPermissionGateSetV1:
        artifacts = {
            "candidate_video_scorer": _dict(candidate_video_scorer),
            "content_scout": _dict(content_scout),
            "research_brain": _dict(research_brain),
            "trend_topic_watcher": _dict(trend_topic_watcher),
            "clip_briefs": _dict(clip_briefs),
            "music_mood": _dict(music_mood),
            "memory": _dict(boba_memory),
        }
        collection_inputs: list[tuple[str, str, Sequence[Any]]] = []
        if manual_items:
            collection_inputs.append(
                ("manual", source_label, list(manual_items))
            )
        if artifacts["candidate_video_scorer"]:
            collection_inputs.append(
                (
                    "candidate_video_scorer",
                    "candidate_video_scorer",
                    _candidate_rows(candidate_video_scorer),
                )
            )
        if artifacts["content_scout"]:
            collection_inputs.append(
                (
                    "content_scout_v2",
                    "content_scout_v2",
                    _scout_rows(content_scout),
                )
            )
        if artifacts["research_brain"]:
            collection_inputs.append(
                (
                    "research_brain",
                    "research_brain",
                    _research_rows(research_brain),
                )
            )
        if artifacts["trend_topic_watcher"]:
            collection_inputs.append(
                (
                    "trend_topic_watcher",
                    "trend_topic_watcher",
                    _trend_rows(trend_topic_watcher),
                )
            )
        reviewed: list[BobaRightsReviewedItemV1] = []
        rejected: list[str] = []
        for artifact_name, label, rows in collection_inputs:
            values, invalid = _collect_rows(
                rows,
                project_id=project_id,
                source_label=label,
                source_artifact=artifact_name,
            )
            reviewed.extend(values)
            rejected.extend(invalid)
        reviewed = _deduplicate_items(reviewed)
        research_warnings = _artifact_warnings(
            research_brain,
            keys=(
                "rights_usage_warnings",
                "copyrighted_content_warnings",
                "blockers",
            ),
        )
        trend_warnings = _artifact_warnings(
            trend_topic_watcher,
            keys=("rights_safety_note", "rights_review_reminders"),
        )
        clip_warnings = _artifact_warnings(
            clip_briefs,
            keys=("risk_warnings", "warnings", "limitations"),
        )
        clip_warnings = [
            warning
            for warning in clip_warnings
            if any(
                term in warning.casefold()
                for term in ("rights", "copyright", "permission")
            )
        ][:32]
        music_warnings = _artifact_warnings(
            music_mood,
            keys=(
                "rights_review_warning",
                "warnings",
                "blockers",
                "fixes",
            ),
        )
        music_warnings = [
            warning
            for warning in music_warnings
            if any(
                term in warning.casefold()
                for term in ("rights", "copyright", "music", "audio")
            )
        ][:32]
        risk_reviews = [
            build_rights_risk_review(
                item,
                research_warnings=research_warnings,
                trend_warnings=trend_warnings,
                clip_brief_warnings=clip_warnings,
                music_mood_warnings=music_warnings,
            )
            for item in reviewed
        ]
        risk_by_item = {
            risk.review_item_id: risk for risk in risk_reviews
        }
        decisions = [
            _gate_decision(item, risk_by_item[item.review_item_id])
            for item in reviewed
        ]
        permission_checklists = [
            build_permission_checklist(
                item,
                risk_by_item[item.review_item_id],
            )
            for item in reviewed
        ]
        handoffs = [
            build_future_ingestion_handoff(item, decision)
            for item, decision in zip(reviewed, decisions, strict=True)
        ]
        unavailable = [
            name for name, artifact in artifacts.items() if not artifact
        ]
        warnings = [
            "Rights + Permission Gate V1 used local/user-provided metadata only.",
            "BOBA did not fetch URLs, scrape, download, ingest media, render, "
            "or call external APIs.",
            "The gate is not legal advice and does not confirm copyright safety.",
            "Unknown or claimed rights are never treated as safe.",
        ]
        if rejected:
            warnings.append(
                f"{len(rejected)} invalid rights review item(s) were rejected."
            )
            warnings.extend(rejected[:12])
        if not reviewed:
            warnings.append(
                "No reviewable rights metadata was available; future ingestion remains blocked."
            )
        if dry_run:
            warnings.append("Dry run: the rights gate artifact was not persisted.")
        return BobaRightsPermissionGateSetV1(
            project_id=project_id,
            source_id=_text(source_id or project_id, maximum=512),
            reviewed_items=reviewed,
            gate_decisions=decisions,
            permission_checklists=permission_checklists,
            risk_reviews=risk_reviews,
            future_ingestion_handoffs=handoffs,
            rights_summary=_summary(reviewed, decisions, risk_reviews),
            signal_usage=BobaRightsPermissionSignalUsageV1(
                candidate_video_scorer_used=bool(
                    artifacts["candidate_video_scorer"]
                ),
                content_scout_used=bool(artifacts["content_scout"]),
                research_brain_used=bool(artifacts["research_brain"]),
                trend_topic_watcher_used=bool(
                    artifacts["trend_topic_watcher"]
                ),
                clip_briefs_used=bool(artifacts["clip_briefs"]),
                music_mood_used=bool(artifacts["music_mood"]),
                memory_used=bool(artifacts["memory"]),
                manual_input_used=bool(manual_items),
                external_api_used=False,
                url_fetching_used=False,
                scraping_used=False,
                downloading_used=False,
                media_ingestion_used=False,
                legal_validation_used=False,
                fallback_used=bool(unavailable),
                unavailable_signals=unavailable,
                warnings=(
                    [
                        "Missing optional BOBA artifacts limited metadata context."
                    ]
                    if unavailable
                    else []
                ),
            ),
            warnings=_unique(warnings, limit=64, maximum=700),
            limitations=[
                "V1 does not provide legal advice or validate legal documents.",
                "V1 does not confirm ownership, license validity, permission, "
                "fair use, public-domain status, or copyright safety.",
                "V1 does not inspect, fetch, download, upload, ingest, or render media.",
                "All decisions and handoffs are advisory and require final human review.",
                "Future provider, legal, platform, and ingestion enforcement "
                "integrations remain separate.",
            ],
        )


def generate_rights_permission_gate(
    project_id: str,
    **kwargs: Any,
) -> BobaRightsPermissionGateSetV1:
    """Convenience wrapper for deterministic local rights review."""

    return BobaRightsPermissionGateV1().analyze(project_id, **kwargs)
