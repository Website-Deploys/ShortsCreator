"""Explicit, local, advisory creator learning for BOBA."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, Literal, TypeAlias, cast
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from olympus.boba.contracts import BobaContract, now_iso

BobaCreatorFeedbackEventType = Literal[
    "approval",
    "rejection",
    "rating",
    "chosen_alternative",
    "correction",
    "preference_note",
    "manual_tag",
    "reset",
    "export",
]
BobaCreatorFeedbackTargetType = Literal[
    "clip",
    "candidate",
    "ranked_clip",
    "editorial_decision",
    "explanation",
    "creative_direction",
    "clip_brief",
    "hook_alternative",
    "caption_motion",
    "music_mood",
    "project",
]
BobaCreatorUserAction = Literal[
    "approved",
    "rejected",
    "liked",
    "disliked",
    "chose",
    "corrected",
    "noted",
    "tagged",
    "reset_requested",
    "export_requested",
]
BobaPreferenceCategory = Literal[
    "clip_type",
    "hook_style",
    "caption_style",
    "motion_style",
    "music_mood",
    "pacing",
    "story_angle",
    "risk_sensitivity",
    "production_priority",
    "general",
]
BobaPreferencePolarity = Literal["prefer", "avoid", "neutral"]
BobaCreatorLearningModule = Literal[
    "ranking",
    "editorial_decision",
    "creative_director",
    "clip_brief",
    "hook_retention",
    "caption_motion",
    "music_mood",
    "all",
]
ArtifactValue: TypeAlias = Mapping[str, Any] | BaseModel | None

_SAFE_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,180}$")
_STYLE_TEXT = re.compile(r"[^a-z0-9]+")
_IDENTIFIER_KEYS = {
    "id",
    "clip_id",
    "candidate_id",
    "ranked_clip_id",
    "decision_id",
    "explanation_id",
    "direction_id",
    "brief_id",
    "alternative_id",
    "recommendation_id",
    "project_id",
}
_EVENT_ACTIONS: dict[BobaCreatorFeedbackEventType, set[BobaCreatorUserAction]] = {
    "approval": {"approved"},
    "rejection": {"rejected"},
    "rating": {"liked", "disliked", "noted"},
    "chosen_alternative": {"chose"},
    "correction": {"corrected"},
    "preference_note": {"noted"},
    "manual_tag": {"tagged"},
    "reset": {"reset_requested"},
    "export": {"export_requested"},
}
_CATEGORY_MODULES: dict[
    BobaPreferenceCategory, tuple[BobaCreatorLearningModule, ...]
] = {
    "clip_type": ("ranking", "editorial_decision", "creative_director"),
    "hook_style": ("ranking", "editorial_decision", "hook_retention"),
    "caption_style": ("creative_director", "clip_brief", "caption_motion"),
    "motion_style": ("creative_director", "clip_brief", "caption_motion"),
    "music_mood": ("creative_director", "clip_brief", "music_mood"),
    "pacing": (
        "ranking",
        "editorial_decision",
        "creative_director",
        "clip_brief",
        "hook_retention",
    ),
    "story_angle": ("ranking", "editorial_decision", "creative_director"),
    "risk_sensitivity": ("editorial_decision", "clip_brief", "all"),
    "production_priority": ("editorial_decision", "creative_director", "clip_brief"),
    "general": ("all",),
}


def _clean_text(value: Any, *, maximum: int) -> str:
    return " ".join(str(value or "").split())[:maximum]


def _unique(values: list[str], *, maximum: int) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))[:maximum]


def _artifact(value: ArtifactValue) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return dict(value) if isinstance(value, Mapping) else {}


def _style(value: Any) -> str:
    text = _clean_text(value, maximum=120).casefold()
    normalized = _STYLE_TEXT.sub("_", text).strip("_")
    return normalized[:80]


def _stable_id(prefix: str, *values: str) -> str:
    digest = sha256("|".join(values).encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


class BobaExtractedPreferenceV1(BobaContract):
    preference_id: str = Field(min_length=1, max_length=128)
    category: BobaPreferenceCategory
    preference: str = Field(min_length=1, max_length=120)
    polarity: BobaPreferencePolarity
    strength: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list, max_length=12)
    confidence: float = Field(ge=0.0, le=1.0)
    applies_to_modules: list[BobaCreatorLearningModule] = Field(
        default_factory=list, max_length=8
    )


class BobaCreatorFeedbackEventV1(BobaContract):
    event_id: str = Field(
        default_factory=lambda: f"creator_feedback_{uuid4().hex[:20]}",
        min_length=1,
        max_length=128,
    )
    project_id: str = Field(min_length=1, max_length=128)
    created_at: str = Field(default_factory=now_iso)
    event_type: BobaCreatorFeedbackEventType
    target_type: BobaCreatorFeedbackTargetType
    target_id: str = Field(min_length=1, max_length=180)
    user_action: BobaCreatorUserAction
    rating: float | None = Field(default=None, ge=0.0, le=5.0)
    note: str = Field(default="", max_length=500)
    tags: list[str] = Field(default_factory=list, max_length=24)
    extracted_preferences: list[BobaExtractedPreferenceV1] = Field(
        default_factory=list, max_length=32
    )
    reversible: bool = True
    source_artifacts: list[str] = Field(default_factory=list, max_length=16)
    warnings: list[str] = Field(default_factory=list, max_length=24)

    @field_validator("event_id", "project_id", "target_id")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        if not _SAFE_ID.fullmatch(value):
            raise ValueError(
                "creator learning identifiers may contain only letters, numbers, "
                "'_', '-', '.', and ':'"
            )
        return value

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: str) -> str:
        return _clean_text(value, maximum=500)

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, value: list[str]) -> list[str]:
        return _unique(
            [_clean_text(item, maximum=80) for item in value],
            maximum=24,
        )

    @model_validator(mode="after")
    def validate_deliberate_action(self) -> BobaCreatorFeedbackEventV1:
        if self.user_action not in _EVENT_ACTIONS[self.event_type]:
            raise ValueError(
                f"{self.user_action!r} is not valid for {self.event_type!r} feedback"
            )
        if self.event_type == "rating" and self.rating is None:
            raise ValueError("rating feedback requires a numeric rating")
        if self.event_type in {"preference_note", "correction"} and not self.note:
            raise ValueError(f"{self.event_type} feedback requires a note")
        if self.event_type == "manual_tag" and not self.tags:
            raise ValueError("manual_tag feedback requires at least one tag")
        return self


class BobaCreatorLearningProfileV1(BobaContract):
    creator_id: str = Field(min_length=1, max_length=80)
    profile_version: Literal["1"] = "1"
    updated_at: str = Field(default_factory=now_iso)
    preferred_clip_types: list[str] = Field(default_factory=list, max_length=100)
    avoided_clip_types: list[str] = Field(default_factory=list, max_length=100)
    preferred_hook_styles: list[str] = Field(default_factory=list, max_length=100)
    avoided_hook_styles: list[str] = Field(default_factory=list, max_length=100)
    preferred_caption_styles: list[str] = Field(default_factory=list, max_length=100)
    avoided_caption_styles: list[str] = Field(default_factory=list, max_length=100)
    preferred_motion_styles: list[str] = Field(default_factory=list, max_length=100)
    avoided_motion_styles: list[str] = Field(default_factory=list, max_length=100)
    preferred_music_moods: list[str] = Field(default_factory=list, max_length=100)
    avoided_music_moods: list[str] = Field(default_factory=list, max_length=100)
    pacing_preferences: list[str] = Field(default_factory=list, max_length=100)
    story_angle_preferences: list[str] = Field(default_factory=list, max_length=100)
    risk_sensitivities: list[str] = Field(default_factory=list, max_length=100)
    repeated_feedback: list[str] = Field(default_factory=list, max_length=100)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    data_points: int = Field(default=0, ge=0)
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)


class BobaLearningInsightV1(BobaContract):
    insight_id: str = Field(min_length=1, max_length=128)
    category: BobaPreferenceCategory
    summary: str = Field(min_length=1, max_length=600)
    evidence_count: int = Field(ge=1)
    confidence: float = Field(ge=0.0, le=1.0)
    suggested_adjustment: str = Field(min_length=1, max_length=500)
    affected_modules: list[BobaCreatorLearningModule] = Field(
        default_factory=list, max_length=8
    )
    warnings: list[str] = Field(default_factory=list, max_length=16)


class BobaRecommendationGuidanceV1(BobaContract):
    ranking_guidance: list[str] = Field(default_factory=list, max_length=32)
    editorial_guidance: list[str] = Field(default_factory=list, max_length=32)
    creative_direction_guidance: list[str] = Field(default_factory=list, max_length=32)
    clip_brief_guidance: list[str] = Field(default_factory=list, max_length=32)
    hook_retention_guidance: list[str] = Field(default_factory=list, max_length=32)
    caption_motion_guidance: list[str] = Field(default_factory=list, max_length=32)
    music_mood_guidance: list[str] = Field(default_factory=list, max_length=32)
    general_guidance: list[str] = Field(default_factory=list, max_length=32)
    apply_automatically: Literal[False] = False


class BobaLearningAuditSummaryV1(BobaContract):
    total_events: int = Field(default=0, ge=0)
    approval_count: int = Field(default=0, ge=0)
    rejection_count: int = Field(default=0, ge=0)
    correction_count: int = Field(default=0, ge=0)
    note_count: int = Field(default=0, ge=0)
    reversible_event_count: int = Field(default=0, ge=0)
    irreversible_event_count: int = Field(default=0, ge=0)
    last_event_at: str | None = None
    reset_available: bool = True
    export_available: bool = True
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaCreatorLearningSignalUsageV1(BobaContract):
    boba_memory_used: bool = False
    feedback_events_used: int = Field(default=0, ge=0)
    clip_ranking_used: bool = False
    editorial_decision_used: bool = False
    explanation_used: bool = False
    creative_direction_used: bool = False
    clip_briefs_used: bool = False
    hook_retention_used: bool = False
    caption_motion_used: bool = False
    music_mood_used: bool = False
    fallback_used: bool = False
    unavailable_signals: list[str] = Field(default_factory=list, max_length=32)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaCreatorLearningSetV1(BobaContract):
    schema_version: Literal["boba_creator_learning_loop_v1"] = (
        "boba_creator_learning_loop_v1"
    )
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(min_length=1, max_length=128)
    created_at: str = Field(default_factory=now_iso)
    learning_profile: BobaCreatorLearningProfileV1
    feedback_events: list[BobaCreatorFeedbackEventV1] = Field(
        default_factory=list, max_length=5000
    )
    learning_insights: list[BobaLearningInsightV1] = Field(
        default_factory=list, max_length=200
    )
    recommendation_guidance: BobaRecommendationGuidanceV1
    audit_summary: BobaLearningAuditSummaryV1
    signal_usage: BobaCreatorLearningSignalUsageV1
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)


@dataclass
class _PreferenceAggregate:
    category: BobaPreferenceCategory
    preference: str
    modules: set[BobaCreatorLearningModule] = field(default_factory=set)
    prefer_count: int = 0
    avoid_count: int = 0
    neutral_count: int = 0
    strength_total: float = 0.0
    confidence_total: float = 0.0

    @property
    def evidence_count(self) -> int:
        return self.prefer_count + self.avoid_count + self.neutral_count

    @property
    def contradictory(self) -> bool:
        return self.prefer_count > 0 and self.avoid_count > 0

    @property
    def dominant_polarity(self) -> BobaPreferencePolarity:
        if self.prefer_count > self.avoid_count:
            return "prefer"
        if self.avoid_count > self.prefer_count:
            return "avoid"
        return "neutral"

    @property
    def confidence(self) -> float:
        if not self.evidence_count:
            return 0.0
        base = self.confidence_total / self.evidence_count
        repeated_boost = min(0.3, max(0, self.evidence_count - 1) * 0.12)
        contradiction_penalty = 0.28 if self.contradictory else 0.0
        return round(max(0.05, min(0.95, base + repeated_boost - contradiction_penalty)), 4)


class BobaCreatorLearningLoopV1:
    """Convert explicit creator feedback into bounded advisory guidance."""

    def create_feedback_event(
        self,
        *,
        project_id: str,
        event_type: BobaCreatorFeedbackEventType,
        target_type: BobaCreatorFeedbackTargetType,
        target_id: str,
        user_action: BobaCreatorUserAction,
        rating: float | None = None,
        note: str = "",
        tags: list[str] | None = None,
        reversible: bool = True,
        artifacts: Mapping[str, ArtifactValue] | None = None,
        event_id: str | None = None,
        created_at: str | None = None,
    ) -> BobaCreatorFeedbackEventV1:
        artifact_values = artifacts or {}
        target, sources = self._target_payload(target_type, target_id, artifact_values)
        event = BobaCreatorFeedbackEventV1(
            **({"event_id": event_id} if event_id else {}),
            **({"created_at": created_at} if created_at else {}),
            project_id=project_id,
            event_type=event_type,
            target_type=target_type,
            target_id=target_id,
            user_action=user_action,
            rating=rating,
            note=note,
            tags=tags or [],
            reversible=reversible,
            source_artifacts=sources,
            warnings=(
                [
                    "The target artifact was unavailable; only explicit note or tag "
                    "content was considered."
                ]
                if not target and target_type != "project"
                else []
            ),
        )
        preferences = self.extract_preferences(event, target)
        warnings = list(event.warnings)
        if not preferences and event_type not in {"reset", "export"}:
            warnings.append(
                "No conservative reusable preference could be extracted from this event."
            )
        return event.model_copy(
            update={
                "extracted_preferences": preferences,
                "warnings": _unique(warnings, maximum=24),
            }
        )

    def extract_preferences(
        self,
        event: BobaCreatorFeedbackEventV1,
        target: Mapping[str, Any] | None = None,
    ) -> list[BobaExtractedPreferenceV1]:
        pending: list[
            tuple[
                BobaPreferenceCategory,
                str,
                BobaPreferencePolarity,
                float,
                str,
            ]
        ] = []
        polarity, strength = self._event_polarity(event)
        if polarity != "neutral":
            for category, preference in self._target_traits(target or {}):
                pending.append(
                    (
                        category,
                        preference,
                        polarity,
                        strength,
                        (
                            f"Explicit {event.user_action} action on "
                            f"{event.target_type.replace('_', ' ')}."
                        ),
                    )
                )
        pending.extend(self._note_preferences(event.note))
        pending.extend(self._tag_preferences(event.tags, polarity))

        merged: dict[
            tuple[BobaPreferenceCategory, str, BobaPreferencePolarity],
            tuple[float, list[str]],
        ] = {}
        for category, preference, item_polarity, item_strength, evidence in pending:
            normalized = _style(preference)
            if not normalized:
                continue
            key = (category, normalized, item_polarity)
            previous_strength, previous_evidence = merged.get(key, (0.0, []))
            merged[key] = (
                max(previous_strength, item_strength),
                _unique([*previous_evidence, evidence], maximum=12),
            )

        extracted: list[BobaExtractedPreferenceV1] = []
        for (category, preference, item_polarity), (
            item_strength,
            evidence_items,
        ) in sorted(merged.items()):
            confidence = min(0.45, 0.18 + item_strength * 0.28)
            extracted.append(
                BobaExtractedPreferenceV1(
                    preference_id=_stable_id(
                        "creator_preference",
                        event.event_id,
                        category,
                        preference,
                        item_polarity,
                    ),
                    category=category,
                    preference=preference,
                    polarity=item_polarity,
                    strength=round(item_strength, 4),
                    evidence=evidence_items,
                    confidence=round(confidence, 4),
                    applies_to_modules=list(_CATEGORY_MODULES[category]),
                )
            )
        return extracted[:32]

    def analyze(
        self,
        project_id: str,
        feedback_events: list[BobaCreatorFeedbackEventV1],
        *,
        creator_id: str = "local_creator",
        source_id: str | None = None,
        boba_memory: ArtifactValue = None,
        clip_ranking: ArtifactValue = None,
        editorial_decision: ArtifactValue = None,
        explanation: ArtifactValue = None,
        creative_direction: ArtifactValue = None,
        clip_briefs: ArtifactValue = None,
        hook_retention: ArtifactValue = None,
        caption_motion: ArtifactValue = None,
        music_mood: ArtifactValue = None,
    ) -> BobaCreatorLearningSetV1:
        artifacts: dict[str, ArtifactValue] = {
            "clip_ranking": clip_ranking,
            "editorial_decision": editorial_decision,
            "explanation": explanation,
            "creative_direction": creative_direction,
            "clip_briefs": clip_briefs,
            "hook_retention": hook_retention,
            "caption_motion": caption_motion,
            "music_mood": music_mood,
        }
        enriched_events: list[BobaCreatorFeedbackEventV1] = []
        for event in feedback_events:
            if event.project_id != project_id:
                raise ValueError("creator feedback events must belong to the requested project")
            if event.extracted_preferences:
                enriched_events.append(event)
                continue
            target, sources = self._target_payload(
                event.target_type,
                event.target_id,
                artifacts,
            )
            preferences = self.extract_preferences(event, target)
            enriched_events.append(
                event.model_copy(
                    update={
                        "extracted_preferences": preferences,
                        "source_artifacts": _unique(
                            [*event.source_artifacts, *sources],
                            maximum=16,
                        ),
                    }
                )
            )

        aggregates = self._aggregate(enriched_events)
        timestamp = (
            max((event.created_at for event in enriched_events), default="")
            or now_iso()
        )
        profile = self._profile(creator_id, timestamp, enriched_events, aggregates)
        insights = self._insights(aggregates)
        guidance = self._guidance(aggregates, bool(_artifact(boba_memory)))
        audit = self._audit(enriched_events)
        usage = self._signal_usage(enriched_events, boba_memory, artifacts)
        warnings = [
            "Creator learning uses only explicit submitted feedback.",
            "Recommendation guidance is advisory and was not applied automatically.",
        ]
        limitations = [
            "No passive behavior, viewer analytics, or external trend data was used.",
            "Low-confidence preferences require repeated explicit feedback.",
        ]
        if not enriched_events:
            warnings.append("No explicit creator feedback events were available.")
            limitations.append("A reusable creator preference profile could not be inferred.")
        if any(item.contradictory for item in aggregates.values()):
            warnings.append(
                "Contradictory feedback was retained and confidence was reduced for review."
            )
        return BobaCreatorLearningSetV1(
            project_id=project_id,
            source_id=_clean_text(source_id or project_id, maximum=128),
            created_at=timestamp,
            learning_profile=profile,
            feedback_events=enriched_events,
            learning_insights=insights,
            recommendation_guidance=guidance,
            audit_summary=audit,
            signal_usage=usage,
            warnings=_unique(warnings, maximum=64),
            limitations=_unique(limitations, maximum=64),
        )

    def analyze_from_signals(
        self,
        project_id: str,
        feedback_events: list[BobaCreatorFeedbackEventV1],
        signals: Mapping[str, Any],
        *,
        creator_id: str = "local_creator",
        source_id: str | None = None,
        boba_memory: ArtifactValue = None,
    ) -> BobaCreatorLearningSetV1:
        return self.analyze(
            project_id,
            feedback_events,
            creator_id=creator_id,
            source_id=source_id,
            boba_memory=boba_memory or signals.get("project_memory"),
            clip_ranking=signals.get("clip_ranking"),
            editorial_decision=signals.get("editorial_decisions"),
            explanation=signals.get("explanations"),
            creative_direction=signals.get("creative_direction_v2"),
            clip_briefs=signals.get("clip_briefs"),
            hook_retention=signals.get("hook_retention"),
            caption_motion=signals.get("caption_motion"),
            music_mood=signals.get("music_mood"),
        )

    @staticmethod
    def _event_polarity(
        event: BobaCreatorFeedbackEventV1,
    ) -> tuple[BobaPreferencePolarity, float]:
        if event.event_type == "rating" and event.rating is not None:
            distance = min(2.0, abs(event.rating - 3.0))
            strength = 0.3 + distance * 0.18
            if event.rating >= 3.5:
                return "prefer", strength
            if event.rating <= 2.5:
                return "avoid", strength
            return "neutral", 0.2
        if event.user_action in {"approved", "liked", "chose"}:
            return "prefer", 0.55
        if event.user_action in {"rejected", "disliked", "corrected"}:
            return "avoid", 0.58
        return "neutral", 0.25

    @staticmethod
    def _target_payload(
        target_type: BobaCreatorFeedbackTargetType,
        target_id: str,
        artifacts: Mapping[str, ArtifactValue],
    ) -> tuple[dict[str, Any], list[str]]:
        preferred_sources = {
            "ranked_clip": ("clip_ranking",),
            "editorial_decision": ("editorial_decision",),
            "explanation": ("explanation",),
            "creative_direction": ("creative_direction",),
            "clip_brief": ("clip_briefs",),
            "hook_alternative": ("hook_retention",),
            "caption_motion": ("caption_motion",),
            "music_mood": ("music_mood",),
            "candidate": (
                "clip_ranking",
                "editorial_decision",
                "creative_direction",
                "clip_briefs",
            ),
            "clip": (
                "clip_briefs",
                "hook_retention",
                "caption_motion",
                "music_mood",
            ),
            "project": (),
        }[target_type]
        source_names = preferred_sources or tuple(artifacts)
        for source_name in source_names:
            payload = _artifact(artifacts.get(source_name))
            target = BobaCreatorLearningLoopV1._find_target(payload, target_id)
            if target:
                return target, [source_name]
        return {}, []

    @staticmethod
    def _find_target(
        value: Any,
        target_id: str,
        *,
        depth: int = 0,
    ) -> dict[str, Any]:
        if depth > 10:
            return {}
        if isinstance(value, Mapping):
            current = dict(value)
            if any(
                _clean_text(current.get(key), maximum=180) == target_id
                for key in _IDENTIFIER_KEYS
            ):
                return current
            for nested in current.values():
                match = BobaCreatorLearningLoopV1._find_target(
                    nested,
                    target_id,
                    depth=depth + 1,
                )
                if match:
                    return match
        elif isinstance(value, list):
            for nested in value:
                match = BobaCreatorLearningLoopV1._find_target(
                    nested,
                    target_id,
                    depth=depth + 1,
                )
                if match:
                    return match
        return {}

    @staticmethod
    def _target_traits(
        target: Mapping[str, Any],
    ) -> list[tuple[BobaPreferenceCategory, str]]:
        field_categories: dict[str, BobaPreferenceCategory] = {
            "candidate_type": "clip_type",
            "clip_type": "clip_type",
            "hook_type": "hook_style",
            "hook_category": "hook_style",
            "final_hook_strategy": "hook_style",
            "caption_style": "caption_style",
            "motion_style": "motion_style",
            "primary_mood": "music_mood",
            "pacing_intensity": "pacing",
            "pacing_level": "pacing",
            "pacing_style": "pacing",
            "story_angle": "story_angle",
            "final_story_angle": "story_angle",
            "production_priority": "production_priority",
        }
        values: list[tuple[BobaPreferenceCategory, str]] = []

        def visit(item: Any, depth: int = 0) -> None:
            if depth > 7:
                return
            if isinstance(item, Mapping):
                for key, nested in item.items():
                    if key == "music_mood" and isinstance(nested, str):
                        normalized = _style(nested)
                        if normalized:
                            values.append(("music_mood", normalized))
                    category = field_categories.get(str(key))
                    if category and isinstance(nested, (str, int, float)):
                        normalized = _style(nested)
                        if normalized:
                            values.append((category, normalized))
                    if isinstance(nested, (Mapping, list)):
                        visit(nested, depth + 1)
            elif isinstance(item, list):
                for nested in item:
                    visit(nested, depth + 1)

        visit(target)
        return list(dict.fromkeys(values))[:16]

    @staticmethod
    def _note_preferences(
        note: str,
    ) -> list[
        tuple[
            BobaPreferenceCategory,
            str,
            BobaPreferencePolarity,
            float,
            str,
        ]
    ]:
        text = note.casefold()
        rules: list[
            tuple[
                tuple[str, ...],
                BobaPreferenceCategory,
                str,
                BobaPreferencePolarity,
                float,
            ]
        ] = [
            (
                ("too much zoom", "too much motion", "heavy motion"),
                "motion_style",
                "high_motion_intensity",
                "avoid",
                0.62,
            ),
            (
                ("captions were too busy", "captions too busy", "heavy captions"),
                "caption_style",
                "high_caption_density",
                "avoid",
                0.62,
            ),
            (
                ("clean captions", "captions were clean"),
                "caption_style",
                "clean_subtitles",
                "prefer",
                0.55,
            ),
            (
                ("too slow", "faster pacing"),
                "pacing",
                "faster_pacing",
                "prefer",
                0.58,
            ),
            (
                ("slow hook", "slow start"),
                "hook_style",
                "slow_start",
                "avoid",
                0.6,
            ),
            (
                ("bold hook", "bolder hook"),
                "hook_style",
                "bold_direct",
                "prefer",
                0.55,
            ),
            (
                ("stable motion", "subtle motion"),
                "motion_style",
                "stable_subtle",
                "prefer",
                0.55,
            ),
            (
                ("emotional music", "cinematic music"),
                "music_mood",
                "emotional_cinematic",
                "prefer",
                0.55,
            ),
            (
                ("clean speech", "voice clarity"),
                "risk_sensitivity",
                "prioritize_clean_speech",
                "prefer",
                0.62,
            ),
            (
                ("heavy sfx", "too many sound effects"),
                "risk_sensitivity",
                "heavy_sfx",
                "avoid",
                0.62,
            ),
        ]
        preferences: list[
            tuple[
                BobaPreferenceCategory,
                str,
                BobaPreferencePolarity,
                float,
                str,
            ]
        ] = []
        for phrases, category, preference, polarity, strength in rules:
            matched = next((phrase for phrase in phrases if phrase in text), None)
            if matched:
                preferences.append(
                    (
                        category,
                        preference,
                        polarity,
                        strength,
                        f"Explicit note matched the bounded phrase: {matched}.",
                    )
                )
        return preferences

    @staticmethod
    def _tag_preferences(
        tags: list[str],
        event_polarity: BobaPreferencePolarity,
    ) -> list[
        tuple[
            BobaPreferenceCategory,
            str,
            BobaPreferencePolarity,
            float,
            str,
        ]
    ]:
        category_names = {
            "clip_type",
            "hook_style",
            "caption_style",
            "motion_style",
            "music_mood",
            "pacing",
            "story_angle",
            "risk_sensitivity",
            "production_priority",
            "general",
        }
        known: dict[
            str,
            tuple[BobaPreferenceCategory, str, BobaPreferencePolarity],
        ] = {
            "captions_good": ("caption_style", "clean_subtitles", "prefer"),
            "too_much_motion": ("motion_style", "high_motion_intensity", "avoid"),
            "stable_motion": ("motion_style", "stable_subtle", "prefer"),
            "bold_hook": ("hook_style", "bold_direct", "prefer"),
            "emotional_music": ("music_mood", "emotional_cinematic", "prefer"),
            "speech_first": (
                "risk_sensitivity",
                "prioritize_clean_speech",
                "prefer",
            ),
        }
        preferences: list[
            tuple[
                BobaPreferenceCategory,
                str,
                BobaPreferencePolarity,
                float,
                str,
            ]
        ] = []
        for raw_tag in tags:
            tag = _style(raw_tag)
            if tag in known:
                category, preference, polarity = known[tag]
                preferences.append(
                    (
                        category,
                        preference,
                        polarity,
                        0.55,
                        f"Explicit manual tag: {tag}.",
                    )
                )
                continue
            parts = [part for part in raw_tag.casefold().split(":") if part]
            polarity = event_polarity if event_polarity != "neutral" else "prefer"
            if len(parts) == 3 and parts[0] in {"prefer", "avoid", "neutral"}:
                polarity = cast(BobaPreferencePolarity, parts[0])
                parts = parts[1:]
            if len(parts) != 2 or parts[0] not in category_names:
                continue
            structured_category = cast(BobaPreferenceCategory, parts[0])
            preference = _style(parts[1])
            if preference:
                preferences.append(
                    (
                        structured_category,
                        preference,
                        polarity,
                        0.5,
                        f"Explicit structured tag for {structured_category}.",
                    )
                )
        return preferences

    @staticmethod
    def _aggregate(
        events: list[BobaCreatorFeedbackEventV1],
    ) -> dict[tuple[BobaPreferenceCategory, str], _PreferenceAggregate]:
        aggregates: dict[
            tuple[BobaPreferenceCategory, str], _PreferenceAggregate
        ] = {}
        for event in events:
            for preference in event.extracted_preferences:
                key = (preference.category, preference.preference)
                aggregate = aggregates.setdefault(
                    key,
                    _PreferenceAggregate(
                        category=preference.category,
                        preference=preference.preference,
                    ),
                )
                aggregate.modules.update(preference.applies_to_modules)
                aggregate.strength_total += preference.strength
                aggregate.confidence_total += preference.confidence
                if preference.polarity == "prefer":
                    aggregate.prefer_count += 1
                elif preference.polarity == "avoid":
                    aggregate.avoid_count += 1
                else:
                    aggregate.neutral_count += 1
        return aggregates

    @staticmethod
    def _profile(
        creator_id: str,
        updated_at: str,
        events: list[BobaCreatorFeedbackEventV1],
        aggregates: dict[tuple[BobaPreferenceCategory, str], _PreferenceAggregate],
    ) -> BobaCreatorLearningProfileV1:
        def values(
            category: BobaPreferenceCategory,
            polarity: BobaPreferencePolarity,
        ) -> list[str]:
            return sorted(
                item.preference
                for item in aggregates.values()
                if item.category == category
                and not item.contradictory
                and item.dominant_polarity == polarity
            )[:100]

        def combined(category: BobaPreferenceCategory) -> list[str]:
            return sorted(
                f"{item.dominant_polarity}:{item.preference}"
                for item in aggregates.values()
                if item.category == category
                and not item.contradictory
                and item.dominant_polarity != "neutral"
            )[:100]
        contradictions = [
            item
            for item in aggregates.values()
            if item.contradictory
        ]
        repeated = [
            (
                f"{item.dominant_polarity.title()} {item.preference.replace('_', ' ')} "
                f"({item.category.replace('_', ' ')}) repeated "
                f"{item.evidence_count} times."
            )
            for item in aggregates.values()
            if item.evidence_count >= 2 and not item.contradictory
        ]
        data_points = sum(item.evidence_count for item in aggregates.values())
        if data_points:
            mean_confidence = sum(
                item.confidence * item.evidence_count for item in aggregates.values()
            ) / data_points
            repeated_groups = sum(
                1 for item in aggregates.values() if item.evidence_count >= 2
            )
            confidence = (
                mean_confidence * 0.65
                + min(0.18, len(events) * 0.04)
                + min(0.16, repeated_groups * 0.06)
                - min(0.4, len(contradictions) * 0.2)
            )
            confidence = round(max(0.05, min(0.95, confidence)), 4)
        else:
            confidence = 0.0
        warnings = [
            (
                f"Conflicting feedback for {item.preference.replace('_', ' ')} "
                f"reduced confidence and requires human review."
            )
            for item in contradictions
        ]
        limitations = []
        if not events:
            limitations.append("No explicit feedback events were available.")
        elif len(events) == 1:
            limitations.append(
                "One event is not enough to establish a reliable creator preference."
            )
        if confidence < 0.5:
            limitations.append(
                "Profile confidence is low; keep all recommendations advisory."
            )
        return BobaCreatorLearningProfileV1(
            creator_id=_clean_text(creator_id, maximum=80),
            updated_at=updated_at,
            preferred_clip_types=values("clip_type", "prefer"),
            avoided_clip_types=values("clip_type", "avoid"),
            preferred_hook_styles=values("hook_style", "prefer"),
            avoided_hook_styles=values("hook_style", "avoid"),
            preferred_caption_styles=values("caption_style", "prefer"),
            avoided_caption_styles=values("caption_style", "avoid"),
            preferred_motion_styles=values("motion_style", "prefer"),
            avoided_motion_styles=values("motion_style", "avoid"),
            preferred_music_moods=values("music_mood", "prefer"),
            avoided_music_moods=values("music_mood", "avoid"),
            pacing_preferences=combined("pacing"),
            story_angle_preferences=combined("story_angle"),
            risk_sensitivities=combined("risk_sensitivity"),
            repeated_feedback=_unique(repeated, maximum=100),
            confidence=confidence,
            data_points=data_points,
            warnings=_unique(warnings, maximum=64),
            limitations=_unique(limitations, maximum=64),
        )

    @staticmethod
    def _insights(
        aggregates: dict[tuple[BobaPreferenceCategory, str], _PreferenceAggregate],
    ) -> list[BobaLearningInsightV1]:
        insights: list[BobaLearningInsightV1] = []
        for item in sorted(
            aggregates.values(),
            key=lambda value: (value.category, value.preference),
        ):
            label = item.preference.replace("_", " ")
            if item.contradictory:
                summary = (
                    f"Creator feedback conflicts about {label}; no preference is assumed."
                )
                adjustment = "Ask for clarification before using this preference."
                warnings = ["Contradictory explicit feedback requires human review."]
            else:
                verb = "prefers" if item.dominant_polarity == "prefer" else "avoids"
                summary = f"Creator {verb} {label}."
                adjustment = (
                    f"Consider {verb[:-1] if verb.endswith('s') else verb}ing "
                    f"{label} only when source evidence supports it."
                )
                warnings = (
                    ["Low-confidence signal; do not apply automatically."]
                    if item.evidence_count < 2 or item.confidence < 0.5
                    else []
                )
            insights.append(
                BobaLearningInsightV1(
                    insight_id=_stable_id(
                        "creator_insight",
                        item.category,
                        item.preference,
                    ),
                    category=item.category,
                    summary=summary,
                    evidence_count=item.evidence_count,
                    confidence=item.confidence,
                    suggested_adjustment=adjustment,
                    affected_modules=sorted(item.modules),
                    warnings=warnings,
                )
            )
        return insights[:200]

    @staticmethod
    def _guidance(
        aggregates: dict[tuple[BobaPreferenceCategory, str], _PreferenceAggregate],
        memory_available: bool,
    ) -> BobaRecommendationGuidanceV1:
        by_module: dict[BobaCreatorLearningModule, list[str]] = defaultdict(list)
        for item in aggregates.values():
            if (
                item.contradictory
                or item.evidence_count < 2
                or item.confidence < 0.45
                or item.dominant_polarity == "neutral"
            ):
                continue
            action = "Prefer" if item.dominant_polarity == "prefer" else "Avoid"
            guidance = (
                f"{action} {item.preference.replace('_', ' ')} as a bounded creator "
                f"preference when source evidence supports it."
            )
            for module in item.modules:
                by_module[module].append(guidance)
        general = [
            "Keep creator-learning guidance advisory; never override source truth or safety.",
            "Require explicit repeated feedback before treating a preference as reusable.",
        ]
        if not any(by_module.values()):
            general.append(
                "No preference currently has enough repeated evidence for reuse."
            )
        if memory_available:
            general.append(
                "Existing explicit BOBA memory was available for consistency review."
            )

        def module_values(module: BobaCreatorLearningModule) -> list[str]:
            return _unique(
                [*by_module.get(module, []), *by_module.get("all", [])],
                maximum=32,
            )

        return BobaRecommendationGuidanceV1(
            ranking_guidance=module_values("ranking"),
            editorial_guidance=module_values("editorial_decision"),
            creative_direction_guidance=module_values("creative_director"),
            clip_brief_guidance=module_values("clip_brief"),
            hook_retention_guidance=module_values("hook_retention"),
            caption_motion_guidance=module_values("caption_motion"),
            music_mood_guidance=module_values("music_mood"),
            general_guidance=general,
        )

    @staticmethod
    def _audit(
        events: list[BobaCreatorFeedbackEventV1],
    ) -> BobaLearningAuditSummaryV1:
        return BobaLearningAuditSummaryV1(
            total_events=len(events),
            approval_count=sum(item.event_type == "approval" for item in events),
            rejection_count=sum(item.event_type == "rejection" for item in events),
            correction_count=sum(item.event_type == "correction" for item in events),
            note_count=sum(bool(item.note) for item in events),
            reversible_event_count=sum(item.reversible for item in events),
            irreversible_event_count=sum(not item.reversible for item in events),
            last_event_at=max((item.created_at for item in events), default=None),
            warnings=(
                ["Reset removes only this project's creator-learning artifact and events."]
                if events
                else []
            ),
        )

    @staticmethod
    def _signal_usage(
        events: list[BobaCreatorFeedbackEventV1],
        boba_memory: ArtifactValue,
        artifacts: Mapping[str, ArtifactValue],
    ) -> BobaCreatorLearningSignalUsageV1:
        available = {
            name: bool(_artifact(value)) for name, value in artifacts.items()
        }
        unavailable = [
            name
            for name, is_available in available.items()
            if not is_available
        ]
        fallback_used = bool(unavailable or not events)
        return BobaCreatorLearningSignalUsageV1(
            boba_memory_used=bool(_artifact(boba_memory)),
            feedback_events_used=len(events),
            clip_ranking_used=available["clip_ranking"],
            editorial_decision_used=available["editorial_decision"],
            explanation_used=available["explanation"],
            creative_direction_used=available["creative_direction"],
            clip_briefs_used=available["clip_briefs"],
            hook_retention_used=available["hook_retention"],
            caption_motion_used=available["caption_motion"],
            music_mood_used=available["music_mood"],
            fallback_used=fallback_used,
            unavailable_signals=unavailable,
            warnings=(
                ["Missing optional BOBA artifacts degraded preference extraction safely."]
                if unavailable
                else []
            ),
        )
