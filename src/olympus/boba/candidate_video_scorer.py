"""Metadata-only candidate source video scoring for BOBA."""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from difflib import SequenceMatcher
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal, TypeAlias
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator

from olympus.boba.contracts import BobaContract, now_iso
from olympus.platform.errors import ValidationError

BobaCandidateVideoSourceTypeV1 = Literal[
    "csv",
    "json",
    "manual",
    "content_scout_v2",
    "research_brain",
    "trend_topic_watcher",
    "test_synthetic",
]
BobaCandidateRightsStatusV1 = Literal[
    "owned",
    "licensed",
    "permission_granted",
    "permission_needed",
    "unknown",
    "blocked",
]
BobaCandidateRightsReadinessV1 = Literal[
    "ready_for_review",
    "needs_permission",
    "unknown_needs_review",
    "blocked",
]
BobaCandidateVideoRecommendationTypeV1 = Literal[
    "review_now",
    "save_for_later",
    "seek_permission",
    "reject",
    "blocked",
]
BobaCandidateVideoPriorityV1 = Literal["low", "medium", "high", "urgent"]
ArtifactValue: TypeAlias = Mapping[str, Any] | BaseModel | None
CandidateImportResult: TypeAlias = tuple[
    "BobaCandidateVideoImportSourceV1",
    list["BobaCandidateVideoV1"],
    list[str],
]

_SPACE = re.compile(r"\s+")
_NON_WORD = re.compile(r"[^a-z0-9]+")
_TOKEN = re.compile(r"[a-z0-9]+")
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_MAX_IMPORT_BYTES = 2_000_000
_SHORTABILITY_TERMS = {
    "after",
    "before",
    "breakdown",
    "comeback",
    "comparison",
    "conflict",
    "interview",
    "lesson",
    "list",
    "mistake",
    "podcast",
    "reaction",
    "result",
    "reveal",
    "story",
    "transformation",
    "tutorial",
}
_HOOK_TERMS = {
    "contradiction",
    "curiosity",
    "how",
    "mistake",
    "mystery",
    "never",
    "nobody",
    "reason",
    "result",
    "reveal",
    "secret",
    "surprising",
    "truth",
    "unexpected",
    "why",
}
_STORY_TERMS = {
    "challenge",
    "conflict",
    "failure",
    "finally",
    "lesson",
    "payoff",
    "problem",
    "result",
    "reveal",
    "struggle",
    "tension",
    "then",
    "transformation",
    "turn",
}
_FORMAT_TERMS = {
    "commentary",
    "comparison",
    "explainer",
    "interview",
    "lesson",
    "list",
    "podcast",
    "reaction",
    "story",
    "tutorial",
}
_EMOTIONAL_TERMS = {
    "breakthrough",
    "comeback",
    "emotional",
    "failure",
    "fear",
    "growth",
    "hope",
    "loss",
    "motivation",
    "motivational",
    "regret",
    "struggle",
    "success",
    "surprise",
}
_RISK_TERMS = {
    "copyright",
    "copied",
    "dangerous",
    "disputed",
    "misleading",
    "permission",
    "private",
    "sensitive",
    "unverified",
    "unknown",
}
_VAGUE_TERMS = {"content", "misc", "stuff", "thing", "topic", "video"}
_RIGHTS_ALIASES: dict[str, BobaCandidateRightsStatusV1] = {
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


def _text(value: Any, *, maximum: int = 800) -> str:
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
        for token in _TOKEN.findall(_text(value, maximum=5_000).casefold())
        if len(token) >= 3
    }


def _compact_values(value: Any, *, maximum: int = 40) -> list[str]:
    if isinstance(value, str):
        parts: Sequence[Any] = re.split(r"[,;|]", value)
    elif isinstance(value, list | tuple | set):
        parts = list(value)
    else:
        parts = ()
    return list(
        dict.fromkeys(
            item
            for raw in parts
            if (item := _text(raw, maximum=100))
        )
    )[:maximum]


