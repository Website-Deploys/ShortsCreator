"""Local snapshot-based topic movement intelligence for BOBA."""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from difflib import SequenceMatcher
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, Field

from olympus.boba.contracts import BobaContract, now_iso
from olympus.platform.errors import ValidationError

BobaTrendTopicSourceTypeV1 = Literal[
    "csv",
    "json",
    "manual",
    "pasted_text",
    "research_brain",
    "content_scout",
    "test_synthetic",
]
BobaTopicMovementTypeV1 = Literal[
    "repeated",
    "new",
    "rising_within_provided_data",
    "fading_within_provided_data",
    "stable",
    "duplicate_or_similar",
    "uncertain",
]
ArtifactValue: TypeAlias = Mapping[str, Any] | BaseModel | None
TopicImportResult: TypeAlias = tuple[
    "BobaTrendTopicImportSourceV1",
    list["BobaTopicSnapshotV1"],
    list[str],
]

_SPACE = re.compile(r"\s+")
_NON_TOPIC = re.compile(r"[^\w\s-]+", re.UNICODE)
_TOKEN = re.compile(r"[a-z0-9][a-z0-9'-]*")
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_MAX_IMPORT_BYTES = 2_000_000
_MAX_PASTED_CHARS = 20_000
_VAGUE_TOPICS = {
    "content",
    "general",
    "idea",
    "misc",
    "miscellaneous",
    "other",
    "stuff",
    "thing",
    "topic",
    "update",
}
_SHORTABILITY_TERMS = {
    "before",
    "comparison",
    "explainer",
    "how",
    "lesson",
    "list",
    "mistake",
    "myth",
    "story",
    "tutorial",
    "versus",
    "why",
}
_HOOK_TERMS = {
    "controversy",
    "mistake",
    "myth",
    "reason",
    "secret",
    "surprising",
    "truth",
    "unexpected",
    "why",
}
_RISK_TERMS = {
    "blocked",
    "copyright",
    "copied",
    "dangerous",
    "diagnosis",
    "financial",
    "guaranteed",
    "legal",
    "medical",
    "permission unknown",
    "prohibited",
    "unverified",
}


def _text(value: Any, *, maximum: int = 800) -> str:
    return _SPACE.sub(" ", str(value or "")).strip()[:maximum]


def _dict(value: Any) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list | tuple | set) else []


def _clamp(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 4)


def _stable_id(prefix: str, *values: str) -> str:
    digest = sha256("|".join(values).encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


def _compact_values(value: Any, *, maximum: int = 32) -> list[str]:
    if isinstance(value, str):
        values = re.split(r"[,;|]", value)
    elif isinstance(value, list | tuple | set):
        values = list(value)
    else:
        values = []
    return list(
        dict.fromkeys(
            item
            for raw in values
            if (item := _text(raw, maximum=100))
        )
    )[:maximum]


def _tokens(*values: Any) -> set[str]:
    return {
        token
        for value in values
        for token in _TOKEN.findall(_text(value, maximum=5_000).casefold())
        if len(token) >= 3
    }


def _safe_local_file(path: str | Path, *, suffix: str) -> Path:
    raw = str(path)
    if "://" in raw:
        raise ValidationError("Trend / Topic Watcher import paths must be local files.")
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise ValidationError("Trend / Topic Watcher import file was not found.")
    if source.suffix.casefold() != suffix:
        raise ValidationError(
            f"Trend / Topic Watcher expected a local {suffix} file."
        )
    if source.stat().st_size > _MAX_IMPORT_BYTES:
        raise ValidationError(
            "Trend / Topic Watcher import exceeds the 2 MB safety limit."
        )
    return source


def _optional_number(
    value: Any,
    *,
    field_name: str,
    warnings: list[str],
) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        warnings.append(f"{field_name} was not numeric and was ignored.")
        return None
    if parsed < 0:
        warnings.append(f"{field_name} was negative and was ignored.")
        return None
    return round(parsed, 4)


def _singular_token(token: str) -> str:
    if len(token) <= 4 or token.endswith(("ss", "us", "is")):
        return token
    if token.endswith("ies") and len(token) > 5:
        return f"{token[:-3]}y"
    if token.endswith("ses") and len(token) > 5:
        return token[:-2]
    if token.endswith("s"):
        return token[:-1]
    return token


def normalize_topic_text(value: Any) -> str:
    """Normalize conservatively without merging unrelated topic concepts."""
    lowered = _text(value, maximum=200).casefold().replace("&", " and ")
    cleaned = _SPACE.sub(" ", _NON_TOPIC.sub(" ", lowered).replace("-", " ")).strip()
    return " ".join(_singular_token(token) for token in cleaned.split())


class BobaTrendTopicImportSourceV1(BobaContract):
    import_id: str = Field(min_length=1, max_length=128)
    source_type: BobaTrendTopicSourceTypeV1
    source_label: str = Field(min_length=1, max_length=160)
    source_path: str = Field(default="", max_length=260)
    imported_at: str = Field(default_factory=now_iso)
    item_count: int = Field(default=0, ge=0)
    accepted_count: int = Field(default=0, ge=0)
    rejected_count: int = Field(default=0, ge=0)
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=32)


class BobaTopicEntryV1(BobaContract):
    topic_id: str = Field(min_length=1, max_length=128)
    topic: str = Field(min_length=1, max_length=200)
    normalized_topic: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=800)
    tags: list[str] = Field(default_factory=list, max_length=32)
    categories: list[str] = Field(default_factory=list, max_length=32)
    user_rank: float | None = Field(default=None, ge=0.0)
    user_frequency: float | None = Field(default=None, ge=0.0)
    user_score: float | None = Field(default=None, ge=0.0)
    source_label: str = Field(min_length=1, max_length=160)
    evidence_note: str = Field(default="", max_length=600)
    rights_safety_note: str = Field(default="", max_length=600)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaTopicSnapshotV1(BobaContract):
    snapshot_id: str = Field(min_length=1, max_length=128)
    source_label: str = Field(min_length=1, max_length=160)
    captured_at: str = Field(min_length=1, max_length=80)
    platform_label: str = Field(default="", max_length=120)
    topics: list[BobaTopicEntryV1] = Field(default_factory=list, max_length=5_000)
    source_notes: str = Field(default="", max_length=800)
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=32)


