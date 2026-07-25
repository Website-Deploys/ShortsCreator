"""Explicit approval and rejection learning for BOBA decisions."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, Field

from olympus.boba.contracts import BobaContract, now_iso
from olympus.boba.creator_learning import (
    BobaCreatorFeedbackEventV1,
    BobaCreatorLearningSetV1,
)

BobaFeedbackFactorCategory = Literal[
    "clip_type",
    "hook",
    "retention",
    "pacing",
    "context",
    "payoff",
    "caption",
    "motion",
    "music_mood",
    "sfx",
    "speech_clarity",
    "editorial_selection",
    "ranking",
    "explanation_quality",
    "rights_risk",
    "render_readiness",
    "general",
]
BobaFeedbackFactorPolarity = Literal[
    "positive",
    "negative",
    "neutral",
    "uncertain",
]
BobaDecisionAttributionModule = Literal[
    "candidate_discovery",
    "clip_ranking",
    "editorial_decision",
    "creative_director",
    "clip_brief",
    "hook_retention",
    "caption_motion",
    "music_mood",
    "explanation",
    "creator_learning",
    "unknown",
]
BobaApprovalRejectionPatternType = Literal[
    "repeated_approval",
    "repeated_rejection",
    "contradiction",
    "weak_signal",
    "strong_signal",
]
ArtifactValue: TypeAlias = Mapping[str, Any] | BaseModel | None

_SPACE = re.compile(r"\s+")
_NORMALIZE = re.compile(r"[^a-z0-9]+")
_DELIBERATE_EVENT_TYPES = {
    "approval",
    "rejection",
    "rating",
    "correction",
    "chosen_alternative",
    "preference_note",
    "manual_tag",
}
_IDENTIFIER_FIELDS = {
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
}
_TARGET_SOURCES: dict[str, tuple[str, ...]] = {
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
        "explanation",
        "creative_direction",
        "clip_briefs",
        "hook_retention",
        "caption_motion",
        "music_mood",
    ),
    "clip": (
        "explanation",
        "clip_briefs",
        "hook_retention",
        "caption_motion",
        "music_mood",
    ),
    "project": (),
}
_EXPLICIT_MODULE: dict[str, BobaDecisionAttributionModule] = {
    "candidate": "candidate_discovery",
    "ranked_clip": "clip_ranking",
    "editorial_decision": "editorial_decision",
    "explanation": "explanation",
    "creative_direction": "creative_director",
    "clip_brief": "clip_brief",
    "hook_alternative": "hook_retention",
    "caption_motion": "caption_motion",
    "music_mood": "music_mood",
}
_CATEGORY_MODULES: dict[
    BobaFeedbackFactorCategory, tuple[BobaDecisionAttributionModule, ...]
] = {
    "clip_type": ("candidate_discovery", "clip_ranking"),
    "hook": ("hook_retention", "clip_ranking"),
    "retention": ("hook_retention",),
    "pacing": ("hook_retention", "creative_director"),
    "context": ("editorial_decision", "clip_ranking"),
    "payoff": ("editorial_decision", "hook_retention", "clip_ranking"),
    "caption": ("caption_motion", "creative_director"),
    "motion": ("caption_motion", "creative_director"),
    "music_mood": ("music_mood", "creative_director"),
    "sfx": ("music_mood",),
    "speech_clarity": ("music_mood",),
    "editorial_selection": ("editorial_decision",),
    "ranking": ("clip_ranking", "candidate_discovery"),
    "explanation_quality": ("explanation",),
    "rights_risk": ("editorial_decision",),
    "render_readiness": ("editorial_decision", "clip_brief"),
    "general": ("unknown",),
}
_PREFERENCE_CATEGORIES: dict[str, BobaFeedbackFactorCategory] = {
    "clip_type": "clip_type",
    "hook_style": "hook",
    "caption_style": "caption",
    "motion_style": "motion",
    "music_mood": "music_mood",
    "pacing": "pacing",
    "story_angle": "general",
    "risk_sensitivity": "general",
    "production_priority": "general",
    "general": "general",
}
_TRAIT_FIELDS: dict[str, BobaFeedbackFactorCategory] = {
    "candidate_type": "clip_type",
    "clip_type": "clip_type",
    "hook_type": "hook",
    "hook_category": "hook",
    "final_hook_strategy": "hook",
    "caption_style": "caption",
    "motion_style": "motion",
    "primary_mood": "music_mood",
    "music_mood": "music_mood",
    "sfx_intensity": "sfx",
    "pacing_intensity": "pacing",
    "pacing_level": "pacing",
    "pacing_style": "pacing",
    "render_readiness": "render_readiness",
}
_SCORE_FIELDS: dict[str, BobaFeedbackFactorCategory] = {
    "hook_score": "hook",
    "payoff_score": "payoff",
    "retention_score": "retention",
    "overall_retention_score": "retention",
    "pacing_score": "pacing",
    "caption_readability_score": "caption",
    "motion_safety_score": "motion",
    "mood_fit_score": "music_mood",
    "speech_clarity_score": "speech_clarity",
    "sfx_fit_score": "sfx",
    "ranking_score": "ranking",
    "total_score": "ranking",
}


def _text(value: Any, *, maximum: int = 500) -> str:
    return _SPACE.sub(" ", str(value or "")).strip()[:maximum]


def _unique(values: Sequence[str], *, maximum: int) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))[:maximum]


def _normalized(value: Any, *, maximum: int = 100) -> str:
    return _NORMALIZE.sub("_", _text(value, maximum=maximum).casefold()).strip("_")


def _stable_id(prefix: str, *values: str) -> str:
    digest = sha256("|".join(values).encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


def _artifact(value: ArtifactValue) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return dict(value) if isinstance(value, Mapping) else {}


def _confidence(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 4)


class BobaFeedbackFactorV1(BobaContract):
    factor_id: str = Field(min_length=1, max_length=128)
    category: BobaFeedbackFactorCategory
    polarity: BobaFeedbackFactorPolarity
    summary: str = Field(min_length=1, max_length=500)
    source_artifact: str = Field(min_length=1, max_length=80)
    source_field: str = Field(min_length=1, max_length=180)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_snippet: str = Field(min_length=1, max_length=300)


class BobaCorrectionMappingV1(BobaContract):
    mapping_id: str = Field(min_length=1, max_length=128)
    feedback_event_id: str = Field(min_length=1, max_length=128)
    candidate_id: str = Field(default="", max_length=128)
    problem_category: BobaFeedbackFactorCategory
    affected_module: BobaDecisionAttributionModule
    suggested_correction: str = Field(min_length=1, max_length=700)
    future_rule_hint: str = Field(min_length=1, max_length=700)
    strength: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    apply_automatically: Literal[False] = False


class BobaApprovalLearningCaseV1(BobaContract):
    case_id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=128)
    feedback_event_id: str = Field(min_length=1, max_length=128)
    target_type: str = Field(min_length=1, max_length=80)
    target_id: str = Field(min_length=1, max_length=180)
    candidate_id: str = Field(default="", max_length=128)
    approved_reason_summary: str = Field(min_length=1, max_length=600)
    what_boba_got_right: list[str] = Field(default_factory=list, max_length=24)
    approval_factors: list[BobaFeedbackFactorV1] = Field(
        default_factory=list, max_length=40
    )
    supporting_evidence: list[str] = Field(default_factory=list, max_length=32)
    reusable_pattern: str = Field(min_length=1, max_length=700)
    confidence: float = Field(ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaRejectionLearningCaseV1(BobaContract):
    case_id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=128)
    feedback_event_id: str = Field(min_length=1, max_length=128)
    target_type: str = Field(min_length=1, max_length=80)
    target_id: str = Field(min_length=1, max_length=180)
    candidate_id: str = Field(default="", max_length=128)
    rejected_reason_summary: str = Field(min_length=1, max_length=600)
    likely_rejection_causes: list[BobaFeedbackFactorV1] = Field(
        default_factory=list, max_length=40
    )
    what_boba_got_wrong: list[str] = Field(default_factory=list, max_length=24)
    supporting_evidence: list[str] = Field(default_factory=list, max_length=32)
    correction_mapping: list[BobaCorrectionMappingV1] = Field(
        default_factory=list, max_length=40
    )
    future_avoidance_guidance: list[str] = Field(default_factory=list, max_length=32)
    confidence: float = Field(ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list, max_length=24)
    limitations: list[str] = Field(default_factory=list, max_length=24)


class BobaDecisionAttributionV1(BobaContract):
    attribution_id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=128)
    feedback_event_id: str = Field(min_length=1, max_length=128)
    candidate_id: str = Field(default="", max_length=128)
    primary_module: BobaDecisionAttributionModule
    secondary_modules: list[BobaDecisionAttributionModule] = Field(
        default_factory=list, max_length=10
    )
    attribution_reason: str = Field(min_length=1, max_length=700)
    evidence: list[str] = Field(default_factory=list, max_length=24)
    confidence: float = Field(ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list, max_length=24)


class BobaApprovalRejectionPatternScoreV1(BobaContract):
    pattern_id: str = Field(min_length=1, max_length=128)
    pattern_type: BobaApprovalRejectionPatternType
    category: BobaFeedbackFactorCategory
    summary: str = Field(min_length=1, max_length=500)
    approval_count: int = Field(default=0, ge=0)
    rejection_count: int = Field(default=0, ge=0)
    contradiction_count: int = Field(default=0, ge=0)
    confidence: float = Field(ge=0.0, le=1.0)
    strength: float = Field(ge=0.0, le=1.0)
    affected_modules: list[BobaDecisionAttributionModule] = Field(
        default_factory=list, max_length=10
    )
    guidance: str = Field(min_length=1, max_length=700)


class BobaApprovalRejectionModuleGuidanceV1(BobaContract):
    ranking_guidance: list[str] = Field(default_factory=list, max_length=32)
    editorial_guidance: list[str] = Field(default_factory=list, max_length=32)
    creative_director_guidance: list[str] = Field(default_factory=list, max_length=32)
    clip_brief_guidance: list[str] = Field(default_factory=list, max_length=32)
    hook_retention_guidance: list[str] = Field(default_factory=list, max_length=32)
    caption_motion_guidance: list[str] = Field(default_factory=list, max_length=32)
    music_mood_guidance: list[str] = Field(default_factory=list, max_length=32)
    explanation_guidance: list[str] = Field(default_factory=list, max_length=32)
    general_guidance: list[str] = Field(default_factory=list, max_length=32)
    apply_automatically: Literal[False] = False


class BobaApprovalRejectionAuditSummaryV1(BobaContract):
    total_feedback_events_used: int = Field(default=0, ge=0)
    approval_events_used: int = Field(default=0, ge=0)
    rejection_events_used: int = Field(default=0, ge=0)
    ambiguous_events: int = Field(default=0, ge=0)
    attributed_cases: int = Field(default=0, ge=0)
    unattributed_cases: int = Field(default=0, ge=0)
    reversible: bool = True
    dry_run: bool = False
    export_available: bool = True
    reset_available: bool = True
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaApprovalRejectionSignalUsageV1(BobaContract):
    creator_learning_used: bool = False
    feedback_events_used: int = Field(default=0, ge=0)
    memory_used: bool = False
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


class BobaApprovalRejectionLearningSetV1(BobaContract):
    schema_version: Literal["boba_approval_rejection_learning_v1"] = (
        "boba_approval_rejection_learning_v1"
    )
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(min_length=1, max_length=512)
    created_at: str = Field(default_factory=now_iso)
    approval_cases: list[BobaApprovalLearningCaseV1] = Field(
        default_factory=list, max_length=5000
    )
    rejection_cases: list[BobaRejectionLearningCaseV1] = Field(
        default_factory=list, max_length=5000
    )
    decision_attributions: list[BobaDecisionAttributionV1] = Field(
        default_factory=list, max_length=5000
    )
    pattern_scores: list[BobaApprovalRejectionPatternScoreV1] = Field(
        default_factory=list, max_length=500
    )
    module_guidance: BobaApprovalRejectionModuleGuidanceV1
    audit_summary: BobaApprovalRejectionAuditSummaryV1
    signal_usage: BobaApprovalRejectionSignalUsageV1
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)


@dataclass(frozen=True, slots=True)
class _PhraseRule:
    patterns: tuple[str, ...]
    category: BobaFeedbackFactorCategory
    polarity: Literal["positive", "negative"]
    summary: str
    modules: tuple[BobaDecisionAttributionModule, ...]


@dataclass(slots=True)
class _PatternAggregate:
    category: BobaFeedbackFactorCategory
    summary: str
    modules: set[BobaDecisionAttributionModule] = field(default_factory=set)
    approval_count: int = 0
    rejection_count: int = 0
    confidence_total: float = 0.0


_PHRASE_RULES = (
    _PhraseRule(
        ("too slow", "slow start", "slow hook", "drags"),
        "pacing",
        "negative",
        "pacing: slow opening",
        ("hook_retention", "creative_director"),
    ),
    _PhraseRule(
        ("bad caption", "unreadable caption", "captions are hard", "caption clutter"),
        "caption",
        "negative",
        "caption: readability problem",
        ("caption_motion",),
    ),
    _PhraseRule(
        ("too much zoom", "heavy zoom", "zoom is distracting", "over zoom"),
        "motion",
        "negative",
        "motion: excessive zoom",
        ("caption_motion", "creative_director"),
    ),
    _PhraseRule(
        ("wrong music", "music feels wrong", "bad music", "mood feels wrong"),
        "music_mood",
        "negative",
        "music mood: mismatch",
        ("music_mood",),
    ),
    _PhraseRule(
        ("no payoff", "weak payoff", "payoff is missing", "ends before payoff"),
        "payoff",
        "negative",
        "payoff: missing or weak",
        ("editorial_decision", "hook_retention", "clip_ranking"),
    ),
    _PhraseRule(
        ("not interesting", "boring", "not compelling", "weak idea"),
        "ranking",
        "negative",
        "ranking: low creator interest",
        ("clip_ranking", "candidate_discovery"),
    ),
    _PhraseRule(
        ("explanation unclear", "unclear explanation", "reason is unclear"),
        "explanation_quality",
        "negative",
        "explanation: unclear reasoning",
        ("explanation",),
    ),
    _PhraseRule(
        ("missing context", "needs context", "too much context", "context is unclear"),
        "context",
        "negative",
        "context: insufficient standalone clarity",
        ("editorial_decision", "clip_ranking"),
    ),
    _PhraseRule(
        ("too many sfx", "bad sfx", "static sound", "noisy sfx"),
        "sfx",
        "negative",
        "sfx: distracting or unsafe",
        ("music_mood",),
    ),
    _PhraseRule(
        ("speech unclear", "cannot hear", "can't hear", "muddy speech"),
        "speech_clarity",
        "negative",
        "speech clarity: words are obscured",
        ("music_mood",),
    ),
    _PhraseRule(
        ("copyright", "rights risk", "permission risk"),
        "rights_risk",
        "negative",
        "rights: unresolved risk",
        ("editorial_decision",),
    ),
    _PhraseRule(
        ("not render ready", "render failed", "not ready"),
        "render_readiness",
        "negative",
        "render readiness: not ready",
        ("editorial_decision", "clip_brief"),
    ),
    _PhraseRule(
        ("curiosity gap",),
        "hook",
        "positive",
        "hook: curiosity gap",
        ("hook_retention", "clip_ranking"),
    ),
    _PhraseRule(
        ("strong hook", "hook works", "great opening"),
        "hook",
        "positive",
        "hook: strong opening",
        ("hook_retention",),
    ),
    _PhraseRule(
        ("clean caption", "readable caption", "captions work"),
        "caption",
        "positive",
        "caption: clean and readable",
        ("caption_motion",),
    ),
    _PhraseRule(
        ("stable motion", "subtle motion", "motion works"),
        "motion",
        "positive",
        "motion: stable and restrained",
        ("caption_motion", "creative_director"),
    ),
    _PhraseRule(
        ("music works", "right music", "cinematic mood"),
        "music_mood",
        "positive",
        "music mood: supports the clip",
        ("music_mood",),
    ),
    _PhraseRule(
        ("strong payoff", "payoff works", "good ending"),
        "payoff",
        "positive",
        "payoff: strong and complete",
        ("editorial_decision", "hook_retention"),
    ),
    _PhraseRule(
        ("interesting", "compelling"),
        "ranking",
        "positive",
        "ranking: strong creator interest",
        ("clip_ranking", "candidate_discovery"),
    ),
    _PhraseRule(
        ("clear explanation", "reason makes sense"),
        "explanation_quality",
        "positive",
        "explanation: clear reasoning",
        ("explanation",),
    ),
    _PhraseRule(
        ("clear speech", "speech sounds good"),
        "speech_clarity",
        "positive",
        "speech clarity: clear and dominant",
        ("music_mood",),
    ),
    _PhraseRule(
        ("tight pacing", "fast pacing", "pacing works"),
        "pacing",
        "positive",
        "pacing: tight opening",
        ("hook_retention", "creative_director"),
    ),
)


class BobaApprovalRejectionLearningV1:
    """Derive advisory decision learning from explicit creator feedback."""

    def analyze(
        self,
        project_id: str,
        feedback_events: Sequence[BobaCreatorFeedbackEventV1],
        *,
        source_id: str | None = None,
        creator_learning: BobaCreatorLearningSetV1 | Mapping[str, Any] | None = None,
        boba_memory: ArtifactValue = None,
        clip_ranking: ArtifactValue = None,
        editorial_decision: ArtifactValue = None,
        explanation: ArtifactValue = None,
        creative_direction: ArtifactValue = None,
        clip_briefs: ArtifactValue = None,
        hook_retention: ArtifactValue = None,
        caption_motion: ArtifactValue = None,
        music_mood: ArtifactValue = None,
        dry_run: bool = False,
    ) -> BobaApprovalRejectionLearningSetV1:
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
        deliberate_events = [
            event
            for event in feedback_events
            if event.event_type in _DELIBERATE_EVENT_TYPES
        ]
        if any(event.project_id != project_id for event in deliberate_events):
            raise ValueError(
                "approval/rejection feedback events must belong to the requested project"
            )

        approvals: list[BobaApprovalLearningCaseV1] = []
        rejections: list[BobaRejectionLearningCaseV1] = []
        attributions: list[BobaDecisionAttributionV1] = []
        ambiguous_events = 0
        for event in deliberate_events:
            polarity = self._event_polarity(event)
            if polarity == "ambiguous":
                ambiguous_events += 1
                targets = self._targets(event, artifacts)
                candidate_id = self._candidate_id(event, targets)
                uncertain_factor = self._factor(
                    event,
                    category="general",
                    polarity="uncertain",
                    summary="general: ambiguous explicit feedback",
                    source_artifact="creator_feedback",
                    source_field="note_or_tags",
                    confidence=0.16,
                    evidence=event.note or ", ".join(event.tags) or event.event_type,
                )
                attribution = self._attribution(
                    event,
                    candidate_id=candidate_id,
                    factors=[uncertain_factor],
                    targets=targets,
                )
                attributions.append(
                    attribution.model_copy(
                        update={
                            "warnings": _unique(
                                [
                                    *attribution.warnings,
                                    "Feedback polarity is ambiguous; no learning case "
                                    "was inferred.",
                                ],
                                maximum=24,
                            )
                        }
                    )
                )
                continue
            targets = self._targets(event, artifacts)
            candidate_id = self._candidate_id(event, targets)
            factors = self._factors(event, polarity, targets)
            attribution = self._attribution(
                event,
                candidate_id=candidate_id,
                factors=factors,
                targets=targets,
            )
            attributions.append(attribution)
            if polarity == "approval":
                approvals.append(
                    self._approval_case(
                        event,
                        candidate_id=candidate_id,
                        factors=factors,
                        targets=targets,
                        attribution=attribution,
                    )
                )
            else:
                rejections.append(
                    self._rejection_case(
                        event,
                        candidate_id=candidate_id,
                        factors=factors,
                        targets=targets,
                        attribution=attribution,
                    )
                )

        patterns = self._patterns(approvals, rejections)
        guidance = self._module_guidance(patterns)
        usage = self._signal_usage(
            creator_learning=creator_learning,
            feedback_events_used=len(deliberate_events),
            memory=boba_memory,
            artifacts=artifacts,
        )
        attributed = sum(item.primary_module != "unknown" for item in attributions)
        audit_warnings: list[str] = []
        if ambiguous_events:
            audit_warnings.append(
                f"{ambiguous_events} explicit event(s) were retained as ambiguous and "
                "did not create approval or rejection cases."
            )
        if any(not event.reversible for event in deliberate_events):
            audit_warnings.append("One or more source feedback events are not reversible.")
        audit = BobaApprovalRejectionAuditSummaryV1(
            total_feedback_events_used=len(deliberate_events),
            approval_events_used=len(approvals),
            rejection_events_used=len(rejections),
            ambiguous_events=ambiguous_events,
            attributed_cases=attributed,
            unattributed_cases=len(attributions) - attributed,
            reversible=all(event.reversible for event in deliberate_events),
            dry_run=dry_run,
            warnings=audit_warnings,
        )
        warnings = [
            "Approval/rejection learning used only explicit submitted feedback.",
            "Module guidance is advisory and was not applied automatically.",
        ]
        limitations = [
            "No passive behavior, viewer analytics, external APIs, or rendering were used.",
            "Decision attribution is evidence-based correlation, not proof of causation.",
            "Low-confidence or contradictory patterns require human review.",
        ]
        if not deliberate_events:
            warnings.append("No explicit approval/rejection feedback was available.")
            limitations.append(
                "Approval and rejection cases cannot be inferred without submitted feedback."
            )
        if ambiguous_events:
            warnings.append(
                "Ambiguous feedback was not forced into an approval or rejection case."
            )
        if any(item.pattern_type == "contradiction" for item in patterns):
            warnings.append(
                "Contradictory explicit feedback was retained and pattern confidence reduced."
            )
        if dry_run:
            warnings.append("Dry run: approval/rejection learning was not persisted.")

        created_at = (
            max((event.created_at for event in deliberate_events), default="") or now_iso()
        )
        return BobaApprovalRejectionLearningSetV1(
            project_id=project_id,
            source_id=_text(source_id or project_id, maximum=512),
            created_at=created_at,
            approval_cases=approvals,
            rejection_cases=rejections,
            decision_attributions=attributions,
            pattern_scores=patterns,
            module_guidance=guidance,
            audit_summary=audit,
            signal_usage=usage,
            warnings=_unique(warnings, maximum=64),
            limitations=_unique(limitations, maximum=64),
        )

    @staticmethod
    def _event_polarity(
        event: BobaCreatorFeedbackEventV1,
    ) -> Literal["approval", "rejection", "ambiguous"]:
        if event.event_type in {"approval", "chosen_alternative"}:
            return "approval"
        if event.event_type in {"rejection", "correction"}:
            return "rejection"
        if event.event_type == "rating":
            if event.rating is not None and event.rating >= 3.5:
                return "approval"
            if event.rating is not None and event.rating <= 2.5:
                return "rejection"
            return "ambiguous"
        if event.user_action in {"approved", "liked", "chose"}:
            return "approval"
        if event.user_action in {"rejected", "disliked", "corrected"}:
            return "rejection"
        combined = " ".join([event.note, *event.tags]).casefold()
        positive = any(
            phrase in combined
            for phrase in ("prefer", "like", "love", "works", "keep", "good", "strong")
        )
        negative = any(
            phrase in combined
            for phrase in (
                "avoid",
                "dislike",
                "hate",
                "wrong",
                "bad",
                "too ",
                "no ",
                "not ",
                "unclear",
                "boring",
            )
        )
        if positive and not negative:
            return "approval"
        if negative and not positive:
            return "rejection"
        return "ambiguous"

    def _targets(
        self,
        event: BobaCreatorFeedbackEventV1,
        artifacts: Mapping[str, ArtifactValue],
    ) -> list[tuple[str, dict[str, Any], str]]:
        source_names = _TARGET_SOURCES[event.target_type] or tuple(artifacts)
        matches: list[tuple[str, dict[str, Any], str]] = []
        for source_name in source_names:
            payload = _artifact(artifacts.get(source_name))
            target, candidate_id = self._find_target(payload, event.target_id)
            if target:
                matches.append((source_name, target, candidate_id))
        return matches

    @classmethod
    def _find_target(
        cls,
        value: Any,
        target_id: str,
        *,
        inherited_candidate_id: str = "",
        depth: int = 0,
    ) -> tuple[dict[str, Any], str]:
        if depth > 10:
            return {}, ""
        if isinstance(value, Mapping):
            current = dict(value)
            candidate_id = _text(
                current.get("candidate_id")
                or current.get("clip_id")
                or inherited_candidate_id,
                maximum=128,
            )
            if any(
                _text(current.get(key), maximum=180) == target_id
                for key in _IDENTIFIER_FIELDS
            ):
                return current, candidate_id
            for nested in current.values():
                target, nested_candidate = cls._find_target(
                    nested,
                    target_id,
                    inherited_candidate_id=candidate_id,
                    depth=depth + 1,
                )
                if target:
                    return target, nested_candidate
        elif isinstance(value, list):
            for nested in value:
                target, candidate_id = cls._find_target(
                    nested,
                    target_id,
                    inherited_candidate_id=inherited_candidate_id,
                    depth=depth + 1,
                )
                if target:
                    return target, candidate_id
        return {}, ""

    @staticmethod
    def _candidate_id(
        event: BobaCreatorFeedbackEventV1,
        targets: Sequence[tuple[str, dict[str, Any], str]],
    ) -> str:
        for _, target, inherited_id in targets:
            candidate_id = _text(
                target.get("candidate_id")
                or target.get("clip_id")
                or inherited_id,
                maximum=128,
            )
            if candidate_id:
                return candidate_id
        if event.target_type in {"candidate", "clip", "ranked_clip"}:
            return _text(event.target_id, maximum=128)
        return ""

    def _factors(
        self,
        event: BobaCreatorFeedbackEventV1,
        polarity: Literal["approval", "rejection"],
        targets: Sequence[tuple[str, dict[str, Any], str]],
    ) -> list[BobaFeedbackFactorV1]:
        factor_polarity: Literal["positive", "negative"] = (
            "positive" if polarity == "approval" else "negative"
        )
        factors: list[BobaFeedbackFactorV1] = []
        combined = " ".join([event.note, *event.tags]).casefold()
        for rule in _PHRASE_RULES:
            if rule.polarity != factor_polarity:
                continue
            matched = next(
                (phrase for phrase in rule.patterns if phrase in combined),
                "",
            )
            if not matched:
                continue
            factors.append(
                self._factor(
                    event,
                    category=rule.category,
                    polarity=factor_polarity,
                    summary=rule.summary,
                    source_artifact="creator_feedback",
                    source_field="note_or_tags",
                    confidence=0.88,
                    evidence=matched,
                )
            )

        for preference in event.extracted_preferences:
            preference_polarity = (
                "positive" if preference.polarity == "prefer" else "negative"
            )
            if preference.polarity == "neutral" or preference_polarity != factor_polarity:
                continue
            category = _PREFERENCE_CATEGORIES[preference.category]
            factors.append(
                self._factor(
                    event,
                    category=category,
                    polarity=factor_polarity,
                    summary=(
                        f"{category.replace('_', ' ')}: "
                        f"{preference.preference.replace('_', ' ')}"
                    ),
                    source_artifact="creator_learning",
                    source_field="extracted_preferences",
                    confidence=max(0.35, preference.confidence),
                    evidence=(
                        preference.evidence[0]
                        if preference.evidence
                        else preference.preference
                    ),
                )
            )

        trait_confidence = 0.62 if polarity == "approval" else 0.42
        for source_name, target, _ in targets:
            factors.extend(
                self._target_factors(
                    event,
                    target,
                    source_name=source_name,
                    polarity=factor_polarity,
                    confidence=trait_confidence,
                )
            )

        if not factors:
            factors.append(
                self._factor(
                    event,
                    category="general",
                    polarity="uncertain",
                    summary="general: explicit feedback without a bounded factor",
                    source_artifact="creator_feedback",
                    source_field="event_type",
                    confidence=0.22,
                    evidence=event.event_type.replace("_", " "),
                )
            )
        deduplicated: dict[
            tuple[BobaFeedbackFactorCategory, BobaFeedbackFactorPolarity, str],
            BobaFeedbackFactorV1,
        ] = {}
        for factor in factors:
            key = (factor.category, factor.polarity, _normalized(factor.summary))
            current = deduplicated.get(key)
            if current is None or factor.confidence > current.confidence:
                deduplicated[key] = factor
        return list(deduplicated.values())[:40]

    def _target_factors(
        self,
        event: BobaCreatorFeedbackEventV1,
        target: Mapping[str, Any],
        *,
        source_name: str,
        polarity: Literal["positive", "negative"],
        confidence: float,
    ) -> list[BobaFeedbackFactorV1]:
        factors: list[BobaFeedbackFactorV1] = []

        def visit(value: Any, path: str = "", depth: int = 0) -> None:
            if depth > 6 or len(factors) >= 28:
                return
            if isinstance(value, Mapping):
                for key, nested in value.items():
                    field_path = f"{path}.{key}".strip(".")
                    category = _TRAIT_FIELDS.get(str(key))
                    if category and isinstance(nested, (str, int, float, bool)):
                        rendered = _text(nested, maximum=120)
                        if rendered:
                            factors.append(
                                self._factor(
                                    event,
                                    category=category,
                                    polarity=polarity,
                                    summary=(
                                        f"{category.replace('_', ' ')}: "
                                        f"{rendered.replace('_', ' ')}"
                                    ),
                                    source_artifact=source_name,
                                    source_field=field_path,
                                    confidence=confidence,
                                    evidence=rendered,
                                )
                            )
                    score_category = _SCORE_FIELDS.get(str(key))
                    if score_category and isinstance(nested, (int, float)):
                        score = float(nested)
                        supports_polarity = (
                            polarity == "positive" and score >= 70.0
                        ) or (polarity == "negative" and score <= 40.0)
                        if supports_polarity:
                            label = "high" if polarity == "positive" else "low"
                            factors.append(
                                self._factor(
                                    event,
                                    category=score_category,
                                    polarity=polarity,
                                    summary=(
                                        f"{score_category.replace('_', ' ')}: "
                                        f"{label} {key.replace('_', ' ')}"
                                    ),
                                    source_artifact=source_name,
                                    source_field=field_path,
                                    confidence=min(0.7, confidence + 0.08),
                                    evidence=f"{key}={score:.1f}",
                                )
                            )
                    if str(key) in {
                        "warnings",
                        "risk_warnings",
                        "risk_fixes",
                        "blockers",
                        "improvement_notes",
                    }:
                        for item in nested if isinstance(nested, list) else [nested]:
                            factors.extend(
                                self._warning_factors(
                                    event,
                                    _text(item, maximum=300),
                                    source_name=source_name,
                                    source_field=field_path,
                                    requested_polarity=polarity,
                                )
                            )
                    visit(nested, field_path, depth + 1)
            elif isinstance(value, list):
                for index, nested in enumerate(value[:40]):
                    visit(nested, f"{path}[{index}]", depth + 1)

        visit(target)
        return factors

    def _warning_factors(
        self,
        event: BobaCreatorFeedbackEventV1,
        warning: str,
        *,
        source_name: str,
        source_field: str,
        requested_polarity: Literal["positive", "negative"],
    ) -> list[BobaFeedbackFactorV1]:
        if requested_polarity != "negative" or not warning:
            return []
        lowered = warning.casefold()
        return [
            self._factor(
                event,
                category=rule.category,
                polarity="negative",
                summary=rule.summary,
                source_artifact=source_name,
                source_field=source_field,
                confidence=0.58,
                evidence=warning,
            )
            for rule in _PHRASE_RULES
            if rule.polarity == "negative"
            and any(pattern in lowered for pattern in rule.patterns)
        ]

    @staticmethod
    def _factor(
        event: BobaCreatorFeedbackEventV1,
        *,
        category: BobaFeedbackFactorCategory,
        polarity: BobaFeedbackFactorPolarity,
        summary: str,
        source_artifact: str,
        source_field: str,
        confidence: float,
        evidence: str,
    ) -> BobaFeedbackFactorV1:
        return BobaFeedbackFactorV1(
            factor_id=_stable_id(
                "feedback_factor",
                event.event_id,
                category,
                polarity,
                _normalized(summary),
            ),
            category=category,
            polarity=polarity,
            summary=_text(summary, maximum=500),
            source_artifact=source_artifact,
            source_field=_text(source_field, maximum=180),
            confidence=_confidence(confidence),
            evidence_snippet=_text(evidence, maximum=300) or "Explicit feedback event.",
        )

    def _attribution(
        self,
        event: BobaCreatorFeedbackEventV1,
        *,
        candidate_id: str,
        factors: Sequence[BobaFeedbackFactorV1],
        targets: Sequence[tuple[str, dict[str, Any], str]],
    ) -> BobaDecisionAttributionV1:
        module_scores: Counter[BobaDecisionAttributionModule] = Counter()
        factor_evidence: list[str] = []
        for factor in factors:
            if factor.source_artifact == "creator_feedback":
                weight = 4
            elif factor.source_artifact == "creator_learning":
                weight = 2
            else:
                weight = 1
            for index, module in enumerate(_CATEGORY_MODULES[factor.category]):
                if module != "unknown":
                    module_scores[module] += max(1, weight - index)
            factor_evidence.append(
                f"{factor.source_artifact}.{factor.source_field}: "
                f"{factor.evidence_snippet}"
            )
        explicit_module = _EXPLICIT_MODULE.get(event.target_type)
        if explicit_module is not None:
            module_scores[explicit_module] += 3
        source_modules: dict[str, BobaDecisionAttributionModule] = {
            "clip_ranking": "clip_ranking",
            "editorial_decision": "editorial_decision",
            "explanation": "explanation",
            "creative_direction": "creative_director",
            "clip_briefs": "clip_brief",
            "hook_retention": "hook_retention",
            "caption_motion": "caption_motion",
            "music_mood": "music_mood",
        }
        for source_name, _, _ in targets:
            source_module = source_modules.get(source_name)
            if source_module is not None:
                module_scores[source_module] += 1

        warnings: list[str] = []
        ranked_modules = module_scores.most_common()
        if not ranked_modules:
            primary: BobaDecisionAttributionModule = "unknown"
            secondary: list[BobaDecisionAttributionModule] = []
            confidence = 0.16
            reason = (
                "No explicit target or bounded module-specific evidence identified "
                "responsible decision ownership."
            )
            warnings.append("Module attribution is unknown; human review is required.")
        else:
            top_score = ranked_modules[0][1]
            tied = [module for module, score in ranked_modules if score == top_score]
            if len(tied) > 1 and event.target_type in {"project", "clip"}:
                primary = "unknown"
                secondary = tied[:4]
                confidence = 0.28
                reason = (
                    "Multiple modules have equally strong explicit evidence and the "
                    "feedback target does not identify one owner."
                )
                warnings.append(
                    "Module attribution is ambiguous; no primary module was invented."
                )
            else:
                primary = ranked_modules[0][0]
                secondary = [
                    module
                    for module, _ in ranked_modules[1:]
                    if module != primary
                ][:6]
                evidence_sources = int(bool(targets)) + int(bool(factor_evidence))
                ambiguity_penalty = min(0.2, len(secondary) * 0.035)
                confidence = _confidence(
                    0.46 + evidence_sources * 0.14 - ambiguity_penalty
                )
                reason = (
                    f"{primary.replace('_', ' ')} has the strongest bounded evidence "
                    f"from target type {event.target_type.replace('_', ' ')} and "
                    "matched feedback factors."
                )
                if len(secondary) >= 3:
                    warnings.append(
                        "Several modules may contribute; attribution confidence was reduced."
                    )
        evidence = [
            f"Explicit target type: {event.target_type.replace('_', ' ')}.",
            *factor_evidence,
        ]
        if targets:
            evidence.append(
                "Matched artifacts: "
                + ", ".join(dict.fromkeys(source for source, _, _ in targets))
                + "."
            )
        return BobaDecisionAttributionV1(
            attribution_id=_stable_id("decision_attribution", event.event_id),
            project_id=event.project_id,
            feedback_event_id=event.event_id,
            candidate_id=candidate_id,
            primary_module=primary,
            secondary_modules=secondary,
            attribution_reason=reason,
            evidence=_unique(evidence, maximum=24),
            confidence=_confidence(confidence),
            warnings=warnings,
        )

    def _approval_case(
        self,
        event: BobaCreatorFeedbackEventV1,
        *,
        candidate_id: str,
        factors: Sequence[BobaFeedbackFactorV1],
        targets: Sequence[tuple[str, dict[str, Any], str]],
        attribution: BobaDecisionAttributionV1,
    ) -> BobaApprovalLearningCaseV1:
        positive = [factor for factor in factors if factor.polarity == "positive"]
        got_right = [
            f"Matched explicit approval on {factor.summary}."
            for factor in positive[:12]
        ]
        if not got_right:
            got_right = [
                "The target received explicit approval, but no bounded reusable factor "
                "was confidently isolated."
            ]
        reason = _text(event.note, maximum=500) or (
            f"Explicit {event.event_type.replace('_', ' ')} for "
            f"{event.target_type.replace('_', ' ')} {event.target_id}."
        )
        reusable = (
            f"Treat {positive[0].summary} as a provisional approval pattern."
            if positive
            else "Retain this approval as a weak general signal until repeated."
        )
        evidence = self._case_evidence(event, factors, targets)
        confidence = 0.5 + int(bool(targets)) * 0.12 + int(bool(positive)) * 0.12
        confidence = min(confidence, attribution.confidence + 0.12)
        warnings = list(attribution.warnings)
        limitations = [
            "Approval indicates creator preference, not guaranteed audience performance."
        ]
        if not targets:
            warnings.append("The approved target was not found in saved BOBA artifacts.")
            limitations.append("Only explicit feedback content could be analyzed.")
        return BobaApprovalLearningCaseV1(
            case_id=_stable_id("approval_case", event.event_id),
            project_id=event.project_id,
            feedback_event_id=event.event_id,
            target_type=event.target_type,
            target_id=event.target_id,
            candidate_id=candidate_id,
            approved_reason_summary=reason,
            what_boba_got_right=got_right,
            approval_factors=list(factors),
            supporting_evidence=evidence,
            reusable_pattern=reusable,
            confidence=_confidence(confidence),
            warnings=_unique(warnings, maximum=24),
            limitations=limitations,
        )

    def _rejection_case(
        self,
        event: BobaCreatorFeedbackEventV1,
        *,
        candidate_id: str,
        factors: Sequence[BobaFeedbackFactorV1],
        targets: Sequence[tuple[str, dict[str, Any], str]],
        attribution: BobaDecisionAttributionV1,
    ) -> BobaRejectionLearningCaseV1:
        negative = [factor for factor in factors if factor.polarity == "negative"]
        corrections = [
            self._correction(event, candidate_id, factor)
            for factor in negative
        ]
        got_wrong = [
            f"The decision did not satisfy the creator on {factor.summary}."
            for factor in negative[:12]
        ]
        if not got_wrong:
            got_wrong = [
                "The target received explicit rejection, but the responsible factor "
                "could not be bounded."
            ]
        reason = _text(event.note, maximum=500) or (
            f"Explicit {event.event_type.replace('_', ' ')} for "
            f"{event.target_type.replace('_', ' ')} {event.target_id}."
        )
        evidence = self._case_evidence(event, factors, targets)
        confidence = 0.5 + int(bool(targets)) * 0.1 + int(bool(negative)) * 0.14
        confidence = min(confidence, attribution.confidence + 0.14)
        warnings = list(attribution.warnings)
        limitations = [
            "Rejection identifies a creator correction signal, not proven model causation."
        ]
        if not targets:
            warnings.append("The rejected target was not found in saved BOBA artifacts.")
            limitations.append("Only explicit feedback content could be analyzed.")
        return BobaRejectionLearningCaseV1(
            case_id=_stable_id("rejection_case", event.event_id),
            project_id=event.project_id,
            feedback_event_id=event.event_id,
            target_type=event.target_type,
            target_id=event.target_id,
            candidate_id=candidate_id,
            rejected_reason_summary=reason,
            likely_rejection_causes=list(factors),
            what_boba_got_wrong=got_wrong,
            supporting_evidence=evidence,
            correction_mapping=corrections,
            future_avoidance_guidance=[
                mapping.future_rule_hint for mapping in corrections[:20]
            ]
            or ["Request a more specific correction before changing future decisions."],
            confidence=_confidence(confidence),
            warnings=_unique(warnings, maximum=24),
            limitations=limitations,
        )

    @staticmethod
    def _case_evidence(
        event: BobaCreatorFeedbackEventV1,
        factors: Sequence[BobaFeedbackFactorV1],
        targets: Sequence[tuple[str, dict[str, Any], str]],
    ) -> list[str]:
        evidence = [
            f"Explicit action: {event.user_action.replace('_', ' ')}.",
            *(
                [f"Creator note: {_text(event.note, maximum=240)}."]
                if event.note
                else []
            ),
            *(
                ["Creator tags: " + ", ".join(event.tags[:12]) + "."]
                if event.tags
                else []
            ),
            *[
                f"{factor.source_artifact}.{factor.source_field}: "
                f"{factor.evidence_snippet}"
                for factor in factors[:20]
            ],
        ]
        if targets:
            evidence.append(
                "Resolved target in: "
                + ", ".join(dict.fromkeys(source for source, _, _ in targets))
                + "."
            )
        return _unique(evidence, maximum=32)

    @staticmethod
    def _correction(
        event: BobaCreatorFeedbackEventV1,
        candidate_id: str,
        factor: BobaFeedbackFactorV1,
    ) -> BobaCorrectionMappingV1:
        corrections: dict[BobaFeedbackFactorCategory, tuple[str, str]] = {
            "clip_type": (
                "Reconsider whether this clip type matches the creator's stated taste.",
                "Downrank the same clip-type pattern until explicit positive evidence repeats.",
            ),
            "hook": (
                "Revise the opening hook using the creator's explicit correction.",
                "Require a reviewed hook alternative before recommending similar openings.",
            ),
            "retention": (
                "Strengthen the retention path and remove unsupported hold tactics.",
                "Flag similar retention risks for creator review.",
            ),
            "pacing": (
                "Tighten the opening and remove avoidable delay before the core idea.",
                "Review similar slow-opening candidates before ranking them highly.",
            ),
            "context": (
                "Restore the minimum context needed for standalone understanding.",
                "Penalize similar context-dependent windows unless repaired.",
            ),
            "payoff": (
                "Preserve and verify the payoff before selecting the clip.",
                "Do not recommend similar windows that end before a supported payoff.",
            ),
            "caption": (
                "Simplify caption density and protect readability.",
                "Prefer reviewed caption treatments over the rejected pattern.",
            ),
            "motion": (
                "Reduce motion intensity and remove unnecessary zooms.",
                "Flag similar high-motion treatments for explicit review.",
            ),
            "music_mood": (
                "Re-evaluate the mood against the clip's emotion and keep speech dominant.",
                "Avoid repeating this mood pattern without creator approval.",
            ),
            "sfx": (
                "Reduce or remove distracting SFX and preserve speech clarity.",
                "Default similar clips to restrained SFX pending review.",
            ),
            "speech_clarity": (
                "Prioritize intelligible speech over music or SFX energy.",
                "Block similar audio guidance when it risks masking speech.",
            ),
            "editorial_selection": (
                "Revisit the selection decision with the explicit rejection evidence.",
                "Require human review before selecting a closely similar case.",
            ),
            "ranking": (
                "Downrank similar candidates unless stronger evidence supports them.",
                "Use this rejection only as a provisional ranking penalty until repeated.",
            ),
            "explanation_quality": (
                "Provide clearer source-field evidence and decision reasoning.",
                "Require an evidence-linked explanation for similar recommendations.",
            ),
            "rights_risk": (
                "Resolve rights evidence before recommending the target.",
                "Keep similar unresolved rights cases blocked for review.",
            ),
            "render_readiness": (
                "Keep the target out of ready state until blockers are resolved.",
                "Require readiness evidence before promoting similar targets.",
            ),
            "general": (
                "Request a more specific creator correction.",
                "Do not generalize this weak signal automatically.",
            ),
        }
        suggested, future = corrections[factor.category]
        modules = _CATEGORY_MODULES[factor.category]
        affected = next(
            (module for module in modules if module != "unknown"),
            "unknown",
        )
        return BobaCorrectionMappingV1(
            mapping_id=_stable_id(
                "correction_mapping",
                event.event_id,
                factor.factor_id,
            ),
            feedback_event_id=event.event_id,
            candidate_id=candidate_id,
            problem_category=factor.category,
            affected_module=affected,
            suggested_correction=suggested,
            future_rule_hint=future,
            strength=_confidence(max(0.3, factor.confidence)),
            confidence=_confidence(factor.confidence * 0.9),
        )

    def _patterns(
        self,
        approvals: Sequence[BobaApprovalLearningCaseV1],
        rejections: Sequence[BobaRejectionLearningCaseV1],
    ) -> list[BobaApprovalRejectionPatternScoreV1]:
        aggregates: dict[
            tuple[BobaFeedbackFactorCategory, str], _PatternAggregate
        ] = {}
        for approval_case in approvals:
            self._add_pattern_factors(
                aggregates,
                approval_case.approval_factors,
                approval=True,
            )
        for rejection_case in rejections:
            self._add_pattern_factors(
                aggregates,
                rejection_case.likely_rejection_causes,
                approval=False,
            )

        patterns: list[BobaApprovalRejectionPatternScoreV1] = []
        for key in sorted(aggregates):
            aggregate = aggregates[key]
            total = aggregate.approval_count + aggregate.rejection_count
            contradiction_count = min(
                aggregate.approval_count,
                aggregate.rejection_count,
            )
            if contradiction_count:
                pattern_type: BobaApprovalRejectionPatternType = "contradiction"
            elif total == 1:
                pattern_type = "weak_signal"
            elif total >= 3:
                pattern_type = "strong_signal"
            elif aggregate.approval_count:
                pattern_type = "repeated_approval"
            else:
                pattern_type = "repeated_rejection"
            average = aggregate.confidence_total / total
            repeated_boost = min(0.28, max(0, total - 1) * 0.13)
            contradiction_penalty = (
                0.34 + min(0.16, contradiction_count * 0.05)
                if contradiction_count
                else 0.0
            )
            pattern_confidence = _confidence(
                average * 0.72 + repeated_boost - contradiction_penalty
            )
            strength = _confidence(0.28 + min(0.65, total * 0.16))
            if pattern_type == "contradiction":
                guidance = (
                    f"Conflicting explicit feedback exists for {aggregate.summary}; "
                    "do not generalize without creator review."
                )
            elif aggregate.approval_count:
                guidance = (
                    f"Consider favoring {aggregate.summary} after review; supported by "
                    f"{aggregate.approval_count} explicit approval(s)."
                )
            else:
                guidance = (
                    f"Consider avoiding {aggregate.summary} after review; supported by "
                    f"{aggregate.rejection_count} explicit rejection(s)."
                )
            patterns.append(
                BobaApprovalRejectionPatternScoreV1(
                    pattern_id=_stable_id(
                        "approval_rejection_pattern",
                        aggregate.category,
                        _normalized(aggregate.summary),
                    ),
                    pattern_type=pattern_type,
                    category=aggregate.category,
                    summary=aggregate.summary,
                    approval_count=aggregate.approval_count,
                    rejection_count=aggregate.rejection_count,
                    contradiction_count=contradiction_count,
                    confidence=pattern_confidence,
                    strength=strength,
                    affected_modules=sorted(aggregate.modules),
                    guidance=guidance,
                )
            )
        return patterns[:500]

    @staticmethod
    def _add_pattern_factors(
        aggregates: dict[
            tuple[BobaFeedbackFactorCategory, str], _PatternAggregate
        ],
        factors: Sequence[BobaFeedbackFactorV1],
        *,
        approval: bool,
    ) -> None:
        seen: set[tuple[BobaFeedbackFactorCategory, str]] = set()
        for factor in factors:
            if factor.polarity not in {"positive", "negative"}:
                continue
            key = (factor.category, _normalized(factor.summary))
            if key in seen:
                continue
            seen.add(key)
            aggregate = aggregates.setdefault(
                key,
                _PatternAggregate(
                    category=factor.category,
                    summary=factor.summary,
                ),
            )
            aggregate.modules.update(
                module
                for module in _CATEGORY_MODULES[factor.category]
                if module != "unknown"
            )
            if approval:
                aggregate.approval_count += 1
            else:
                aggregate.rejection_count += 1
            aggregate.confidence_total += factor.confidence

    @staticmethod
    def _module_guidance(
        patterns: Sequence[BobaApprovalRejectionPatternScoreV1],
    ) -> BobaApprovalRejectionModuleGuidanceV1:
        buckets: dict[str, list[str]] = defaultdict(list)
        field_by_module: dict[BobaDecisionAttributionModule, str] = {
            "candidate_discovery": "ranking_guidance",
            "clip_ranking": "ranking_guidance",
            "editorial_decision": "editorial_guidance",
            "creative_director": "creative_director_guidance",
            "clip_brief": "clip_brief_guidance",
            "hook_retention": "hook_retention_guidance",
            "caption_motion": "caption_motion_guidance",
            "music_mood": "music_mood_guidance",
            "explanation": "explanation_guidance",
            "creator_learning": "general_guidance",
            "unknown": "general_guidance",
        }
        for pattern in patterns:
            if pattern.pattern_type == "contradiction":
                buckets["general_guidance"].append(pattern.guidance)
                continue
            if pattern.pattern_type == "weak_signal":
                buckets["general_guidance"].append(
                    f"Weak signal only: {pattern.summary}; wait for repeated feedback."
                )
                continue
            for module in pattern.affected_modules:
                buckets[field_by_module[module]].append(pattern.guidance)
        return BobaApprovalRejectionModuleGuidanceV1(
            ranking_guidance=_unique(buckets["ranking_guidance"], maximum=32),
            editorial_guidance=_unique(buckets["editorial_guidance"], maximum=32),
            creative_director_guidance=_unique(
                buckets["creative_director_guidance"], maximum=32
            ),
            clip_brief_guidance=_unique(
                buckets["clip_brief_guidance"], maximum=32
            ),
            hook_retention_guidance=_unique(
                buckets["hook_retention_guidance"], maximum=32
            ),
            caption_motion_guidance=_unique(
                buckets["caption_motion_guidance"], maximum=32
            ),
            music_mood_guidance=_unique(
                buckets["music_mood_guidance"], maximum=32
            ),
            explanation_guidance=_unique(
                buckets["explanation_guidance"], maximum=32
            ),
            general_guidance=_unique(buckets["general_guidance"], maximum=32),
        )

    @staticmethod
    def _signal_usage(
        *,
        creator_learning: BobaCreatorLearningSetV1 | Mapping[str, Any] | None,
        feedback_events_used: int,
        memory: ArtifactValue,
        artifacts: Mapping[str, ArtifactValue],
    ) -> BobaApprovalRejectionSignalUsageV1:
        available = {name: bool(_artifact(value)) for name, value in artifacts.items()}
        unavailable = [
            name for name, is_available in available.items() if not is_available
        ]
        warnings = (
            [
                "One or more optional BOBA artifacts were unavailable; explicit "
                "feedback-only fallback was used."
            ]
            if unavailable
            else []
        )
        return BobaApprovalRejectionSignalUsageV1(
            creator_learning_used=bool(_artifact(creator_learning)),
            feedback_events_used=feedback_events_used,
            memory_used=bool(_artifact(memory)),
            clip_ranking_used=available["clip_ranking"],
            editorial_decision_used=available["editorial_decision"],
            explanation_used=available["explanation"],
            creative_direction_used=available["creative_direction"],
            clip_briefs_used=available["clip_briefs"],
            hook_retention_used=available["hook_retention"],
            caption_motion_used=available["caption_motion"],
            music_mood_used=available["music_mood"],
            fallback_used=bool(unavailable),
            unavailable_signals=unavailable,
            warnings=warnings,
        )
