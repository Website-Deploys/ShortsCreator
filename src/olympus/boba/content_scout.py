"""Project-scoped metadata-only content scouting for BOBA Content Scout V2."""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal, TypeAlias
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator

from olympus.boba.contracts import BobaContract, now_iso
from olympus.platform.errors import ValidationError

BobaScoutImportSourceTypeV2 = Literal["csv", "json", "manual", "test_synthetic"]
BobaScoutRightsStatusV2 = Literal[
    "owned",
    "licensed",
    "permission_granted",
    "permission_needed",
    "unknown",
    "blocked",
]
BobaScoutRecommendationTypeV2 = Literal[
    "review_now",
    "save_for_later",
    "seek_permission",
    "reject",
    "blocked",
]
BobaScoutPriorityV2 = Literal["low", "medium", "high", "urgent"]
ArtifactValue: TypeAlias = Mapping[str, Any] | BaseModel | None
ScoutImportResult: TypeAlias = tuple[
    "BobaScoutImportSourceV2",
    list["BobaScoutItemV2"],
    list["BobaScoutRejectedItemV2"],
]

_SPACE = re.compile(r"\s+")
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_TOKEN = re.compile(r"[a-z0-9]+")
_MAX_IMPORT_BYTES = 2_000_000
_HOOK_TERMS = {
    "why",
    "how",
    "secret",
    "truth",
    "mistake",
    "unexpected",
    "nobody",
    "never",
    "reason",
    "reveal",
    "mystery",
    "contradiction",
    "lesson",
    "result",
}
_SHORTABILITY_TERMS = {
    "tutorial",
    "interview",
    "reaction",
    "podcast",
    "story",
    "lesson",
    "mistake",
    "reveal",
    "transformation",
    "before",
    "after",
    "conflict",
    "turning",
    "comeback",
}
_EMOTIONAL_TERMS = {
    "struggle",
    "surprise",
    "growth",
    "failure",
    "success",
    "regret",
    "comeback",
    "rescue",
    "emotional",
    "hope",
    "loss",
    "fear",
    "breakthrough",
    "motivation",
    "motivational",
}
_RIGHTS_ALIASES: dict[str, BobaScoutRightsStatusV2] = {
    "owned": "owned",
    "user_owned": "owned",
    "licensed": "licensed",
    "permission_granted": "permission_granted",
    "permission_confirmed": "permission_granted",
    "permission_needed": "permission_needed",
    "needs_permission": "permission_needed",
    "unknown": "unknown",
    "blocked": "blocked",
    "not_allowed": "blocked",
    "denied": "blocked",
    "rejected": "blocked",
}


def _text(value: Any, *, maximum: int = 700) -> str:
    return _SPACE.sub(" ", str(value or "")).strip()[:maximum]


def _dict(value: Any) -> dict[str, Any]:
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


def _tokens(*values: Any) -> set[str]:
    return {
        token
        for value in values
        for token in _TOKEN.findall(_text(value, maximum=3_000).casefold())
        if len(token) > 2
    }


def _compact_values(value: Any, *, maximum: int = 40) -> list[str]:
    if isinstance(value, str):
        parts = re.split(r"[,;|]", value)
    elif isinstance(value, list | tuple | set):
        parts = list(value)
    else:
        parts = []
    return list(
        dict.fromkeys(
            item
            for raw in parts
            if (item := _text(raw, maximum=80))
        )
    )[:maximum]


def _duration(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value) if float(value) >= 0 else None
    text = _text(value, maximum=40)
    if ":" in text:
        try:
            parts = [float(item) for item in text.split(":")]
        except ValueError:
            return None
        seconds = 0.0
        for part in parts:
            seconds = seconds * 60 + part
        return seconds if seconds >= 0 else None
    try:
        numeric = float(text)
    except ValueError:
        return None
    return numeric if numeric >= 0 else None


def _safe_local_path(path: str | Path, *, suffix: str) -> Path:
    raw = str(path)
    if "://" in raw:
        raise ValidationError("Content Scout import paths must be local files.")
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise ValidationError("Content Scout import file was not found.")
    if source.suffix.casefold() != suffix:
        raise ValidationError(f"Content Scout expected a {suffix} local file.")
    if source.stat().st_size > _MAX_IMPORT_BYTES:
        raise ValidationError("Content Scout import exceeds the 2 MB limit.")
    return source


class BobaScoutImportSourceV2(BobaContract):
    import_id: str = Field(min_length=1, max_length=128)
    source_type: BobaScoutImportSourceTypeV2
    source_label: str = Field(min_length=1, max_length=160)
    source_path: str = Field(default="", max_length=260)
    imported_at: str = Field(default_factory=now_iso)
    item_count: int = Field(default=0, ge=0)
    accepted_count: int = Field(default=0, ge=0)
    rejected_count: int = Field(default=0, ge=0)
    warnings: list[str] = Field(default_factory=list, max_length=32)
    limitations: list[str] = Field(default_factory=list, max_length=32)


