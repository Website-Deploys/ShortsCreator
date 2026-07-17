"""Deterministic, local BOBA Memory V1 retrieval without external dependencies."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from olympus.boba.memory_contracts import (
    BobaMemoryQueryV1,
    BobaMemoryRecordV1,
    BobaMemoryRetrievalResultV1,
    MemoryTargetSystem,
)

if TYPE_CHECKING:
    from olympus.boba.store import BobaMemoryStore


def _age_days(record: BobaMemoryRecordV1) -> float:
    try:
        updated = datetime.fromisoformat(record.updated_at.replace("Z", "+00:00"))
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=UTC)
        return max(0.0, (datetime.now(UTC) - updated).total_seconds() / 86_400)
    except ValueError:
        return 365.0


def _effective_confidence(record: BobaMemoryRecordV1) -> float:
    decay = record.decay_rate * (_age_days(record) / 365.0)
    return max(0.0, record.confidence * (1.0 - decay))


def _eligible(record: BobaMemoryRecordV1, query: BobaMemoryQueryV1) -> bool:
    if query.scope_filter and record.scope not in query.scope_filter:
        return False
    if record.scope == "creator" and record.creator_profile_id != query.creator_profile_id:
        return False
    if record.scope == "project" and record.project_id != query.project_id:
        return False
    confidence = _effective_confidence(record)
    if confidence < query.min_confidence:
        return False
    return query.include_expired or confidence > 0.05


def _score(record: BobaMemoryRecordV1, query: BobaMemoryQueryV1) -> float:
    score = _effective_confidence(record) * 0.35 + record.importance * 0.25
    score += max(0.0, 1.0 - _age_days(record) / 365.0) * 0.1
    query_tags = {item.lower() for item in [*query.tags, *query.clip_traits]}
    record_tags = {item.lower() for item in record.tags}
    if query_tags:
        score += min(0.2, len(query_tags.intersection(record_tags)) * 0.06)
    if query.target_system and query.target_system in record.applies_to:
        score += 0.2
    if query.content_niche and (
        query.content_niche.lower() in record_tags
        or str(record.metadata.get("content_niche") or "").lower() == query.content_niche.lower()
    ):
        score += 0.12
    if record.project_id and record.project_id == query.project_id:
        score += 0.1
    if record.creator_profile_id and record.creator_profile_id == query.creator_profile_id:
        score += 0.1
    if record.record_type in {"known_limitation", "safety_warning"}:
        score += 0.08
    return round(score, 6)


def retrieve_memory(
    store: BobaMemoryStore,
    query: BobaMemoryQueryV1,
) -> BobaMemoryRetrievalResultV1:
    candidates = [record for record in store.list_records() if _eligible(record, query)]
    ranked = sorted(
        candidates,
        key=lambda item: (_score(item, query), item.updated_at),
        reverse=True,
    )
    selected = ranked[: query.limit]
    confidence = (
        round(sum(_effective_confidence(item) for item in selected) / len(selected), 3)
        if selected
        else 0.0
    )
    target = query.target_system or "this decision"
    return BobaMemoryRetrievalResultV1(
        query_id=query.query_id,
        records=selected,
        summary=(
            f"Retrieved {len(selected)} bounded memory record(s) for {target}."
            if selected
            else f"No eligible memory records were available for {target}."
        ),
        applied_lessons=[item.summary for item in selected[:8]],
        warnings=[] if selected else ["Memory fallback: no relevant eligible records were found."],
        confidence=confidence,
    )


def _query(
    store: BobaMemoryStore,
    *,
    project_id: str,
    creator_profile_id: str | None = None,
    target_system: MemoryTargetSystem,
    clip_traits: list[str] | None = None,
) -> BobaMemoryRetrievalResultV1:
    return retrieve_memory(
        store,
        BobaMemoryQueryV1(
            project_id=project_id,
            creator_profile_id=creator_profile_id,
            target_system=target_system,
            clip_traits=clip_traits or [],
            reason=f"Retrieve advisory memory for {target_system}.",
        ),
    )


def retrieve_for_project(
    store: BobaMemoryStore, project_id: str, creator_profile_id: str | None = None
) -> BobaMemoryRetrievalResultV1:
    return _query(
        store,
        project_id=project_id,
        creator_profile_id=creator_profile_id,
        target_system="planning",
    )


def retrieve_for_creator(
    store: BobaMemoryStore, profile_id: str
) -> BobaMemoryRetrievalResultV1:
    return retrieve_memory(
        store,
        BobaMemoryQueryV1(
            scope_filter=["creator"],
            creator_profile_id=profile_id,
            target_system="frontend",
            reason="Inspect explicit creator memory.",
        ),
    )


def retrieve_for_clip_decision(
    store: BobaMemoryStore,
    project_id: str,
    clip_traits: list[str],
    creator_profile_id: str | None = None,
) -> BobaMemoryRetrievalResultV1:
    return _query(
        store,
        project_id=project_id,
        creator_profile_id=creator_profile_id,
        target_system="ranking",
        clip_traits=clip_traits,
    )


def retrieve_for_editorial_policy(
    store: BobaMemoryStore,
    project_id: str,
    clip_id: str,
    creator_profile_id: str | None = None,
) -> BobaMemoryRetrievalResultV1:
    return _query(
        store,
        project_id=project_id,
        creator_profile_id=creator_profile_id,
        target_system="editorial_policy",
        clip_traits=[clip_id],
    )


def retrieve_for_upload_metadata(
    store: BobaMemoryStore, project_id: str, clip_id: str
) -> BobaMemoryRetrievalResultV1:
    return _query(
        store,
        project_id=project_id,
        target_system="upload_metadata",
        clip_traits=[clip_id],
    )


def retrieve_for_music(
    store: BobaMemoryStore, project_id: str, clip_id: str
) -> BobaMemoryRetrievalResultV1:
    return _query(store, project_id=project_id, target_system="music", clip_traits=[clip_id])


def retrieve_for_captions(
    store: BobaMemoryStore, project_id: str, clip_id: str
) -> BobaMemoryRetrievalResultV1:
    return _query(store, project_id=project_id, target_system="captions", clip_traits=[clip_id])


def retrieve_for_motion(
    store: BobaMemoryStore, project_id: str, clip_id: str
) -> BobaMemoryRetrievalResultV1:
    return _query(store, project_id=project_id, target_system="motion", clip_traits=[clip_id])
