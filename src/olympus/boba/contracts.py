"""JSON-safe contracts for BOBA Core Brain V1."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from olympus.boba.memory_contracts import BobaMemoryApplicationV1

BOBA_VERSION = "1"
BobaMode = Literal[
    "observe_only",
    "advise",
    "influence_planning",
    "influence_editing",
    "full_brain",
]
BobaDecisionType = Literal[
    "source_assessment",
    "whole_video_understanding",
    "clip_candidate_discovery",
    "clip_candidate_ranking",
    "clip_boundary_decision",
    "editing_policy",
    "caption_policy",
    "music_policy",
    "motion_policy",
    "upload_metadata_policy",
    "safety_policy",
    "trend_policy",
    "personalization_policy",
    "experiment_policy",
]
BobaTargetSystem = Literal[
    "story",
    "virality",
    "planning",
    "editing",
    "captions",
    "music",
    "motion",
    "upload_metadata",
    "safety",
    "trend",
    "personalization",
    "frontend",
]


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


class BobaContract(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class BobaReasoningV1(BobaContract):
    summary: str = Field(min_length=1, max_length=600)
    evidence: list[str] = Field(default_factory=list, max_length=24)
    tradeoffs: list[str] = Field(default_factory=list, max_length=16)
    rejected_options: list[str] = Field(default_factory=list, max_length=16)
    risks: list[str] = Field(default_factory=list, max_length=16)
    explanation_for_user: str = Field(min_length=1, max_length=800)


class BobaOutputDirectiveV1(BobaContract):
    target_system: BobaTargetSystem
    directive_type: str = Field(min_length=1, max_length=80)
    parameters: dict[str, Any] = Field(default_factory=dict)
    priority: int = Field(default=50, ge=0, le=100)
    constraints: list[str] = Field(default_factory=list, max_length=24)


class BobaDecisionValidationV1(BobaContract):
    passed: bool = True
    warnings: list[str] = Field(default_factory=list, max_length=32)
    errors: list[str] = Field(default_factory=list, max_length=32)


class BobaDecisionV1(BobaContract):
    decision_id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=128)
    clip_id: str | None = Field(default=None, max_length=128)
    created_at: str = Field(default_factory=now_iso)
    decision_type: BobaDecisionType
    question: str = Field(min_length=1, max_length=400)
    answer: str = Field(min_length=1, max_length=600)
    confidence: float = Field(ge=0.0, le=1.0)
    input_signals: dict[str, dict[str, Any]] = Field(default_factory=dict)
    reasoning: BobaReasoningV1
    output_directive: BobaOutputDirectiveV1
    validation: BobaDecisionValidationV1 = Field(default_factory=BobaDecisionValidationV1)
    memory_application_v1: BobaMemoryApplicationV1 | None = None


class BobaObservationV1(BobaContract):
    observation_id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=128)
    source: str = Field(min_length=1, max_length=80)
    observation_type: Literal[
        "project_signal",
        "missing_signal",
        "candidate_pattern",
        "quality_warning",
        "safety_warning",
        "user_feedback",
        "trend_observation",
        "editing_observation",
    ]
    summary: str = Field(min_length=1, max_length=600)
    evidence: list[str] = Field(default_factory=list, max_length=24)
    confidence: float = Field(ge=0.0, le=1.0)
    created_at: str = Field(default_factory=now_iso)
    safe_to_learn: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=24)


class BobaLearningNoteV1(BobaContract):
    note_id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=128)
    learning_scope: Literal["project", "creator", "global"] = "project"
    source: str = Field(min_length=1, max_length=80)
    lesson: str = Field(min_length=1, max_length=600)
    confidence: float = Field(ge=0.0, le=1.0)
    applies_to: list[str] = Field(default_factory=list, max_length=24)
    should_experiment: bool = False
    created_at: str = Field(default_factory=now_iso)
    safety_checked: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=24)


class BobaSourceUnderstandingV1(BobaContract):
    source_type: str = "unknown"
    duration_seconds: float | None = Field(default=None, ge=0.0)
    transcript_available: bool = False
    visual_signals_available: bool = False
    speaker_signals_available: bool = False
    trend_signals_available: bool = False
    safety_signals_available: bool = False
    personalization_signals_available: bool = False
    missing_signals: list[str] = Field(default_factory=list, max_length=32)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaProjectMemorySummaryV1(BobaContract):
    main_topics: list[str] = Field(default_factory=list, max_length=24)
    speakers_or_roles: list[str] = Field(default_factory=list, max_length=24)
    story_threads: list[str] = Field(default_factory=list, max_length=24)
    emotional_moments: list[str] = Field(default_factory=list, max_length=24)
    repeated_information: list[str] = Field(default_factory=list, max_length=24)
    callbacks: list[str] = Field(default_factory=list, max_length=24)
    unused_opportunities: list[str] = Field(default_factory=list, max_length=24)
    already_selected_ranges: list[dict[str, float]] = Field(default_factory=list, max_length=100)
    rejected_ranges: list[dict[str, float]] = Field(default_factory=list, max_length=100)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaDecisionContextV1(BobaContract):
    creator_profile_id: str | None = None
    creator_profile_name: str | None = None
    content_niche: str = "unknown"
    target_platforms: list[str] = Field(default_factory=list, max_length=12)
    safety_status: str = "unknown"
    trend_provider_status: str = "unavailable"
    personalization_status: str = "unavailable"
    known_limitations: list[str] = Field(default_factory=list, max_length=32)


class BobaGoalV1(BobaContract):
    goal_id: str = Field(min_length=1, max_length=128)
    goal_type: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=300)
    priority: int = Field(ge=0, le=100)
    success_criteria: list[str] = Field(default_factory=list, max_length=16)


class BobaBrainResultV1(BobaContract):
    ready_for_planning: bool = False
    ready_for_editing: bool = False
    ready_for_rendering: bool = False
    blockers: list[str] = Field(default_factory=list, max_length=32)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaBrainStateV1(BobaContract):
    brain_id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=128)
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    version: Literal["1"] = "1"
    mode: BobaMode = "advise"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source_understanding: BobaSourceUnderstandingV1
    project_memory_summary: BobaProjectMemorySummaryV1 = Field(
        default_factory=BobaProjectMemorySummaryV1
    )
    decision_context: BobaDecisionContextV1 = Field(default_factory=BobaDecisionContextV1)
    active_goals: list[BobaGoalV1] = Field(default_factory=list, max_length=24)
    decisions: list[BobaDecisionV1] = Field(default_factory=list, max_length=500)
    observations: list[BobaObservationV1] = Field(default_factory=list, max_length=500)
    experiments: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    learning_notes: list[BobaLearningNoteV1] = Field(default_factory=list, max_length=500)
    result: BobaBrainResultV1 = Field(default_factory=BobaBrainResultV1)


class BobaCandidateInsightV1(BobaContract):
    candidate_id: str = Field(min_length=1, max_length=128)
    clip_id: str | None = Field(default=None, max_length=128)
    source_start: float = Field(ge=0.0)
    source_end: float = Field(ge=0.0)
    duration: float = Field(ge=0.0)
    hook_summary: str = Field(default="", max_length=300)
    payoff_summary: str = Field(default="", max_length=300)
    story_completeness: float = Field(default=0.0, ge=0.0, le=1.0)
    curiosity_strength: float = Field(default=0.0, ge=0.0, le=1.0)
    emotional_strength: float = Field(default=0.0, ge=0.0, le=1.0)
    context_requirement: float = Field(default=0.0, ge=0.0, le=1.0)
    duplicate_risk: float = Field(default=0.0, ge=0.0, le=1.0)
    editing_opportunity: float = Field(default=0.0, ge=0.0, le=1.0)
    safety_risk: float = Field(default=0.0, ge=0.0, le=1.0)
    creator_fit: float = Field(default=0.0, ge=0.0, le=1.0)
    trend_fit: float = Field(default=0.0, ge=0.0, le=1.0)
    overall_recommendation: float = Field(default=0.0, ge=0.0, le=1.0)
    reasons: list[str] = Field(default_factory=list, max_length=24)
    warnings: list[str] = Field(default_factory=list, max_length=24)


class BobaClipRankingV1(BobaContract):
    project_id: str = Field(min_length=1, max_length=128)
    candidate_count: int = Field(ge=0)
    ranked_candidates: list[BobaCandidateInsightV1] = Field(default_factory=list)
    rejected_candidates: list[BobaCandidateInsightV1] = Field(default_factory=list)
    duplicate_groups: list[list[str]] = Field(default_factory=list)
    coverage_summary: dict[str, Any] = Field(default_factory=dict)
    reasoning_summary: str = Field(default="", max_length=800)
    warnings: list[str] = Field(default_factory=list, max_length=32)
    memory_application_v1: BobaMemoryApplicationV1 | None = None


class BobaEditorialPolicyV1(BobaContract):
    project_id: str = Field(min_length=1, max_length=128)
    clip_id: str = Field(min_length=1, max_length=128)
    policy_name: str = Field(min_length=1, max_length=80)
    pacing: Literal["slow", "balanced", "fast", "aggressive"] = "balanced"
    hook_treatment: dict[str, Any] = Field(default_factory=dict)
    caption_directives: dict[str, Any] = Field(default_factory=dict)
    music_directives: dict[str, Any] = Field(default_factory=dict)
    motion_directives: dict[str, Any] = Field(default_factory=dict)
    sfx_directives: dict[str, Any] = Field(default_factory=dict)
    silence_directives: dict[str, Any] = Field(default_factory=dict)
    ending_directives: dict[str, Any] = Field(default_factory=dict)
    safety_constraints: list[str] = Field(default_factory=list, max_length=24)
    explanation: str = Field(min_length=1, max_length=800)
    confidence: float = Field(ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list, max_length=32)
    memory_application_v1: BobaMemoryApplicationV1 | None = None


class BobaValidationResultV1(BobaContract):
    passed: bool
    mode: str
    project_id: str | None = None
    brain_state_created: bool = False
    memory_written: bool = False
    decisions_created: int = Field(default=0, ge=0)
    ranking_created: bool = False
    editorial_policy_created: bool = False
    unified_metadata_present: bool = False
    unified_metadata_checked: bool = False
    api_checked: bool = False
    frontend_checked: bool = False
    missing_signals: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