class BobaScoutItemV2(BobaContract):
    item_id: str = Field(min_length=1, max_length=128)
    title: str = Field(default="", max_length=300)
    description: str = Field(default="", max_length=1_500)
    source_label: str = Field(min_length=1, max_length=160)
    source_reference: str = Field(default="", max_length=300)
    source_url: str | None = Field(default=None, max_length=2_048)
    duration_seconds: float | None = Field(default=None, ge=0.0, le=172_800.0)
    tags: list[str] = Field(default_factory=list, max_length=40)
    categories: list[str] = Field(default_factory=list, max_length=40)
    creator_or_channel: str = Field(default="", max_length=200)
    published_at: str = Field(default="", max_length=80)
    rights_status: BobaScoutRightsStatusV2 = "unknown"
    permission_notes: str = Field(default="", max_length=600)
    user_notes: str = Field(default="", max_length=600)
    raw_metadata_summary: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list, max_length=32)

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("source_url must be an absolute HTTP or HTTPS reference")
        return value


class BobaScoutScoreV2(BobaContract):
    item_id: str = Field(min_length=1, max_length=128)
    creator_fit_score: float = Field(ge=0.0, le=1.0)
    topic_fit_score: float = Field(ge=0.0, le=1.0)
    shortability_score: float = Field(ge=0.0, le=1.0)
    hook_potential_score: float = Field(ge=0.0, le=1.0)
    emotional_story_score: float = Field(ge=0.0, le=1.0)
    trend_context_score: float = Field(ge=0.0, le=1.0)
    novelty_score: float = Field(ge=0.0, le=1.0)
    rights_readiness_score: float = Field(ge=0.0, le=1.0)
    review_priority_score: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    score_reasons: list[str] = Field(default_factory=list, max_length=32)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaSuggestedShortAngleV2(BobaContract):
    angle_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=300)
    hook_direction: str = Field(min_length=1, max_length=500)
    why_it_might_work: str = Field(min_length=1, max_length=500)
    risk: str = Field(min_length=1, max_length=500)
    confidence: float = Field(ge=0.0, le=1.0)


class BobaScoutRecommendationV2(BobaContract):
    item_id: str = Field(min_length=1, max_length=128)
    recommendation: BobaScoutRecommendationTypeV2
    priority: BobaScoutPriorityV2
    reason: str = Field(min_length=1, max_length=700)
    suggested_short_angles: list[BobaSuggestedShortAngleV2] = Field(
        default_factory=list,
        max_length=3,
    )
    suggested_review_questions: list[str] = Field(
        default_factory=list,
        max_length=16,
    )
    rights_review_required: bool = True
    human_review_required: bool = True
    warnings: list[str] = Field(default_factory=list, max_length=32)
    limitations: list[str] = Field(default_factory=list, max_length=32)


class BobaScoutReviewQueueV2(BobaContract):
    top_items: list[BobaScoutRecommendationV2] = Field(
        default_factory=list,
        max_length=200,
    )
    backup_items: list[BobaScoutRecommendationV2] = Field(
        default_factory=list,
        max_length=500,
    )
    permission_needed_items: list[BobaScoutRecommendationV2] = Field(
        default_factory=list,
        max_length=500,
    )
    blocked_items: list[BobaScoutRecommendationV2] = Field(
        default_factory=list,
        max_length=500,
    )
    duplicate_or_similar_items: list[BobaScoutRecommendationV2] = Field(
        default_factory=list,
        max_length=500,
    )
    queue_summary: str = Field(min_length=1, max_length=1_000)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaScoutRejectedItemV2(BobaContract):
    item_id: str = Field(min_length=1, max_length=128)
    reason_rejected: str = Field(min_length=1, max_length=500)
    risk: str = Field(min_length=1, max_length=500)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaContentScoutSummaryV2(BobaContract):
    total_items: int = Field(default=0, ge=0)
    review_now_count: int = Field(default=0, ge=0)
    save_for_later_count: int = Field(default=0, ge=0)
    permission_needed_count: int = Field(default=0, ge=0)
    blocked_count: int = Field(default=0, ge=0)
    strongest_topics: list[str] = Field(default_factory=list, max_length=32)
    weakest_topics: list[str] = Field(default_factory=list, max_length=32)
    repeated_themes: list[str] = Field(default_factory=list, max_length=32)
    rights_summary: list[str] = Field(default_factory=list, max_length=32)
    human_review_notes: list[str] = Field(default_factory=list, max_length=32)


class BobaContentScoutSignalUsageV2(BobaContract):
    scout_v1_used: bool = False
    creator_learning_used: bool = False
    approval_rejection_learning_used: bool = False
    performance_feedback_used: bool = False
    memory_used: bool = False
    local_import_used: bool = False
    external_api_used: Literal[False] = False
    url_fetching_used: Literal[False] = False
    downloading_used: Literal[False] = False
    fallback_used: bool = False
    unavailable_signals: list[str] = Field(default_factory=list, max_length=32)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaContentScoutSetV2(BobaContract):
    schema_version: Literal["boba_content_scout_v2"] = "boba_content_scout_v2"
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(min_length=1, max_length=512)
    created_at: str = Field(default_factory=now_iso)
    imported_sources: list[BobaScoutImportSourceV2] = Field(
        default_factory=list,
        max_length=100,
    )
    scout_items: list[BobaScoutItemV2] = Field(default_factory=list, max_length=5_000)
    scored_items: list[BobaScoutScoreV2] = Field(default_factory=list, max_length=5_000)
    review_queue: BobaScoutReviewQueueV2
    rejected_items: list[BobaScoutRejectedItemV2] = Field(
        default_factory=list,
        max_length=5_000,
    )
    scout_summary: BobaContentScoutSummaryV2
    signal_usage: BobaContentScoutSignalUsageV2
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)


