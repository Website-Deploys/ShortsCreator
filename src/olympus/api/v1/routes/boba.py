"""Inspection-only API routes for BOBA Core Brain V1."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from olympus.api.dependencies import (
    BobaIntegrationDep,
    PersonalizationServiceDep,
    SettingsDep,
)
from olympus.boba.approvals import BobaApprovalDecision
from olympus.boba.creator_learning import (
    BobaCreatorFeedbackEventType,
    BobaCreatorFeedbackTargetType,
    BobaCreatorUserAction,
)
from olympus.boba.creator_memory import build_and_save_creator_memory
from olympus.boba.experimentation import BobaExperimentOutcomeLabel
from olympus.boba.global_memory import build_and_save_global_memory
from olympus.boba.memory_contracts import BobaMemoryQueryV1
from olympus.boba.memory_learning import BobaMemoryLearner
from olympus.boba.performance_feedback import (
    BobaManualPerformanceMetricsV1,
    BobaPerformanceEventType,
    BobaPerformanceOutcomeLabel,
    BobaPerformanceTargetType,
)
from olympus.boba.scout import BobaCandidateV1
from olympus.platform.errors import NotFoundError, ValidationError

router = APIRouter(prefix="/boba", tags=["boba"])


class EditorialPolicyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clip_id: str = Field(min_length=1, max_length=128)


class MemoryFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str = Field(min_length=1, max_length=80)
    project_id: str = Field(min_length=1, max_length=128)
    clip_id: str = Field(min_length=1, max_length=128)
    rating: dict[str, Any] | str = "neutral"
    labels: list[str] = Field(default_factory=list, max_length=24)
    notes: str = Field(default="", max_length=500)
    clip_traits: dict[str, Any] = Field(default_factory=dict)


class MemoryImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm: bool = False
    payload: dict[str, Any]


class MemoryResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm: bool = False
    scope: Literal["project", "creator", "global"]
    identifier: str | None = Field(default=None, max_length=128)


class CreatorLearningEventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: BobaCreatorFeedbackEventType
    target_type: BobaCreatorFeedbackTargetType
    target_id: str = Field(
        min_length=1,
        max_length=180,
        pattern=r"^[A-Za-z0-9_.:-]+$",
    )
    user_action: BobaCreatorUserAction
    rating: float | None = Field(default=None, ge=0.0, le=5.0)
    note: str = Field(default="", max_length=500)
    tags: list[str] = Field(default_factory=list, max_length=24)
    reversible: bool = True


class CreatorLearningGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    creator_id: str = Field(
        default="local_creator",
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    dry_run: bool = False


class ApprovalRejectionLearningGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    creator_id: str = Field(
        default="local_creator",
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    dry_run: bool = False


class ExperimentationGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    creator_id: str = Field(
        default="local_creator",
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    dry_run: bool = False


class ExperimentManualResultRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    experiment_id: str = Field(min_length=1, max_length=128)
    selected_variant_id: str = Field(min_length=1, max_length=128)
    manual_rating: float = Field(ge=0.0, le=5.0)
    creator_note: str = Field(default="", max_length=500)
    outcome_label: BobaExperimentOutcomeLabel
    should_feed_learning: bool = False


class PerformanceFeedbackEventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: BobaPerformanceEventType
    target_type: BobaPerformanceTargetType
    target_id: str = Field(min_length=1, max_length=180)
    candidate_id: str = Field(default="", max_length=128)
    brief_id: str = Field(default="", max_length=160)
    experiment_id: str = Field(default="", max_length=128)
    variant_id: str = Field(default="", max_length=128)
    manual_rating: float | None = Field(default=None, ge=0.0, le=5.0)
    creator_note: str = Field(default="", max_length=500)
    platform: str = Field(default="", max_length=80)
    source_label: str = Field(default="manual_entry", min_length=1, max_length=120)
    metrics: BobaManualPerformanceMetricsV1 = Field(
        default_factory=BobaManualPerformanceMetricsV1
    )
    retention_notes: str = Field(default="", max_length=500)
    creator_interpretation: str = Field(default="", max_length=500)
    outcome_label: BobaPerformanceOutcomeLabel | None = None
    baseline_id: str = Field(default="", max_length=128)
    selected_variant_id: str = Field(default="", max_length=128)
    should_feed_learning: bool = False


class PerformanceFeedbackGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dry_run: bool = False


class ContentScoutGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manual_items: list[dict[str, Any]] = Field(default_factory=list, max_length=500)
    import_paths: list[str] = Field(default_factory=list, max_length=20)
    source_label: str = Field(default="manual", min_length=1, max_length=160)
    dry_run: bool = False


class ScoutScoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    creator_profile_id: str | None = Field(default=None, max_length=80)


class CandidateDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(default="", max_length=500)
    creator_profile_id: str | None = Field(default=None, max_length=80)
    approve_for_processing: bool = False


class CreativeBriefDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(default="", max_length=500)
    creator_profile_id: str | None = Field(default=None, max_length=80)


def _require_enabled(settings: SettingsDep) -> None:
    if not settings.boba.enabled:
        raise ValidationError("BOBA Core Brain is disabled by configuration.")


def _require_memory_enabled(settings: SettingsDep) -> None:
    _require_enabled(settings)
    if not settings.boba_memory.enabled:
        raise ValidationError("BOBA Memory is disabled by configuration.")


async def _require_project(project_id: str, boba: BobaIntegrationDep) -> None:
    if await boba.projects.get(project_id) is None:
        raise NotFoundError("Project was not found.", details={"id": project_id})


@router.post("/candidates")
def create_candidate(
    body: BobaCandidateV1,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    return boba.scout.create_candidate(body).model_dump(mode="json")


@router.get("/candidates")
def list_candidates(
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    candidates = boba.scout.list_candidates()
    return {
        "count": len(candidates),
        "candidates": [item.model_dump(mode="json") for item in candidates],
        "scores": {
            item.candidate_id: score.model_dump(mode="json")
            for item in candidates
            if (score := boba.store.load_scout_score(item.candidate_id)) is not None
        },
        "metadata_only": True,
        "external_calls_made": False,
    }


@router.post("/candidates/{candidate_id}/score")
def score_candidate(
    candidate_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
    body: ScoutScoreRequest | None = None,
) -> dict[str, Any]:
    _require_enabled(settings)
    return boba.scout.score_candidate(
        candidate_id,
        creator_profile_id=body.creator_profile_id if body else None,
    ).model_dump(mode="json")


def _candidate_decision(
    candidate_id: str,
    decision: BobaApprovalDecision,
    body: CandidateDecisionRequest,
    boba: BobaIntegrationDep,
) -> dict[str, Any]:
    event, candidate, lesson = boba.approvals.decide_candidate(
        candidate_id,
        decision=decision,
        reason=body.reason,
        approve_for_processing=body.approve_for_processing,
        creator_profile_id=body.creator_profile_id,
    )
    return {
        "candidate": candidate.model_dump(mode="json"),
        "approval": event.model_dump(mode="json"),
        "memory_lesson_id": lesson.memory_id,
        "processing_triggered": False,
    }


@router.post("/candidates/{candidate_id}/approve")
def approve_candidate(
    candidate_id: str,
    body: CandidateDecisionRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_memory_enabled(settings)
    return _candidate_decision(candidate_id, "approved", body, boba)


@router.post("/candidates/{candidate_id}/reject")
def reject_candidate(
    candidate_id: str,
    body: CandidateDecisionRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_memory_enabled(settings)
    return _candidate_decision(candidate_id, "rejected", body, boba)


@router.post("/projects/{project_id}/creative-briefs")
async def create_creative_briefs(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    briefs = await boba.generate_creative_briefs(project_id)
    return {
        "project_id": project_id,
        "count": len(briefs),
        "briefs": [item.model_dump(mode="json") for item in briefs],
        "rendering_triggered": False,
    }


@router.get("/projects/{project_id}/creative-briefs")
async def get_creative_briefs(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    briefs = boba.creative_director.list_briefs(project_id)
    return {
        "project_id": project_id,
        "count": len(briefs),
        "briefs": [item.model_dump(mode="json") for item in briefs],
    }


@router.post("/projects/{project_id}/whole-video-understanding")
async def create_whole_video_understanding(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    understanding = await boba.generate_whole_video_understanding(project_id)
    return understanding.model_dump(mode="json")


@router.get("/projects/{project_id}/whole-video-understanding")
async def get_whole_video_understanding(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    understanding = boba.store.load_whole_video_understanding(project_id)
    if understanding is None:
        raise NotFoundError(
            "BOBA whole-video understanding is not available.",
            details={"project_id": project_id},
        )
    return understanding.model_dump(mode="json")


@router.post("/projects/{project_id}/candidate-clips/discover")
async def discover_candidate_clips(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    discovery = await boba.discover_candidate_clips(project_id)
    return discovery.model_dump(mode="json")


@router.get("/projects/{project_id}/candidate-clips")
async def get_candidate_clips(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    discovery = boba.store.load_candidate_clip_discovery(project_id)
    if discovery is None:
        raise NotFoundError(
            "BOBA candidate clip discovery is not available.",
            details={"project_id": project_id},
        )
    return discovery.model_dump(mode="json")


@router.post("/projects/{project_id}/clip-ranking/rank")
async def rank_discovered_candidate_clips(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    if not settings.boba.enable_candidate_ranking:
        raise ValidationError("BOBA candidate ranking is disabled by configuration.")
    await _require_project(project_id, boba)
    ranking = await boba.rank_discovered_candidate_clips(project_id)
    return ranking.model_dump(mode="json")


@router.get("/projects/{project_id}/clip-ranking")
async def get_clip_ranking(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    ranking = boba.store.load_clip_ranking(project_id)
    if ranking is None:
        raise NotFoundError(
            "BOBA clip ranking is not available.",
            details={"project_id": project_id},
        )
    return ranking.model_dump(mode="json")


@router.post("/projects/{project_id}/editorial-decisions")
async def create_editorial_decisions(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    if not settings.boba.enable_editorial_policy:
        raise ValidationError("BOBA editorial decisions are disabled by configuration.")
    await _require_project(project_id, boba)
    decisions = await boba.generate_editorial_decisions(project_id)
    return decisions.model_dump(mode="json")


@router.get("/projects/{project_id}/editorial-decisions")
async def get_editorial_decisions(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    decisions = boba.store.load_editorial_decisions(project_id)
    if decisions is None:
        raise NotFoundError(
            "BOBA editorial decisions are not available.",
            details={"project_id": project_id},
        )
    return decisions.model_dump(mode="json")


@router.post("/projects/{project_id}/explanations")
async def create_explanations(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    explanations = await boba.generate_explanations(project_id)
    return explanations.model_dump(mode="json")


@router.get("/projects/{project_id}/explanations")
async def get_explanations(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    explanations = boba.store.load_explanations(project_id)
    if explanations is None:
        raise NotFoundError(
            "BOBA explanations are not available.",
            details={"project_id": project_id},
        )
    return explanations.model_dump(mode="json")


@router.post("/projects/{project_id}/creative-direction-v2")
async def create_creative_direction_v2(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    direction = await boba.generate_creative_direction_v2(project_id)
    return direction.model_dump(mode="json")


@router.get("/projects/{project_id}/creative-direction-v2")
async def get_creative_direction_v2(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    direction = boba.store.load_creative_direction_v2(project_id)
    if direction is None:
        raise NotFoundError(
            "BOBA Creative Director V2 direction is not available.",
            details={"project_id": project_id},
        )
    return direction.model_dump(mode="json")


@router.post("/projects/{project_id}/clip-briefs")
async def create_clip_briefs(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    briefs = await boba.generate_clip_briefs(project_id)
    return briefs.model_dump(mode="json")


@router.get("/projects/{project_id}/clip-briefs")
async def get_clip_briefs(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    briefs = boba.store.load_clip_briefs(project_id)
    if briefs is None:
        raise NotFoundError(
            "BOBA clip briefs are not available.",
            details={"project_id": project_id},
        )
    return briefs.model_dump(mode="json")


@router.post("/projects/{project_id}/hook-retention")
async def create_hook_retention(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    analysis = await boba.generate_hook_retention(project_id)
    return analysis.model_dump(mode="json")


@router.get("/projects/{project_id}/hook-retention")
async def get_hook_retention(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    analysis = boba.store.load_hook_retention(project_id)
    if analysis is None:
        raise NotFoundError(
            "BOBA hook and retention analysis is not available.",
            details={"project_id": project_id},
        )
    return analysis.model_dump(mode="json")


@router.post("/projects/{project_id}/caption-motion")
async def create_caption_motion(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    recommendations = await boba.generate_caption_motion(project_id)
    return recommendations.model_dump(mode="json")


@router.get("/projects/{project_id}/caption-motion")
async def get_caption_motion(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    recommendations = boba.store.load_caption_motion(project_id)
    if recommendations is None:
        raise NotFoundError(
            "BOBA caption and motion recommendations are not available.",
            details={"project_id": project_id},
        )
    return recommendations.model_dump(mode="json")


@router.post("/projects/{project_id}/music-mood")
async def create_music_mood(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    recommendations = await boba.generate_music_mood(project_id)
    return recommendations.model_dump(mode="json")


@router.get("/projects/{project_id}/music-mood")
async def get_music_mood(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    recommendations = boba.store.load_music_mood(project_id)
    if recommendations is None:
        raise NotFoundError(
            "BOBA music mood recommendations are not available.",
            details={"project_id": project_id},
        )
    return recommendations.model_dump(mode="json")


@router.post("/projects/{project_id}/experimentation")
async def create_experimentation(
    project_id: str,
    body: ExperimentationGenerateRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    experimentation = await boba.generate_experimentation_plan(
        project_id,
        creator_id=body.creator_id,
        dry_run=body.dry_run,
    )
    return experimentation.model_dump(mode="json")


@router.get("/projects/{project_id}/experimentation")
async def get_experimentation(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    experimentation = boba.load_experimentation_plan(project_id)
    if experimentation is None:
        raise NotFoundError(
            "BOBA experimentation plan is not available.",
            details={"project_id": project_id},
        )
    return experimentation.model_dump(mode="json")


@router.get("/projects/{project_id}/experimentation/export")
async def export_experimentation(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    if boba.load_experimentation_plan(project_id) is None:
        raise NotFoundError(
            "BOBA experimentation plan is not available for export.",
            details={"project_id": project_id},
        )
    return boba.export_experimentation_plan(project_id)


@router.delete("/projects/{project_id}/experimentation")
async def reset_experimentation(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    removed = boba.reset_experimentation_plan(project_id)
    return {
        "reset": removed,
        "project_id": project_id,
        "experimentation_removed": removed,
        "unrelated_memory_removed": False,
    }


@router.post("/projects/{project_id}/experimentation/results")
async def record_experimentation_result(
    project_id: str,
    body: ExperimentManualResultRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    result = boba.record_manual_experiment_result(
        project_id,
        experiment_id=body.experiment_id,
        selected_variant_id=body.selected_variant_id,
        manual_rating=body.manual_rating,
        outcome_label=body.outcome_label,
        creator_note=body.creator_note,
        should_feed_learning=body.should_feed_learning,
    )
    return result.model_dump(mode="json")


@router.post("/projects/{project_id}/performance-feedback/events")
async def record_performance_feedback_event(
    project_id: str,
    body: PerformanceFeedbackEventRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    event, feedback = await boba.record_performance_feedback_event(
        project_id,
        event_type=body.event_type,
        target_type=body.target_type,
        target_id=body.target_id,
        candidate_id=body.candidate_id,
        brief_id=body.brief_id,
        experiment_id=body.experiment_id,
        variant_id=body.variant_id,
        manual_rating=body.manual_rating,
        creator_note=body.creator_note,
        platform=body.platform,
        source_label=body.source_label,
        metrics=body.metrics,
        retention_notes=body.retention_notes,
        creator_interpretation=body.creator_interpretation,
        outcome_label=body.outcome_label,
        baseline_id=body.baseline_id,
        selected_variant_id=body.selected_variant_id,
        should_feed_learning=body.should_feed_learning,
    )
    return {
        "event": event.model_dump(mode="json"),
        "performance_feedback": feedback.model_dump(mode="json"),
        "analytics_collected": False,
        "automatically_applied": False,
    }


@router.post("/projects/{project_id}/performance-feedback")
async def create_performance_feedback(
    project_id: str,
    body: PerformanceFeedbackGenerateRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    feedback = await boba.generate_performance_feedback(
        project_id,
        dry_run=body.dry_run,
    )
    return feedback.model_dump(mode="json")


@router.get("/projects/{project_id}/performance-feedback")
async def get_performance_feedback(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    feedback = boba.load_performance_feedback(project_id)
    if feedback is None:
        raise NotFoundError(
            "BOBA performance feedback is not available.",
            details={"project_id": project_id},
        )
    return feedback.model_dump(mode="json")


@router.get("/projects/{project_id}/performance-feedback/export")
async def export_performance_feedback(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    if boba.load_performance_feedback(project_id) is None:
        raise NotFoundError(
            "BOBA performance feedback is not available for export.",
            details={"project_id": project_id},
        )
    return boba.export_performance_feedback(project_id)


@router.delete("/projects/{project_id}/performance-feedback")
async def reset_performance_feedback(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    removed = boba.reset_performance_feedback(project_id)
    return {
        "reset": removed,
        "project_id": project_id,
        "performance_feedback_removed": removed,
        "experimentation_removed": False,
        "creator_learning_removed": False,
        "approval_rejection_learning_removed": False,
        "unrelated_memory_removed": False,
    }


@router.post("/projects/{project_id}/content-scout-v2")
async def create_content_scout_v2(
    project_id: str,
    body: ContentScoutGenerateRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    scout = await boba.generate_content_scout_v2(
        project_id,
        manual_items=body.manual_items,
        import_paths=body.import_paths,
        source_label=body.source_label,
        dry_run=body.dry_run,
    )
    return scout.model_dump(mode="json")


@router.get("/projects/{project_id}/content-scout-v2")
async def get_content_scout_v2(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    scout = boba.load_content_scout_v2(project_id)
    if scout is None:
        raise NotFoundError(
            "BOBA Content Scout V2 is not available.",
            details={"project_id": project_id},
        )
    return scout.model_dump(mode="json")


@router.get("/projects/{project_id}/content-scout-v2/export")
async def export_content_scout_v2(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    if boba.load_content_scout_v2(project_id) is None:
        raise NotFoundError(
            "BOBA Content Scout V2 is not available for export.",
            details={"project_id": project_id},
        )
    return boba.export_content_scout_v2(project_id)


@router.delete("/projects/{project_id}/content-scout-v2")
async def reset_content_scout_v2(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    removed = boba.reset_content_scout_v2(project_id)
    return {
        "reset": removed,
        "project_id": project_id,
        "content_scout_v2_removed": removed,
        "scout_v1_removed": False,
        "creator_learning_removed": False,
        "approval_rejection_learning_removed": False,
        "performance_feedback_removed": False,
        "memory_removed": False,
    }


@router.post("/projects/{project_id}/creator-learning/events")
async def record_creator_learning_event(
    project_id: str,
    body: CreatorLearningEventRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_memory_enabled(settings)
    await _require_project(project_id, boba)
    event = await boba.record_creator_feedback_event(
        project_id,
        event_type=body.event_type,
        target_type=body.target_type,
        target_id=body.target_id,
        user_action=body.user_action,
        rating=body.rating,
        note=body.note,
        tags=body.tags,
        reversible=body.reversible,
    )
    return event.model_dump(mode="json")


@router.post("/projects/{project_id}/creator-learning")
async def generate_creator_learning(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
    body: CreatorLearningGenerateRequest | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    _require_memory_enabled(settings)
    await _require_project(project_id, boba)
    request = body or CreatorLearningGenerateRequest()
    learning = await boba.generate_creator_learning_profile(
        project_id,
        creator_id=request.creator_id,
        dry_run=dry_run or request.dry_run,
    )
    return learning.model_dump(mode="json")


@router.get("/projects/{project_id}/creator-learning")
async def get_creator_learning(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_memory_enabled(settings)
    await _require_project(project_id, boba)
    learning = boba.load_creator_learning_profile(project_id)
    if learning is None:
        raise NotFoundError(
            "BOBA creator learning is not available.",
            details={"project_id": project_id},
        )
    return learning.model_dump(mode="json")


@router.get("/projects/{project_id}/creator-learning/export")
async def export_creator_learning(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_memory_enabled(settings)
    await _require_project(project_id, boba)
    if boba.load_creator_learning_profile(project_id) is None:
        raise NotFoundError(
            "BOBA creator learning is not available for export.",
            details={"project_id": project_id},
        )
    return boba.export_creator_learning_profile(project_id)


@router.delete("/projects/{project_id}/creator-learning")
async def reset_creator_learning(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_memory_enabled(settings)
    await _require_project(project_id, boba)
    removed = boba.reset_creator_learning_profile(project_id)
    return {
        "reset": True,
        "project_id": project_id,
        "creator_learning_removed": removed,
        "unrelated_memory_removed": False,
    }


@router.post("/projects/{project_id}/approval-rejection-learning")
async def generate_approval_rejection_learning(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
    body: ApprovalRejectionLearningGenerateRequest | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    _require_memory_enabled(settings)
    await _require_project(project_id, boba)
    request = body or ApprovalRejectionLearningGenerateRequest()
    learning = await boba.generate_approval_rejection_learning(
        project_id,
        creator_id=request.creator_id,
        dry_run=dry_run or request.dry_run,
    )
    return learning.model_dump(mode="json")


@router.get("/projects/{project_id}/approval-rejection-learning")
async def get_approval_rejection_learning(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_memory_enabled(settings)
    await _require_project(project_id, boba)
    learning = boba.load_approval_rejection_learning(project_id)
    if learning is None:
        raise NotFoundError(
            "BOBA approval/rejection learning is not available.",
            details={"project_id": project_id},
        )
    return learning.model_dump(mode="json")


@router.get("/projects/{project_id}/approval-rejection-learning/export")
async def export_approval_rejection_learning(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_memory_enabled(settings)
    await _require_project(project_id, boba)
    if boba.load_approval_rejection_learning(project_id) is None:
        raise NotFoundError(
            "BOBA approval/rejection learning is not available for export.",
            details={"project_id": project_id},
        )
    return boba.export_approval_rejection_learning(project_id)


@router.delete("/projects/{project_id}/approval-rejection-learning")
async def reset_approval_rejection_learning(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_memory_enabled(settings)
    await _require_project(project_id, boba)
    removed = boba.reset_approval_rejection_learning(project_id)
    return {
        "reset": True,
        "project_id": project_id,
        "approval_rejection_learning_removed": removed,
        "creator_learning_removed": False,
        "unrelated_memory_removed": False,
    }


def _brief_decision(
    project_id: str,
    clip_id: str,
    decision: BobaApprovalDecision,
    body: CreativeBriefDecisionRequest,
    boba: BobaIntegrationDep,
) -> dict[str, Any]:
    event, lesson = boba.approvals.decide_clip_idea(
        project_id,
        clip_id,
        decision=decision,
        reason=body.reason,
        creator_profile_id=body.creator_profile_id,
    )
    return {
        "approval": event.model_dump(mode="json"),
        "memory_lesson_id": lesson.memory_id,
        "rendering_triggered": False,
    }


@router.post("/projects/{project_id}/creative-briefs/{clip_id}/approve")
async def approve_creative_brief(
    project_id: str,
    clip_id: str,
    body: CreativeBriefDecisionRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_memory_enabled(settings)
    await _require_project(project_id, boba)
    return _brief_decision(project_id, clip_id, "approved", body, boba)


@router.post("/projects/{project_id}/creative-briefs/{clip_id}/reject")
async def reject_creative_brief(
    project_id: str,
    clip_id: str,
    body: CreativeBriefDecisionRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_memory_enabled(settings)
    await _require_project(project_id, boba)
    return _brief_decision(project_id, clip_id, "rejected", body, boba)


@router.get("/projects/{project_id}/brain")
async def get_brain(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    state = boba.store.load_brain_state(project_id)
    if state is None:
        state = await boba.generate_boba_for_project(project_id)
    return state.model_dump(mode="json")


@router.get("/projects/{project_id}/decisions")
async def get_decisions(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    decisions = boba.store.list_decisions(project_id)
    return {
        "project_id": project_id,
        "mode": "advisory",
        "count": len(decisions),
        "decisions": [item.model_dump(mode="json") for item in decisions],
    }


@router.get("/projects/{project_id}/observations")
async def get_observations(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    observations = boba.store.list_observations(project_id)
    return {
        "project_id": project_id,
        "count": len(observations),
        "observations": [item.model_dump(mode="json") for item in observations],
    }


@router.post("/projects/{project_id}/summarize")
async def summarize_project(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    await _require_project(project_id, boba)
    state = await boba.generate_boba_for_project(project_id)
    return {
        "brain": state.model_dump(mode="json"),
        "summary": boba.brain.summarize_current_state(project_id),
    }


@router.post("/projects/{project_id}/rank-candidates")
async def rank_project_candidates(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    if not settings.boba.enable_candidate_ranking:
        raise ValidationError("BOBA candidate ranking is disabled by configuration.")
    await _require_project(project_id, boba)
    return (await boba.rank_project_candidates(project_id)).model_dump(mode="json")


@router.post("/projects/{project_id}/editorial-policy")
async def create_project_editorial_policy(
    project_id: str,
    body: EditorialPolicyRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_enabled(settings)
    if not settings.boba.enable_editorial_policy:
        raise ValidationError("BOBA editorial policy is disabled by configuration.")
    await _require_project(project_id, boba)
    return (await boba.generate_boba_for_clip(project_id, body.clip_id)).model_dump(
        mode="json"
    )


@router.get("/memory/projects/{project_id}")
async def get_project_memory(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_memory_enabled(settings)
    await _require_project(project_id, boba)
    memory = boba.store.load_project_memory(project_id)
    if memory is None:
        memory = await boba.build_project_memory(project_id)
    return memory.model_dump(mode="json")


@router.post("/memory/projects/{project_id}/build")
async def build_project_memory_route(
    project_id: str,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_memory_enabled(settings)
    await _require_project(project_id, boba)
    return (await boba.build_project_memory(project_id)).model_dump(mode="json")


@router.get("/memory/creators/{profile_id}")
def get_creator_memory(
    profile_id: str,
    boba: BobaIntegrationDep,
    personalization: PersonalizationServiceDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_memory_enabled(settings)
    if not settings.boba_memory.allow_creator_memory:
        raise ValidationError("Creator memory is disabled by configuration.")
    memory = boba.store.load_creator_memory(profile_id)
    if memory is None:
        profile = personalization.get_profile(profile_id)
        memory = build_and_save_creator_memory(
            boba.store,
            profile,
            personalization.store.list_feedback(profile_id),
        )
    return memory.model_dump(mode="json")


@router.post("/memory/creators/{profile_id}/build")
def build_creator_memory_route(
    profile_id: str,
    boba: BobaIntegrationDep,
    personalization: PersonalizationServiceDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_memory_enabled(settings)
    if not settings.boba_memory.allow_creator_memory:
        raise ValidationError("Creator memory is disabled by configuration.")
    profile = personalization.get_profile(profile_id)
    return build_and_save_creator_memory(
        boba.store,
        profile,
        personalization.store.list_feedback(profile_id),
    ).model_dump(mode="json")


@router.get("/memory/global")
def get_global_memory(
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_memory_enabled(settings)
    if not settings.boba_memory.allow_global_memory:
        raise ValidationError("Global memory is disabled by configuration.")
    memory = boba.store.load_global_memory() or build_and_save_global_memory(boba.store)
    return memory.model_dump(mode="json")


@router.post("/memory/global/build")
def build_global_memory_route(
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_memory_enabled(settings)
    if not settings.boba_memory.allow_global_memory:
        raise ValidationError("Global memory is disabled by configuration.")
    return build_and_save_global_memory(boba.store).model_dump(mode="json")


@router.post("/memory/query")
def query_memory(
    body: BobaMemoryQueryV1,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_memory_enabled(settings)
    return boba.store.query_memory(body).model_dump(mode="json")


@router.post("/memory/feedback")
async def record_memory_feedback(
    body: MemoryFeedbackRequest,
    boba: BobaIntegrationDep,
    personalization: PersonalizationServiceDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_memory_enabled(settings)
    await _require_project(body.project_id, boba)
    feedback = personalization.record_feedback(
        profile_id=body.profile_id,
        project_id=body.project_id,
        clip_id=body.clip_id,
        rating=body.rating,
        labels=body.labels,
        notes=body.notes,
        clip_traits=body.clip_traits,
    )
    if personalization.memory_feedback_callback is None:
        BobaMemoryLearner(boba.store).learn_from_feedback(feedback)
        build_and_save_creator_memory(
            boba.store,
            personalization.get_profile(body.profile_id),
            personalization.store.list_feedback(body.profile_id),
        )
    creator_memory = boba.store.load_creator_memory(body.profile_id)
    if creator_memory is None:
        raise ValidationError("Creator memory was not created from explicit feedback.")
    return {
        "feedback": feedback.model_dump(mode="json"),
        "creator_memory": creator_memory.model_dump(mode="json"),
    }


@router.get("/memory/export")
def export_memory(
    boba: BobaIntegrationDep,
    settings: SettingsDep,
    scope: Literal["project", "creator", "global"] | None = None,
    identifier: str | None = None,
) -> dict[str, Any]:
    _require_memory_enabled(settings)
    if not settings.boba_memory.allow_import_export:
        raise ValidationError("BOBA memory export is disabled by configuration.")
    return boba.store.export_memory(scope, identifier)


@router.post("/memory/import")
def import_memory(
    body: MemoryImportRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_memory_enabled(settings)
    if not body.confirm:
        raise ValidationError("BOBA memory import requires explicit confirmation.")
    if not settings.boba_memory.allow_import_export:
        raise ValidationError("BOBA memory import is disabled by configuration.")
    return {"imported": boba.store.import_memory(body.payload)}


@router.post("/memory/reset")
def reset_memory(
    body: MemoryResetRequest,
    boba: BobaIntegrationDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    _require_memory_enabled(settings)
    if not body.confirm:
        raise ValidationError("BOBA memory reset requires explicit confirmation.")
    if body.scope == "project":
        if not body.identifier:
            raise ValidationError("Project memory reset requires identifier.")
        backup = boba.store.reset_project_memory(body.identifier)
    elif body.scope == "creator":
        if not body.identifier:
            raise ValidationError("Creator memory reset requires identifier.")
        backup = boba.store.reset_creator_memory(body.identifier)
    else:
        backup = boba.store.reset_global_memory()
    return {
        "reset": True,
        "scope": body.scope,
        "identifier": body.identifier,
        "backup_created": backup is not None,
        "backup_name": backup.name if backup else None,
    }