def _duration(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return round(float(value), 3) if float(value) >= 0 else None
    compact = _text(value, maximum=40)
    if ":" in compact:
        try:
            parts = [float(item) for item in compact.split(":")]
        except ValueError:
            return None
        seconds = 0.0
        for part in parts:
            seconds = seconds * 60 + part
        return round(seconds, 3) if seconds >= 0 else None
    try:
        parsed = float(compact)
    except ValueError:
        return None
    return round(parsed, 3) if parsed >= 0 else None


def _safe_local_file(path: str | Path, *, suffix: str) -> Path:
    raw = str(path)
    if "://" in raw:
        raise ValidationError(
            "Candidate Video Scorer import paths must be local files."
        )
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise ValidationError("Candidate Video Scorer import file was not found.")
    if source.suffix.casefold() != suffix:
        raise ValidationError(
            f"Candidate Video Scorer expected a local {suffix} file."
        )
    if source.stat().st_size > _MAX_IMPORT_BYTES:
        raise ValidationError(
            "Candidate Video Scorer import exceeds the 2 MB safety limit."
        )
    return source


def _normalize_label(value: Any) -> str:
    lowered = _text(value, maximum=300).casefold()
    return _SPACE.sub(" ", _NON_WORD.sub(" ", lowered)).strip()


def _normalized_rights(
    value: Any,
) -> tuple[BobaCandidateRightsStatusV1, list[str]]:
    normalized = _normalize_label(value).replace(" ", "_")
    if not normalized:
        return "unknown", [
            "Rights status was not provided and remains unknown."
        ]
    resolved = _RIGHTS_ALIASES.get(normalized)
    if resolved is None:
        return "unknown", [
            f"Unsupported rights status '{_text(value, maximum=80)}' became unknown."
        ]
    return resolved, []


def _signal_texts(
    artifact: ArtifactValue,
    *,
    keys: Sequence[str],
) -> str:
    payload = _dict(artifact)
    values: list[str] = []
    stack: list[Any] = [payload]
    while stack and len(values) < 300:
        current = stack.pop()
        if isinstance(current, Mapping):
            for key, value in current.items():
                if key in keys:
                    if isinstance(value, str | int | float):
                        values.append(_text(value, maximum=500))
                    elif isinstance(value, list | tuple):
                        values.extend(
                            _text(item, maximum=500)
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


class BobaCandidateVideoImportSourceV1(BobaContract):
    import_id: str = Field(min_length=1, max_length=128)
    source_type: BobaCandidateVideoSourceTypeV1
    source_label: str = Field(min_length=1, max_length=160)
    source_path: str = Field(default="", max_length=260)
    imported_at: str = Field(default_factory=now_iso)
    item_count: int = Field(default=0, ge=0)
    accepted_count: int = Field(default=0, ge=0)
    rejected_count: int = Field(default=0, ge=0)
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=32)


class BobaCandidateVideoV1(BobaContract):
    candidate_video_id: str = Field(min_length=1, max_length=128)
    title: str = Field(default="", max_length=300)
    description: str = Field(default="", max_length=1_500)
    source_label: str = Field(min_length=1, max_length=160)
    source_reference: str = Field(default="", max_length=300)
    source_url: str | None = Field(default=None, max_length=2_048)
    duration_seconds: float | None = Field(default=None, ge=0.0, le=172_800.0)
    creator_or_channel: str = Field(default="", max_length=200)
    published_at: str = Field(default="", max_length=80)
    topic_tags: list[str] = Field(default_factory=list, max_length=40)
    categories: list[str] = Field(default_factory=list, max_length=40)
    rights_status: BobaCandidateRightsStatusV1 = "unknown"
    permission_notes: str = Field(default="", max_length=600)
    user_notes: str = Field(default="", max_length=600)
    source_artifact_refs: list[str] = Field(default_factory=list, max_length=32)
    raw_metadata_summary: dict[str, Any] = Field(default_factory=dict)
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


class BobaCandidateVideoScoreV1(BobaContract):
    candidate_video_id: str = Field(min_length=1, max_length=128)
    creator_fit_score: float = Field(ge=0.0, le=1.0)
    topic_opportunity_score: float = Field(ge=0.0, le=1.0)
    research_support_score: float = Field(ge=0.0, le=1.0)
    trend_support_score: float = Field(ge=0.0, le=1.0)
    shortability_score: float = Field(ge=0.0, le=1.0)
    hook_potential_score: float = Field(ge=0.0, le=1.0)
    story_potential_score: float = Field(ge=0.0, le=1.0)
    format_fit_score: float = Field(ge=0.0, le=1.0)
    rights_readiness_score: float = Field(ge=0.0, le=1.0)
    risk_score: float = Field(ge=0.0, le=1.0)
    review_priority_score: float = Field(ge=0.0, le=1.0)
    overall_candidate_score: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    score_reasons: list[str] = Field(default_factory=list, max_length=32)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaShortsPotentialReviewV1(BobaContract):
    candidate_video_id: str = Field(min_length=1, max_length=128)
    possible_clip_types: list[str] = Field(default_factory=list, max_length=16)
    possible_hook_directions: list[str] = Field(
        default_factory=list,
        max_length=16,
    )
    possible_story_angles: list[str] = Field(default_factory=list, max_length=16)
    possible_format_styles: list[str] = Field(default_factory=list, max_length=16)
    emotional_story_promise: str = Field(min_length=1, max_length=700)
    likely_weaknesses: list[str] = Field(default_factory=list, max_length=24)
    human_review_questions: list[str] = Field(default_factory=list, max_length=24)
    confidence: float = Field(ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaCandidateRightsReviewV1(BobaContract):
    candidate_video_id: str = Field(min_length=1, max_length=128)
    rights_status: BobaCandidateRightsStatusV1
    rights_readiness: BobaCandidateRightsReadinessV1
    rights_review_required: bool
    permission_required: bool
    blocked: bool
    reason: str = Field(min_length=1, max_length=700)
    human_review_notes: list[str] = Field(default_factory=list, max_length=24)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaCandidateVideoRecommendationV1(BobaContract):
    candidate_video_id: str = Field(min_length=1, max_length=128)
    recommendation: BobaCandidateVideoRecommendationTypeV1
    priority: BobaCandidateVideoPriorityV1
    reason: str = Field(min_length=1, max_length=700)
    shorts_potential: BobaShortsPotentialReviewV1
    rights_review: BobaCandidateRightsReviewV1
    next_human_action: str = Field(min_length=1, max_length=700)
    warnings: list[str] = Field(default_factory=list, max_length=32)
    limitations: list[str] = Field(default_factory=list, max_length=32)


class BobaScoredCandidateVideoV1(BobaContract):
    candidate_video: BobaCandidateVideoV1
    score: BobaCandidateVideoScoreV1
    shorts_potential: BobaShortsPotentialReviewV1
    rights_review: BobaCandidateRightsReviewV1
    recommendation: BobaCandidateVideoRecommendationV1
    duplicate_of_candidate_video_id: str | None = Field(
        default=None,
        max_length=128,
    )


class BobaCandidateVideoReviewQueueV1(BobaContract):
    top_candidates: list[BobaCandidateVideoRecommendationV1] = Field(
        default_factory=list,
        max_length=500,
    )
    backup_candidates: list[BobaCandidateVideoRecommendationV1] = Field(
        default_factory=list,
        max_length=500,
    )
    permission_needed_candidates: list[
        BobaCandidateVideoRecommendationV1
    ] = Field(default_factory=list, max_length=500)
    blocked_candidates: list[BobaCandidateVideoRecommendationV1] = Field(
        default_factory=list,
        max_length=500,
    )
    duplicate_or_similar_candidates: list[
        BobaCandidateVideoRecommendationV1
    ] = Field(default_factory=list, max_length=500)
    rejected_candidates: list[BobaCandidateVideoRecommendationV1] = Field(
        default_factory=list,
        max_length=500,
    )
    queue_summary: str = Field(min_length=1, max_length=1_000)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaCandidateVideoHandoffTargetV1(BobaContract):
    candidate_video_ids: list[str] = Field(default_factory=list, max_length=100)
    topics: list[str] = Field(default_factory=list, max_length=64)
    recommended_actions: list[str] = Field(default_factory=list, max_length=32)
    prerequisites: list[str] = Field(default_factory=list, max_length=32)
    warnings: list[str] = Field(default_factory=list, max_length=32)
    apply_automatically: Literal[False] = False


class BobaCandidateVideoSourceHandoffV1(BobaContract):
    content_scout_handoff: BobaCandidateVideoHandoffTargetV1
    research_brain_handoff: BobaCandidateVideoHandoffTargetV1
    trend_topic_handoff: BobaCandidateVideoHandoffTargetV1
    rights_permission_gate_handoff: BobaCandidateVideoHandoffTargetV1
    future_ingestion_handoff: BobaCandidateVideoHandoffTargetV1
    apply_automatically: Literal[False] = False


class BobaCandidateVideoSummaryV1(BobaContract):
    total_candidates: int = Field(default=0, ge=0)
    review_now_count: int = Field(default=0, ge=0)
    save_for_later_count: int = Field(default=0, ge=0)
    seek_permission_count: int = Field(default=0, ge=0)
    blocked_count: int = Field(default=0, ge=0)
    rejected_count: int = Field(default=0, ge=0)
    strongest_candidates: list[str] = Field(default_factory=list, max_length=32)
    strongest_topics: list[str] = Field(default_factory=list, max_length=32)
    common_risks: list[str] = Field(default_factory=list, max_length=32)
    rights_summary: list[str] = Field(default_factory=list, max_length=32)
    human_review_notes: list[str] = Field(default_factory=list, max_length=32)


class BobaCandidateVideoSignalUsageV1(BobaContract):
    content_scout_used: bool = False
    research_brain_used: bool = False
    trend_topic_watcher_used: bool = False
    creator_learning_used: bool = False
    approval_rejection_learning_used: bool = False
    performance_feedback_used: bool = False
    memory_used: bool = False
    local_import_used: bool = False
    manual_input_used: bool = False
    external_api_used: Literal[False] = False
    url_fetching_used: Literal[False] = False
    scraping_used: Literal[False] = False
    downloading_used: Literal[False] = False
    media_ingestion_used: Literal[False] = False
    fallback_used: bool = False
    unavailable_signals: list[str] = Field(default_factory=list, max_length=32)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaCandidateVideoScorerSetV1(BobaContract):
    schema_version: Literal[
        "boba_candidate_video_scorer_v1"
    ] = "boba_candidate_video_scorer_v1"
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(min_length=1, max_length=512)
    created_at: str = Field(default_factory=now_iso)
    imported_sources: list[BobaCandidateVideoImportSourceV1] = Field(
        default_factory=list,
        max_length=200,
    )
    candidate_videos: list[BobaCandidateVideoV1] = Field(
        default_factory=list,
        max_length=5_000,
    )
    scored_candidates: list[BobaScoredCandidateVideoV1] = Field(
        default_factory=list,
        max_length=5_000,
    )
    review_queue: BobaCandidateVideoReviewQueueV1
    scorer_summary: BobaCandidateVideoSummaryV1
    source_handoffs: BobaCandidateVideoSourceHandoffV1
    signal_usage: BobaCandidateVideoSignalUsageV1
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)


def normalize_candidate_video(
    raw: Mapping[str, Any],
    *,
    source_label: str = "manual",
    item_index: int = 0,
    source_artifact_refs: Sequence[str] = (),
) -> BobaCandidateVideoV1:
    title = _text(raw.get("title") or raw.get("name"), maximum=300)
    description = _text(
        raw.get("description")
        or raw.get("summary")
        or raw.get("notes")
        or raw.get("user_notes"),
        maximum=1_500,
    )
    if not title and not description:
        raise ValidationError(
            "Candidate video requires a non-empty title or description.",
            details={"item_index": item_index},
        )
    effective_label = _text(
        raw.get("source_label") or raw.get("source") or source_label,
        maximum=160,
    ) or source_label
    rights_status, warnings = _normalized_rights(raw.get("rights_status"))
    raw_url = _text(
        raw.get("source_url") or raw.get("url"),
        maximum=2_048,
    )
    source_url: str | None = None
    if raw_url:
        parsed = urlparse(raw_url)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            source_url = raw_url
        else:
            warnings.append(
                "Invalid source URL was retained only as a source reference."
            )
    source_reference = _text(
        raw.get("source_reference")
        or raw.get("reference")
        or (raw_url if source_url is None else ""),
        maximum=300,
    )
    supplied_id = _text(
        raw.get("candidate_video_id")
        or raw.get("candidate_id")
        or raw.get("item_id"),
        maximum=128,
    )
    normalized_title = _normalize_label(title or description[:120])
    candidate_id = (
        supplied_id
        if _SAFE_ID.fullmatch(supplied_id)
        else _stable_id(
            "candidate_video",
            effective_label,
            source_reference,
            normalized_title,
            str(item_index),
        )
    )
    duration = _duration(
        raw.get("duration_seconds")
        if "duration_seconds" in raw
        else raw.get("duration")
    )
    if (
        raw.get("duration_seconds") not in (None, "")
        or raw.get("duration") not in (None, "")
    ) and duration is None:
        warnings.append("Invalid duration was ignored.")
    provided_fields = sorted(
        _text(key, maximum=80)
        for key, value in raw.items()
        if value not in (None, "", [], {})
    )[:48]
    references = list(
        dict.fromkeys(
            [
                *_compact_values(
                    raw.get("source_artifact_refs"),
                    maximum=32,
                ),
                *(
                    _text(value, maximum=200)
                    for value in source_artifact_refs
                    if _text(value, maximum=200)
                ),
            ]
        )
    )[:32]
    return BobaCandidateVideoV1(
        candidate_video_id=candidate_id,
        title=title,
        description=description,
        source_label=effective_label,
        source_reference=source_reference,
        source_url=source_url,
        duration_seconds=duration,
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
        topic_tags=_compact_values(
            raw.get("topic_tags") or raw.get("tags"),
            maximum=40,
        ),
        categories=_compact_values(
            raw.get("categories") or raw.get("category"),
            maximum=40,
        ),
        rights_status=rights_status,
        permission_notes=_text(
            raw.get("permission_notes"),
            maximum=600,
        ),
        user_notes=_text(
            raw.get("user_notes")
            or raw.get("notes"),
            maximum=600,
        ),
        source_artifact_refs=references,
        raw_metadata_summary={
            "metadata_only": True,
            "provided_fields": provided_fields,
            "raw_values_stored": False,
        },
        warnings=[
            *warnings,
            "A source URL or reference was preserved as text and was not fetched.",
        ],
        limitations=[
            "This record contains compact user-provided or local artifact metadata only.",
            "BOBA did not inspect, download, ingest, or verify the source video.",
            "Rights status is user-provided and is not a copyright-safety determination.",
        ],
    )


def _import_rows(
    values: Sequence[Any],
    *,
    source_type: BobaCandidateVideoSourceTypeV1,
    source_label: str,
    source_path: str = "",
    artifact_ref_prefix: str = "",
) -> CandidateImportResult:
    candidates: list[BobaCandidateVideoV1] = []
    rejected: list[str] = []
    for item_index, value in enumerate(values):
        if not isinstance(value, Mapping):
            rejected.append(f"Item {item_index + 1} was not an object.")
            continue
        artifact_id = _text(
            value.get("item_id")
            or value.get("idea_id")
            or value.get("watched_topic_id")
            or value.get("candidate_video_id"),
            maximum=128,
        )
        references = (
            [f"{artifact_ref_prefix}:{artifact_id}"]
            if artifact_ref_prefix and artifact_id
            else []
        )
        try:
            candidates.append(
                normalize_candidate_video(
                    value,
                    source_label=source_label,
                    item_index=item_index,
                    source_artifact_refs=references,
                )
            )
        except (ValidationError, ValueError) as exc:
            rejected.append(
                f"Item {item_index + 1}: {_text(exc, maximum=500)}"
            )
    warnings = (
        [
            f"{len(rejected)} invalid candidate item(s) were rejected.",
            *rejected[:20],
        ]
        if rejected
        else []
    )
    imported = BobaCandidateVideoImportSourceV1(
        import_id=_stable_id(
            "candidate_video_import",
            source_type,
            source_label,
            source_path,
            str(len(values)),
        ),
        source_type=source_type,
        source_label=source_label,
        source_path=source_path,
        item_count=len(values),
        accepted_count=len(candidates),
        rejected_count=len(rejected),
        warnings=warnings,
        limitations=[
            "Only compact candidate metadata was imported.",
            "No URL, platform, external API, download, or media ingestion was used.",
        ],
    )
    return imported, candidates, rejected


def import_candidate_videos_from_manual(
    values: Sequence[Mapping[str, Any]],
    *,
    source_label: str = "manual",
    source_type: BobaCandidateVideoSourceTypeV1 = "manual",
) -> CandidateImportResult:
    return _import_rows(
        values,
        source_type=source_type,
        source_label=source_label,
    )


def import_candidate_videos_from_csv(
    path: str | Path,
    *,
    source_label: str = "",
) -> CandidateImportResult:
    source = _safe_local_file(path, suffix=".csv")
    try:
        with source.open("r", encoding="utf-8-sig", newline="") as handle:
            values = list(csv.DictReader(handle))
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ValidationError(
            "Candidate Video Scorer CSV import could not be parsed."
        ) from exc
    return _import_rows(
        values,
        source_type="csv",
        source_label=source_label or source.stem,
        source_path=source.name,
    )


def import_candidate_videos_from_json(
    path: str | Path,
    *,
    source_label: str = "",
) -> CandidateImportResult:
    source = _safe_local_file(path, suffix=".json")
    try:
        raw = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValidationError(
            "Candidate Video Scorer JSON import could not be parsed."
        ) from exc
    if isinstance(raw, list):
        values = list(raw)
    elif isinstance(raw, Mapping):
        raw_values = (
            raw.get("candidates")
            or raw.get("candidate_videos")
            or raw.get("items")
            or raw.get("source_items")
        )
        if not isinstance(raw_values, list):
            raise ValidationError(
                "Candidate Video Scorer JSON must be a list or contain "
                "candidates, candidate_videos, items, or source_items."
            )
        values = list(raw_values)
    else:
        raise ValidationError(
            "Candidate Video Scorer JSON must contain candidate objects."
        )
    return _import_rows(
        values,
        source_type="json",
        source_label=source_label or source.stem,
        source_path=source.name,
    )


def _artifact_candidate_import(
    artifact: ArtifactValue,
    *,
    source_type: Literal[
        "content_scout_v2",
        "research_brain",
        "trend_topic_watcher",
    ],
) -> CandidateImportResult:
    payload = _dict(artifact)
    rows: list[dict[str, Any]] = []
    if source_type == "content_scout_v2":
        for item in _list(payload.get("scout_items")):
            if not isinstance(item, Mapping):
                continue
            rows.append(
                {
                    **dict(item),
                    "candidate_video_id": item.get("item_id"),
                    "topic_tags": item.get("tags"),
                    "source_label": "content_scout_v2",
                }
            )
    elif source_type == "research_brain":
        for idea in _list(payload.get("shorts_ideas")):
            if not isinstance(idea, Mapping):
                continue
            rows.append(
                {
                    "candidate_video_id": idea.get("idea_id"),
                    "title": idea.get("title"),
                    "description": " ".join(
                        value
                        for value in (
                            _text(idea.get("why_it_might_work"), maximum=600),
                            _text(idea.get("hook_direction"), maximum=500),
                        )
                        if value
                    ),
                    "source_label": "research_brain",
                    "source_reference": idea.get("idea_id"),
                    "topic_tags": [
                        idea.get("topic"),
                        idea.get("format_style"),
                    ],
                    "rights_status": "unknown",
                    "user_notes": (
                        "Research Brain idea metadata is conceptual and does not "
                        "identify a rights-cleared source video."
                    ),
                }
            )
    else:
        for topic in _list(payload.get("watched_topics")):
            if not isinstance(topic, Mapping):
                continue
            suggested_angles = _compact_values(
                topic.get("suggested_angles"),
                maximum=8,
            )
            rows.append(
                {
                    "candidate_video_id": topic.get("watched_topic_id"),
                    "title": f"Topic opportunity: {_text(topic.get('topic'), maximum=200)}",
                    "description": " ".join(
                        [
                            _text(topic.get("reason_for_watch"), maximum=700),
                            *suggested_angles,
                        ]
                    ),
                    "source_label": "trend_topic_watcher",
                    "source_reference": topic.get("watched_topic_id"),
                    "topic_tags": [topic.get("topic")],
                    "rights_status": "unknown",
                    "user_notes": (
                        "Trend Watcher topic metadata is not a source video and "
                        "is not real-time verified."
                    ),
                }
            )
    return _import_rows(
        rows,
        source_type=source_type,
        source_label=source_type,
        artifact_ref_prefix=source_type,
    )


def _duplicate_map(
    candidates: Sequence[BobaCandidateVideoV1],
) -> dict[str, str]:
    duplicates: dict[str, str] = {}
    canonical: list[tuple[BobaCandidateVideoV1, str]] = []
    for candidate in candidates:
        label = _normalize_label(candidate.title or candidate.description[:160])
        matched_id: str | None = None
        for existing, existing_label in canonical:
            if not label or not existing_label:
                continue
            exact_reference = bool(
                candidate.source_reference
                and existing.source_reference
                and candidate.source_reference.casefold()
                == existing.source_reference.casefold()
            )
            similarity = SequenceMatcher(
                None,
                label,
                existing_label,
            ).ratio()
            if exact_reference or label == existing_label or similarity >= 0.92:
                matched_id = existing.candidate_video_id
                break
        if matched_id:
            duplicates[candidate.candidate_video_id] = matched_id
        else:
            canonical.append((candidate, label))
    return duplicates


def _research_terms(artifact: ArtifactValue) -> set[str]:
    payload = _dict(artifact)
    summary = _dict(payload.get("research_summary"))
    values: list[Any] = [
        *_list(summary.get("strongest_topics")),
        *_list(summary.get("strongest_hook_angles")),
    ]
    for idea in _list(payload.get("shorts_ideas")):
        if isinstance(idea, Mapping):
            values.extend(
                [
                    idea.get("title"),
                    idea.get("topic"),
                    idea.get("hook_direction"),
                    idea.get("format_style"),
                ]
            )
    for insight in _list(payload.get("research_insights")):
        if isinstance(insight, Mapping):
            values.extend(
                [
                    insight.get("summary"),
                    insight.get("content_opportunity"),
                ]
            )
    return _tokens(*values)


def _trend_support(
    candidate_terms: set[str],
    artifact: ArtifactValue,
) -> tuple[float, list[str]]:
    payload = _dict(artifact)
    overlap_topics: list[str] = []
    priority = 0.0
    scores_by_topic = {
        _normalize_label(item.get("topic")): item
        for item in _list(payload.get("opportunity_scores"))
        if isinstance(item, Mapping)
    }
    for topic in _list(payload.get("watched_topics")):
        if not isinstance(topic, Mapping):
            continue
        topic_label = _text(topic.get("topic"), maximum=200)
        topic_tokens = _tokens(topic_label)
        if candidate_terms & topic_tokens:
            overlap_topics.append(topic_label)
            score = scores_by_topic.get(_normalize_label(topic_label), {})
            priority = max(
                priority,
                float(score.get("overall_topic_priority_score") or 0.0),
                float(topic.get("content_angle_potential") or 0.0),
            )
    if not overlap_topics:
        return (0.24 if payload else 0.2), []
    return _clamp(0.52 + min(0.3, priority * 0.3)), overlap_topics[:8]


def _scout_support(
    candidate: BobaCandidateVideoV1,
    candidate_terms: set[str],
    artifact: ArtifactValue,
) -> tuple[float, list[str]]:
    payload = _dict(artifact)
    if not payload:
        return 0.2, []
    score_by_id = {
        _text(item.get("item_id"), maximum=128): item
        for item in _list(payload.get("scored_items"))
        if isinstance(item, Mapping)
    }
    matched: list[str] = []
    support = 0.28
    for item in _list(payload.get("scout_items")):
        if not isinstance(item, Mapping):
            continue
        item_id = _text(item.get("item_id"), maximum=128)
        item_terms = _tokens(
            item.get("title"),
            item.get("description"),
            item.get("tags"),
            item.get("categories"),
        )
        exact_ref = (
            f"content_scout_v2:{item_id}" in candidate.source_artifact_refs
        )
        if exact_ref or candidate_terms & item_terms:
            matched.append(_text(item.get("title"), maximum=300) or item_id)
            item_score = score_by_id.get(item_id, {})
            support = max(
                support,
                0.5
                + float(item_score.get("review_priority_score") or 0.0) * 0.4,
            )
    return _clamp(support), matched[:8]


def _approval_terms(
    artifact: ArtifactValue,
) -> tuple[set[str], set[str]]:
    payload = _dict(artifact)
    positive: list[Any] = []
    negative: list[Any] = []
    for pattern in _list(payload.get("pattern_scores")):
        if not isinstance(pattern, Mapping):
            continue
        values = [pattern.get("summary"), pattern.get("guidance")]
        approvals = int(pattern.get("approval_count") or 0)
        rejections = int(pattern.get("rejection_count") or 0)
        if approvals > rejections:
            positive.extend(values)
        elif rejections > approvals:
            negative.extend(values)
    for case in _list(payload.get("approval_cases")):
        if isinstance(case, Mapping):
            positive.extend(
                [
                    case.get("approved_reason_summary"),
                    case.get("reusable_pattern"),
                ]
            )
    for case in _list(payload.get("rejection_cases")):
        if isinstance(case, Mapping):
            negative.extend(
                [
                    case.get("rejected_reason_summary"),
                    case.get("avoidance_rule"),
                ]
            )
    return _tokens(*positive), _tokens(*negative)


def _performance_terms(
    artifact: ArtifactValue,
) -> tuple[set[str], set[str]]:
    payload = _dict(artifact)
    summary = _dict(payload.get("pattern_summary"))
    positive = [
        *_list(summary.get("strongest_positive_patterns")),
        *_list(summary.get("repeated_winners")),
    ]
    negative = [
        *_list(summary.get("strongest_negative_patterns")),
        *_list(summary.get("repeated_failures")),
    ]
    return (
        _tokens(json.dumps(positive, default=str)),
        _tokens(json.dumps(negative, default=str)),
    )


def _rights_review(
    candidate: BobaCandidateVideoV1,
) -> BobaCandidateRightsReviewV1:
    if candidate.rights_status in {
        "owned",
        "licensed",
        "permission_granted",
    }:
        readiness: BobaCandidateRightsReadinessV1 = "ready_for_review"
        reason = (
            f"The user-provided rights status is {candidate.rights_status}; "
            "a human may review the source, but BOBA does not confirm copyright safety."
        )
        required = False
        permission_required = False
        blocked = False
    elif candidate.rights_status == "permission_needed":
        readiness = "needs_permission"
        reason = (
            "The user-provided status says permission is needed before any "
            "future ingestion or processing."
        )
        required = True
        permission_required = True
        blocked = False
    elif candidate.rights_status == "blocked":
        readiness = "blocked"
        reason = (
            "The user-provided rights status is blocked; the candidate must "
            "not proceed to ingestion."
        )
        required = True
        permission_required = False
        blocked = True
    else:
        readiness = "unknown_needs_review"
        reason = (
            "Rights are unknown. Unknown rights are never treated as safe or "
            "ready for ingestion."
        )
        required = True
        permission_required = True
        blocked = False
    warnings = [
        "This review reflects supplied metadata only and is not legal advice.",
        "BOBA does not confirm copyright safety.",
    ]
    if candidate.permission_notes:
        warnings.append(
            "Permission notes were preserved but were not independently verified."
        )
    return BobaCandidateRightsReviewV1(
        candidate_video_id=candidate.candidate_video_id,
        rights_status=candidate.rights_status,
        rights_readiness=readiness,
        rights_review_required=required,
        permission_required=permission_required,
        blocked=blocked,
        reason=reason,
        human_review_notes=[
            "Confirm ownership, license scope, or explicit permission.",
            "Confirm that planned clipping, editing, and publication are permitted.",
            "Do not rely on a URL, title, or metadata as evidence of rights.",
        ],
        warnings=warnings,
    )


def _shorts_potential(
    candidate: BobaCandidateVideoV1,
    score: BobaCandidateVideoScoreV1,
) -> BobaShortsPotentialReviewV1:
    terms = _tokens(
        candidate.title,
        candidate.description,
        candidate.topic_tags,
        candidate.categories,
    )
    clip_types = [
        f"Possible {format_name} clip, subject to source review."
        for format_name in sorted(terms & _FORMAT_TERMS)
    ][:6]
    if not clip_types:
        clip_types = [
            "Possible commentary or explainer clip, subject to source review."
        ]
    hook_directions: list[str] = []
    if terms & _HOOK_TERMS:
        hook_directions.append(
            "Possible hook direction: test the supplied curiosity, result, or "
            "reveal wording without adding unsupported claims."
        )
    if candidate.title:
        hook_directions.append(
            f"Possible hook direction: reframe the supplied title '{candidate.title}' "
            "only after reviewing the actual source."
        )
    story_angles: list[str] = []
    if terms & _STORY_TERMS:
        story_angles.append(
            "Possible story angle: organize the supplied problem, tension, turn, "
            "or result language into a complete arc if the source supports it."
        )
    else:
        story_angles.append(
            "Possible story angle: look for a complete setup and payoff during "
            "human source review; metadata alone does not establish one."
        )
    formats = [
        f"Possible {format_name} format."
        for format_name in sorted(terms & _FORMAT_TERMS)
    ][:6] or ["Possible explainer format after source review."]
    emotional = sorted(terms & _EMOTIONAL_TERMS)
    emotional_promise = (
        "Metadata may support an emotional story involving "
        + ", ".join(emotional[:5])
        + ", if the source confirms those elements."
        if emotional
        else (
            "Metadata does not establish a clear emotional promise; a human "
            "must inspect the source before choosing an angle."
        )
    )
    weaknesses: list[str] = []
    if not candidate.description:
        weaknesses.append("Description is missing, so context is weak.")
    if not candidate.topic_tags and not candidate.categories:
        weaknesses.append("Topic tags and categories are missing.")
    if candidate.duration_seconds is None:
        weaknesses.append("Duration was not provided.")
    if candidate.rights_status == "unknown":
        weaknesses.append("Rights are unknown and require review.")
    if score.research_support_score < 0.4:
        weaknesses.append("Research support is limited in saved local artifacts.")
    if score.trend_support_score < 0.4:
        weaknesses.append(
            "Trend support is limited and never real-time verified."
        )
    return BobaShortsPotentialReviewV1(
        candidate_video_id=candidate.candidate_video_id,
        possible_clip_types=clip_types,
        possible_hook_directions=hook_directions[:8],
        possible_story_angles=story_angles,
        possible_format_styles=formats,
        emotional_story_promise=emotional_promise,
        likely_weaknesses=weaknesses,
        human_review_questions=[
            "Does the actual source contain a complete setup, tension, and payoff?",
            "Can a Short remain accurate without inventing missing context?",
            "Does the source contain a strong opening or reveal supported by evidence?",
            "Are ownership, license, and permission sufficient for the intended use?",
        ],
        confidence=_clamp(
            0.24
            + (0.16 if candidate.description else 0.0)
            + (0.12 if candidate.topic_tags or candidate.categories else 0.0)
            + score.shortability_score * 0.18
            + score.story_potential_score * 0.12
        ),
        warnings=[
            "All suggestions are possible directions derived from metadata only.",
            "BOBA did not inspect or ingest the source video.",
        ],
    )


def _score_candidate(
    candidate: BobaCandidateVideoV1,
    *,
    duplicate_of: str | None,
    content_scout: ArtifactValue,
    research_brain: ArtifactValue,
    trend_topic_watcher: ArtifactValue,
    creator_learning: ArtifactValue,
    approval_rejection_learning: ArtifactValue,
    performance_feedback: ArtifactValue,
    boba_memory: ArtifactValue,
) -> tuple[BobaCandidateVideoScoreV1, float]:
    terms = _tokens(
        candidate.title,
        candidate.description,
        candidate.topic_tags,
        candidate.categories,
        candidate.user_notes,
    )
    creator_text = " ".join(
        (
            _signal_texts(
                creator_learning,
                keys=(
                    "preferred_clip_types",
                    "preferred_hook_styles",
                    "story_angle_preferences",
                    "pacing_preferences",
                    "repeated_feedback",
                    "summary",
                ),
            ),
            _signal_texts(
                boba_memory,
                keys=("main_topics", "source_summary", "summary"),
            ),
        )
    )
    creator_terms = _tokens(creator_text)
    creator_overlap = terms & creator_terms
    creator_fit = 0.38
    creator_fit += min(0.24, len(creator_overlap) * 0.05)
    if candidate.topic_tags or candidate.categories:
        creator_fit += 0.05

    approval_positive, approval_negative = _approval_terms(
        approval_rejection_learning
    )
    approval_adjustment = (
        0.08 if terms & approval_positive else 0.0
    ) - (0.08 if terms & approval_negative else 0.0)
    performance_positive, performance_negative = _performance_terms(
        performance_feedback
    )
    performance_adjustment = (
        0.08 if terms & performance_positive else 0.0
    ) - (0.08 if terms & performance_negative else 0.0)
    creator_fit = _clamp(
        creator_fit + approval_adjustment + performance_adjustment
    )

    research_overlap = terms & _research_terms(research_brain)
    research_support = _clamp(
        (0.26 if _dict(research_brain) else 0.2)
        + min(0.58, len(research_overlap) * 0.08)
    )
    trend_support, trend_topics = _trend_support(
        terms,
        trend_topic_watcher,
    )
    scout_support, scout_matches = _scout_support(
        candidate,
        terms,
        content_scout,
    )
    topic_opportunity = _clamp(
        0.22
        + research_support * 0.22
        + trend_support * 0.28
        + scout_support * 0.18
        + (0.08 if candidate.topic_tags or candidate.categories else 0.0)
    )

    shortability = _clamp(
        0.25
        + min(0.48, len(terms & _SHORTABILITY_TERMS) * 0.08)
        + (
            0.1
            if candidate.duration_seconds is not None
            and 60 <= candidate.duration_seconds <= 10_800
            else 0.0
        )
    )
    hook = _clamp(
        0.22
        + min(0.55, len(terms & _HOOK_TERMS) * 0.1)
        + (0.08 if "?" in candidate.title else 0.0)
    )
    story = _clamp(
        0.22
        + min(0.58, len(terms & _STORY_TERMS) * 0.09)
        + min(0.12, len(terms & _EMOTIONAL_TERMS) * 0.04)
    )
    format_fit = _clamp(
        0.3 + min(0.52, len(terms & _FORMAT_TERMS) * 0.11)
    )
    rights = {
        "owned": 1.0,
        "licensed": 0.94,
        "permission_granted": 0.9,
        "permission_needed": 0.28,
        "unknown": 0.12,
        "blocked": 0.0,
    }[candidate.rights_status]
    risk = 0.12
    if candidate.rights_status == "unknown":
        risk += 0.34
    elif candidate.rights_status == "permission_needed":
        risk += 0.28
    elif candidate.rights_status == "blocked":
        risk += 0.72
    if duplicate_of:
        risk += 0.26
    risk += min(
        0.3,
        len(
            terms
            & _tokens(
                candidate.permission_notes,
                candidate.user_notes,
                candidate.description,
            )
            & _RISK_TERMS
        )
        * 0.08,
    )
    normalized_title_terms = _tokens(candidate.title)
    if not candidate.description or (
        normalized_title_terms
        and normalized_title_terms.issubset(_VAGUE_TERMS)
    ):
        risk += 0.1
    risk = _clamp(risk)

    review_priority = _clamp(
        creator_fit * 0.1
        + topic_opportunity * 0.12
        + research_support * 0.08
        + trend_support * 0.08
        + scout_support * 0.08
        + shortability * 0.13
        + hook * 0.1
        + story * 0.1
        + format_fit * 0.07
        + rights * 0.09
        + (1.0 - risk) * 0.05
        - (0.12 if duplicate_of else 0.0)
    )
    overall = _clamp(
        review_priority * 0.55
        + shortability * 0.1
        + hook * 0.08
        + story * 0.08
        + creator_fit * 0.07
        + rights * 0.08
        + (1.0 - risk) * 0.04
    )
    confidence = _clamp(
        0.22
        + (0.12 if candidate.title else 0.0)
        + (0.14 if candidate.description else 0.0)
        + (0.08 if candidate.topic_tags or candidate.categories else 0.0)
        + (0.08 if candidate.duration_seconds is not None else 0.0)
        + (0.1 if candidate.rights_status != "unknown" else 0.0)
        + (0.05 if _dict(research_brain) else 0.0)
        + (0.05 if _dict(trend_topic_watcher) else 0.0)
        + (0.04 if _dict(content_scout) else 0.0)
    )
    reasons = [
        "All scores use local/user-provided metadata and saved BOBA artifacts only.",
        f"Rights readiness {rights:.2f} reflects the supplied rights status only.",
        f"Shortability {shortability:.2f} reflects supplied format and story terms.",
        f"Hook potential {hook:.2f} reflects supplied title and description terms.",
    ]
    if creator_overlap:
        reasons.append(
            "Matched bounded Creator Learning or memory terms: "
            + ", ".join(sorted(creator_overlap)[:6])
            + "."
        )
    if research_overlap:
        reasons.append(
            "Research Brain contains related local evidence or idea terms."
        )
    if trend_topics:
        reasons.append(
            "Trend support matched watched topics within provided data: "
            + ", ".join(trend_topics[:5])
            + "."
        )
    if scout_matches:
        reasons.append(
            "Content Scout contains related candidate metadata."
        )
    if approval_adjustment:
        reasons.append(
            "Explicit Approval/Rejection Learning adjusted creator fit by "
            f"{approval_adjustment:+.2f}."
        )
    if performance_adjustment:
        reasons.append(
            "Manual Performance Feedback adjusted creator fit by "
            f"{performance_adjustment:+.2f}."
        )
    warnings = [
        "No URL was fetched and no source video was inspected.",
        "No external popularity, real-time trend, or audience prediction was used.",
        "The score does not establish copyright safety or guaranteed performance.",
    ]
    if candidate.rights_status == "unknown":
        warnings.append("Unknown rights remain unsafe for ingestion.")
    if duplicate_of:
        warnings.append(
            f"Candidate is similar to {duplicate_of}; priority was reduced."
        )
    return (
        BobaCandidateVideoScoreV1(
            candidate_video_id=candidate.candidate_video_id,
            creator_fit_score=creator_fit,
            topic_opportunity_score=topic_opportunity,
            research_support_score=research_support,
            trend_support_score=trend_support,
            shortability_score=shortability,
            hook_potential_score=hook,
            story_potential_score=story,
            format_fit_score=format_fit,
            rights_readiness_score=rights,
            risk_score=risk,
            review_priority_score=review_priority,
            overall_candidate_score=overall,
            confidence=confidence,
            score_reasons=reasons,
            warnings=warnings,
        ),
        scout_support,
    )


def _recommendation(
    candidate: BobaCandidateVideoV1,
    score: BobaCandidateVideoScoreV1,
    shorts: BobaShortsPotentialReviewV1,
    rights: BobaCandidateRightsReviewV1,
    *,
    duplicate_of: str | None,
) -> BobaCandidateVideoRecommendationV1:
    if rights.blocked:
        recommendation: BobaCandidateVideoRecommendationTypeV1 = "blocked"
        reason = "Blocked rights prevent future ingestion or source processing."
        next_action = "Keep blocked unless a human records a new verified rights state."
    elif duplicate_of:
        recommendation = "reject"
        reason = (
            f"Candidate metadata is substantially similar to {duplicate_of}; "
            "review the earlier candidate instead."
        )
        next_action = "Confirm the duplicate match and keep only the stronger record."
    elif candidate.rights_status in {"permission_needed", "unknown"}:
        recommendation = "seek_permission"
        reason = (
            "Metadata may merit review, but rights are not ready for any future ingestion."
        )
        next_action = (
            "Confirm ownership, license, or explicit permission before any ingestion."
        )
    elif score.review_priority_score >= 0.64:
        recommendation = "review_now"
        reason = (
            "The candidate combines strong metadata-only Shorts potential with "
            "a user-provided reviewable rights state."
        )
        next_action = (
            "Human-review the actual source, verify rights scope, and approve or reject it."
        )
    elif score.review_priority_score >= 0.42:
        recommendation = "save_for_later"
        reason = (
            "The candidate is reviewable but has moderate metadata-only priority."
        )
        next_action = "Save the metadata and revisit after stronger evidence is available."
    else:
        recommendation = "reject"
        reason = (
            "The supplied metadata does not currently support useful review priority."
        )
        next_action = "Reject or enrich the candidate metadata before rescoring."
    if recommendation == "review_now" and score.review_priority_score >= 0.8:
        priority: BobaCandidateVideoPriorityV1 = "urgent"
    elif score.review_priority_score >= 0.64:
        priority = "high"
    elif score.review_priority_score >= 0.44:
        priority = "medium"
    else:
        priority = "low"
    return BobaCandidateVideoRecommendationV1(
        candidate_video_id=candidate.candidate_video_id,
        recommendation=recommendation,
        priority=priority,
        reason=reason,
        shorts_potential=shorts,
        rights_review=rights,
        next_human_action=next_action,
        warnings=[
            "Recommendation is advisory and metadata-only.",
            "Human approval and rights review are required before any future ingestion.",
        ],
        limitations=[
            "BOBA did not fetch, download, inspect, or ingest the source.",
            "Recommendation does not establish copyright safety or audience performance.",
        ],
    )


def score_candidate_videos(
    candidates: Sequence[BobaCandidateVideoV1],
    *,
    content_scout: ArtifactValue = None,
    research_brain: ArtifactValue = None,
    trend_topic_watcher: ArtifactValue = None,
    creator_learning: ArtifactValue = None,
    approval_rejection_learning: ArtifactValue = None,
    performance_feedback: ArtifactValue = None,
    boba_memory: ArtifactValue = None,
) -> list[BobaScoredCandidateVideoV1]:
    duplicates = _duplicate_map(candidates)
    scored: list[BobaScoredCandidateVideoV1] = []
    for candidate in candidates:
        duplicate_of = duplicates.get(candidate.candidate_video_id)
        score, _scout_support_score = _score_candidate(
            candidate,
            duplicate_of=duplicate_of,
            content_scout=content_scout,
            research_brain=research_brain,
            trend_topic_watcher=trend_topic_watcher,
            creator_learning=creator_learning,
            approval_rejection_learning=approval_rejection_learning,
            performance_feedback=performance_feedback,
            boba_memory=boba_memory,
        )
        rights = _rights_review(candidate)
        shorts = _shorts_potential(candidate, score)
        recommendation = _recommendation(
            candidate,
            score,
            shorts,
            rights,
            duplicate_of=duplicate_of,
        )
        scored.append(
            BobaScoredCandidateVideoV1(
                candidate_video=candidate,
                score=score,
                shorts_potential=shorts,
                rights_review=rights,
                recommendation=recommendation,
                duplicate_of_candidate_video_id=duplicate_of,
            )
        )
    return sorted(
        scored,
        key=lambda item: (
            item.score.review_priority_score,
            item.score.overall_candidate_score,
            item.candidate_video.candidate_video_id,
        ),
        reverse=True,
    )


def _review_queue(
    scored: Sequence[BobaScoredCandidateVideoV1],
) -> BobaCandidateVideoReviewQueueV1:
    recommendations = [item.recommendation for item in scored]
    top = [
        item for item in recommendations if item.recommendation == "review_now"
    ]
    backup = [
        item
        for item in recommendations
        if item.recommendation == "save_for_later"
    ]
    permission = [
        item
        for item in recommendations
        if item.recommendation == "seek_permission"
    ]
    blocked = [
        item for item in recommendations if item.recommendation == "blocked"
    ]
    duplicates = [
        item.recommendation
        for item in scored
        if item.duplicate_of_candidate_video_id is not None
    ]
    rejected = [
        item for item in recommendations if item.recommendation == "reject"
    ]
    return BobaCandidateVideoReviewQueueV1(
        top_candidates=top,
        backup_candidates=backup,
        permission_needed_candidates=permission,
        blocked_candidates=blocked,
        duplicate_or_similar_candidates=duplicates,
        rejected_candidates=rejected,
        queue_summary=(
            f"{len(top)} review-now, {len(backup)} backup, "
            f"{len(permission)} permission-needed, {len(blocked)} blocked, "
            f"{len(duplicates)} duplicate/similar, and {len(rejected)} rejected "
            "candidate recommendation(s)."
        ),
        warnings=[
            "Queue ordering is advisory and based on supplied metadata only.",
            "No candidate is approved for ingestion automatically.",
        ],
    )


def _source_handoffs(
    scored: Sequence[BobaScoredCandidateVideoV1],
    queue: BobaCandidateVideoReviewQueueV1,
) -> BobaCandidateVideoSourceHandoffV1:
    top_ids = [
        item.candidate_video.candidate_video_id
        for item in scored
        if item.recommendation.recommendation
        in {"review_now", "save_for_later", "seek_permission"}
    ][:50]
    topics = list(
        dict.fromkeys(
            topic
            for item in scored[:30]
            for topic in [
                *item.candidate_video.topic_tags,
                *item.candidate_video.categories,
            ]
        )
    )[:48]
    permission_ids = [
        item.candidate_video_id
        for item in [
            *queue.permission_needed_candidates,
            *queue.blocked_candidates,
        ]
    ]
    ingestion_ids = [
        item.candidate_video_id for item in queue.top_candidates
    ]
    common_prerequisites = [
        "Human approval is required.",
        "Rights and permission must be independently verified.",
        "No downstream module may fetch or ingest the source automatically.",
    ]
    return BobaCandidateVideoSourceHandoffV1(
        content_scout_handoff=BobaCandidateVideoHandoffTargetV1(
            candidate_video_ids=top_ids,
            topics=topics,
            recommended_actions=[
                "Use the advisory queue during a future explicit Scout review.",
                "Retain duplicate and rights warnings.",
            ],
            prerequisites=common_prerequisites,
            warnings=["Content Scout was not mutated by this scorer."],
        ),
        research_brain_handoff=BobaCandidateVideoHandoffTargetV1(
            candidate_video_ids=top_ids,
            topics=topics,
            recommended_actions=[
                "Research missing context and weak claims using local material.",
                "Verify possible hooks before publication.",
            ],
            prerequisites=common_prerequisites,
            warnings=["Research Brain was not mutated by this scorer."],
        ),
        trend_topic_handoff=BobaCandidateVideoHandoffTargetV1(
            candidate_video_ids=top_ids,
            topics=topics,
            recommended_actions=[
                "Watch these topics only in future user-provided snapshots."
            ],
            prerequisites=common_prerequisites,
            warnings=[
                "Trend Watcher was not mutated and no real-time trend was verified."
            ],
        ),
        rights_permission_gate_handoff=BobaCandidateVideoHandoffTargetV1(
            candidate_video_ids=permission_ids,
            topics=[],
            recommended_actions=[
                "Perform a deeper rights and permission review in a future gate."
            ],
            prerequisites=common_prerequisites,
            warnings=["This V1 scorer does not confirm copyright safety."],
        ),
        future_ingestion_handoff=BobaCandidateVideoHandoffTargetV1(
            candidate_video_ids=ingestion_ids,
            topics=[],
            recommended_actions=[
                "Consider ingestion only after explicit human approval and rights clearance."
            ],
            prerequisites=common_prerequisites,
            warnings=[
                "No media ingestion was triggered or authorized by this handoff."
            ],
        ),
        apply_automatically=False,
    )


def _summary(
    scored: Sequence[BobaScoredCandidateVideoV1],
) -> BobaCandidateVideoSummaryV1:
    recommendations = Counter(
        item.recommendation.recommendation for item in scored
    )
    rights = Counter(item.candidate_video.rights_status for item in scored)
    risks: list[str] = []
    if rights["unknown"]:
        risks.append(f"{rights['unknown']} candidate(s) have unknown rights.")
    if rights["permission_needed"]:
        risks.append(
            f"{rights['permission_needed']} candidate(s) need permission."
        )
    if rights["blocked"]:
        risks.append(f"{rights['blocked']} candidate(s) are blocked.")
    duplicate_count = sum(
        item.duplicate_of_candidate_video_id is not None for item in scored
    )
    if duplicate_count:
        risks.append(
            f"{duplicate_count} duplicate or similar candidate(s) need review."
        )
    topics = Counter(
        topic
        for item in scored
        for topic in [
            *item.candidate_video.topic_tags,
            *item.candidate_video.categories,
        ]
    )
    return BobaCandidateVideoSummaryV1(
        total_candidates=len(scored),
        review_now_count=recommendations["review_now"],
        save_for_later_count=recommendations["save_for_later"],
        seek_permission_count=recommendations["seek_permission"],
        blocked_count=recommendations["blocked"],
        rejected_count=recommendations["reject"],
        strongest_candidates=[
            item.candidate_video.title or item.candidate_video.description[:80]
            for item in scored[:12]
        ],
        strongest_topics=[
            topic for topic, _count in topics.most_common(16)
        ],
        common_risks=risks,
        rights_summary=[
            f"{status}: {count}"
            for status, count in sorted(rights.items())
        ],
        human_review_notes=[
            "Review the actual source before selecting any clip direction.",
            "Unknown rights are never safe or ingestion-ready.",
            "No recommendation guarantees performance.",
        ],
    )


class BobaCandidateVideoScorerV1:
    """Score local candidate metadata without source or network access."""

    def analyze(
        self,
        project_id: str,
        *,
        source_id: str | None = None,
        manual_candidates: Sequence[Mapping[str, Any]] = (),
        import_paths: Sequence[str | Path] = (),
        manual_source_type: BobaCandidateVideoSourceTypeV1 = "manual",
        source_label: str = "manual",
        content_scout: ArtifactValue = None,
        research_brain: ArtifactValue = None,
        trend_topic_watcher: ArtifactValue = None,
        creator_learning: ArtifactValue = None,
        approval_rejection_learning: ArtifactValue = None,
        performance_feedback: ArtifactValue = None,
        boba_memory: ArtifactValue = None,
        dry_run: bool = False,
    ) -> BobaCandidateVideoScorerSetV1:
        imported_sources: list[BobaCandidateVideoImportSourceV1] = []
        candidates: list[BobaCandidateVideoV1] = []
        rejected: list[str] = []
        if manual_candidates:
            imported, values, invalid = import_candidate_videos_from_manual(
                manual_candidates,
                source_label=source_label,
                source_type=manual_source_type,
            )
            imported_sources.append(imported)
            candidates.extend(values)
            rejected.extend(invalid)
        importers = {
            ".csv": import_candidate_videos_from_csv,
            ".json": import_candidate_videos_from_json,
        }
        for path in import_paths:
            importer = importers.get(Path(path).suffix.casefold())
            if importer is None:
                raise ValidationError(
                    "Candidate Video Scorer supports only local CSV and JSON imports."
                )
            imported, values, invalid = importer(path)
            imported_sources.append(imported)
            candidates.extend(values)
            rejected.extend(invalid)
        artifact_inputs: tuple[
            tuple[
                ArtifactValue,
                Literal[
                    "content_scout_v2",
                    "research_brain",
                    "trend_topic_watcher",
                ],
            ],
            ...,
        ] = (
            (content_scout, "content_scout_v2"),
            (research_brain, "research_brain"),
            (trend_topic_watcher, "trend_topic_watcher"),
        )
        for artifact, artifact_type in artifact_inputs:
            if not _dict(artifact):
                continue
            imported, values, invalid = _artifact_candidate_import(
                artifact,
                source_type=artifact_type,
            )
            imported_sources.append(imported)
            candidates.extend(values)
            rejected.extend(invalid)
        scored = score_candidate_videos(
            candidates,
            content_scout=content_scout,
            research_brain=research_brain,
            trend_topic_watcher=trend_topic_watcher,
            creator_learning=creator_learning,
            approval_rejection_learning=approval_rejection_learning,
            performance_feedback=performance_feedback,
            boba_memory=boba_memory,
        )
        queue = _review_queue(scored)
        summary = _summary(scored)
        handoffs = _source_handoffs(scored, queue)
        artifacts = {
            "content_scout": _dict(content_scout),
            "research_brain": _dict(research_brain),
            "trend_topic_watcher": _dict(trend_topic_watcher),
            "creator_learning": _dict(creator_learning),
            "approval_rejection_learning": _dict(
                approval_rejection_learning
            ),
            "performance_feedback": _dict(performance_feedback),
            "memory": _dict(boba_memory),
        }
        unavailable = [
            name for name, artifact in artifacts.items() if not artifact
        ]
        warnings = [
            "Candidate Video Scorer V1 used local/user-provided metadata only.",
            "BOBA did not fetch URLs, scrape, download, ingest media, or call external APIs.",
            "Human approval and rights review are required before future ingestion.",
        ]
        if rejected:
            warnings.append(
                f"{len(rejected)} invalid candidate item(s) were rejected."
            )
        if dry_run:
            warnings.append("Dry run: the scorer artifact was not persisted.")
        return BobaCandidateVideoScorerSetV1(
            project_id=project_id,
            source_id=_text(source_id or project_id, maximum=512),
            imported_sources=imported_sources,
            candidate_videos=candidates,
            scored_candidates=scored,
            review_queue=queue,
            scorer_summary=summary,
            source_handoffs=handoffs,
            signal_usage=BobaCandidateVideoSignalUsageV1(
                content_scout_used=bool(artifacts["content_scout"]),
                research_brain_used=bool(artifacts["research_brain"]),
                trend_topic_watcher_used=bool(
                    artifacts["trend_topic_watcher"]
                ),
                creator_learning_used=bool(artifacts["creator_learning"]),
                approval_rejection_learning_used=bool(
                    artifacts["approval_rejection_learning"]
                ),
                performance_feedback_used=bool(
                    artifacts["performance_feedback"]
                ),
                memory_used=bool(artifacts["memory"]),
                local_import_used=any(
                    source.source_type in {"csv", "json"}
                    for source in imported_sources
                ),
                manual_input_used=any(
                    source.source_type in {"manual", "test_synthetic"}
                    for source in imported_sources
                ),
                external_api_used=False,
                url_fetching_used=False,
                scraping_used=False,
                downloading_used=False,
                media_ingestion_used=False,
                fallback_used=bool(unavailable),
                unavailable_signals=unavailable,
                warnings=(
                    [
                        "Missing optional BOBA artifacts limited advisory scoring."
                    ]
                    if unavailable
                    else []
                ),
            ),
            warnings=warnings,
            limitations=[
                "V1 does not inspect source media or verify metadata accuracy.",
                "V1 does not confirm copyright safety, ownership, license scope, or permission.",
                "V1 does not verify real-time trends, popularity, or audience performance.",
                "Source handoffs are advisory and apply_automatically is always false.",
                "No candidate is ingested or sent to Olympus automatically.",
            ],
        )


def generate_candidate_video_scorer(
    project_id: str,
    **kwargs: Any,
) -> BobaCandidateVideoScorerSetV1:
    """Convenience wrapper for deterministic metadata-only scoring."""

    return BobaCandidateVideoScorerV1().analyze(project_id, **kwargs)