def _normalized_rights(value: Any) -> tuple[BobaScoutRightsStatusV2, list[str]]:
    raw = _text(value, maximum=80).casefold().replace(" ", "_") or "unknown"
    normalized = _RIGHTS_ALIASES.get(raw)
    if normalized is not None:
        return normalized, []
    return (
        "unknown",
        [
            f"Unsupported rights status '{raw}' was treated as unknown and requires review."
        ],
    )


def normalize_scout_item(
    raw: Mapping[str, Any],
    *,
    source_label: str = "manual",
    item_index: int = 0,
) -> BobaScoutItemV2:
    title = _text(raw.get("title"), maximum=300)
    description = _text(
        raw.get("description")
        or raw.get("summary")
        or raw.get("content_summary"),
        maximum=1_500,
    )
    if not title and not description:
        raise ValidationError(
            "Content Scout item requires a title or description.",
            details={"item_index": item_index},
        )
    warnings: list[str] = []
    rights_status, rights_warnings = _normalized_rights(raw.get("rights_status"))
    warnings.extend(rights_warnings)
    raw_url = _text(raw.get("source_url") or raw.get("url"), maximum=2_048)
    source_url: str | None = None
    if raw_url:
        parsed = urlparse(raw_url)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            source_url = raw_url
        else:
            warnings.append(
                "Invalid source URL was ignored; Content Scout never fetches references."
            )
    duration_value = raw.get("duration_seconds")
    if duration_value in (None, ""):
        duration_value = raw.get("duration")
    duration_seconds = _duration(duration_value)
    if duration_value not in (None, "") and duration_seconds is None:
        warnings.append("Unsupported duration was ignored.")
    effective_label = _text(
        raw.get("source_label") or raw.get("source") or source_label,
        maximum=160,
    ) or source_label
    source_reference = _text(
        raw.get("source_reference")
        or raw.get("reference")
        or raw.get("external_id"),
        maximum=300,
    )
    item_id_value = _text(raw.get("item_id"), maximum=128)
    item_id = (
        item_id_value
        if _SAFE_ID.fullmatch(item_id_value)
        else _stable_id(
            "scout_item",
            effective_label,
            str(item_index),
            title,
            description[:300],
            source_reference,
        )
    )
    provided_fields = sorted(
        key
        for key in raw
        if key
        in {
            "title",
            "description",
            "summary",
            "source",
            "source_label",
            "source_reference",
            "url",
            "source_url",
            "duration",
            "duration_seconds",
            "tags",
            "categories",
            "creator",
            "channel",
            "creator_or_channel",
            "published_at",
            "rights_status",
            "permission_notes",
            "notes",
            "user_notes",
        }
    )
    return BobaScoutItemV2(
        item_id=item_id,
        title=title,
        description=description,
        source_label=effective_label,
        source_reference=source_reference,
        source_url=source_url,
        duration_seconds=duration_seconds,
        tags=_compact_values(raw.get("tags")),
        categories=_compact_values(raw.get("categories") or raw.get("category")),
        creator_or_channel=_text(
            raw.get("creator_or_channel")
            or raw.get("creator")
            or raw.get("channel"),
            maximum=200,
        ),
        published_at=_text(
            raw.get("published_at") or raw.get("published_date"),
            maximum=80,
        ),
        rights_status=rights_status,
        permission_notes=_text(raw.get("permission_notes"), maximum=600),
        user_notes=_text(
            raw.get("user_notes") or raw.get("notes"),
            maximum=600,
        ),
        raw_metadata_summary={
            "provided_fields": provided_fields,
            "metadata_only": True,
            "url_was_not_fetched": True,
        },
        warnings=warnings,
    )


def _rejected_row(
    *,
    source_label: str,
    item_index: int,
    reason: str,
) -> BobaScoutRejectedItemV2:
    return BobaScoutRejectedItemV2(
        item_id=_stable_id("scout_rejected", source_label, str(item_index), reason),
        reason_rejected=reason,
        risk="The row was excluded from scoring because required metadata was invalid.",
        warnings=["Other valid rows remain eligible for local metadata review."],
    )