class BobaTopicMovementItemV1(BobaContract):
    topic: str = Field(min_length=1, max_length=200)
    normalized_topic: str = Field(min_length=1, max_length=200)
    movement_type: BobaTopicMovementTypeV1
    snapshot_count: int = Field(default=0, ge=0)
    previous_score: float | None = None
    latest_score: float | None = None
    delta: float | None = None
    evidence_sources: list[str] = Field(default_factory=list, max_length=64)
    reason: str = Field(min_length=1, max_length=800)
    confidence: float = Field(ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaTopicMovementAnalysisV1(BobaContract):
    repeated_topics: list[BobaTopicMovementItemV1] = Field(
        default_factory=list,
        max_length=500,
    )
    newly_appearing_topics: list[BobaTopicMovementItemV1] = Field(
        default_factory=list,
        max_length=500,
    )
    rising_topics_within_provided_data: list[BobaTopicMovementItemV1] = Field(
        default_factory=list,
        max_length=500,
    )
    fading_topics_within_provided_data: list[BobaTopicMovementItemV1] = Field(
        default_factory=list,
        max_length=500,
    )
    stable_topics: list[BobaTopicMovementItemV1] = Field(
        default_factory=list,
        max_length=500,
    )
    duplicate_or_similar_topics: list[BobaTopicMovementItemV1] = Field(
        default_factory=list,
        max_length=500,
    )
    uncertain_topics: list[BobaTopicMovementItemV1] = Field(
        default_factory=list,
        max_length=500,
    )
    analysis_notes: list[str] = Field(default_factory=list, max_length=64)
    warnings: list[str] = Field(default_factory=list, max_length=64)


class BobaTopicOpportunityScoreV1(BobaContract):
    topic: str = Field(min_length=1, max_length=200)
    normalized_topic: str = Field(min_length=1, max_length=200)
    creator_fit_score: float = Field(ge=0.0, le=1.0)
    research_support_score: float = Field(ge=0.0, le=1.0)
    scout_support_score: float = Field(ge=0.0, le=1.0)
    shortability_score: float = Field(ge=0.0, le=1.0)
    hook_potential_score: float = Field(ge=0.0, le=1.0)
    freshness_within_user_data_score: float = Field(ge=0.0, le=1.0)
    risk_score: float = Field(ge=0.0, le=1.0)
    overall_topic_priority_score: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    reasons: list[str] = Field(default_factory=list, max_length=32)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaWatchedTopicV1(BobaContract):
    watched_topic_id: str = Field(min_length=1, max_length=128)
    topic: str = Field(min_length=1, max_length=200)
    normalized_topic: str = Field(min_length=1, max_length=200)
    reason_for_watch: str = Field(min_length=1, max_length=800)
    creator_fit: float = Field(ge=0.0, le=1.0)
    research_fit: float = Field(ge=0.0, le=1.0)
    scout_fit: float = Field(ge=0.0, le=1.0)
    content_angle_potential: float = Field(ge=0.0, le=1.0)
    suggested_angles: list[str] = Field(default_factory=list, max_length=12)
    human_review_notes: list[str] = Field(default_factory=list, max_length=16)
    confidence: float = Field(ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaTrendConfidenceReviewV1(BobaContract):
    overall_confidence: float = Field(ge=0.0, le=1.0)
    snapshot_count: int = Field(default=0, ge=0)
    source_count: int = Field(default=0, ge=0)
    strongest_evidence: list[str] = Field(default_factory=list, max_length=32)
    weakest_evidence: list[str] = Field(default_factory=list, max_length=32)
    not_real_time_verified: Literal[True] = True
    weak_data_warnings: list[str] = Field(default_factory=list, max_length=64)
    human_verification_notes: list[str] = Field(
        default_factory=list,
        max_length=32,
    )
    warnings: list[str] = Field(default_factory=list, max_length=64)


class BobaTrendContentScoutHandoffV1(BobaContract):
    recommended_scout_topics: list[str] = Field(default_factory=list, max_length=32)
    recommended_keywords: list[str] = Field(default_factory=list, max_length=64)
    recommended_categories: list[str] = Field(default_factory=list, max_length=32)
    topics_to_avoid: list[str] = Field(default_factory=list, max_length=32)
    rights_review_reminders: list[str] = Field(default_factory=list, max_length=32)
    scout_review_questions: list[str] = Field(default_factory=list, max_length=32)
    apply_automatically: Literal[False] = False


class BobaTrendResearchBrainHandoffV1(BobaContract):
    recommended_research_topics: list[str] = Field(
        default_factory=list,
        max_length=32,
    )
    claims_to_verify: list[str] = Field(default_factory=list, max_length=32)
    audience_questions_to_research: list[str] = Field(
        default_factory=list,
        max_length=32,
    )
    sources_needed: list[str] = Field(default_factory=list, max_length=32)
    apply_automatically: Literal[False] = False


class BobaTrendWatcherSummaryV1(BobaContract):
    total_snapshots: int = Field(default=0, ge=0)
    total_topics: int = Field(default=0, ge=0)
    watched_topic_count: int = Field(default=0, ge=0)
    rising_count: int = Field(default=0, ge=0)
    repeated_count: int = Field(default=0, ge=0)
    fading_count: int = Field(default=0, ge=0)
    strongest_topics: list[str] = Field(default_factory=list, max_length=32)
    riskiest_topics: list[str] = Field(default_factory=list, max_length=32)
    human_review_notes: list[str] = Field(default_factory=list, max_length=32)


class BobaTrendTopicSignalUsageV1(BobaContract):
    research_brain_used: bool = False
    content_scout_used: bool = False
    creator_learning_used: bool = False
    performance_feedback_used: bool = False
    memory_used: bool = False
    local_import_used: bool = False
    manual_input_used: bool = False
    external_api_used: Literal[False] = False
    url_fetching_used: Literal[False] = False
    scraping_used: Literal[False] = False
    platform_monitoring_used: Literal[False] = False
    downloading_used: Literal[False] = False
    fallback_used: bool = False
    unavailable_signals: list[str] = Field(default_factory=list, max_length=32)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaTrendTopicWatcherSetV1(BobaContract):
    schema_version: Literal[
        "boba_trend_topic_watcher_v1"
    ] = "boba_trend_topic_watcher_v1"
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(min_length=1, max_length=512)
    created_at: str = Field(default_factory=now_iso)
    imported_sources: list[BobaTrendTopicImportSourceV1] = Field(
        default_factory=list,
        max_length=200,
    )
    topic_snapshots: list[BobaTopicSnapshotV1] = Field(
        default_factory=list,
        max_length=2_000,
    )
    watched_topics: list[BobaWatchedTopicV1] = Field(
        default_factory=list,
        max_length=500,
    )
    movement_analysis: BobaTopicMovementAnalysisV1
    opportunity_scores: list[BobaTopicOpportunityScoreV1] = Field(
        default_factory=list,
        max_length=2_000,
    )
    confidence_review: BobaTrendConfidenceReviewV1
    content_scout_handoff: BobaTrendContentScoutHandoffV1
    research_brain_handoff: BobaTrendResearchBrainHandoffV1
    watcher_summary: BobaTrendWatcherSummaryV1
    signal_usage: BobaTrendTopicSignalUsageV1
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)


def normalize_topic_entry(
    raw: Mapping[str, Any],
    *,
    source_label: str = "manual",
    item_index: int = 0,
) -> BobaTopicEntryV1:
    topic = _text(
        raw.get("topic") or raw.get("title") or raw.get("keyword"),
        maximum=200,
    )
    normalized = normalize_topic_text(topic)
    if not topic or not normalized:
        raise ValidationError(
            "Topic entry requires a non-empty topic, title, or keyword.",
            details={"item_index": item_index},
        )
    effective_label = _text(
        raw.get("source_label") or raw.get("source") or source_label,
        maximum=160,
    ) or source_label
    warnings: list[str] = []
    supplied_id = _text(raw.get("topic_id"), maximum=128)
    topic_id = (
        supplied_id
        if _SAFE_ID.fullmatch(supplied_id)
        else _stable_id(
            "topic",
            effective_label,
            str(item_index),
            normalized,
        )
    )
    return BobaTopicEntryV1(
        topic_id=topic_id,
        topic=topic,
        normalized_topic=normalized,
        description=_text(raw.get("description") or raw.get("summary")),
        tags=_compact_values(raw.get("tags"), maximum=32),
        categories=_compact_values(
            raw.get("categories") or raw.get("category"),
            maximum=32,
        ),
        user_rank=_optional_number(
            raw.get("rank") if "rank" in raw else raw.get("user_rank"),
            field_name="rank",
            warnings=warnings,
        ),
        user_frequency=_optional_number(
            (
                raw.get("frequency")
                if "frequency" in raw
                else raw.get("user_frequency")
            ),
            field_name="frequency",
            warnings=warnings,
        ),
        user_score=_optional_number(
            raw.get("score") if "score" in raw else raw.get("user_score"),
            field_name="score",
            warnings=warnings,
        ),
        source_label=effective_label,
        evidence_note=_text(
            raw.get("evidence_note") or raw.get("evidence") or raw.get("notes"),
            maximum=600,
        ),
        rights_safety_note=_text(
            raw.get("rights_safety_note")
            or raw.get("rights_notes")
            or raw.get("safety_notes"),
            maximum=600,
        ),
        warnings=warnings,
    )


def _snapshot(
    entries: Sequence[BobaTopicEntryV1],
    *,
    source_label: str,
    captured_at: str,
    platform_label: str = "",
    source_notes: str = "",
    warnings: Sequence[str] = (),
) -> BobaTopicSnapshotV1:
    return BobaTopicSnapshotV1(
        snapshot_id=_stable_id(
            "topic_snapshot",
            source_label,
            captured_at,
            platform_label,
            *sorted(entry.normalized_topic for entry in entries),
        ),
        source_label=source_label,
        captured_at=captured_at,
        platform_label=platform_label,
        topics=list(entries),
        source_notes=source_notes,
        warnings=list(warnings),
        limitations=[
            "Snapshot reflects only local/user-provided topic data.",
            "Platform labels and numeric fields were not externally verified.",
        ],
    )


def _import_rows(
    values: Sequence[Any],
    *,
    source_type: BobaTrendTopicSourceTypeV1,
    source_label: str,
    source_path: str = "",
    default_captured_at: str = "",
    default_platform_label: str = "",
) -> TopicImportResult:
    accepted_groups: dict[
        tuple[str, str, str, str],
        list[BobaTopicEntryV1],
    ] = defaultdict(list)
    rejected: list[str] = []
    for item_index, value in enumerate(values):
        if not isinstance(value, Mapping):
            rejected.append(f"Row {item_index + 1} was not an object.")
            continue
        try:
            effective_label = _text(
                value.get("source_label") or value.get("source") or source_label,
                maximum=160,
            ) or source_label
            captured_at = _text(
                value.get("captured_at")
                or value.get("captured")
                or value.get("date")
                or default_captured_at
                or now_iso(),
                maximum=80,
            )
            platform_label = _text(
                value.get("platform")
                or value.get("platform_label")
                or default_platform_label,
                maximum=120,
            )
            source_notes = _text(
                value.get("source_notes") or value.get("snapshot_notes"),
                maximum=800,
            )
            entry = normalize_topic_entry(
                value,
                source_label=effective_label,
                item_index=item_index,
            )
            accepted_groups[
                (effective_label, captured_at, platform_label, source_notes)
            ].append(entry)
        except (ValidationError, ValueError) as exc:
            rejected.append(f"Row {item_index + 1}: {_text(exc, maximum=500)}")
    snapshots = [
        _snapshot(
            entries,
            source_label=group_label,
            captured_at=captured_at,
            platform_label=platform_label,
            source_notes=source_notes,
        )
        for (
            group_label,
            captured_at,
            platform_label,
            source_notes,
        ), entries in accepted_groups.items()
    ]
    accepted_count = sum(len(snapshot.topics) for snapshot in snapshots)
    warnings = (
        [
            f"{len(rejected)} invalid topic entry or row(s) were rejected "
            "without stopping the remaining import.",
            *rejected[:20],
        ]
        if rejected
        else []
    )
    imported = BobaTrendTopicImportSourceV1(
        import_id=_stable_id(
            "topic_import",
            source_type,
            source_label,
            source_path,
            str(len(values)),
        ),
        source_type=source_type,
        source_label=source_label,
        source_path=source_path,
        item_count=len(values),
        accepted_count=accepted_count,
        rejected_count=len(rejected),
        warnings=warnings,
        limitations=[
            "Only compact topic metadata was imported.",
            "No URL, platform, or external API was contacted.",
        ],
    )
    return imported, snapshots, rejected


def _import_snapshot_objects(
    values: Sequence[Any],
    *,
    source_type: BobaTrendTopicSourceTypeV1,
    source_label: str,
    source_path: str = "",
) -> TopicImportResult:
    imported_sources: list[BobaTrendTopicImportSourceV1] = []
    snapshots: list[BobaTopicSnapshotV1] = []
    rejected: list[str] = []
    item_count = 0
    accepted_count = 0
    for snapshot_index, value in enumerate(values):
        if not isinstance(value, Mapping):
            rejected.append(f"Snapshot {snapshot_index + 1} was not an object.")
            item_count += 1
            continue
        nested = (
            value.get("topics")
            or value.get("topic_entries")
            or value.get("items")
        )
        if isinstance(nested, list):
            nested_rows = [
                {
                    **dict(row),
                    "source_label": (
                        row.get("source_label")
                        or value.get("source_label")
                        or value.get("source")
                        or source_label
                    ),
                    "captured_at": (
                        row.get("captured_at")
                        or value.get("captured_at")
                        or value.get("date")
                        or now_iso()
                    ),
                    "platform": (
                        row.get("platform")
                        or value.get("platform")
                        or value.get("platform_label")
                        or ""
                    ),
                    "source_notes": (
                        value.get("source_notes")
                        or value.get("notes")
                        or ""
                    ),
                }
                if isinstance(row, Mapping)
                else row
                for row in nested
            ]
        else:
            nested_rows = [value]
        imported, imported_snapshots, nested_rejected = _import_rows(
            nested_rows,
            source_type=source_type,
            source_label=_text(
                value.get("source_label") or value.get("source") or source_label,
                maximum=160,
            )
            or source_label,
            source_path=source_path,
            default_captured_at=_text(
                value.get("captured_at") or value.get("date") or now_iso(),
                maximum=80,
            ),
            default_platform_label=_text(
                value.get("platform") or value.get("platform_label"),
                maximum=120,
            ),
        )
        imported_sources.append(imported)
        snapshots.extend(imported_snapshots)
        rejected.extend(
            f"Snapshot {snapshot_index + 1}: {message}"
            for message in nested_rejected
        )
        item_count += imported.item_count
        accepted_count += imported.accepted_count
    imported = BobaTrendTopicImportSourceV1(
        import_id=_stable_id(
            "topic_import",
            source_type,
            source_label,
            source_path,
            str(item_count),
        ),
        source_type=source_type,
        source_label=source_label,
        source_path=source_path,
        item_count=item_count,
        accepted_count=accepted_count,
        rejected_count=len(rejected),
        warnings=(
            [
                f"{len(rejected)} invalid topic entry or snapshot(s) were rejected.",
                *rejected[:20],
            ]
            if rejected
            else []
        ),
        limitations=[
            "Only compact topic snapshots were retained.",
            "No external trend verification was performed.",
        ],
    )
    return imported, snapshots, rejected


def import_topics_from_manual(
    values: Sequence[Mapping[str, Any]],
    *,
    source_label: str = "manual",
    source_type: BobaTrendTopicSourceTypeV1 = "manual",
) -> TopicImportResult:
    return _import_snapshot_objects(
        values,
        source_type=source_type,
        source_label=source_label,
    )


def import_topics_from_csv(
    path: str | Path,
    *,
    source_label: str = "",
) -> TopicImportResult:
    source = _safe_local_file(path, suffix=".csv")
    try:
        with source.open("r", encoding="utf-8-sig", newline="") as handle:
            values = list(csv.DictReader(handle))
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ValidationError(
            "Trend / Topic Watcher CSV import could not be parsed."
        ) from exc
    return _import_rows(
        values,
        source_type="csv",
        source_label=source_label or source.stem,
        source_path=source.name,
    )


def import_topics_from_json(
    path: str | Path,
    *,
    source_label: str = "",
) -> TopicImportResult:
    source = _safe_local_file(path, suffix=".json")
    try:
        raw = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValidationError(
            "Trend / Topic Watcher JSON import could not be parsed."
        ) from exc
    values: list[Any]
    if isinstance(raw, list):
        values = list(raw)
    elif isinstance(raw, Mapping):
        raw_values = (
            raw.get("snapshots")
            or raw.get("topics")
            or raw.get("topic_entries")
            or raw.get("items")
        )
        if not isinstance(raw_values, list):
            raise ValidationError(
                "Trend / Topic Watcher JSON must be a list or contain "
                "topics, topic_entries, items, or snapshots."
            )
        values = list(raw_values)
    else:
        raise ValidationError(
            "Trend / Topic Watcher JSON must contain objects or snapshots."
        )
    return _import_snapshot_objects(
        values,
        source_type="json",
        source_label=source_label or source.stem,
        source_path=source.name,
    )


def import_topics_from_pasted_text(
    values: Sequence[str | Mapping[str, Any]],
    *,
    source_label: str = "pasted_text",
) -> TopicImportResult:
    rows: list[dict[str, Any]] = []
    rejected: list[str] = []
    for value_index, value in enumerate(values):
        if isinstance(value, Mapping):
            text_value = value.get("text") or value.get("topics")
            captured_at = value.get("captured_at") or value.get("date") or now_iso()
            effective_label = (
                value.get("source_label") or value.get("source") or source_label
            )
            platform = value.get("platform") or value.get("platform_label") or ""
        else:
            text_value = value
            captured_at = now_iso()
            effective_label = source_label
            platform = ""
        compact = _text(text_value, maximum=_MAX_PASTED_CHARS)
        if not compact:
            rejected.append(f"Pasted topic list {value_index + 1} was empty.")
            continue
        topic_values = [
            item
            for part in compact.splitlines()
            for item in re.split(r"[,;|]", part)
            if _text(item, maximum=200)
        ]
        if not topic_values:
            rejected.append(
                f"Pasted topic list {value_index + 1} contained no usable topics."
            )
            continue
        rows.extend(
            {
                "topic": topic,
                "captured_at": captured_at,
                "source_label": effective_label,
                "platform": platform,
            }
            for topic in topic_values
        )
    imported, snapshots, row_rejected = _import_rows(
        rows,
        source_type="pasted_text",
        source_label=source_label,
    )
    all_rejected = [*rejected, *row_rejected]
    if all_rejected:
        imported = imported.model_copy(
            update={
                "item_count": imported.item_count + len(rejected),
                "rejected_count": len(all_rejected),
                "warnings": [
                    f"{len(all_rejected)} pasted topic item(s) were rejected.",
                    *all_rejected[:20],
                ],
            }
        )
    return imported, snapshots, all_rejected


def group_similar_topics(
    topics: Sequence[str | BobaTopicEntryV1],
) -> dict[str, list[str]]:
    """Group exact/plural variants and only very-high-similarity topic strings."""
    values = [
        item.topic if isinstance(item, BobaTopicEntryV1) else _text(item, maximum=200)
        for item in topics
    ]
    groups: dict[str, list[str]] = {}
    for value in values:
        normalized = normalize_topic_text(value)
        if not normalized:
            continue
        match = next(
            (
                canonical
                for canonical in groups
                if canonical == normalized
                or (
                    SequenceMatcher(None, canonical, normalized).ratio() >= 0.92
                    and abs(len(canonical) - len(normalized)) <= 3
                )
            ),
            None,
        )
        canonical = match or normalized
        groups.setdefault(canonical, [])
        if value and value not in groups[canonical]:
            groups[canonical].append(value)
    return groups


def _metric_value(entry: BobaTopicEntryV1) -> tuple[str, float] | None:
    if entry.user_score is not None:
        normalized_score = (
            entry.user_score / 100.0
            if entry.user_score > 1.0
            else entry.user_score
        )
        return "score", _clamp(normalized_score)
    if entry.user_frequency is not None:
        return "frequency", entry.user_frequency
    if entry.user_rank is not None and entry.user_rank > 0:
        return "rank", entry.user_rank
    return None


def _metric_delta(
    previous: BobaTopicEntryV1,
    latest: BobaTopicEntryV1,
) -> tuple[float | None, float | None, float | None, str]:
    previous_metric = _metric_value(previous)
    latest_metric = _metric_value(latest)
    if (
        previous_metric is None
        or latest_metric is None
        or previous_metric[0] != latest_metric[0]
    ):
        return None, None, None, ""
    metric_type = previous_metric[0]
    previous_value = previous_metric[1]
    latest_value = latest_metric[1]
    if metric_type == "rank":
        delta = previous_value - latest_value
    else:
        delta = latest_value - previous_value
    return (
        round(previous_value, 4),
        round(latest_value, 4),
        round(delta, 4),
        metric_type,
    )


def _movement_item(
    entry: BobaTopicEntryV1,
    *,
    movement_type: BobaTopicMovementTypeV1,
    snapshot_count: int,
    evidence_sources: Sequence[str],
    reason: str,
    confidence: float,
    previous_score: float | None = None,
    latest_score: float | None = None,
    delta: float | None = None,
    warnings: Sequence[str] = (),
) -> BobaTopicMovementItemV1:
    return BobaTopicMovementItemV1(
        topic=entry.topic,
        normalized_topic=entry.normalized_topic,
        movement_type=movement_type,
        snapshot_count=snapshot_count,
        previous_score=previous_score,
        latest_score=latest_score,
        delta=delta,
        evidence_sources=list(dict.fromkeys(evidence_sources))[:64],
        reason=reason,
        confidence=_clamp(confidence),
        warnings=list(warnings),
    )


def analyze_topic_movement(
    snapshots: Sequence[BobaTopicSnapshotV1],
) -> BobaTopicMovementAnalysisV1:
    ordered = sorted(
        enumerate(snapshots),
        key=lambda item: (item[1].captured_at, item[0]),
    )
    if not ordered:
        return BobaTopicMovementAnalysisV1(
            analysis_notes=[
                "No local/user-provided topic snapshots were available."
            ],
            warnings=[
                "Movement could not be analyzed without provided snapshots."
            ],
        )
    latest_captured_at = max(snapshot.captured_at for _, snapshot in ordered)
    latest_snapshot_ids = {
        snapshot.snapshot_id
        for _, snapshot in ordered
        if snapshot.captured_at == latest_captured_at
    }
    occurrences: dict[
        str,
        list[tuple[int, BobaTopicSnapshotV1, BobaTopicEntryV1]],
    ] = defaultdict(list)
    for order_index, (_, snapshot) in enumerate(ordered):
        seen_in_snapshot: set[str] = set()
        for entry in snapshot.topics:
            canonical = entry.normalized_topic
            if canonical in seen_in_snapshot:
                continue
            seen_in_snapshot.add(canonical)
            occurrences[canonical].append((order_index, snapshot, entry))

    repeated: list[BobaTopicMovementItemV1] = []
    newly_appearing: list[BobaTopicMovementItemV1] = []
    rising: list[BobaTopicMovementItemV1] = []
    fading: list[BobaTopicMovementItemV1] = []
    stable: list[BobaTopicMovementItemV1] = []
    uncertain: list[BobaTopicMovementItemV1] = []
    for topic_occurrences in occurrences.values():
        topic_occurrences.sort(key=lambda item: item[0])
        latest_occurrence = topic_occurrences[-1]
        latest_entry = latest_occurrence[2]
        sources = [item[1].source_label for item in topic_occurrences]
        snapshot_count = len(topic_occurrences)
        appears_in_latest = any(
            snapshot.snapshot_id in latest_snapshot_ids
            for _, snapshot, _entry in topic_occurrences
        )
        if snapshot_count >= 2:
            repeated.append(
                _movement_item(
                    latest_entry,
                    movement_type="repeated",
                    snapshot_count=snapshot_count,
                    evidence_sources=sources,
                    reason=(
                        f"{latest_entry.topic} repeats across {snapshot_count} "
                        "local/user-provided snapshots."
                    ),
                    confidence=0.56 + min(0.28, snapshot_count * 0.07),
                )
            )
        if not appears_in_latest:
            fading.append(
                _movement_item(
                    latest_entry,
                    movement_type="fading_within_provided_data",
                    snapshot_count=snapshot_count,
                    evidence_sources=sources,
                    reason=(
                        f"{latest_entry.topic} appeared in earlier provided data "
                        "but is absent from the latest provided snapshot."
                    ),
                    confidence=0.62 if snapshot_count >= 2 else 0.48,
                    warnings=[
                        "Absence from provided data does not establish external decline."
                    ],
                )
            )
            continue
        first_in_latest = all(
            snapshot.snapshot_id in latest_snapshot_ids
            for _, snapshot, _entry in topic_occurrences
        )
        if first_in_latest:
            newly_appearing.append(
                _movement_item(
                    latest_entry,
                    movement_type="new",
                    snapshot_count=snapshot_count,
                    evidence_sources=sources,
                    reason=(
                        f"{latest_entry.topic} appears only in the latest provided "
                        "snapshot set."
                    ),
                    confidence=0.56 if len(snapshots) >= 2 else 0.34,
                    warnings=[
                        "New within provided data does not mean new on any platform."
                    ],
                )
            )
            if (
                len(snapshots) == 1
                or latest_entry.normalized_topic in _VAGUE_TOPICS
                or _metric_value(latest_entry) is None
            ):
                uncertain.append(
                    _movement_item(
                        latest_entry,
                        movement_type="uncertain",
                        snapshot_count=snapshot_count,
                        evidence_sources=sources,
                        reason=(
                            f"{latest_entry.topic} has insufficient comparative "
                            "evidence within provided data."
                        ),
                        confidence=0.28,
                        warnings=[
                            "Provide another dated snapshot or user-supplied metric."
                        ],
                    )
                )
            continue
        previous_entry = topic_occurrences[-2][2]
        latest_comparison_entry = latest_entry
        metric_occurrences = [
            occurrence
            for occurrence in topic_occurrences
            if _metric_value(occurrence[2]) is not None
        ]
        if len(metric_occurrences) >= 2:
            latest_metric_entry = metric_occurrences[-1][2]
            latest_metric = _metric_value(latest_metric_entry)
            matching_previous: BobaTopicEntryV1 | None = None
            if latest_metric is not None:
                for occurrence in reversed(metric_occurrences[:-1]):
                    previous_metric = _metric_value(occurrence[2])
                    if (
                        previous_metric is not None
                        and previous_metric[0] == latest_metric[0]
                    ):
                        matching_previous = occurrence[2]
                        break
            if matching_previous is not None:
                previous_entry = matching_previous
                latest_comparison_entry = latest_metric_entry
        (
            previous_score,
            latest_score,
            delta,
            metric_type,
        ) = _metric_delta(previous_entry, latest_comparison_entry)
        if delta is None:
            stable.append(
                _movement_item(
                    latest_entry,
                    movement_type="stable",
                    snapshot_count=snapshot_count,
                    evidence_sources=sources,
                    reason=(
                        f"{latest_entry.topic} repeats without comparable user-provided "
                        "rank, frequency, or score movement."
                    ),
                    confidence=0.48 + min(0.18, snapshot_count * 0.04),
                    warnings=[
                        "Stable means repeated with no comparable movement metric."
                    ],
                )
            )
            continue
        threshold = 0.03 if metric_type == "score" else max(
            1.0,
            abs(previous_score or 0.0) * 0.05,
        )
        if delta > threshold:
            rising.append(
                _movement_item(
                    latest_entry,
                    movement_type="rising_within_provided_data",
                    snapshot_count=snapshot_count,
                    evidence_sources=sources,
                    reason=(
                        f"{latest_entry.topic} improved by user-provided {metric_type} "
                        "within provided data."
                    ),
                    confidence=0.7,
                    previous_score=previous_score,
                    latest_score=latest_score,
                    delta=delta,
                    warnings=[
                        "This movement is not externally or real-time verified."
                    ],
                )
            )
        elif delta < -threshold:
            fading.append(
                _movement_item(
                    latest_entry,
                    movement_type="fading_within_provided_data",
                    snapshot_count=snapshot_count,
                    evidence_sources=sources,
                    reason=(
                        f"{latest_entry.topic} declined by user-provided {metric_type} "
                        "within provided data."
                    ),
                    confidence=0.7,
                    previous_score=previous_score,
                    latest_score=latest_score,
                    delta=delta,
                    warnings=[
                        "This movement is not externally or real-time verified."
                    ],
                )
            )
        else:
            stable.append(
                _movement_item(
                    latest_entry,
                    movement_type="stable",
                    snapshot_count=snapshot_count,
                    evidence_sources=sources,
                    reason=(
                        f"{latest_entry.topic} changed only slightly in user-provided "
                        f"{metric_type} within provided data."
                    ),
                    confidence=0.66,
                    previous_score=previous_score,
                    latest_score=latest_score,
                    delta=delta,
                )
            )

    all_entries = [
        entry
        for snapshot in snapshots
        for entry in snapshot.topics
    ]
    similar_groups = group_similar_topics(all_entries)
    duplicate_items: list[BobaTopicMovementItemV1] = []
    for canonical, variants in similar_groups.items():
        unique_variants = list(dict.fromkeys(variants))
        if len(unique_variants) < 2:
            continue
        representative = next(
            entry
            for entry in all_entries
            if normalize_topic_text(entry.topic) == canonical
            or entry.topic in unique_variants
        )
        duplicate_items.append(
            _movement_item(
                representative,
                movement_type="duplicate_or_similar",
                snapshot_count=len(occurrences.get(canonical, [])),
                evidence_sources=[
                    entry.source_label
                    for entry in all_entries
                    if entry.topic in unique_variants
                ],
                reason=(
                    "Conservatively grouped similar provided labels: "
                    f"{', '.join(unique_variants[:6])}."
                ),
                confidence=0.72,
                warnings=[
                    "Similarity grouping does not imply identical audience meaning."
                ],
            )
        )
    return BobaTopicMovementAnalysisV1(
        repeated_topics=repeated,
        newly_appearing_topics=newly_appearing,
        rising_topics_within_provided_data=rising,
        fading_topics_within_provided_data=fading,
        stable_topics=stable,
        duplicate_or_similar_topics=duplicate_items,
        uncertain_topics=uncertain,
        analysis_notes=[
            "All movement labels describe only the supplied local snapshots.",
            "Rank, frequency, and score are optional user-provided fields.",
            "No platform popularity or real-time trend truth was measured.",
        ],
        warnings=[
            "Movement is measured only within provided data.",
            "Snapshot coverage and source quality may be incomplete.",
        ],
    )


def _artifact_topic_sets(
    research_brain: ArtifactValue,
    content_scout: ArtifactValue,
) -> tuple[set[str], set[str]]:
    research = _dict(research_brain)
    research_summary = _dict(research.get("research_summary"))
    research_handoff = _dict(research.get("content_scout_handoff"))
    research_topics = {
        normalize_topic_text(value)
        for value in [
            *_list(research_summary.get("strongest_topics")),
            *_list(research_handoff.get("recommended_topics")),
            *_list(research_handoff.get("recommended_keywords")),
        ]
        if normalize_topic_text(value)
    }
    scout = _dict(content_scout)
    scout_summary = _dict(scout.get("scout_summary"))
    scout_topics = {
        normalize_topic_text(value)
        for value in [
            *_list(scout_summary.get("strongest_topics")),
            *(
                topic
                for item in _list(scout.get("scout_items"))
                if isinstance(item, Mapping)
                for topic in [
                    *_list(item.get("tags")),
                    *_list(item.get("categories")),
                ]
            ),
        ]
        if normalize_topic_text(value)
    }
    return research_topics, scout_topics


def _signal_texts(
    artifact: ArtifactValue,
    *,
    keys: Sequence[str],
) -> str:
    payload = _dict(artifact)
    values: list[str] = []
    stack: list[Any] = [payload]
    while stack and len(values) < 200:
        current = stack.pop()
        if isinstance(current, Mapping):
            for key, value in current.items():
                if key in keys:
                    if isinstance(value, str | int | float):
                        values.append(_text(value, maximum=300))
                    elif isinstance(value, list | tuple):
                        values.extend(
                            _text(item, maximum=300)
                            for item in value
                            if isinstance(item, str | int | float)
                        )
                        stack.extend(
                            item
                            for item in value
                            if isinstance(item, Mapping | list | tuple)
                        )
                    elif isinstance(value, Mapping):
                        stack.append(value)
                elif isinstance(value, Mapping | list | tuple):
                    stack.append(value)
        elif isinstance(current, list | tuple):
            stack.extend(current)
    return " ".join(values)


def _movement_lookup(
    movement: BobaTopicMovementAnalysisV1,
) -> dict[str, set[BobaTopicMovementTypeV1]]:
    result: dict[str, set[BobaTopicMovementTypeV1]] = defaultdict(set)
    for items in (
        movement.repeated_topics,
        movement.newly_appearing_topics,
        movement.rising_topics_within_provided_data,
        movement.fading_topics_within_provided_data,
        movement.stable_topics,
        movement.duplicate_or_similar_topics,
        movement.uncertain_topics,
    ):
        for item in items:
            result[item.normalized_topic].add(item.movement_type)
    return result


def score_topic_opportunities(
    snapshots: Sequence[BobaTopicSnapshotV1],
    movement: BobaTopicMovementAnalysisV1,
    *,
    research_brain: ArtifactValue = None,
    content_scout: ArtifactValue = None,
    creator_learning: ArtifactValue = None,
    performance_feedback: ArtifactValue = None,
    boba_memory: ArtifactValue = None,
) -> list[BobaTopicOpportunityScoreV1]:
    entries_by_topic: dict[str, list[BobaTopicEntryV1]] = defaultdict(list)
    for snapshot in snapshots:
        for entry in snapshot.topics:
            entries_by_topic[entry.normalized_topic].append(entry)
    research_topics, scout_topics = _artifact_topic_sets(
        research_brain,
        content_scout,
    )
    creator_text = " ".join(
        (
            _signal_texts(
                creator_learning,
                keys=(
                    "preferred_clip_types",
                    "preferred_hook_styles",
                    "story_angle_preferences",
                    "preferred_topics",
                    "summary",
                ),
            ),
            _signal_texts(
                boba_memory,
                keys=("main_topics", "source_summary", "summary"),
            ),
        )
    ).casefold()
    positive_text = _signal_texts(
        performance_feedback,
        keys=("summary", "factor", "reason", "label"),
    ).casefold()
    negative_values = _dict(
        _dict(performance_feedback).get("pattern_summary")
    ).get("strongest_negative_patterns")
    negative_text = json.dumps(negative_values or []).casefold()
    movement_by_topic = _movement_lookup(movement)
    scores: list[BobaTopicOpportunityScoreV1] = []
    for normalized, entries in entries_by_topic.items():
        representative = entries[-1]
        topic_tokens = _tokens(
            representative.topic,
            representative.description,
            representative.tags,
            representative.categories,
        )
        creator_tokens = _tokens(creator_text)
        creator_overlap = bool(topic_tokens & creator_tokens)
        creator_fit = 0.42 + (0.25 if creator_overlap else 0.0)
        if normalized in normalize_topic_text(creator_text):
            creator_fit += 0.08
        research_support = 0.82 if normalized in research_topics else 0.28
        scout_support = 0.82 if normalized in scout_topics else 0.28
        combined_text = " ".join(
            (
                representative.topic,
                representative.description,
                " ".join(representative.tags),
                " ".join(representative.categories),
            )
        ).casefold()
        shortability = 0.42 + min(
            0.36,
            len(_tokens(combined_text) & _SHORTABILITY_TERMS) * 0.09,
        )
        hook_potential = 0.38 + min(
            0.4,
            len(_tokens(combined_text) & _HOOK_TERMS) * 0.1,
        )
        movement_types = movement_by_topic.get(normalized, set())
        if "rising_within_provided_data" in movement_types:
            freshness = 0.84
        elif "new" in movement_types:
            freshness = 0.74
        elif "repeated" in movement_types:
            freshness = 0.64
        elif "stable" in movement_types:
            freshness = 0.5
        elif "fading_within_provided_data" in movement_types:
            freshness = 0.26
        else:
            freshness = 0.34
        risk_text = " ".join(
            f"{entry.rights_safety_note} {entry.evidence_note}"
            for entry in entries
        ).casefold()
        risk_hits = len(_tokens(risk_text) & _RISK_TERMS)
        risk = 0.18 + min(0.58, risk_hits * 0.14)
        if normalized in _VAGUE_TOPICS or "uncertain" in movement_types:
            risk += 0.16
        positive_overlap = bool(topic_tokens & _tokens(positive_text))
        negative_overlap = bool(topic_tokens & _tokens(negative_text))
        performance_adjustment = (
            0.08 if positive_overlap else 0.0
        ) - (0.08 if negative_overlap else 0.0)
        creator_fit += performance_adjustment
        reasons = [
            "Priority is advisory and bounded to local/user-provided signals.",
            (
                "Topic repeats or moves positively within provided data."
                if movement_types
                & {"repeated", "rising_within_provided_data", "new"}
                else "Topic has limited freshness evidence within provided data."
            ),
        ]
        if creator_overlap:
            reasons.append("Creator Learning or memory contains related wording.")
        if normalized in research_topics:
            reasons.append("Research Brain contains related topic support.")
        if normalized in scout_topics:
            reasons.append("Content Scout contains related metadata support.")
        if positive_overlap or negative_overlap:
            reasons.append(
                "Manual performance feedback influenced fit conservatively."
            )
        overall = (
            creator_fit * 0.2
            + research_support * 0.16
            + scout_support * 0.16
            + shortability * 0.14
            + hook_potential * 0.12
            + freshness * 0.16
            + (1.0 - risk) * 0.06
        )
        comparable_metrics = sum(
            _metric_value(entry) is not None for entry in entries
        )
        confidence = (
            0.32
            + min(0.24, len(entries) * 0.06)
            + (0.1 if comparable_metrics >= 2 else 0.0)
            + (0.08 if normalized in research_topics else 0.0)
            + (0.08 if normalized in scout_topics else 0.0)
        )
        scores.append(
            BobaTopicOpportunityScoreV1(
                topic=representative.topic,
                normalized_topic=normalized,
                creator_fit_score=_clamp(creator_fit),
                research_support_score=_clamp(research_support),
                scout_support_score=_clamp(scout_support),
                shortability_score=_clamp(shortability),
                hook_potential_score=_clamp(hook_potential),
                freshness_within_user_data_score=_clamp(freshness),
                risk_score=_clamp(risk),
                overall_topic_priority_score=_clamp(overall),
                confidence=_clamp(confidence),
                reasons=reasons,
                warnings=[
                    "No external popularity or real-time trend signal was used."
                ],
            )
        )
    return sorted(
        scores,
        key=lambda item: (
            item.overall_topic_priority_score,
            item.confidence,
            item.normalized_topic,
        ),
        reverse=True,
    )


def _watchlist(
    scores: Sequence[BobaTopicOpportunityScoreV1],
    movement: BobaTopicMovementAnalysisV1,
) -> list[BobaWatchedTopicV1]:
    movement_by_topic = _movement_lookup(movement)
    watched: list[BobaWatchedTopicV1] = []
    for score in scores:
        movement_types = movement_by_topic.get(score.normalized_topic, set())
        if (
            score.overall_topic_priority_score < 0.45
            and not movement_types
            & {"repeated", "rising_within_provided_data", "new"}
        ):
            continue
        movement_reason = (
            ", ".join(sorted(movement_types)).replace("_", " ")
            if movement_types
            else "limited movement evidence"
        )
        watched.append(
            BobaWatchedTopicV1(
                watched_topic_id=_stable_id(
                    "watched_topic",
                    score.normalized_topic,
                ),
                topic=score.topic,
                normalized_topic=score.normalized_topic,
                reason_for_watch=(
                    f"Watch because the topic has {movement_reason} within provided "
                    f"data and an advisory priority score of "
                    f"{score.overall_topic_priority_score:.2f}."
                ),
                creator_fit=score.creator_fit_score,
                research_fit=score.research_support_score,
                scout_fit=score.scout_support_score,
                content_angle_potential=_clamp(
                    (
                        score.shortability_score
                        + score.hook_potential_score
                    )
                    / 2
                ),
                suggested_angles=[
                    f"Possible explainer: what the provided data says about {score.topic}.",
                    f"Possible question: why is {score.topic} worth watching next?",
                    "Possible comparison using only source-supported points.",
                ],
                human_review_notes=[
                    "Verify claims and source quality before publication.",
                    "Do not present this watchlist as external popularity proof.",
                ],
                confidence=score.confidence,
                warnings=[
                    "Watch status is advisory and not real-time verified."
                ],
            )
        )
    return watched[:100]


def _confidence_review(
    snapshots: Sequence[BobaTopicSnapshotV1],
    movement: BobaTopicMovementAnalysisV1,
) -> BobaTrendConfidenceReviewV1:
    source_labels = {
        snapshot.source_label for snapshot in snapshots if snapshot.source_label
    }
    entries = [
        entry
        for snapshot in snapshots
        for entry in snapshot.topics
    ]
    metric_count = sum(_metric_value(entry) is not None for entry in entries)
    weak: list[str] = []
    if len(snapshots) <= 1:
        weak.append("Only one snapshot is available; movement confidence is low.")
    if len(source_labels) <= 1:
        weak.append("Only one source label is available.")
    if metric_count == 0:
        weak.append("No user-provided rank, frequency, or score is available.")
    if movement.uncertain_topics:
        weak.append(
            f"{len(movement.uncertain_topics)} topic(s) have insufficient evidence."
        )
    vague_count = sum(
        entry.normalized_topic in _VAGUE_TOPICS for entry in entries
    )
    if vague_count:
        weak.append(f"{vague_count} vague topic label(s) reduce confidence.")
    confidence = (
        0.22
        + min(0.28, len(snapshots) * 0.07)
        + min(0.18, len(source_labels) * 0.06)
        + (0.14 if metric_count >= 2 else 0.0)
        - min(0.24, len(weak) * 0.05)
    )
    return BobaTrendConfidenceReviewV1(
        overall_confidence=_clamp(confidence),
        snapshot_count=len(snapshots),
        source_count=len(source_labels),
        strongest_evidence=[
            f"{len(movement.repeated_topics)} repeated topic(s) in provided data.",
            (
                f"{metric_count} topic entry metric(s) were explicitly provided."
                if metric_count
                else "No numeric movement metrics were supplied."
            ),
        ],
        weakest_evidence=weak[:16],
        not_real_time_verified=True,
        weak_data_warnings=weak,
        human_verification_notes=[
            "Confirm dates, source labels, and numeric fields.",
            "Compare against authoritative sources before factual publication.",
            "Treat movement as local snapshot comparison, not platform truth.",
        ],
        warnings=[
            "Trend / Topic Watcher V1 is not real-time verified.",
            "Confidence describes evidence quality inside provided data only.",
        ],
    )


def _handoffs(
    watched: Sequence[BobaWatchedTopicV1],
    scores: Sequence[BobaTopicOpportunityScoreV1],
    snapshots: Sequence[BobaTopicSnapshotV1],
    movement: BobaTopicMovementAnalysisV1,
) -> tuple[BobaTrendContentScoutHandoffV1, BobaTrendResearchBrainHandoffV1]:
    score_by_topic = {item.normalized_topic: item for item in scores}
    top_topics = [item.topic for item in watched[:20]]
    keywords = list(
        dict.fromkeys(
            token
            for item in watched[:20]
            for token in item.normalized_topic.split()
            if len(token) >= 3
        )
    )[:40]
    categories = list(
        dict.fromkeys(
            category
            for snapshot in snapshots
            for entry in snapshot.topics
            for category in entry.categories
        )
    )[:24]
    avoid = [
        item.topic
        for item in scores
        if item.risk_score >= 0.65
    ][:20]
    uncertain = [
        item.topic for item in movement.uncertain_topics
    ]
    risky = [
        item.topic
        for item in scores
        if item.risk_score >= 0.45
    ]
    research_topics = list(
        dict.fromkeys([*uncertain, *risky, *top_topics])
    )[:24]
    claims = list(
        dict.fromkeys(
            entry.evidence_note
            for snapshot in snapshots
            for entry in snapshot.topics
            if entry.evidence_note
            and (
                entry.normalized_topic in {
                    item.normalized_topic for item in movement.uncertain_topics
                }
                or score_by_topic.get(
                    entry.normalized_topic,
                    BobaTopicOpportunityScoreV1(
                        topic=entry.topic,
                        normalized_topic=entry.normalized_topic,
                        creator_fit_score=0,
                        research_support_score=0,
                        scout_support_score=0,
                        shortability_score=0,
                        hook_potential_score=0,
                        freshness_within_user_data_score=0,
                        risk_score=0,
                        overall_topic_priority_score=0,
                        confidence=0,
                    ),
                ).risk_score
                >= 0.45
            )
        )
    )[:24]
    scout_handoff = BobaTrendContentScoutHandoffV1(
        recommended_scout_topics=top_topics,
        recommended_keywords=keywords,
        recommended_categories=categories,
        topics_to_avoid=avoid,
        rights_review_reminders=[
            "Keep unknown rights in permission review.",
            "Do not ingest, download, or process sources without permission.",
            "Topic movement does not establish copyright safety.",
        ],
        scout_review_questions=[
            "Which local snapshot supports this topic?",
            "Are the source rights and permission sufficient?",
            "Does candidate metadata support a complete Shorts angle?",
            "Is the topic still useful after factual verification?",
        ],
        apply_automatically=False,
    )
    research_handoff = BobaTrendResearchBrainHandoffV1(
        recommended_research_topics=research_topics,
        claims_to_verify=claims
        or [
            "Verify any factual claim before using watched-topic guidance."
        ],
        audience_questions_to_research=[
            f"What audience problem is actually supported for {topic}?"
            for topic in research_topics[:8]
        ],
        sources_needed=[
            "Authoritative sources for factual claims.",
            "Explicitly dated local snapshots for movement comparison.",
            "Rights-cleared summaries rather than copied source text.",
        ],
        apply_automatically=False,
    )
    return scout_handoff, research_handoff


def _summary(
    snapshots: Sequence[BobaTopicSnapshotV1],
    watched: Sequence[BobaWatchedTopicV1],
    movement: BobaTopicMovementAnalysisV1,
    scores: Sequence[BobaTopicOpportunityScoreV1],
) -> BobaTrendWatcherSummaryV1:
    return BobaTrendWatcherSummaryV1(
        total_snapshots=len(snapshots),
        total_topics=len(
            {
                entry.normalized_topic
                for snapshot in snapshots
                for entry in snapshot.topics
            }
        ),
        watched_topic_count=len(watched),
        rising_count=len(movement.rising_topics_within_provided_data),
        repeated_count=len(movement.repeated_topics),
        fading_count=len(movement.fading_topics_within_provided_data),
        strongest_topics=[item.topic for item in scores[:12]],
        riskiest_topics=[
            item.topic
            for item in sorted(
                scores,
                key=lambda value: value.risk_score,
                reverse=True,
            )[:12]
            if item.risk_score >= 0.35
        ],
        human_review_notes=[
            "Movement always means within provided data.",
            "Verify dates, source quality, claims, and rights.",
            "Opportunity scores do not predict performance.",
        ],
    )


def _artifact_snapshot(
    artifact: ArtifactValue,
    *,
    source_type: Literal["research_brain", "content_scout"],
    captured_at: str,
) -> TopicImportResult:
    payload = _dict(artifact)
    if not payload:
        imported = BobaTrendTopicImportSourceV1(
            import_id=_stable_id("topic_import", source_type, "unavailable"),
            source_type=source_type,
            source_label=source_type,
            item_count=0,
            accepted_count=0,
            rejected_count=0,
            warnings=[f"{source_type.replace('_', ' ')} artifact was unavailable."],
            limitations=["No artifact-derived topic snapshot was created."],
        )
        return imported, [], []
    if source_type == "research_brain":
        summary = _dict(payload.get("research_summary"))
        handoff = _dict(payload.get("content_scout_handoff"))
        topic_values = [
            *_list(summary.get("strongest_topics")),
            *_list(handoff.get("recommended_topics")),
            *_list(handoff.get("recommended_keywords")),
        ]
        source_label = "research_brain"
    else:
        summary = _dict(payload.get("scout_summary"))
        topic_values = [
            *_list(summary.get("strongest_topics")),
            *(
                topic
                for item in _list(payload.get("scout_items"))
                if isinstance(item, Mapping)
                for topic in [
                    *_list(item.get("tags")),
                    *_list(item.get("categories")),
                ]
            ),
        ]
        source_label = "content_scout"
    rows = [
        {
            "topic": topic,
            "source_label": source_label,
            "captured_at": captured_at,
            "evidence_note": (
                f"Imported from saved {source_label.replace('_', ' ')} metadata."
            ),
        }
        for topic in list(dict.fromkeys(_text(value, maximum=200) for value in topic_values))
        if topic
    ]
    return _import_rows(
        rows,
        source_type=source_type,
        source_label=source_label,
        default_captured_at=captured_at,
    )


class BobaTrendTopicWatcherV1:
    """Compare explicit local topic snapshots without external monitoring."""

    def analyze(
        self,
        project_id: str,
        *,
        source_id: str | None = None,
        manual_snapshots: Sequence[Mapping[str, Any]] = (),
        pasted_topic_lists: Sequence[str | Mapping[str, Any]] = (),
        import_paths: Sequence[str | Path] = (),
        manual_source_type: BobaTrendTopicSourceTypeV1 = "manual",
        source_label: str = "manual",
        research_brain: ArtifactValue = None,
        content_scout: ArtifactValue = None,
        creator_learning: ArtifactValue = None,
        performance_feedback: ArtifactValue = None,
        boba_memory: ArtifactValue = None,
        dry_run: bool = False,
    ) -> BobaTrendTopicWatcherSetV1:
        imported_sources: list[BobaTrendTopicImportSourceV1] = []
        snapshots: list[BobaTopicSnapshotV1] = []
        rejected: list[str] = []
        if manual_snapshots:
            imported, values, invalid = import_topics_from_manual(
                manual_snapshots,
                source_label=source_label,
                source_type=manual_source_type,
            )
            imported_sources.append(imported)
            snapshots.extend(values)
            rejected.extend(invalid)
        if pasted_topic_lists:
            imported, values, invalid = import_topics_from_pasted_text(
                pasted_topic_lists,
            )
            imported_sources.append(imported)
            snapshots.extend(values)
            rejected.extend(invalid)
        importers = {
            ".csv": import_topics_from_csv,
            ".json": import_topics_from_json,
        }
        for path in import_paths:
            importer = importers.get(Path(path).suffix.casefold())
            if importer is None:
                raise ValidationError(
                    "Trend / Topic Watcher supports only local CSV and JSON imports."
                )
            imported, values, invalid = importer(path)
            imported_sources.append(imported)
            snapshots.extend(values)
            rejected.extend(invalid)
        anchor_time = max(
            (snapshot.captured_at for snapshot in snapshots),
            default=now_iso(),
        )
        artifact_inputs: tuple[
            tuple[
                ArtifactValue,
                Literal["research_brain", "content_scout"],
            ],
            ...,
        ] = (
            (research_brain, "research_brain"),
            (content_scout, "content_scout"),
        )
        for artifact, artifact_type in artifact_inputs:
            if not _dict(artifact):
                continue
            imported, values, invalid = _artifact_snapshot(
                artifact,
                source_type=artifact_type,
                captured_at=anchor_time,
            )
            imported_sources.append(imported)
            snapshots.extend(values)
            rejected.extend(invalid)
        movement = analyze_topic_movement(snapshots)
        scores = score_topic_opportunities(
            snapshots,
            movement,
            research_brain=research_brain,
            content_scout=content_scout,
            creator_learning=creator_learning,
            performance_feedback=performance_feedback,
            boba_memory=boba_memory,
        )
        watched = _watchlist(scores, movement)
        confidence = _confidence_review(snapshots, movement)
        scout_handoff, research_handoff = _handoffs(
            watched,
            scores,
            snapshots,
            movement,
        )
        summary = _summary(snapshots, watched, movement, scores)
        artifacts = {
            "research_brain": _dict(research_brain),
            "content_scout": _dict(content_scout),
            "creator_learning": _dict(creator_learning),
            "performance_feedback": _dict(performance_feedback),
            "memory": _dict(boba_memory),
        }
        unavailable = [
            name for name, artifact in artifacts.items() if not artifact
        ]
        warnings = [
            "Trend / Topic Watcher V1 used local/user-provided topic data only.",
            "Movement is measured only within provided data.",
            "No URL, platform, external API, or real-time trend source was contacted.",
        ]
        if rejected:
            warnings.append(f"{len(rejected)} invalid topic item(s) were rejected.")
        if dry_run:
            warnings.append("Dry run: the watcher artifact was not persisted.")
        return BobaTrendTopicWatcherSetV1(
            project_id=project_id,
            source_id=_text(source_id or project_id, maximum=512),
            imported_sources=imported_sources,
            topic_snapshots=snapshots,
            watched_topics=watched,
            movement_analysis=movement,
            opportunity_scores=scores,
            confidence_review=confidence,
            content_scout_handoff=scout_handoff,
            research_brain_handoff=research_handoff,
            watcher_summary=summary,
            signal_usage=BobaTrendTopicSignalUsageV1(
                research_brain_used=bool(artifacts["research_brain"]),
                content_scout_used=bool(artifacts["content_scout"]),
                creator_learning_used=bool(artifacts["creator_learning"]),
                performance_feedback_used=bool(
                    artifacts["performance_feedback"]
                ),
                memory_used=bool(artifacts["memory"]),
                local_import_used=any(
                    source.source_type in {"csv", "json"}
                    for source in imported_sources
                ),
                manual_input_used=any(
                    source.source_type
                    in {"manual", "pasted_text", "test_synthetic"}
                    for source in imported_sources
                ),
                external_api_used=False,
                url_fetching_used=False,
                scraping_used=False,
                platform_monitoring_used=False,
                downloading_used=False,
                fallback_used=bool(unavailable),
                unavailable_signals=unavailable,
                warnings=(
                    [
                        "Missing optional BOBA artifacts limited advisory fit scoring."
                    ]
                    if unavailable
                    else []
                ),
            ),
            warnings=warnings,
            limitations=[
                "The watcher does not scrape, fetch URLs, call external APIs, "
                "or monitor platforms.",
                "The watcher does not verify real-time popularity or trend direction.",
                "Movement labels apply only within provided snapshots.",
                "Opportunity scores are advisory and do not guarantee performance.",
                "Content Scout and Research Brain handoffs are never applied automatically.",
            ],
        )


def generate_trend_topic_watcher(
    project_id: str,
    **kwargs: Any,
) -> BobaTrendTopicWatcherSetV1:
    """Convenience wrapper for deterministic watcher generation."""
    return BobaTrendTopicWatcherV1().analyze(project_id, **kwargs)
