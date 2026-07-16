"""Stable JSON-safe contracts for BOBA Memory System V1."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MemoryScope = Literal["project", "creator", "global"]
MemoryRecordType = Literal[
    "project_summary",
    "clip_selection",
    "clip_rejection",
    "editing_decision",
    "title_decision",
    "caption_decision",
    "music_decision",
    "motion_decision",
    "safety_warning",
    "user_feedback",
    "creator_preference",
    "learned_pattern",
    "failed_pattern",
    "experiment_result",
    "performance_result",
    "known_limitation",
]
MemoryTargetSystem = Literal[
    "planning",
    "ranking",
    "editorial_policy",
    "captions",
    "music",
    "motion",
    "upload_metadata",
    "safety",
    "frontend",
]


def memory_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def new_memory_id(prefix: str = "memory") -> str:
    return f"{prefix}_{uuid4().hex[:20]}"


class MemoryContract(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class BobaMemoryRecordV1(MemoryContract):
    memory_id: str = Field(default_factory=new_memory_id, min_length=1, max_length=128)
    scope: MemoryScope
    record_type: MemoryRecordType
    created_at: str = Field(default_factory=memory_now_iso)
    updated_at: str = Field(default_factory=memory_now_iso)
    source: str = Field(min_length=1, max_length=80)
    project_id: str | None = Field(default=None, max_length=128)
    clip_id: str | None = Field(default=None, max_length=128)
    creator_profile_id: str | None = Field(default=None, max_length=80)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    decay_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    tags: list[str] = Field(default_factory=list, max_length=32)
    summary: str = Field(min_length=1, max_length=600)
    evidence: list[str] = Field(default_factory=list, max_length=24)
    safe_excerpt: str = Field(default="", max_length=800)
    applies_to: list[MemoryTargetSystem] = Field(default_factory=list, max_length=16)
    warnings: list[str] = Field(default_factory=list, max_length=24)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("memory_id", "project_id", "clip_id", "creator_profile_id")
    @classmethod
    def validate_identifier(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.replace("_", "").replace("-", "").isalnum():
            raise ValueError("memory identifiers may contain only letters, numbers, '_' and '-'")
        return value

    @model_validator(mode="after")
    def validate_scope_identity(self) -> BobaMemoryRecordV1:
        if self.scope == "project" and not self.project_id:
            raise ValueError("project memory records require project_id")
        if self.scope == "creator" and not self.creator_profile_id:
            raise ValueError("creator memory records require creator_profile_id")
        return self


class BobaProjectMemoryV1(MemoryContract):
    project_id: str = Field(min_length=1, max_length=128)
    created_at: str = Field(default_factory=memory_now_iso)
    updated_at: str = Field(default_factory=memory_now_iso)
    version: Literal["1"] = "1"
    source_summary: str = Field(default="", max_length=600)
    video_duration: float | None = Field(default=None, ge=0.0)
    main_topics: list[str] = Field(default_factory=list, max_length=24)
    speakers_or_roles: list[str] = Field(default_factory=list, max_length=24)
    story_threads: list[str] = Field(default_factory=list, max_length=24)
    emotional_moments: list[str] = Field(default_factory=list, max_length=24)
    candidate_count: int = Field(default=0, ge=0)
    selected_clip_ids: list[str] = Field(default_factory=list, max_length=500)
    rejected_clip_ids: list[str] = Field(default_factory=list, max_length=1000)
    used_source_ranges: list[dict[str, float]] = Field(default_factory=list, max_length=500)
    unused_opportunities: list[str] = Field(default_factory=list, max_length=100)
    decisions_count: int = Field(default=0, ge=0)
    feedback_count: int = Field(default=0, ge=0)
    known_limitations: list[str] = Field(default_factory=list, max_length=64)
    memory_records: list[str] = Field(default_factory=list, max_length=2000)
    warnings: list[str] = Field(default_factory=list, max_length=64)


class BobaCreatorMemoryV1(MemoryContract):
    creator_memory_id: str = Field(default_factory=lambda: new_memory_id("creator_memory"))
    creator_profile_id: str = Field(min_length=1, max_length=80)
    created_at: str = Field(default_factory=memory_now_iso)
    updated_at: str = Field(default_factory=memory_now_iso)
    version: Literal["1"] = "1"
    learning_enabled: bool = False
    explicit_feedback_only: Literal[True] = True
    style_summary: str = Field(default="", max_length=600)
    preferred_clip_traits: list[str] = Field(default_factory=list, max_length=100)
    avoided_clip_traits: list[str] = Field(default_factory=list, max_length=100)
    preferred_hook_styles: list[str] = Field(default_factory=list, max_length=100)
    avoided_hook_styles: list[str] = Field(default_factory=list, max_length=100)
    preferred_title_styles: list[str] = Field(default_factory=list, max_length=100)
    avoided_title_styles: list[str] = Field(default_factory=list, max_length=100)
    preferred_caption_styles: list[str] = Field(default_factory=list, max_length=100)
    avoided_caption_styles: list[str] = Field(default_factory=list, max_length=100)
    preferred_music_moods: list[str] = Field(default_factory=list, max_length=100)
    avoided_music_moods: list[str] = Field(default_factory=list, max_length=100)
    preferred_motion_styles: list[str] = Field(default_factory=list, max_length=100)
    avoided_motion_styles: list[str] = Field(default_factory=list, max_length=100)
    banned_hashtags: list[str] = Field(default_factory=list, max_length=100)
    preferred_hashtags: list[str] = Field(default_factory=list, max_length=100)
    known_good_patterns: list[str] = Field(default_factory=list, max_length=100)
    known_bad_patterns: list[str] = Field(default_factory=list, max_length=100)
    feedback_count: int = Field(default=0, ge=0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list, max_length=64)


class BobaGlobalMemoryV1(MemoryContract):
    global_memory_id: str = Field(default="global_memory_v1", min_length=1, max_length=128)
    created_at: str = Field(default_factory=memory_now_iso)
    updated_at: str = Field(default_factory=memory_now_iso)
    version: Literal["1"] = "1"
    principles: list[str] = Field(default_factory=list, max_length=100)
    platform_patterns: list[str] = Field(default_factory=list, max_length=100)
    hook_patterns: list[str] = Field(default_factory=list, max_length=100)
    editing_patterns: list[str] = Field(default_factory=list, max_length=100)
    caption_patterns: list[str] = Field(default_factory=list, max_length=100)
    music_patterns: list[str] = Field(default_factory=list, max_length=100)
    motion_patterns: list[str] = Field(default_factory=list, max_length=100)
    metadata_patterns: list[str] = Field(default_factory=list, max_length=100)
    safety_principles: list[str] = Field(default_factory=list, max_length=100)
    known_limitations: list[str] = Field(default_factory=list, max_length=64)
    source_attribution: list[str] = Field(default_factory=list, max_length=32)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list, max_length=64)


class BobaMemoryQueryV1(MemoryContract):
    query_id: str = Field(default_factory=lambda: new_memory_id("query"))
    created_at: str = Field(default_factory=memory_now_iso)
    scope_filter: list[MemoryScope] = Field(default_factory=list, max_length=3)
    project_id: str | None = Field(default=None, max_length=128)
    creator_profile_id: str | None = Field(default=None, max_length=80)
    content_niche: str | None = Field(default=None, max_length=80)
    clip_traits: list[str] = Field(default_factory=list, max_length=32)
    target_system: MemoryTargetSystem | None = None
    tags: list[str] = Field(default_factory=list, max_length=32)
    limit: int = Field(default=20, ge=1, le=100)
    min_confidence: float = Field(default=0.2, ge=0.0, le=1.0)
    include_expired: bool = False
    reason: str = Field(default="", max_length=400)


class BobaMemoryRetrievalResultV1(MemoryContract):
    query_id: str = Field(min_length=1, max_length=128)
    records: list[BobaMemoryRecordV1] = Field(default_factory=list, max_length=100)
    summary: str = Field(default="", max_length=800)
    applied_lessons: list[str] = Field(default_factory=list, max_length=32)
    warnings: list[str] = Field(default_factory=list, max_length=32)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class BobaMemoryApplicationV1(MemoryContract):
    application_id: str = Field(default_factory=lambda: new_memory_id("application"))
    project_id: str = Field(min_length=1, max_length=128)
    clip_id: str | None = Field(default=None, max_length=128)
    target_system: MemoryTargetSystem
    memory_used: list[str] = Field(default_factory=list, max_length=100)
    adjustments: list[dict[str, Any]] = Field(default_factory=list, max_length=32)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    explanation: str = Field(default="", max_length=800)
    warnings: list[str] = Field(default_factory=list, max_length=32)