def _import_values(
    values: Sequence[Any],
    *,
    source_type: BobaScoutImportSourceTypeV2,
    source_label: str,
    source_path: str,
) -> ScoutImportResult:
    items: list[BobaScoutItemV2] = []
    rejected: list[BobaScoutRejectedItemV2] = []
    for index, value in enumerate(values):
        if not isinstance(value, Mapping):
            rejected.append(
                _rejected_row(
                    source_label=source_label,
                    item_index=index,
                    reason="Imported row was not an object.",
                )
            )
            continue
        try:
            items.append(
                normalize_scout_item(
                    value,
                    source_label=source_label,
                    item_index=index,
                )
            )
        except (ValidationError, ValueError) as exc:
            rejected.append(
                _rejected_row(
                    source_label=source_label,
                    item_index=index,
                    reason=_text(exc, maximum=500),
                )
            )
    warnings = [
        f"{len(rejected)} invalid row(s) were rejected without stopping the import."
    ] if rejected else []
    source = BobaScoutImportSourceV2(
        import_id=_stable_id(
            "scout_import",
            source_type,
            source_label,
            source_path,
            str(len(values)),
        ),
        source_type=source_type,
        source_label=source_label,
        source_path=source_path,
        item_count=len(values),
        accepted_count=len(items),
        rejected_count=len(rejected),
        warnings=warnings,
        limitations=[
            "Import reads local metadata only and does not inspect or fetch media."
        ],
    )
    return source, items, rejected


def import_scout_items_from_csv(
    path: str | Path,
    *,
    source_label: str = "",
) -> ScoutImportResult:
    source = _safe_local_path(path, suffix=".csv")
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        values = list(csv.DictReader(handle))
    return _import_values(
        values,
        source_type="csv",
        source_label=source_label or source.stem,
        source_path=source.name,
    )


def import_scout_items_from_json(
    path: str | Path,
    *,
    source_label: str = "",
) -> ScoutImportResult:
    source = _safe_local_path(path, suffix=".json")
    try:
        raw = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError("Content Scout JSON import could not be parsed.") from exc
    if isinstance(raw, dict):
        values = next(
            (
                raw[key]
                for key in ("items", "source_items", "scout_items")
                if isinstance(raw.get(key), list)
            ),
            None,
        )
    else:
        values = raw
    if not isinstance(values, list):
        raise ValidationError(
            "Content Scout JSON must be a list or contain items/source_items/scout_items."
        )
    return _import_values(
        values,
        source_type="json",
        source_label=source_label or source.stem,
        source_path=source.name,
    )


def _artifact_terms(
    creator_learning: Mapping[str, Any],
    approval_rejection: Mapping[str, Any],
    performance_feedback: Mapping[str, Any],
    memory: Mapping[str, Any],
) -> tuple[set[str], set[str]]:
    positive: set[str] = set()
    negative: set[str] = set()
    profile = _dict(creator_learning.get("learning_profile"))
    for field in (
        "preferred_clip_types",
        "preferred_hook_styles",
        "pacing_preferences",
        "story_angle_preferences",
    ):
        positive.update(_tokens(*_list(profile.get(field))))
    for field in ("avoided_clip_types", "avoided_hook_styles", "risk_sensitivities"):
        negative.update(_tokens(*_list(profile.get(field))))
    for pattern in (
        _dict(item)
        for item in _list(approval_rejection.get("pattern_scores"))
    ):
        terms = _tokens(pattern.get("summary"), pattern.get("guidance"))
        if int(pattern.get("approval_count") or 0) > int(
            pattern.get("rejection_count") or 0
        ):
            positive.update(terms)
        elif int(pattern.get("rejection_count") or 0) > 0:
            negative.update(terms)
    pattern_summary = _dict(performance_feedback.get("pattern_summary"))
    for item in _list(pattern_summary.get("strongest_positive_patterns")):
        positive.update(_tokens(_dict(item).get("summary")))
    for item in _list(pattern_summary.get("strongest_negative_patterns")):
        negative.update(_tokens(_dict(item).get("summary")))
    positive.update(
        _tokens(
            memory.get("source_summary"),
            *_list(memory.get("main_topics")),
            *_list(memory.get("story_patterns")),
        )
    )
    return positive, negative


def _duplicate_map(items: Sequence[BobaScoutItemV2]) -> dict[str, str]:
    duplicates: dict[str, str] = {}
    seen: list[tuple[BobaScoutItemV2, set[str], str]] = []
    for item in items:
        item_tokens = _tokens(item.title, item.description)
        normalized_title = " ".join(sorted(_tokens(item.title)))
        for previous, previous_tokens, previous_title in seen:
            union = item_tokens | previous_tokens
            similarity = (
                len(item_tokens & previous_tokens) / len(union)
                if union
                else 0.0
            )
            if (
                (
                    normalized_title
                    and normalized_title == previous_title
                )
                or similarity >= 0.82
            ):
                duplicates[item.item_id] = previous.item_id
                break
        seen.append((item, item_tokens, normalized_title))
    return duplicates


