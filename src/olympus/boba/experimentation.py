"""Deterministic advisory creative experimentation plans for BOBA."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from hashlib import sha256
from typing import Any, Literal, TypeAlias
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from olympus.boba.contracts import BobaContract, now_iso

BobaExperimentTargetType = Literal[
    "clip",
    "candidate",
    "clip_brief",
    "hook_alternative",
    "caption_motion",
    "music_mood",
    "creative_direction",
    "project",
]
BobaExperimentType = Literal[
    "hook_ab_test",
    "caption_ab_test",
    "motion_ab_test",
    "music_mood_ab_test",
    "sfx_ab_test",
    "opening_ab_test",
    "retention_ab_test",
    "brief_ab_test",
    "project_style_test",
]
BobaExperimentStatus = Literal[
    "draft",
    "needs_creator_approval",
    "approved",
    "rejected",
    "completed_manually",
    "cancelled",
]
BobaExperimentVariantType = Literal[
    "hook",
    "caption",
    "motion",
    "music_mood",
    "sfx",
    "opening",
    "retention",
    "brief",
    "style",
]
BobaExperimentImprovementArea = Literal[
    "hook_strength",
    "retention",
    "clarity",
    "emotional_pull",
    "caption_readability",
    "motion_safety",
    "audio_fit",
    "speech_clarity",
    "payoff_strength",
    "creator_preference_fit",
]
BobaExperimentPrimaryMetric = Literal[
    "manual_creator_preference",
    "approval_rate",
    "hook_quality_review",
    "retention_quality_review",
    "caption_readability_review",
    "motion_safety_review",
    "audio_fit_review",
    "future_viewer_retention",
    "future_viewer_engagement",
]
BobaExperimentApprovalType = Literal[
    "creator_approval",
    "rights_review",
    "human_review",
    "safety_review",
]
BobaExperimentOutcomeLabel = Literal[
    "baseline_preferred",
    "variant_preferred",
    "no_clear_winner",
    "rejected_all",
    "needs_more_review",
]
ArtifactValue: TypeAlias = Mapping[str, Any] | BaseModel | None

_SPACE = re.compile(r"\s+")
_NORMALIZE = re.compile(r"[^a-z0-9]+")
_FUTURE_METRICS = {"future_viewer_retention", "future_viewer_engagement"}
_MISLEADING_TERMS = (
    "misleading",
    "deceptive",
    "unsupported claim",
    "false promise",
    "bait and switch",
    "sensational",
)
_RIGHTS_TERMS = ("copyright", "rights", "license", "permission")


def _text(value: Any, *, maximum: int = 700) -> str:
    return _SPACE.sub(" ", str(value or "")).strip()[:maximum]


def _normalized(value: Any, *, maximum: int = 120) -> str:
    return _NORMALIZE.sub("_", _text(value, maximum=maximum).casefold()).strip("_")


def _unique(values: Sequence[str], *, maximum: int) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))[:maximum]


def _dict(value: Any) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list | tuple) else []


def _bool(value: Any) -> bool:
    return value is True


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _confidence(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 4)


def _stable_id(prefix: str, *values: str) -> str:
    digest = sha256("|".join(values).encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


def _contains_any(value: Any, terms: Sequence[str]) -> bool:
    rendered = _text(value, maximum=2000).casefold()
    return any(term in rendered for term in terms)


class BobaExperimentBaselineV1(BobaContract):
    baseline_id: str = Field(min_length=1, max_length=128)
    source_artifact: str = Field(min_length=1, max_length=80)
    source_field: str = Field(min_length=1, max_length=180)
    summary: str = Field(min_length=1, max_length=600)
    current_instruction: str = Field(min_length=1, max_length=1000)
    strengths: list[str] = Field(default_factory=list, max_length=16)
    weaknesses: list[str] = Field(default_factory=list, max_length=16)
    confidence: float = Field(ge=0.0, le=1.0)


class BobaExperimentVariantV1(BobaContract):
    variant_id: str = Field(min_length=1, max_length=128)
    label: str = Field(min_length=1, max_length=80)
    variant_type: BobaExperimentVariantType
    summary: str = Field(min_length=1, max_length=500)
    changed_variable: str = Field(min_length=1, max_length=120)
    instruction: str = Field(min_length=1, max_length=1000)
    expected_effect: str = Field(min_length=1, max_length=700)
    risk: str = Field(min_length=1, max_length=700)
    should_test: bool
    reason: str = Field(min_length=1, max_length=700)


class BobaExperimentHypothesisV1(BobaContract):
    hypothesis_id: str = Field(min_length=1, max_length=128)
    statement: str = Field(min_length=1, max_length=800)
    reason: str = Field(min_length=1, max_length=800)
    expected_improvement_area: BobaExperimentImprovementArea
    confidence: float = Field(ge=0.0, le=1.0)
    assumptions: list[str] = Field(default_factory=list, max_length=16)


class BobaExperimentMetricPlanV1(BobaContract):
    primary_metric: BobaExperimentPrimaryMetric
    secondary_metrics: list[BobaExperimentPrimaryMetric] = Field(
        default_factory=list, max_length=8
    )
    manual_review_questions: list[str] = Field(default_factory=list, max_length=16)
    required_result_fields: list[str] = Field(default_factory=list, max_length=16)
    analytics_required_later: bool = False
    notes: list[str] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def validate_future_analytics_flag(self) -> BobaExperimentMetricPlanV1:
        metrics = {self.primary_metric, *self.secondary_metrics}
        uses_future_metric = bool(metrics & _FUTURE_METRICS)
        if self.analytics_required_later != uses_future_metric:
            raise ValueError(
                "analytics_required_later must be true exactly when a future viewer "
                "metric is present"
            )
        return self


class BobaExperimentSuccessCriteriaV1(BobaContract):
    success_definition: str = Field(min_length=1, max_length=800)
    minimum_manual_rating: float = Field(default=3.5, ge=0.0, le=5.0)
    approval_required: bool = True
    failure_conditions: list[str] = Field(default_factory=list, max_length=16)
    decision_rule: str = Field(min_length=1, max_length=800)


class BobaExperimentRiskReviewV1(BobaContract):
    rights_risk: bool = False
    clarity_risk: bool = False
    over_editing_risk: bool = False
    under_editing_risk: bool = False
    misleading_hook_risk: bool = False
    caption_overload_risk: bool = False
    motion_safety_risk: bool = False
    audio_mismatch_risk: bool = False
    speech_clarity_risk: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=32)
    blockers: list[str] = Field(default_factory=list, max_length=24)


class BobaExperimentLearningHandoffV1(BobaContract):
    consume_result_in_modules: list[str] = Field(default_factory=list, max_length=12)
    feedback_to_collect: list[str] = Field(default_factory=list, max_length=16)
    expected_learning_update: str = Field(min_length=1, max_length=700)
    approval_rejection_learning_target: str = Field(
        min_length=1, max_length=180
    )
    creator_learning_target: str = Field(min_length=1, max_length=180)
    apply_automatically: Literal[False] = False


class BobaExperimentPlanV1(BobaContract):
    experiment_id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=128)
    target_type: BobaExperimentTargetType
    target_id: str = Field(min_length=1, max_length=180)
    candidate_id: str = Field(default="", max_length=128)
    brief_id: str = Field(default="", max_length=160)
    experiment_type: BobaExperimentType
    title: str = Field(min_length=1, max_length=180)
    baseline: BobaExperimentBaselineV1
    variants: list[BobaExperimentVariantV1] = Field(min_length=1, max_length=3)
    hypothesis: BobaExperimentHypothesisV1
    metric_plan: BobaExperimentMetricPlanV1
    success_criteria: BobaExperimentSuccessCriteriaV1
    risk_review: BobaExperimentRiskReviewV1
    learning_handoff: BobaExperimentLearningHandoffV1
    required_creator_approval: bool = True
    status: BobaExperimentStatus = "needs_creator_approval"
    confidence: float = Field(ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list, max_length=32)
    limitations: list[str] = Field(default_factory=list, max_length=24)

    @model_validator(mode="after")
    def validate_single_changed_variable(self) -> BobaExperimentPlanV1:
        variables = {
            _normalized(variant.changed_variable) for variant in self.variants
        }
        if len(variables) != 1:
            raise ValueError("all variants in one experiment must change one variable")
        if not self.required_creator_approval and self.status == "needs_creator_approval":
            raise ValueError("needs_creator_approval requires creator approval")
        return self


class BobaRejectedExperimentIdeaV1(BobaContract):
    idea_id: str = Field(min_length=1, max_length=128)
    target_id: str = Field(min_length=1, max_length=180)
    experiment_type: BobaExperimentType
    reason_rejected: str = Field(min_length=1, max_length=700)
    risk: str = Field(min_length=1, max_length=700)
    warnings: list[str] = Field(default_factory=list, max_length=24)


class BobaExperimentApprovalRequirementV1(BobaContract):
    requirement_id: str = Field(min_length=1, max_length=128)
    experiment_id: str = Field(min_length=1, max_length=128)
    approval_type: BobaExperimentApprovalType
    reason: str = Field(min_length=1, max_length=700)
    required_before_status: BobaExperimentStatus
    warnings: list[str] = Field(default_factory=list, max_length=16)


class BobaExperimentationSignalUsageV1(BobaContract):
    clip_briefs_used: bool = False
    hook_retention_used: bool = False
    caption_motion_used: bool = False
    music_mood_used: bool = False
    creative_direction_used: bool = False
    editorial_decision_used: bool = False
    explanation_used: bool = False
    creator_learning_used: bool = False
    approval_rejection_learning_used: bool = False
    memory_used: bool = False
    fallback_used: bool = False
    unavailable_signals: list[str] = Field(default_factory=list, max_length=32)
    warnings: list[str] = Field(default_factory=list, max_length=32)


class BobaExperimentationSetV1(BobaContract):
    schema_version: Literal["boba_experimentation_system_v1"] = (
        "boba_experimentation_system_v1"
    )
    project_id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(min_length=1, max_length=512)
    created_at: str = Field(default_factory=now_iso)
    experiment_plans: list[BobaExperimentPlanV1] = Field(
        default_factory=list, max_length=100
    )
    rejected_experiment_ideas: list[BobaRejectedExperimentIdeaV1] = Field(
        default_factory=list, max_length=100
    )
    experiment_summary: str = Field(min_length=1, max_length=1800)
    approval_requirements: list[BobaExperimentApprovalRequirementV1] = Field(
        default_factory=list, max_length=300
    )
    signal_usage: BobaExperimentationSignalUsageV1
    warnings: list[str] = Field(default_factory=list, max_length=64)
    limitations: list[str] = Field(default_factory=list, max_length=64)


class BobaExperimentManualResultV1(BobaContract):
    result_id: str = Field(
        default_factory=lambda: f"experiment_result_{uuid4().hex[:20]}",
        min_length=1,
        max_length=128,
    )
    experiment_id: str = Field(min_length=1, max_length=128)
    selected_variant_id: str = Field(min_length=1, max_length=128)
    manual_rating: float = Field(ge=0.0, le=5.0)
    creator_note: str = Field(default="", max_length=500)
    outcome_label: BobaExperimentOutcomeLabel
    created_at: str = Field(default_factory=now_iso)
    should_feed_learning: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=24)

    @field_validator("creator_note")
    @classmethod
    def normalize_note(cls, value: str) -> str:
        return _text(value, maximum=500)


class BobaExperimentationSystemV1:
    """Create compact test plans without executing or observing experiments."""

    def analyze(
        self,
        project_id: str,
        *,
        source_id: str | None = None,
        clip_briefs: ArtifactValue = None,
        hook_retention: ArtifactValue = None,
        caption_motion: ArtifactValue = None,
        music_mood: ArtifactValue = None,
        creative_direction: ArtifactValue = None,
        editorial_decision: ArtifactValue = None,
        explanation: ArtifactValue = None,
        creator_learning: ArtifactValue = None,
        approval_rejection_learning: ArtifactValue = None,
        boba_memory: ArtifactValue = None,
        dry_run: bool = False,
    ) -> BobaExperimentationSetV1:
        artifacts = {
            "clip_briefs": _dict(clip_briefs),
            "hook_retention": _dict(hook_retention),
            "caption_motion": _dict(caption_motion),
            "music_mood": _dict(music_mood),
            "creative_direction": _dict(creative_direction),
            "editorial_decision": _dict(editorial_decision),
            "explanation": _dict(explanation),
            "creator_learning": _dict(creator_learning),
            "approval_rejection_learning": _dict(
                approval_rejection_learning
            ),
            "memory": _dict(boba_memory),
        }
        contexts = self._candidate_contexts(artifacts)
        plans: list[BobaExperimentPlanV1] = []
        rejected: list[BobaRejectedExperimentIdeaV1] = []
        for candidate_id in sorted(contexts):
            context = contexts[candidate_id]
            if context.get("blocked"):
                rejected.append(
                    self._rejected(
                        target_id=context["brief_id"] or candidate_id,
                        experiment_type="brief_ab_test",
                        reason=(
                            "The clip brief is blocked; creative testing must wait until "
                            "its source blockers are resolved."
                        ),
                        risk="Testing a blocked brief could hide unresolved editorial risk.",
                    )
                )
                continue
            generated, rejected_ideas = self._candidate_plans(
                project_id,
                candidate_id,
                context,
                artifacts,
            )
            plans.extend(generated)
            rejected.extend(rejected_ideas)

        plans = sorted(
            plans,
            key=lambda item: (
                item.candidate_id,
                item.experiment_type,
                item.experiment_id,
            ),
        )[:100]
        rejected = self._deduplicate_rejections(rejected)[:100]
        approvals = [
            requirement
            for plan in plans
            for requirement in self._approval_requirements(plan)
        ]
        usage = self._signal_usage(artifacts)
        warnings = [
            "Experiments are advisory plans only; no rendering or uploading occurred.",
            "No viewer analytics or hidden behavior was collected.",
            "Every experiment requires explicit creator approval before activation.",
            "No experiment winner is applied automatically.",
        ]
        limitations = [
            "Hypotheses describe testable creative questions, not performance predictions.",
            "Manual review is required before any plan is executed outside V1.",
            "Future viewer metrics require a separate consented analytics system.",
        ]
        if not contexts:
            warnings.append("No candidate-level BOBA artifacts were available.")
            limitations.append(
                "Experiment plans require at least a clip brief or candidate recommendation."
            )
        if not plans:
            warnings.append("No safe evidence-backed experiment plan could be generated.")
            limitations.append(
                "Unsafe or unsupported ideas were rejected rather than fabricated."
            )
        if dry_run:
            warnings.append("Dry run: experimentation plans were not persisted.")
        summary = self._summary(plans, rejected)
        return BobaExperimentationSetV1(
            project_id=project_id,
            source_id=_text(source_id or project_id, maximum=512),
            experiment_plans=plans,
            rejected_experiment_ideas=rejected,
            experiment_summary=summary,
            approval_requirements=approvals,
            signal_usage=usage,
            warnings=_unique(warnings, maximum=64),
            limitations=_unique(limitations, maximum=64),
        )

    def create_manual_result(
        self,
        experiment: BobaExperimentPlanV1,
        *,
        selected_variant_id: str,
        manual_rating: float,
        outcome_label: BobaExperimentOutcomeLabel,
        creator_note: str = "",
        should_feed_learning: bool = False,
        result_id: str | None = None,
        created_at: str | None = None,
    ) -> BobaExperimentManualResultV1:
        valid_variants = {
            experiment.baseline.baseline_id,
            *(variant.variant_id for variant in experiment.variants),
        }
        if selected_variant_id not in valid_variants:
            raise ValueError("selected_variant_id is not part of the experiment")
        warnings = [
            "Manual result recorded without applying a winner automatically.",
        ]
        if should_feed_learning:
            warnings.append(
                "Explicit learning handoff was requested but remains pending review."
            )
        return BobaExperimentManualResultV1(
            **({"result_id": result_id} if result_id else {}),
            **({"created_at": created_at} if created_at else {}),
            experiment_id=experiment.experiment_id,
            selected_variant_id=selected_variant_id,
            manual_rating=manual_rating,
            creator_note=creator_note,
            outcome_label=outcome_label,
            should_feed_learning=should_feed_learning,
            warnings=warnings,
        )

    def _candidate_contexts(
        self,
        artifacts: Mapping[str, dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        contexts: dict[str, dict[str, Any]] = {}

        def context(candidate_id: str) -> dict[str, Any]:
            return contexts.setdefault(
                candidate_id,
                {
                    "candidate_id": candidate_id,
                    "brief_id": "",
                    "brief": {},
                    "hook": {},
                    "caption": {},
                    "music": {},
                    "creative": {},
                    "editorial": {},
                    "explanation": {},
                    "blocked": False,
                },
            )

        briefs = artifacts["clip_briefs"]
        for collection_name, blocked in (
            ("selected_briefs", False),
            ("backup_briefs", False),
            ("blocked_briefs", True),
        ):
            for raw in _list(briefs.get(collection_name)):
                item = _dict(raw)
                candidate_id = _text(
                    item.get("candidate_id") or item.get("clip_id"),
                    maximum=128,
                )
                if not candidate_id:
                    continue
                current = context(candidate_id)
                if not current["brief"] or not blocked:
                    current["brief"] = item
                    current["brief_id"] = _text(
                        item.get("brief_id"),
                        maximum=160,
                    )
                    current["blocked"] = blocked

        source_collections = (
            ("hook_retention", "analyses", "hook"),
            ("caption_motion", "recommendations", "caption"),
            ("music_mood", "recommendations", "music"),
            ("creative_direction", "clip_directions", "creative"),
            ("editorial_decision", "decisions", "editorial"),
        )
        for artifact_name, collection_name, context_key in source_collections:
            for raw in _list(artifacts[artifact_name].get(collection_name)):
                item = _dict(raw)
                candidate_id = _text(
                    item.get("candidate_id") or item.get("clip_id"),
                    maximum=128,
                )
                if not candidate_id:
                    continue
                current = context(candidate_id)
                current[context_key] = item
                if not current["brief_id"]:
                    current["brief_id"] = _text(
                        item.get("brief_id"),
                        maximum=160,
                    )

        explanation = artifacts["explanation"]
        for collection_name in (
            "candidate_explanations",
            "ranking_explanations",
            "editorial_explanations",
            "explanations",
        ):
            for raw in _list(explanation.get(collection_name)):
                item = _dict(raw)
                candidate_id = _text(
                    item.get("candidate_id") or item.get("clip_id"),
                    maximum=128,
                )
                if candidate_id and not context(candidate_id)["explanation"]:
                    context(candidate_id)["explanation"] = item
        return contexts

    def _candidate_plans(
        self,
        project_id: str,
        candidate_id: str,
        context: dict[str, Any],
        artifacts: Mapping[str, dict[str, Any]],
    ) -> tuple[list[BobaExperimentPlanV1], list[BobaRejectedExperimentIdeaV1]]:
        plans: list[BobaExperimentPlanV1] = []
        rejected: list[BobaRejectedExperimentIdeaV1] = []
        creators = self._creator_preferences(artifacts["creator_learning"])
        approval_guidance = self._approval_guidance(
            artifacts["approval_rejection_learning"]
        )

        hook_plan, hook_rejections = self._hook_plan(
            project_id,
            candidate_id,
            context,
            creators,
            approval_guidance,
        )
        if hook_plan is not None:
            plans.append(hook_plan)
        rejected.extend(hook_rejections)

        caption_plan = self._caption_plan(
            project_id,
            candidate_id,
            context,
            creators,
            approval_guidance,
        )
        if caption_plan is not None:
            plans.append(caption_plan)

        motion_plan, motion_rejections = self._motion_plan(
            project_id,
            candidate_id,
            context,
            creators,
            approval_guidance,
        )
        if motion_plan is not None:
            plans.append(motion_plan)
        rejected.extend(motion_rejections)

        music_plan, music_rejections = self._music_plan(
            project_id,
            candidate_id,
            context,
            creators,
            approval_guidance,
        )
        if music_plan is not None:
            plans.append(music_plan)
        rejected.extend(music_rejections)

        sfx_plan = self._sfx_plan(project_id, candidate_id, context)
        if sfx_plan is not None:
            plans.append(sfx_plan)

        retention_plan = self._retention_plan(
            project_id,
            candidate_id,
            context,
        )
        if retention_plan is not None:
            plans.append(retention_plan)

        opening_plan = self._opening_plan(
            project_id,
            candidate_id,
            context,
        )
        if opening_plan is not None:
            plans.append(opening_plan)

        brief_plan = self._brief_plan(project_id, candidate_id, context)
        if brief_plan is not None:
            plans.append(brief_plan)
        return plans, rejected

    def _hook_plan(
        self,
        project_id: str,
        candidate_id: str,
        context: dict[str, Any],
        creator_preferences: dict[str, list[str]],
        approval_guidance: dict[str, list[str]],
    ) -> tuple[BobaExperimentPlanV1 | None, list[BobaRejectedExperimentIdeaV1]]:
        hook = _dict(context.get("hook"))
        analysis = _dict(hook.get("hook_analysis"))
        alternatives = [_dict(item) for item in _list(hook.get("hook_alternatives"))]
        if not analysis or not alternatives:
            return None, []
        experiment_id = _stable_id("experiment_hook", project_id, candidate_id)
        hook_type = _text(analysis.get("hook_type"), maximum=80) or "current hook"
        current = _text(
            analysis.get("opening_line_direction")
            or analysis.get("improved_hook_direction"),
            maximum=1000,
        )
        if not current:
            return None, [
                self._rejected(
                    target_id=context["brief_id"] or candidate_id,
                    experiment_type="hook_ab_test",
                    reason="The current hook instruction is unavailable.",
                    risk="A baseline-free experiment would not be traceable.",
                )
            ]
        hook_risk = _text(analysis.get("hook_risk"), maximum=700)
        risk_review = self._risk_review(context, "hook_ab_test")
        variants: list[BobaExperimentVariantV1] = []
        rejected: list[BobaRejectedExperimentIdeaV1] = []
        for alternative in alternatives:
            alternative_id = _text(alternative.get("alternative_id"), maximum=180)
            instruction = _text(
                alternative.get("opening_line_direction"),
                maximum=1000,
            )
            risk_score = _number(alternative.get("risk_score"), 50.0)
            why_fail = _text(alternative.get("why_it_may_fail"), maximum=700)
            unsafe = (
                risk_score > 68.0
                or _contains_any(why_fail, _MISLEADING_TERMS)
                or _contains_any(instruction, _MISLEADING_TERMS)
            )
            if unsafe:
                rejected.append(
                    self._rejected(
                        target_id=alternative_id or candidate_id,
                        experiment_type="hook_ab_test",
                        reason=(
                            "The hook alternative has excessive misleading or unsupported "
                            "risk."
                        ),
                        risk=why_fail or f"Hook alternative risk score is {risk_score:.1f}.",
                    )
                )
                continue
            if not instruction or instruction.casefold() == current.casefold():
                continue
            label = chr(ord("B") + len(variants))
            variants.append(
                self._variant(
                    experiment_id,
                    label=label,
                    variant_type="hook",
                    summary=(
                        "Test "
                        f"{_text(alternative.get('hook_type'), maximum=80) or 'an alternate hook'} "
                        "while preserving all other treatment."
                    ),
                    changed_variable="opening_hook",
                    instruction=instruction,
                    expected_effect=(
                        "Improve manual hook-strength review without changing caption, "
                        "motion, audio, or source boundaries."
                    ),
                    risk=why_fail or "The alternate hook may reduce clarity.",
                    reason=_text(
                        alternative.get("why_it_may_work"),
                        maximum=700,
                    )
                    or "The existing hook module supplied this bounded alternative.",
                )
            )
            if len(variants) >= 3:
                break
        if not variants:
            return None, [
                *rejected,
                self._rejected(
                    target_id=context["brief_id"] or candidate_id,
                    experiment_type="hook_ab_test",
                    reason="No distinct safe hook alternative remained after risk review.",
                    risk="Generating an unsupported hook would invent evidence.",
                ),
            ]
        score = _number(analysis.get("hook_strength"), 60.0)
        weaknesses = [hook_risk] if hook_risk else []
        preferred_hooks = creator_preferences["preferred_hook_styles"]
        if preferred_hooks:
            weaknesses.append(
                "Creator preference to review: " + preferred_hooks[0].replace("_", " ")
            )
        weaknesses.extend(approval_guidance["hook"])
        baseline = self._baseline(
            experiment_id,
            source_artifact="hook_retention",
            source_field="analyses[].hook_analysis.opening_line_direction",
            summary=f"Current {hook_type.replace('_', ' ')} hook direction.",
            instruction=current,
            strengths=[
                f"Current hook-strength score: {score:.1f}/100.",
                _text(analysis.get("reason"), maximum=500),
            ],
            weaknesses=weaknesses,
            confidence=_number(hook.get("confidence"), 0.62),
        )
        return (
            self._plan(
                experiment_id=experiment_id,
                project_id=project_id,
                context=context,
                experiment_type="hook_ab_test",
                title="Hook direction comparison",
                baseline=baseline,
                variants=variants,
                improvement_area="hook_strength",
                hypothesis_statement=(
                    "Changing only the opening hook direction may improve the creator's "
                    "manual hook-quality assessment."
                ),
                hypothesis_reason=(
                    "The Hook + Retention Brain supplied bounded alternatives with "
                    "different strength and risk trade-offs."
                ),
                metric="hook_quality_review",
                secondary_metrics=["manual_creator_preference"],
                review_questions=[
                    "Which opening is clearest in the first three seconds?",
                    "Which version creates curiosity without overpromising?",
                ],
                risk_review=risk_review,
                confidence=0.64 + min(0.16, len(variants) * 0.04),
            ),
            rejected,
        )

    def _caption_plan(
        self,
        project_id: str,
        candidate_id: str,
        context: dict[str, Any],
        creator_preferences: dict[str, list[str]],
        approval_guidance: dict[str, list[str]],
    ) -> BobaExperimentPlanV1 | None:
        recommendation = _dict(context.get("caption"))
        caption = _dict(recommendation.get("caption_recommendation"))
        safety = _dict(recommendation.get("safety_review"))
        enhancement = _dict(recommendation.get("brief_enhancement"))
        if not caption:
            return None
        experiment_id = _stable_id("experiment_caption", project_id, candidate_id)
        current_style = _text(caption.get("caption_style"), maximum=80) or "current"
        current_instruction = _text(
            caption.get("hook_caption_instruction")
            or caption.get("reason"),
            maximum=1000,
        )
        if not current_instruction:
            return None
        overload = _bool(safety.get("caption_overload_risk")) or _bool(
            safety.get("readability_risk")
        )
        improved = _text(
            enhancement.get("improved_caption_instruction"),
            maximum=1000,
        )
        if not improved:
            improved = (
                "Use shorter phrase groups, fewer simultaneous highlights, and stable "
                "line breaks while preserving the spoken wording."
                if overload
                else "Use a restrained readable caption rhythm with one emphasis word "
                "per meaningful beat."
            )
        variants = [
            self._variant(
                experiment_id,
                label="B",
                variant_type="caption",
                summary="Readability-focused caption treatment.",
                changed_variable="caption_treatment",
                instruction=improved,
                expected_effect=(
                    "Improve manual caption-readability review while keeping hook, motion, "
                    "audio, and clip timing unchanged."
                ),
                risk="Reduced density may lower visual energy if simplified too far.",
                reason=(
                    _text(enhancement.get("readability_warning"), maximum=700)
                    or "Caption safety evidence supports a controlled readability test."
                ),
            )
        ]
        preferred = creator_preferences["preferred_caption_styles"]
        if preferred and _normalized(preferred[0]) != _normalized(current_style):
            variants.append(
                self._variant(
                    experiment_id,
                    label="C",
                    variant_type="caption",
                    summary="Creator-preferred caption style.",
                    changed_variable="caption_treatment",
                    instruction=(
                        f"Use the explicitly preferred {preferred[0].replace('_', ' ')} "
                        "caption style without changing wording or timing."
                    ),
                    expected_effect="Improve creator preference fit and readability review.",
                    risk="A preferred style may not fit this clip's information density.",
                    reason="Creator Learning contains an explicit caption preference.",
                )
            )
        baseline = self._baseline(
            experiment_id,
            source_artifact="caption_motion",
            source_field="recommendations[].caption_recommendation",
            summary=f"Current {current_style.replace('_', ' ')} caption plan.",
            instruction=current_instruction,
            strengths=[
                _text(caption.get("reason"), maximum=500),
                *[
                    _text(item, maximum=300)
                    for item in _list(caption.get("readability_notes"))
                ],
            ],
            weaknesses=[
                *(
                    ["Caption overload or readability risk is present."]
                    if overload
                    else []
                ),
                *approval_guidance["caption"],
            ],
            confidence=_number(recommendation.get("confidence"), 0.62),
        )
        return self._plan(
            experiment_id=experiment_id,
            project_id=project_id,
            context=context,
            experiment_type="caption_ab_test",
            title="Caption readability comparison",
            baseline=baseline,
            variants=variants[:2],
            improvement_area="caption_readability",
            hypothesis_statement=(
                "Changing only caption treatment may improve readability and creator "
                "preference without altering the edit."
            ),
            hypothesis_reason=(
                "Caption recommendations, safety review, and explicit creator preferences "
                "provide bounded alternatives."
            ),
            metric="caption_readability_review",
            secondary_metrics=["manual_creator_preference"],
            review_questions=[
                "Can every caption be read comfortably at phone size?",
                "Does emphasis support meaning without visual overload?",
            ],
            risk_review=self._risk_review(context, "caption_ab_test"),
            confidence=0.68 if overload else 0.62,
        )

    def _motion_plan(
        self,
        project_id: str,
        candidate_id: str,
        context: dict[str, Any],
        creator_preferences: dict[str, list[str]],
        approval_guidance: dict[str, list[str]],
    ) -> tuple[BobaExperimentPlanV1 | None, list[BobaRejectedExperimentIdeaV1]]:
        recommendation = _dict(context.get("caption"))
        motion = _dict(recommendation.get("motion_recommendation"))
        safety = _dict(recommendation.get("safety_review"))
        if not motion:
            return None, []
        experiment_id = _stable_id("experiment_motion", project_id, candidate_id)
        current_style = _text(motion.get("motion_style"), maximum=80) or "current"
        current_intensity = _text(
            motion.get("motion_intensity"),
            maximum=80,
        ) or "moderate"
        current = _text(motion.get("reason"), maximum=1000)
        if not current:
            current = (
                f"Use {current_style.replace('_', ' ')} motion at "
                f"{current_intensity.replace('_', ' ')} intensity."
            )
        safety_risk = any(
            _bool(safety.get(key))
            for key in (
                "face_cutoff_risk",
                "multi_speaker_layout_risk",
                "over_motion_risk",
                "hook_distraction_risk",
            )
        )
        explicit_zoom_rejection = any(
            "zoom" in item.casefold() or "motion" in item.casefold()
            for item in approval_guidance["motion"]
        )
        preferred = creator_preferences["preferred_motion_styles"]
        safer_instruction = (
            "Use stable framing and at most one evidence-backed restrained punch-in; "
            "do not add repeated zooms."
        )
        variants = [
            self._variant(
                experiment_id,
                label="B",
                variant_type="motion",
                summary="Stable restrained motion treatment.",
                changed_variable="motion_intensity",
                instruction=safer_instruction,
                expected_effect=(
                    "Improve manual motion-safety review while preserving captions, audio, "
                    "hook, and source timing."
                ),
                risk="Lower motion may feel less energetic if the source already lacks movement.",
                reason=(
                    "Safety evidence or creator feedback supports a stable comparison."
                    if safety_risk or explicit_zoom_rejection
                    else "A stable control tests whether the current motion adds value."
                ),
            )
        ]
        if preferred and "stable" in preferred[0].casefold():
            variants[0] = variants[0].model_copy(
                update={
                    "reason": (
                        "Creator Learning explicitly prefers a stable motion style."
                    )
                }
            )
        rejected: list[BobaRejectedExperimentIdeaV1] = []
        blockers = [_text(item, maximum=500) for item in _list(safety.get("blockers"))]
        if safety_risk or blockers:
            rejected.append(
                self._rejected(
                    target_id=context["brief_id"] or candidate_id,
                    experiment_type="motion_ab_test",
                    reason=(
                        "A stronger-motion variant was rejected because face, layout, "
                        "over-motion, or hook-distraction risk is unresolved."
                    ),
                    risk="; ".join(blockers)
                    or "Saved Caption + Motion safety flags require a restrained test.",
                )
            )
        else:
            variants.append(
                self._variant(
                    experiment_id,
                    label="C",
                    variant_type="motion",
                    summary="Single focused motion accent.",
                    changed_variable="motion_intensity",
                    instruction=(
                        "Add one restrained punch-in at the strongest supported hook or "
                        "payoff beat; keep every other frame stable."
                    ),
                    expected_effect="Test whether one controlled accent improves emphasis.",
                    risk="The accent may distract from speech or captions.",
                    reason="No saved motion-safety blocker prevents a restrained comparison.",
                )
            )
        baseline = self._baseline(
            experiment_id,
            source_artifact="caption_motion",
            source_field="recommendations[].motion_recommendation",
            summary=(
                f"Current {current_style.replace('_', ' ')} motion at "
                f"{current_intensity.replace('_', ' ')} intensity."
            ),
            instruction=current,
            strengths=[
                *[
                    _text(item, maximum=300)
                    for item in _list(motion.get("stable_moments"))
                ],
                _text(motion.get("payoff_emphasis_moment"), maximum=400),
            ],
            weaknesses=[
                *(
                    ["Saved motion safety risk requires review."]
                    if safety_risk
                    else []
                ),
                *approval_guidance["motion"],
            ],
            confidence=_number(recommendation.get("confidence"), 0.6),
        )
        return (
            self._plan(
                experiment_id=experiment_id,
                project_id=project_id,
                context=context,
                experiment_type="motion_ab_test",
                title="Motion safety comparison",
                baseline=baseline,
                variants=variants[:2],
                improvement_area="motion_safety",
                hypothesis_statement=(
                    "Changing only motion intensity may improve safety and emphasis without "
                    "changing narrative or audio treatment."
                ),
                hypothesis_reason=(
                    "Saved motion recommendations and safety flags define a bounded "
                    "stable-versus-accent comparison."
                ),
                metric="motion_safety_review",
                secondary_metrics=["manual_creator_preference"],
                review_questions=[
                    "Does the treatment keep faces and captions comfortably framed?",
                    "Does motion support rather than compete with the spoken idea?",
                ],
                risk_review=self._risk_review(context, "motion_ab_test"),
                confidence=0.7 if safety_risk else 0.62,
            ),
            rejected,
        )

    def _music_plan(
        self,
        project_id: str,
        candidate_id: str,
        context: dict[str, Any],
        creator_preferences: dict[str, list[str]],
        approval_guidance: dict[str, list[str]],
    ) -> tuple[BobaExperimentPlanV1 | None, list[BobaRejectedExperimentIdeaV1]]:
        recommendation = _dict(context.get("music"))
        mood = _dict(recommendation.get("music_mood"))
        risk = _dict(recommendation.get("audio_risk_review"))
        if not mood:
            return None, []
        experiment_id = _stable_id("experiment_music", project_id, candidate_id)
        primary = _text(mood.get("primary_mood"), maximum=80) or "neutral"
        secondary = _text(mood.get("secondary_mood"), maximum=80)
        preferred = creator_preferences["preferred_music_moods"]
        alternatives = [
            value
            for value in [*preferred[:1], secondary, "neutral"]
            if value and _normalized(value) != _normalized(primary)
        ]
        alternate = next(iter(dict.fromkeys(alternatives)), "")
        if not alternate:
            return None, []
        current = _text(mood.get("reason"), maximum=1000) or (
            f"Use {primary.replace('_', ' ')} mood at "
            f"{_text(mood.get('energy_level'), maximum=80) or 'restrained'} energy."
        )
        variants = [
            self._variant(
                experiment_id,
                label="B",
                variant_type="music_mood",
                summary=f"Alternate {alternate.replace('_', ' ')} mood direction.",
                changed_variable="music_mood",
                instruction=(
                    f"Change only the mood direction to {alternate.replace('_', ' ')}; "
                    "keep speech priority, SFX, timing, and all visual choices unchanged."
                ),
                expected_effect=(
                    "Improve manual audio-fit or emotional-fit review without selecting "
                    "a specific track."
                ),
                risk="The alternate mood may weaken emotional or pacing alignment.",
                reason=(
                    "Creator Learning supplies this preferred mood."
                    if alternate in preferred
                    else "The Music Mood Brain supplies a bounded alternate direction."
                ),
            )
        ]
        rights = _bool(risk.get("rights_review_required"))
        rejected: list[BobaRejectedExperimentIdeaV1] = []
        if rights:
            rejected.append(
                self._rejected(
                    target_id=context["brief_id"] or candidate_id,
                    experiment_type="music_mood_ab_test",
                    reason=(
                        "A track-level music experiment was rejected until rights review "
                        "is resolved."
                    ),
                    risk=(
                        _text(
                            _dict(recommendation.get("brief_enhancement")).get(
                                "rights_review_warning"
                            ),
                            maximum=700,
                        )
                        or "Saved audio risk review requires rights approval."
                    ),
                    warnings=["Mood-only planning remains advisory; no track was selected."],
                )
            )
        baseline = self._baseline(
            experiment_id,
            source_artifact="music_mood",
            source_field="recommendations[].music_mood",
            summary=f"Current {primary.replace('_', ' ')} mood direction.",
            instruction=current,
            strengths=[
                _text(mood.get("emotional_direction"), maximum=500),
                _text(mood.get("pacing_fit"), maximum=500),
            ],
            weaknesses=[
                *(
                    ["Saved audio review flags a wrong-mood risk."]
                    if _bool(risk.get("wrong_mood_risk"))
                    else []
                ),
                *approval_guidance["music"],
            ],
            confidence=_number(recommendation.get("confidence"), 0.6),
        )
        return (
            self._plan(
                experiment_id=experiment_id,
                project_id=project_id,
                context=context,
                experiment_type="music_mood_ab_test",
                title="Music mood direction comparison",
                baseline=baseline,
                variants=variants,
                improvement_area="audio_fit",
                hypothesis_statement=(
                    "Changing only mood direction may improve manual audio and emotional "
                    "fit while speech remains dominant."
                ),
                hypothesis_reason=(
                    "Saved mood recommendations and explicit creator preferences provide "
                    "a bounded mood-level alternative."
                ),
                metric="audio_fit_review",
                secondary_metrics=[
                    "manual_creator_preference",
                ],
                review_questions=[
                    "Which mood supports the spoken meaning without manipulating it?",
                    "Does speech remain fully clear in both directions?",
                ],
                risk_review=self._risk_review(context, "music_mood_ab_test"),
                confidence=0.66 if preferred else 0.58,
            ),
            rejected,
        )

    def _sfx_plan(
        self,
        project_id: str,
        candidate_id: str,
        context: dict[str, Any],
    ) -> BobaExperimentPlanV1 | None:
        recommendation = _dict(context.get("music"))
        sfx = _dict(recommendation.get("sfx_recommendation"))
        if not sfx:
            return None
        experiment_id = _stable_id("experiment_sfx", project_id, candidate_id)
        intensity = _text(sfx.get("sfx_intensity"), maximum=80) or "none"
        current = _text(sfx.get("reason"), maximum=1000)
        alternate = "none" if intensity != "none" else "subtle"
        variant = self._variant(
            experiment_id,
            label="B",
            variant_type="sfx",
            summary=f"Use {alternate} SFX intensity.",
            changed_variable="sfx_intensity",
            instruction=(
                f"Change only SFX intensity to {alternate}; keep music mood, speech, "
                "timing, captions, and motion unchanged."
            ),
            expected_effect="Improve speech-clarity and distraction review.",
            risk=(
                "Removing SFX may reduce emphasis."
                if alternate == "none"
                else "Even subtle SFX may distract from speech."
            ),
            reason="A restrained SFX control isolates whether sound accents add value.",
        )
        baseline = self._baseline(
            experiment_id,
            source_artifact="music_mood",
            source_field="recommendations[].sfx_recommendation",
            summary=f"Current {intensity.replace('_', ' ')} SFX direction.",
            instruction=current or f"Use {intensity.replace('_', ' ')} SFX intensity.",
            strengths=[
                _text(sfx.get("hook_sfx_guidance"), maximum=400),
                _text(sfx.get("payoff_sfx_guidance"), maximum=400),
            ],
            weaknesses=[
                *[
                    _text(item, maximum=300)
                    for item in _list(sfx.get("warnings"))
                ]
            ],
            confidence=_number(recommendation.get("confidence"), 0.58),
        )
        return self._plan(
            experiment_id=experiment_id,
            project_id=project_id,
            context=context,
            experiment_type="sfx_ab_test",
            title="SFX restraint comparison",
            baseline=baseline,
            variants=[variant],
            improvement_area="speech_clarity",
            hypothesis_statement=(
                "Changing only SFX intensity may improve speech clarity and reduce "
                "distraction."
            ),
            hypothesis_reason=(
                "The Music Mood Brain supplies bounded SFX intensity guidance."
            ),
            metric="audio_fit_review",
            secondary_metrics=["manual_creator_preference"],
            review_questions=[
                "Are all words equally clear?",
                "Does the SFX add useful emphasis rather than noise?",
            ],
            risk_review=self._risk_review(context, "sfx_ab_test"),
            confidence=0.62,
        )

    def _retention_plan(
        self,
        project_id: str,
        candidate_id: str,
        context: dict[str, Any],
    ) -> BobaExperimentPlanV1 | None:
        hook = _dict(context.get("hook"))
        retention = _dict(hook.get("retention_plan"))
        risks = _dict(hook.get("retention_risk_review"))
        if not retention:
            return None
        experiment_id = _stable_id("experiment_retention", project_id, candidate_id)
        if _bool(risks.get("weak_payoff_risk")):
            changed = "payoff_timing"
            baseline_instruction = _text(
                retention.get("payoff_timing_strategy"),
                maximum=1000,
            )
            variant_instruction = _text(
                _dict(hook.get("brief_enhancements")).get(
                    "enhanced_payoff_timing"
                ),
                maximum=1000,
            ) or "Move payoff emphasis to the supported reveal without changing source boundaries."
            area: BobaExperimentImprovementArea = "payoff_strength"
        elif _bool(risks.get("filler_risk")):
            changed = "middle_hold_strategy"
            baseline_instruction = _text(
                retention.get("middle_hold_strategy"),
                maximum=1000,
            )
            variant_instruction = (
                "Use one concise open-loop reminder in the middle and remove repeated "
                "retention prompts."
            )
            area = "retention"
        else:
            changed = "replay_trigger"
            baseline_instruction = _text(
                retention.get("ending_replay_trigger"),
                maximum=1000,
            )
            variant_instruction = _text(
                _dict(hook.get("brief_enhancements")).get(
                    "enhanced_replay_trigger"
                ),
                maximum=1000,
            ) or "End on a concise callback to the opening without adding a new claim."
            area = "retention"
        if not baseline_instruction:
            return None
        variant = self._variant(
            experiment_id,
            label="B",
            variant_type="retention",
            summary=f"Alternate {changed.replace('_', ' ')}.",
            changed_variable=changed,
            instruction=variant_instruction,
            expected_effect=(
                "Improve manual retention-quality review while all other creative "
                "variables remain fixed."
            ),
            risk="The alternate retention cue may feel forced or repetitive.",
            reason="Saved retention risks and enhancements support this isolated test.",
        )
        baseline = self._baseline(
            experiment_id,
            source_artifact="hook_retention",
            source_field=f"analyses[].retention_plan.{changed}",
            summary=f"Current {changed.replace('_', ' ')}.",
            instruction=baseline_instruction,
            strengths=[
                *[
                    _text(item, maximum=300)
                    for item in _list(retention.get("retention_tactics"))
                ]
            ],
            weaknesses=[
                *[
                    _text(item, maximum=300)
                    for item in _list(risks.get("warnings"))
                ],
                *[
                    key.replace("_", " ")
                    for key in (
                        "weak_payoff_risk",
                        "filler_risk",
                        "slow_start_risk",
                    )
                    if _bool(risks.get(key))
                ],
            ],
            confidence=_number(hook.get("confidence"), 0.6),
        )
        return self._plan(
            experiment_id=experiment_id,
            project_id=project_id,
            context=context,
            experiment_type="retention_ab_test",
            title="Retention treatment comparison",
            baseline=baseline,
            variants=[variant],
            improvement_area=area,
            hypothesis_statement=(
                f"Changing only {changed.replace('_', ' ')} may improve manual "
                "retention-quality review."
            ),
            hypothesis_reason=(
                "The Hook + Retention artifact identifies a bounded risk or enhancement."
            ),
            metric="retention_quality_review",
            secondary_metrics=[
                "manual_creator_preference",
                "future_viewer_retention",
            ],
            review_questions=[
                "Does the variant preserve clarity and payoff?",
                "Would the retention cue feel natural to a human editor?",
            ],
            risk_review=self._risk_review(context, "retention_ab_test"),
            confidence=0.66,
        )

    def _opening_plan(
        self,
        project_id: str,
        candidate_id: str,
        context: dict[str, Any],
    ) -> BobaExperimentPlanV1 | None:
        brief = _dict(context.get("brief"))
        hook = _dict(context.get("hook"))
        risks = _dict(hook.get("retention_risk_review"))
        instruction = _dict(brief.get("opening_three_second_instruction"))
        if not instruction or not _bool(risks.get("slow_start_risk")):
            return None
        experiment_id = _stable_id("experiment_opening", project_id, candidate_id)
        current = _text(
            instruction.get("do_this") or instruction.get("summary"),
            maximum=1000,
        )
        if not current:
            return None
        variant = self._variant(
            experiment_id,
            label="B",
            variant_type="opening",
            summary="Faster first-three-second opening.",
            changed_variable="opening_three_seconds",
            instruction=(
                "Begin on the first supported meaningful hook words and remove only "
                "confirmed dead air; preserve all later timing."
            ),
            expected_effect="Improve opening clarity and manual hook review.",
            risk="Over-tightening may remove context needed for understanding.",
            reason="Saved retention review identifies slow-start risk.",
        )
        baseline = self._baseline(
            experiment_id,
            source_artifact="clip_briefs",
            source_field="selected_briefs[].opening_three_second_instruction",
            summary="Current opening-three-second instruction.",
            instruction=current,
            strengths=[_text(instruction.get("reason"), maximum=500)],
            weaknesses=["Saved retention review flags a slow-start risk."],
            confidence=_number(brief.get("confidence"), 0.58),
        )
        return self._plan(
            experiment_id=experiment_id,
            project_id=project_id,
            context=context,
            experiment_type="opening_ab_test",
            title="Opening three-second comparison",
            baseline=baseline,
            variants=[variant],
            improvement_area="hook_strength",
            hypothesis_statement=(
                "Changing only the first-three-second start may improve manual hook "
                "clarity without altering the selected story."
            ),
            hypothesis_reason="The retention review identifies a slow-start risk.",
            metric="hook_quality_review",
            secondary_metrics=["manual_creator_preference"],
            review_questions=[
                "Does the faster opening remain understandable?",
                "Is the first meaningful promise supported by the clip?",
            ],
            risk_review=self._risk_review(context, "opening_ab_test"),
            confidence=0.68,
        )

    def _brief_plan(
        self,
        project_id: str,
        candidate_id: str,
        context: dict[str, Any],
    ) -> BobaExperimentPlanV1 | None:
        brief = _dict(context.get("brief"))
        if not brief:
            return None
        risk_fixes = [
            _text(item, maximum=400) for item in _list(brief.get("risk_fixes"))
        ]
        warnings = [
            _text(item, maximum=400) for item in _list(brief.get("warnings"))
        ]
        if not risk_fixes and not warnings:
            return None
        experiment_id = _stable_id("experiment_brief", project_id, candidate_id)
        current = _text(
            brief.get("final_clip_angle") or brief.get("brief_title"),
            maximum=1000,
        )
        if not current:
            return None
        variant_instruction = (
            "Keep the same clip angle but rewrite the editor packet so each instruction "
            "names one action, one avoid condition, and one evidence-backed reason."
        )
        variant = self._variant(
            experiment_id,
            label="B",
            variant_type="brief",
            summary="Clarified editor instruction packet.",
            changed_variable="brief_instruction_clarity",
            instruction=variant_instruction,
            expected_effect="Improve manual instruction-clarity review.",
            risk="Additional specificity may make the brief less flexible.",
            reason="Saved risk fixes or warnings indicate the brief needs human review.",
        )
        baseline = self._baseline(
            experiment_id,
            source_artifact="clip_briefs",
            source_field="selected_briefs[].final_clip_angle",
            summary="Current clip-brief direction.",
            instruction=current,
            strengths=[_text(brief.get("target_viewer_feeling"), maximum=300)],
            weaknesses=[*risk_fixes, *warnings],
            confidence=_number(brief.get("confidence"), 0.58),
        )
        return self._plan(
            experiment_id=experiment_id,
            project_id=project_id,
            context=context,
            experiment_type="brief_ab_test",
            title="Clip brief clarity comparison",
            baseline=baseline,
            variants=[variant],
            improvement_area="clarity",
            hypothesis_statement=(
                "Changing only instruction clarity may improve manual editor-readiness "
                "without changing the creative direction."
            ),
            hypothesis_reason="The saved brief includes risk fixes or warnings.",
            metric="manual_creator_preference",
            secondary_metrics=[],
            review_questions=[
                "Can an editor execute every instruction without guessing?",
                "Does the clarified brief preserve creative flexibility?",
            ],
            risk_review=self._risk_review(context, "brief_ab_test"),
            confidence=0.58,
        )

    def _plan(
        self,
        *,
        experiment_id: str,
        project_id: str,
        context: dict[str, Any],
        experiment_type: BobaExperimentType,
        title: str,
        baseline: BobaExperimentBaselineV1,
        variants: list[BobaExperimentVariantV1],
        improvement_area: BobaExperimentImprovementArea,
        hypothesis_statement: str,
        hypothesis_reason: str,
        metric: BobaExperimentPrimaryMetric,
        secondary_metrics: list[BobaExperimentPrimaryMetric],
        review_questions: list[str],
        risk_review: BobaExperimentRiskReviewV1,
        confidence: float,
    ) -> BobaExperimentPlanV1:
        analytics_later = bool(
            {metric, *secondary_metrics} & _FUTURE_METRICS
        )
        warnings = [
            "Plan only: this experiment was not rendered, uploaded, or started.",
        ]
        if risk_review.blockers:
            warnings.append(
                "Risk blockers require review before creator approval can activate the plan."
            )
        return BobaExperimentPlanV1(
            experiment_id=experiment_id,
            project_id=project_id,
            target_type="clip_brief" if context.get("brief_id") else "candidate",
            target_id=context.get("brief_id") or context["candidate_id"],
            candidate_id=context["candidate_id"],
            brief_id=context.get("brief_id") or "",
            experiment_type=experiment_type,
            title=title,
            baseline=baseline,
            variants=variants,
            hypothesis=BobaExperimentHypothesisV1(
                hypothesis_id=_stable_id("experiment_hypothesis", experiment_id),
                statement=hypothesis_statement,
                reason=hypothesis_reason,
                expected_improvement_area=improvement_area,
                confidence=_confidence(confidence - 0.06),
                assumptions=[
                    "Only the declared changed variable differs from the baseline.",
                    "A creator will review both baseline and variant under comparable conditions.",
                    "No audience outcome is assumed before a future consented test.",
                ],
            ),
            metric_plan=BobaExperimentMetricPlanV1(
                primary_metric=metric,
                secondary_metrics=secondary_metrics,
                manual_review_questions=review_questions,
                required_result_fields=[
                    "experiment_id",
                    "selected_variant_id",
                    "manual_rating",
                    "outcome_label",
                    "should_feed_learning",
                ],
                analytics_required_later=analytics_later,
                notes=[
                    "V1 records manual creator review only.",
                    *(
                        [
                            "Future viewer metrics are descriptive handoff fields; "
                            "V1 does not collect them."
                        ]
                        if analytics_later
                        else []
                    ),
                ],
            ),
            success_criteria=BobaExperimentSuccessCriteriaV1(
                success_definition=(
                    "A variant succeeds only when the creator explicitly prefers it, "
                    "rates it at or above the threshold, and no risk blocker remains."
                ),
                minimum_manual_rating=3.5,
                approval_required=True,
                failure_conditions=[
                    "Creator prefers the baseline.",
                    "Manual rating is below 3.5.",
                    "The variant creates a new clarity, rights, safety, or speech risk.",
                    "No clear winner is found.",
                ],
                decision_rule=(
                    "Record the outcome manually; never apply a winner automatically. "
                    "A reviewed result may be handed to learning only when explicitly chosen."
                ),
            ),
            risk_review=risk_review,
            learning_handoff=BobaExperimentLearningHandoffV1(
                consume_result_in_modules=[
                    "creator_learning",
                    "approval_rejection_learning",
                    "future_performance_feedback",
                ],
                feedback_to_collect=[
                    "selected variant or baseline",
                    "manual creator rating",
                    "explicit creator note",
                    "outcome label",
                    "explicit learning handoff choice",
                ],
                expected_learning_update=(
                    "A reviewed manual outcome can become an explicit preference or "
                    "approval/rejection case in a future handoff."
                ),
                approval_rejection_learning_target=experiment_id,
                creator_learning_target=context.get("brief_id")
                or context["candidate_id"],
            ),
            required_creator_approval=True,
            status="needs_creator_approval",
            confidence=_confidence(
                confidence
                - (0.08 if risk_review.blockers else 0.0)
                - (0.04 if risk_review.warnings else 0.0)
            ),
            warnings=warnings,
            limitations=[
                "No experiment media was produced.",
                "No viewer analytics or outcome data was observed.",
            ],
        )

    @staticmethod
    def _baseline(
        experiment_id: str,
        *,
        source_artifact: str,
        source_field: str,
        summary: str,
        instruction: str,
        strengths: Sequence[str],
        weaknesses: Sequence[str],
        confidence: float,
    ) -> BobaExperimentBaselineV1:
        return BobaExperimentBaselineV1(
            baseline_id=_stable_id("experiment_baseline", experiment_id),
            source_artifact=source_artifact,
            source_field=source_field,
            summary=_text(summary, maximum=600),
            current_instruction=_text(instruction, maximum=1000),
            strengths=_unique(
                [_text(item, maximum=500) for item in strengths],
                maximum=16,
            ),
            weaknesses=_unique(
                [_text(item, maximum=500) for item in weaknesses],
                maximum=16,
            ),
            confidence=_confidence(confidence),
        )

    @staticmethod
    def _variant(
        experiment_id: str,
        *,
        label: str,
        variant_type: BobaExperimentVariantType,
        summary: str,
        changed_variable: str,
        instruction: str,
        expected_effect: str,
        risk: str,
        reason: str,
    ) -> BobaExperimentVariantV1:
        return BobaExperimentVariantV1(
            variant_id=_stable_id(
                "experiment_variant",
                experiment_id,
                label,
                changed_variable,
            ),
            label=f"Variant {label}",
            variant_type=variant_type,
            summary=_text(summary, maximum=500),
            changed_variable=_text(changed_variable, maximum=120),
            instruction=_text(instruction, maximum=1000),
            expected_effect=_text(expected_effect, maximum=700),
            risk=_text(risk, maximum=700),
            should_test=True,
            reason=_text(reason, maximum=700),
        )

    @staticmethod
    def _rejected(
        *,
        target_id: str,
        experiment_type: BobaExperimentType,
        reason: str,
        risk: str,
        warnings: Sequence[str] = (),
    ) -> BobaRejectedExperimentIdeaV1:
        return BobaRejectedExperimentIdeaV1(
            idea_id=_stable_id(
                "rejected_experiment",
                target_id,
                experiment_type,
                reason,
            ),
            target_id=_text(target_id, maximum=180),
            experiment_type=experiment_type,
            reason_rejected=_text(reason, maximum=700),
            risk=_text(risk, maximum=700),
            warnings=_unique(
                [_text(item, maximum=500) for item in warnings],
                maximum=24,
            ),
        )

    def _risk_review(
        self,
        context: dict[str, Any],
        experiment_type: BobaExperimentType,
    ) -> BobaExperimentRiskReviewV1:
        hook = _dict(context.get("hook"))
        hook_analysis = _dict(hook.get("hook_analysis"))
        retention = _dict(hook.get("retention_risk_review"))
        caption = _dict(context.get("caption"))
        caption_safety = _dict(caption.get("safety_review"))
        music = _dict(context.get("music"))
        audio = _dict(music.get("audio_risk_review"))
        editorial = _dict(context.get("editorial"))
        editorial_risk = _dict(editorial.get("risk_review"))
        explanation = _dict(context.get("explanation"))

        rights = _bool(audio.get("rights_review_required")) or _contains_any(
            [
                *_list(editorial_risk.get("warnings")),
                *_list(editorial_risk.get("blockers")),
            ],
            _RIGHTS_TERMS,
        )
        misleading = _contains_any(
            [
                hook_analysis.get("hook_risk"),
                *_list(retention.get("warnings")),
            ],
            _MISLEADING_TERMS,
        )
        motion_safety = any(
            _bool(caption_safety.get(key))
            for key in (
                "face_cutoff_risk",
                "multi_speaker_layout_risk",
                "unavailable_face_signal_risk",
                "unavailable_layout_signal_risk",
                "over_motion_risk",
            )
        )
        warnings = [
            *[_text(item, maximum=500) for item in _list(retention.get("warnings"))],
            *[
                _text(item, maximum=500)
                for item in _list(caption_safety.get("warnings"))
            ],
            *[_text(item, maximum=500) for item in _list(audio.get("warnings"))],
            *[_text(item, maximum=500) for item in _list(editorial_risk.get("warnings"))],
            *[_text(item, maximum=500) for item in _list(explanation.get("warnings"))],
        ]
        blockers = [
            *[_text(item, maximum=500) for item in _list(retention.get("blockers"))],
            *[
                _text(item, maximum=500)
                for item in _list(caption_safety.get("blockers"))
            ],
            *[_text(item, maximum=500) for item in _list(audio.get("blockers"))],
            *[_text(item, maximum=500) for item in _list(editorial_risk.get("blockers"))],
        ]
        if rights and experiment_type in {"music_mood_ab_test", "sfx_ab_test"}:
            blockers.append("Rights review is required before any audio asset is used.")
        if misleading and experiment_type in {"hook_ab_test", "opening_ab_test"}:
            blockers.append("Misleading-hook risk requires human review.")
        if motion_safety and experiment_type == "motion_ab_test":
            blockers.append("Motion safety must be reviewed before testing.")
        return BobaExperimentRiskReviewV1(
            rights_risk=rights,
            clarity_risk=(
                _bool(retention.get("unclear_context_risk"))
                or _bool(caption_safety.get("readability_risk"))
                or bool(_list(explanation.get("warnings")))
            ),
            over_editing_risk=(
                _bool(retention.get("over_editing_risk"))
                or _bool(caption_safety.get("over_motion_risk"))
            ),
            under_editing_risk=_bool(retention.get("under_editing_risk")),
            misleading_hook_risk=misleading,
            caption_overload_risk=(
                _bool(retention.get("caption_overload_risk"))
                or _bool(caption_safety.get("caption_overload_risk"))
            ),
            motion_safety_risk=motion_safety,
            audio_mismatch_risk=(
                _bool(audio.get("wrong_mood_risk"))
                or _bool(audio.get("emotional_mismatch_risk"))
            ),
            speech_clarity_risk=(
                _bool(audio.get("speech_clarity_risk"))
                or _bool(
                    _dict(music.get("speech_clarity_plan")).get("clarity_risk")
                )
            ),
            warnings=_unique(warnings, maximum=32),
            blockers=_unique(blockers, maximum=24),
        )

    @staticmethod
    def _creator_preferences(
        creator_learning: Mapping[str, Any],
    ) -> dict[str, list[str]]:
        profile = _dict(creator_learning.get("learning_profile"))
        return {
            "preferred_hook_styles": [
                _text(item, maximum=120)
                for item in _list(profile.get("preferred_hook_styles"))
            ],
            "preferred_caption_styles": [
                _text(item, maximum=120)
                for item in _list(profile.get("preferred_caption_styles"))
            ],
            "preferred_motion_styles": [
                _text(item, maximum=120)
                for item in _list(profile.get("preferred_motion_styles"))
            ],
            "preferred_music_moods": [
                _text(item, maximum=120)
                for item in _list(profile.get("preferred_music_moods"))
            ],
        }

    @staticmethod
    def _approval_guidance(
        learning: Mapping[str, Any],
    ) -> dict[str, list[str]]:
        guidance = _dict(learning.get("module_guidance"))
        patterns = [_dict(item) for item in _list(learning.get("pattern_scores"))]

        def matching(category: str, field: str) -> list[str]:
            return _unique(
                [
                    *[
                        _text(item, maximum=500)
                        for item in _list(guidance.get(field))
                    ],
                    *[
                        _text(pattern.get("guidance"), maximum=500)
                        for pattern in patterns
                        if _text(pattern.get("category"), maximum=80) == category
                    ],
                ],
                maximum=8,
            )

        return {
            "hook": matching("hook", "hook_retention_guidance"),
            "caption": matching("caption", "caption_motion_guidance"),
            "motion": matching("motion", "caption_motion_guidance"),
            "music": matching("music_mood", "music_mood_guidance"),
        }

    @staticmethod
    def _approval_requirements(
        plan: BobaExperimentPlanV1,
    ) -> list[BobaExperimentApprovalRequirementV1]:
        requirements = [
            BobaExperimentApprovalRequirementV1(
                requirement_id=_stable_id(
                    "experiment_approval",
                    plan.experiment_id,
                    "creator",
                ),
                experiment_id=plan.experiment_id,
                approval_type="creator_approval",
                reason=(
                    "The creator must explicitly approve the plan before it can be "
                    "treated as active."
                ),
                required_before_status="approved",
            )
        ]
        if plan.risk_review.rights_risk:
            requirements.append(
                BobaExperimentApprovalRequirementV1(
                    requirement_id=_stable_id(
                        "experiment_approval",
                        plan.experiment_id,
                        "rights",
                    ),
                    experiment_id=plan.experiment_id,
                    approval_type="rights_review",
                    reason="Any asset used later must pass rights and license review.",
                    required_before_status="approved",
                )
            )
        if plan.risk_review.motion_safety_risk:
            requirements.append(
                BobaExperimentApprovalRequirementV1(
                    requirement_id=_stable_id(
                        "experiment_approval",
                        plan.experiment_id,
                        "safety",
                    ),
                    experiment_id=plan.experiment_id,
                    approval_type="safety_review",
                    reason="Motion and layout safety blockers require explicit review.",
                    required_before_status="approved",
                )
            )
        if plan.risk_review.blockers or plan.confidence < 0.55:
            requirements.append(
                BobaExperimentApprovalRequirementV1(
                    requirement_id=_stable_id(
                        "experiment_approval",
                        plan.experiment_id,
                        "human",
                    ),
                    experiment_id=plan.experiment_id,
                    approval_type="human_review",
                    reason=(
                        "Risk blockers or low confidence require a human editorial review."
                    ),
                    required_before_status="approved",
                    warnings=plan.risk_review.blockers[:8],
                )
            )
        return requirements

    @staticmethod
    def _signal_usage(
        artifacts: Mapping[str, dict[str, Any]],
    ) -> BobaExperimentationSignalUsageV1:
        keys = (
            "clip_briefs",
            "hook_retention",
            "caption_motion",
            "music_mood",
            "creative_direction",
            "editorial_decision",
            "explanation",
            "creator_learning",
            "approval_rejection_learning",
            "memory",
        )
        availability = {key: bool(artifacts[key]) for key in keys}
        unavailable = [
            key for key in keys if not availability[key]
        ]
        required_missing = [
            key
            for key in ("clip_briefs", "hook_retention")
            if not availability[key]
        ]
        warnings = (
            [
                "Required planning evidence is incomplete; only supported fallback "
                "experiments were generated."
            ]
            if required_missing
            else []
        )
        return BobaExperimentationSignalUsageV1(
            clip_briefs_used=availability["clip_briefs"],
            hook_retention_used=availability["hook_retention"],
            caption_motion_used=availability["caption_motion"],
            music_mood_used=availability["music_mood"],
            creative_direction_used=availability["creative_direction"],
            editorial_decision_used=availability["editorial_decision"],
            explanation_used=availability["explanation"],
            creator_learning_used=availability["creator_learning"],
            approval_rejection_learning_used=availability[
                "approval_rejection_learning"
            ],
            memory_used=availability["memory"],
            fallback_used=bool(unavailable),
            unavailable_signals=unavailable,
            warnings=warnings,
        )

    @staticmethod
    def _summary(
        plans: Sequence[BobaExperimentPlanV1],
        rejected: Sequence[BobaRejectedExperimentIdeaV1],
    ) -> str:
        if not plans:
            return (
                "No safe evidence-backed experiments were generated. Unsupported or "
                "unsafe ideas remain rejected for human review."
            )
        strongest = sorted(
            plans,
            key=lambda plan: plan.confidence,
            reverse=True,
        )[:3]
        riskiest = [
            plan
            for plan in plans
            if plan.risk_review.blockers
            or any(
                (
                    plan.risk_review.rights_risk,
                    plan.risk_review.misleading_hook_risk,
                    plan.risk_review.motion_safety_risk,
                    plan.risk_review.speech_clarity_risk,
                )
            )
        ]
        rights_review_count = sum(
            plan.risk_review.rights_risk for plan in plans
        )
        human_review_count = sum(
            bool(plan.risk_review.blockers) or plan.confidence < 0.55
            for plan in plans
        )
        return _text(
            (
                f"Generated {len(plans)} advisory experiment plan(s); "
                f"{len(rejected)} unsafe or unsupported idea(s) were rejected. "
                "Strongest manual-first plans: "
                + ", ".join(item.title for item in strongest)
                + ". "
                + (
                    f"{len(riskiest)} plan(s) require elevated rights, safety, or "
                    "human review. Riskiest plans: "
                    + ", ".join(item.title for item in riskiest[:3])
                    + ". "
                    if riskiest
                    else "No elevated risk plan was identified. "
                )
                + f"Rights review: {rights_review_count} plan(s); "
                + f"human review: {human_review_count} plan(s). "
                + "Every plan remains inactive until creator approval."
            ),
            maximum=1800,
        )

    @staticmethod
    def _deduplicate_rejections(
        rejected: Sequence[BobaRejectedExperimentIdeaV1],
    ) -> list[BobaRejectedExperimentIdeaV1]:
        result: dict[str, BobaRejectedExperimentIdeaV1] = {}
        for item in rejected:
            result.setdefault(item.idea_id, item)
        return list(result.values())