class BobaContentScoutV2:
    """Score explicit local metadata and produce a human review queue."""

    def analyze(
        self,
        project_id: str,
        *,
        source_id: str | None = None,
        manual_items: Sequence[Mapping[str, Any]] = (),
        import_paths: Sequence[str | Path] = (),
        manual_source_type: BobaScoutImportSourceTypeV2 = "manual",
        source_label: str = "manual",
        creator_learning: ArtifactValue = None,
        approval_rejection_learning: ArtifactValue = None,
        performance_feedback: ArtifactValue = None,
        boba_memory: ArtifactValue = None,
        scout_v1: Sequence[BaseModel | Mapping[str, Any]] = (),
        dry_run: bool = False,
    ) -> BobaContentScoutSetV2:
        imported_sources: list[BobaScoutImportSourceV2] = []
        items: list[BobaScoutItemV2] = []
        rejected: list[BobaScoutRejectedItemV2] = []
        manual_values = list(manual_items)
        if manual_values:
            source, accepted, rejected_rows = _import_values(
                manual_values,
                source_type=manual_source_type,
                source_label=source_label,
                source_path="",
            )
            imported_sources.append(source)
            items.extend(accepted)
            rejected.extend(rejected_rows)
        for path in import_paths:
            suffix = Path(path).suffix.casefold()
            if suffix == ".csv":
                source, accepted, rejected_rows = import_scout_items_from_csv(path)
            elif suffix == ".json":
                source, accepted, rejected_rows = import_scout_items_from_json(path)
            else:
                rejected.append(
                    _rejected_row(
                        source_label=source_label,
                        item_index=len(rejected),
                        reason="Only local CSV and JSON import files are supported.",
                    )
                )
                continue
            imported_sources.append(source)
            items.extend(accepted)
            rejected.extend(rejected_rows)
        if scout_v1:
            v1_values = [
                self._v1_item(_dict(value))
                for value in scout_v1
                if _dict(value)
            ]
            source, accepted, rejected_rows = _import_values(
                v1_values,
                source_type="manual",
                source_label="scout_v1",
                source_path="",
            )
            imported_sources.append(source)
            items.extend(accepted)
            rejected.extend(rejected_rows)

        creator = _dict(creator_learning)
        approval = _dict(approval_rejection_learning)
        performance = _dict(performance_feedback)
        memory = _dict(boba_memory)
        positive_terms, negative_terms = _artifact_terms(
            creator,
            approval,
            performance,
            memory,
        )
        duplicate_map = _duplicate_map(items)
        scores = self.score_items(
            items,
            duplicate_map=duplicate_map,
            positive_terms=positive_terms,
            negative_terms=negative_terms,
            creator_learning_available=bool(creator),
            approval_learning_available=bool(approval),
            performance_feedback_available=bool(performance),
        )
        score_by_id = {score.item_id: score for score in scores}
        recommendations = [
            self._recommend(
                item,
                score_by_id[item.item_id],
                duplicate_of=duplicate_map.get(item.item_id),
            )
            for item in items
        ]
        queue = self._queue(recommendations, score_by_id, duplicate_map)
        for recommendation in recommendations:
            if recommendation.recommendation == "reject":
                rejected.append(
                    BobaScoutRejectedItemV2(
                        item_id=recommendation.item_id,
                        reason_rejected=recommendation.reason,
                        risk=(
                            "Low-fit or duplicate metadata should not enter a future "
                            "ingestion flow."
                        ),
                        warnings=recommendation.warnings,
                    )
                )
        summary = self._summary(items, scores, recommendations)
        unavailable = [
            name
            for name, value in {
                "creator_learning": creator,
                "approval_rejection_learning": approval,
                "performance_feedback": performance,
                "memory": memory,
                "scout_v1": list(scout_v1),
            }.items()
            if not value
        ]
        warnings = [
            "Content Scout V2 used local/user-provided metadata only.",
            "URLs were retained as references only and were not fetched.",
            "Rights status is user-provided and does not establish copyright safety.",
        ]
        if rejected:
            warnings.append(
                f"{len(rejected)} invalid, duplicate, or low-priority item(s) were rejected."
            )
        if dry_run:
            warnings.append("Dry run: the Content Scout V2 artifact was not persisted.")
        return BobaContentScoutSetV2(
            project_id=project_id,
            source_id=_text(source_id or project_id, maximum=512),
            imported_sources=imported_sources,
            scout_items=items,
            scored_items=scores,
            review_queue=queue,
            rejected_items=rejected,
            scout_summary=summary,
            signal_usage=BobaContentScoutSignalUsageV2(
                scout_v1_used=bool(scout_v1),
                creator_learning_used=bool(creator),
                approval_rejection_learning_used=bool(approval),
                performance_feedback_used=bool(performance),
                memory_used=bool(memory),
                local_import_used=bool(imported_sources),
                external_api_used=False,
                url_fetching_used=False,
                downloading_used=False,
                fallback_used=bool(unavailable),
                unavailable_signals=unavailable,
                warnings=(
                    ["Missing optional BOBA signals limited creator-fit attribution."]
                    if unavailable
                    else []
                ),
            ),
            warnings=warnings,
            limitations=[
                "Scores estimate metadata fit only and do not predict audience performance.",
                "No external trend knowledge was verified or used.",
                "Human review and an independent rights check remain required.",
                "Candidate Video Scorer, Research Brain, Trend Watcher, deeper rights checks, "
                "and ingestion are future handoffs only.",
            ],
        )

    @staticmethod
    def _v1_item(value: Mapping[str, Any]) -> dict[str, Any]:
        metadata = _dict(value.get("metadata"))
        return {
            "item_id": _text(value.get("candidate_id"), maximum=128),
            "title": value.get("title"),
            "description": metadata.get("description") or metadata.get("summary"),
            "source_label": "scout_v1",
            "source_reference": value.get("candidate_id"),
            "source_url": value.get("url"),
            "duration_seconds": value.get("duration_seconds"),
            "tags": metadata.get("tags"),
            "categories": [
                metadata.get("topic")
                or metadata.get("category")
                or metadata.get("niche")
            ],
            "creator_or_channel": value.get("creator"),
            "published_at": value.get("published_at"),
            "rights_status": value.get("rights_status"),
            "permission_notes": (
                "Scout V1 recorded explicit permission confirmation."
                if value.get("permission_confirmed")
                else ""
            ),
            "user_notes": "Imported from existing local BOBA Scout V1 metadata.",
        }

    def score_items(
        self,
        items: Sequence[BobaScoutItemV2],
        *,
        duplicate_map: Mapping[str, str] | None = None,
        positive_terms: set[str] | None = None,
        negative_terms: set[str] | None = None,
        creator_learning_available: bool = False,
        approval_learning_available: bool = False,
        performance_feedback_available: bool = False,
    ) -> list[BobaScoutScoreV2]:
        duplicates = duplicate_map or _duplicate_map(items)
        positive = positive_terms or set()
        negative = negative_terms or set()
        return [
            self._score(
                item,
                duplicate_of=duplicates.get(item.item_id),
                positive_terms=positive,
                negative_terms=negative,
                creator_learning_available=creator_learning_available,
                approval_learning_available=approval_learning_available,
                performance_feedback_available=performance_feedback_available,
            )
            for item in items
        ]

    def _score(
        self,
        item: BobaScoutItemV2,
        *,
        duplicate_of: str | None,
        positive_terms: set[str],
        negative_terms: set[str],
        creator_learning_available: bool,
        approval_learning_available: bool,
        performance_feedback_available: bool,
    ) -> BobaScoutScoreV2:
        item_terms = _tokens(
            item.title,
            item.description,
            *item.tags,
            *item.categories,
            item.user_notes,
        )
        positive_overlap = item_terms & positive_terms
        negative_overlap = item_terms & negative_terms
        creator_fit = 0.42
        creator_fit += min(0.28, len(positive_overlap) * 0.05)
        creator_fit -= min(0.28, len(negative_overlap) * 0.06)
        if item.tags or item.categories:
            creator_fit += 0.05

        topic_fit = 0.32
        topic_fit += 0.16 if item.tags or item.categories else 0.0
        topic_fit += min(0.2, len(positive_overlap) * 0.04)
        topic_fit -= min(0.16, len(negative_overlap) * 0.04)
        if item.description:
            topic_fit += 0.08

        short_hits = len(item_terms & _SHORTABILITY_TERMS)
        shortability = 0.28 + min(0.42, short_hits * 0.08)
        if item.duration_seconds is not None:
            if 60 <= item.duration_seconds <= 7_200:
                shortability += 0.12
            elif item.duration_seconds < 30:
                shortability -= 0.08
        hook_hits = len(item_terms & _HOOK_TERMS)
        hook = 0.25 + min(0.48, hook_hits * 0.1)
        if "?" in item.title:
            hook += 0.1
        if 4 <= len(item.title.split()) <= 16:
            hook += 0.08
        emotional_hits = len(item_terms & _EMOTIONAL_TERMS)
        emotional = 0.22 + min(0.58, emotional_hits * 0.1)
        trend_context = 0.25
        trend_context += 0.12 if item.tags or item.categories else 0.0
        trend_context += 0.08 if item.published_at else 0.0
        if item.user_notes and any(
            term in item.user_notes.casefold()
            for term in ("current", "timely", "trend", "seasonal")
        ):
            trend_context += 0.08
        novelty = 0.18 if duplicate_of else 0.68
        if {"unexpected", "unusual", "first", "myth"} & item_terms:
            novelty += 0.12
        rights = {
            "owned": 1.0,
            "licensed": 0.95,
            "permission_granted": 0.9,
            "permission_needed": 0.35,
            "unknown": 0.18,
            "blocked": 0.0,
        }[item.rights_status]
        creator_fit = _clamp(creator_fit)
        topic_fit = _clamp(topic_fit)
        shortability = _clamp(shortability)
        hook = _clamp(hook)
        emotional = _clamp(emotional)
        trend_context = _clamp(trend_context)
        novelty = _clamp(novelty)
        review_priority = _clamp(
            creator_fit * 0.14
            + topic_fit * 0.14
            + shortability * 0.17
            + hook * 0.16
            + emotional * 0.13
            + trend_context * 0.07
            + novelty * 0.09
            + rights * 0.1
        )
        confidence = 0.3
        confidence += 0.08 if item.title else 0.0
        confidence += 0.1 if item.description else 0.0
        confidence += 0.08 if item.tags or item.categories else 0.0
        confidence += 0.06 if item.duration_seconds is not None else 0.0
        confidence += 0.1 if item.rights_status != "unknown" else 0.0
        confidence += 0.05 if creator_learning_available else 0.0
        confidence += 0.04 if approval_learning_available else 0.0
        confidence += 0.04 if performance_feedback_available else 0.0
        reasons = [
            f"Hook potential {hook:.2f} from supplied title and description terms.",
            f"Shortability {shortability:.2f} from supplied format, story, and duration metadata.",
            f"Rights readiness {rights:.2f} from the user-provided rights status only.",
        ]
        if positive_overlap:
            reasons.append(
                "Matched bounded positive creator signals: "
                + ", ".join(sorted(positive_overlap)[:6])
                + "."
            )
        if negative_overlap:
            reasons.append(
                "Matched bounded caution signals: "
                + ", ".join(sorted(negative_overlap)[:6])
                + "."
            )
        if performance_feedback_available:
            reasons.append(
                "Performance Feedback was used conservatively as manual advisory evidence."
            )
        warnings = [
            "No external trend verification or audience prediction was used.",
            "A source URL, when present, was not fetched.",
        ]
        if duplicate_of:
            warnings.append(
                f"Metadata is similar to {duplicate_of}; novelty was reduced."
            )
        if item.rights_status == "unknown":
            warnings.append(
                "Rights are unknown and must not be treated as safe or processing-ready."
            )
        elif item.rights_status == "permission_needed":
            warnings.append("Permission is needed before any future ingestion.")
        elif item.rights_status == "blocked":
            warnings.append("Rights status is blocked; the item must not be ingested.")
        return BobaScoutScoreV2(
            item_id=item.item_id,
            creator_fit_score=creator_fit,
            topic_fit_score=topic_fit,
            shortability_score=shortability,
            hook_potential_score=hook,
            emotional_story_score=_clamp(emotional),
            trend_context_score=trend_context,
            novelty_score=novelty,
            rights_readiness_score=rights,
            review_priority_score=review_priority,
            confidence=_clamp(confidence),
            score_reasons=reasons,
            warnings=warnings,
        )

    def _recommend(
        self,
        item: BobaScoutItemV2,
        score: BobaScoutScoreV2,
        *,
        duplicate_of: str | None,
    ) -> BobaScoutRecommendationV2:
        if item.rights_status == "blocked":
            recommendation: BobaScoutRecommendationTypeV2 = "blocked"
            reason = "The user-provided rights status is blocked."
        elif duplicate_of:
            recommendation = "reject"
            reason = (
                f"Metadata is substantially similar to {duplicate_of}; review the original "
                "instead of creating a duplicate queue entry."
            )
        elif item.rights_status in {"permission_needed", "unknown"}:
            recommendation = "seek_permission"
            reason = (
                "The metadata may merit review, but rights or permission are not ready."
            )
        elif score.review_priority_score >= 0.64:
            recommendation = "review_now"
            reason = "The item combines strong metadata promise with a reviewable rights state."
        elif score.review_priority_score >= 0.4:
            recommendation = "save_for_later"
            reason = "The item is reviewable but has lower metadata-only priority."
        else:
            recommendation = "reject"
            reason = "The supplied metadata does not currently support a useful review priority."
        priority: BobaScoutPriorityV2
        if score.review_priority_score >= 0.8 and recommendation == "review_now":
            priority = "urgent"
        elif score.review_priority_score >= 0.64:
            priority = "high"
        elif score.review_priority_score >= 0.45:
            priority = "medium"
        else:
            priority = "low"
        rights_review_required = item.rights_status not in {
            "owned",
            "licensed",
            "permission_granted",
        }
        angles = (
            self._angles(item, score)
            if recommendation in {"review_now", "save_for_later", "seek_permission"}
            and score.review_priority_score >= 0.42
            else []
        )
        review_questions = [
            "Does the metadata accurately describe the source without inventing context?",
            "Does this possible angle fit the creator's current project goals?",
            "Has a human independently confirmed rights and permission?",
        ]
        if item.source_url:
            review_questions.append(
                "Open the reference manually only if authorized; BOBA did not fetch it."
            )
        return BobaScoutRecommendationV2(
            item_id=item.item_id,
            recommendation=recommendation,
            priority=priority,
            reason=reason,
            suggested_short_angles=angles,
            suggested_review_questions=review_questions,
            rights_review_required=rights_review_required,
            human_review_required=True,
            warnings=[
                *score.warnings,
                "Content Scout cannot confirm copyright safety.",
            ],
            limitations=[
                "Recommendation is based only on local/user-provided metadata.",
                "No popularity, audience, media, or verified trend signal was available.",
            ],
        )

    @staticmethod
    def _angles(
        item: BobaScoutItemV2,
        score: BobaScoutScoreV2,
    ) -> list[BobaSuggestedShortAngleV2]:
        base = item.title or item.description[:120]
        terms = _tokens(item.title, item.description)
        specs: list[tuple[str, str, str]] = []
        if terms & _HOOK_TERMS or "?" in item.title:
            specs.append(
                (
                    f"Possible angle: the central question in {base}",
                    f"Open with the question already implied by the supplied metadata for {base}.",
                    "A bounded open loop may help a reviewer find a clear source-supported payoff.",
                )
            )
        if terms & _EMOTIONAL_TERMS:
            specs.append(
                (
                    f"Possible angle: the emotional turn in {base}",
                    f"Review whether {base} contains a source-supported struggle-to-change beat.",
                    "A genuine emotional turn may support a complete short story.",
                )
            )
        if terms & _SHORTABILITY_TERMS or not specs:
            specs.append(
                (
                    f"Possible angle: the concise lesson in {base}",
                    f"Look for one source-supported lesson already described by {base}.",
                    "A focused lesson may reduce context dependency.",
                )
            )
        return [
            BobaSuggestedShortAngleV2(
                angle_id=_stable_id("scout_angle", item.item_id, str(index), title),
                title=_text(title, maximum=300),
                hook_direction=_text(hook, maximum=500),
                why_it_might_work=_text(why, maximum=500),
                risk=(
                    "Verify the source manually and preserve its actual meaning; this possible "
                    "angle must not invent facts or imply rights clearance."
                ),
                confidence=_clamp(score.confidence - 0.08 - index * 0.04),
            )
            for index, (title, hook, why) in enumerate(specs[:3])
        ]

    @staticmethod
    def _queue(
        recommendations: Sequence[BobaScoutRecommendationV2],
        scores: Mapping[str, BobaScoutScoreV2],
        duplicate_map: Mapping[str, str],
    ) -> BobaScoutReviewQueueV2:
        ordered = sorted(
            recommendations,
            key=lambda item: (
                scores[item.item_id].review_priority_score,
                item.item_id,
            ),
            reverse=True,
        )
        top = [item for item in ordered if item.recommendation == "review_now"]
        backup = [
            item for item in ordered if item.recommendation == "save_for_later"
        ]
        permission = [
            item for item in ordered if item.recommendation == "seek_permission"
        ]
        blocked = [item for item in ordered if item.recommendation == "blocked"]
        duplicates = [item for item in ordered if item.item_id in duplicate_map]
        warnings = [
            "Queue order is advisory and requires human review before any future action."
        ]
        if permission:
            warnings.append(
                "Permission-needed and unknown-rights items are separated from review-ready items."
            )
        return BobaScoutReviewQueueV2(
            top_items=top,
            backup_items=backup,
            permission_needed_items=permission,
            blocked_items=blocked,
            duplicate_or_similar_items=duplicates,
            queue_summary=(
                f"{len(top)} review-now, {len(backup)} backup, "
                f"{len(permission)} permission-review, {len(blocked)} blocked, and "
                f"{len(duplicates)} duplicate/similar item(s)."
            ),
            warnings=warnings,
        )

    @staticmethod
    def _summary(
        items: Sequence[BobaScoutItemV2],
        scores: Sequence[BobaScoutScoreV2],
        recommendations: Sequence[BobaScoutRecommendationV2],
    ) -> BobaContentScoutSummaryV2:
        score_by_id = {score.item_id: score for score in scores}
        topics = Counter(
            topic.casefold()
            for item in items
            for topic in [*item.categories, *item.tags]
            if topic
        )
        topic_scores: dict[str, list[float]] = {}
        for item in items:
            for topic in [*item.categories, *item.tags]:
                topic_scores.setdefault(topic.casefold(), []).append(
                    score_by_id[item.item_id].review_priority_score
                )
        strongest = sorted(
            topic_scores,
            key=lambda topic: sum(topic_scores[topic]) / len(topic_scores[topic]),
            reverse=True,
        )[:8]
        weakest = sorted(
            topic_scores,
            key=lambda topic: sum(topic_scores[topic]) / len(topic_scores[topic]),
        )[:8]
        rights = Counter(item.rights_status for item in items)
        recommendation_counts = Counter(
            item.recommendation for item in recommendations
        )
        return BobaContentScoutSummaryV2(
            total_items=len(items),
            review_now_count=recommendation_counts["review_now"],
            save_for_later_count=recommendation_counts["save_for_later"],
            permission_needed_count=recommendation_counts["seek_permission"],
            blocked_count=recommendation_counts["blocked"],
            strongest_topics=strongest,
            weakest_topics=weakest,
            repeated_themes=[
                f"{topic} appears in {count} item(s)."
                for topic, count in topics.most_common(12)
                if count >= 2
            ],
            rights_summary=[
                f"{status.replace('_', ' ')}: {count}"
                for status, count in sorted(rights.items())
            ],
            human_review_notes=[
                "Review the highest-priority rights-ready metadata first.",
                "Seek explicit permission for unknown or permission-needed items.",
                "Do not ingest, download, or render blocked items.",
                "Suggested angles are possibilities, not claims about source content.",
            ],
        )


def score_scout_items(
    items: Sequence[BobaScoutItemV2],
    *,
    creator_learning: ArtifactValue = None,
    approval_rejection_learning: ArtifactValue = None,
    performance_feedback: ArtifactValue = None,
    boba_memory: ArtifactValue = None,
) -> list[BobaScoutScoreV2]:
    creator = _dict(creator_learning)
    approval = _dict(approval_rejection_learning)
    performance = _dict(performance_feedback)
    memory = _dict(boba_memory)
    positive, negative = _artifact_terms(
        creator,
        approval,
        performance,
        memory,
    )
    return BobaContentScoutV2().score_items(
        items,
        positive_terms=positive,
        negative_terms=negative,
        creator_learning_available=bool(creator),
        approval_learning_available=bool(approval),
        performance_feedback_available=bool(performance),
    )
