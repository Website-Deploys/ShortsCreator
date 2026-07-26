"""Read existing Olympus artifacts and build bounded BOBA advisory context."""

from __future__ import annotations

import json
from typing import Any

from olympus.boba.approval_rejection_learning import (
    BobaApprovalRejectionLearningSetV1,
    BobaApprovalRejectionLearningV1,
    BobaApprovalRejectionModuleGuidanceV1,
)
from olympus.boba.approvals import BobaApprovalService
from olympus.boba.brain import BobaBrain
from olympus.boba.candidate_video_scorer import (
    BobaCandidateVideoScorerSetV1,
    BobaCandidateVideoScorerV1,
)
from olympus.boba.caption_motion import (
    BobaCaptionMotionRecommendationBrainV1,
    BobaCaptionMotionRecommendationSetV1,
)
from olympus.boba.clip_brief import BobaClipBriefGeneratorV1, BobaClipBriefSetV1
from olympus.boba.clip_discovery import (
    BobaCandidateClipDiscoveryEngine,
    BobaCandidateClipDiscoveryV1,
)
from olympus.boba.clip_ranking import (
    BobaClipRankingEngine,
)
from olympus.boba.clip_ranking import (
    BobaClipRankingV1 as BobaDiscoveryClipRankingV1,
)
from olympus.boba.content_scout import (
    BobaContentScoutSetV2,
    BobaContentScoutV2,
)
from olympus.boba.contracts import (
    BobaBrainStateV1,
    BobaClipRankingV1,
    BobaDecisionV1,
    BobaEditorialPolicyV1,
    BobaReasoningV1,
)
from olympus.boba.creative_director import (
    BobaCreativeBriefV1,
    BobaCreativeDirectionSetV2,
    BobaCreativeDirector,
    BobaCreativeDirectorV2Engine,
)
from olympus.boba.creator_learning import (
    BobaCreatorFeedbackEventType,
    BobaCreatorFeedbackEventV1,
    BobaCreatorFeedbackTargetType,
    BobaCreatorLearningLoopV1,
    BobaCreatorLearningSetV1,
    BobaCreatorUserAction,
    BobaRecommendationGuidanceV1,
)
from olympus.boba.decision_bus import BobaDecisionBus
from olympus.boba.editorial_decision import (
    BobaEditorialDecisionEngine,
    BobaEditorialDecisionSetV1,
)
from olympus.boba.editorial_policy import create_editorial_policy
from olympus.boba.error_doctor import BobaErrorDoctorSetV1, BobaErrorDoctorV1
from olympus.boba.experimentation import (
    BobaExperimentationSetV1,
    BobaExperimentationSystemV1,
    BobaExperimentManualResultV1,
    BobaExperimentOutcomeLabel,
)
from olympus.boba.explanation import BobaExplanationEngine, BobaExplanationSetV1
from olympus.boba.global_memory import build_and_save_global_memory
from olympus.boba.hook_retention import (
    BobaHookRetentionBrainV1,
    BobaHookRetentionSetV1,
)
from olympus.boba.memory_application import create_memory_application
from olympus.boba.memory_contracts import BobaProjectMemoryV1
from olympus.boba.memory_retrieval import (
    retrieve_for_clip_decision,
    retrieve_for_editorial_policy,
    retrieve_for_project,
)
from olympus.boba.music_mood import (
    BobaMusicMoodBrainV1,
    BobaMusicMoodRecommendationSetV1,
    music_manifest_awareness,
)
from olympus.boba.observer import BobaObserverSetV1, BobaObserverV1
from olympus.boba.performance_feedback import (
    BobaManualPerformanceMetricsV1,
    BobaPerformanceEventType,
    BobaPerformanceFeedbackBrainV1,
    BobaPerformanceFeedbackEventV1,
    BobaPerformanceFeedbackSetV1,
    BobaPerformanceOutcomeLabel,
    BobaPerformanceTargetType,
)
from olympus.boba.project_memory import build_and_save_project_memory
from olympus.boba.ranking import rank_candidates
from olympus.boba.reasoning import explain_clip_selection, summarize_project_understanding
from olympus.boba.research_brain import (
    BobaResearchBrainSetV1,
    BobaResearchBrainV1,
)
from olympus.boba.rights_permission_gate import (
    BobaRightsPermissionGateSetV1,
    BobaRightsPermissionGateV1,
)
from olympus.boba.scout import BobaScout
from olympus.boba.store import BobaMemoryStore
from olympus.boba.trend_topic_watcher import (
    BobaTrendTopicWatcherSetV1,
    BobaTrendTopicWatcherV1,
)
from olympus.boba.validation import compact_boba_summary
from olympus.boba.whole_video import (
    BobaWholeVideoUnderstandingEngine,
    BobaWholeVideoUnderstandingV1,
    build_whole_video_memory_summary,
    whole_video_memory_record,
)
from olympus.data.repositories.project_repository import StorageProjectRepository
from olympus.domain.contracts.storage import StoragePort
from olympus.music import load_music_assets
from olympus.personalization import apply as personalization
from olympus.platform.config import get_settings
from olympus.platform.errors import NotFoundError, ValidationError
from olympus.utils import new_id


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _data(stage: dict[str, Any]) -> dict[str, Any]:
    return _dict(stage.get("data"))


class BobaIntegration:
    def __init__(
        self,
        storage: StoragePort,
        store: BobaMemoryStore,
        *,
        mode: str = "advise",
        memory_enabled: bool = True,
        allow_global_memory: bool = True,
    ) -> None:
        self.storage = storage
        self.projects = StorageProjectRepository(storage)
        self.store = store
        self.brain = BobaBrain(store, mode=mode)  # type: ignore[arg-type]
        self.bus = BobaDecisionBus(store)
        self.scout = BobaScout(store)
        self.content_scout_v2 = BobaContentScoutV2()
        self.research_brain = BobaResearchBrainV1()
        self.trend_topic_watcher = BobaTrendTopicWatcherV1()
        self.candidate_video_scorer = BobaCandidateVideoScorerV1()
        self.rights_permission_gate = BobaRightsPermissionGateV1()
        self.observer = BobaObserverV1(
            store.root,
            validation_report_root=store.root.parent / "validation_reports",
        )
        self.error_doctor = BobaErrorDoctorV1()
        self.creative_director = BobaCreativeDirector(store)
        self.creative_director_v2 = BobaCreativeDirectorV2Engine()
        self.clip_brief_generator = BobaClipBriefGeneratorV1()
        self.hook_retention_brain = BobaHookRetentionBrainV1()
        self.caption_motion_brain = BobaCaptionMotionRecommendationBrainV1()
        self.music_mood_brain = BobaMusicMoodBrainV1()
        self.experimentation_system = BobaExperimentationSystemV1()
        self.performance_feedback_brain = BobaPerformanceFeedbackBrainV1()
        self.creator_learning_loop = BobaCreatorLearningLoopV1()
        self.approval_rejection_learning = BobaApprovalRejectionLearningV1()
        self.whole_video = BobaWholeVideoUnderstandingEngine()
        self.candidate_discovery = BobaCandidateClipDiscoveryEngine()
        self.clip_ranking = BobaClipRankingEngine()
        self.editorial_decision = BobaEditorialDecisionEngine()
        self.explanation = BobaExplanationEngine()
        self.approvals = BobaApprovalService(store)
        self.memory_enabled = memory_enabled
        self.allow_global_memory = allow_global_memory

    def _ensure_global_memory(self) -> None:
        if (
            self.memory_enabled
            and self.allow_global_memory
            and self.store.load_global_memory() is None
        ):
            build_and_save_global_memory(self.store)

    def _creator_learning_artifacts(self, project_id: str) -> dict[str, Any]:
        return {
            "clip_ranking": self.store.load_clip_ranking(project_id),
            "editorial_decision": self.store.load_editorial_decisions(project_id),
            "explanation": self.store.load_explanations(project_id),
            "creative_direction": self.store.load_creative_direction_v2(project_id),
            "clip_briefs": self.store.load_clip_briefs(project_id),
            "hook_retention": self.store.load_hook_retention(project_id),
            "caption_motion": self.store.load_caption_motion(project_id),
            "music_mood": self.store.load_music_mood(project_id),
        }

    async def record_creator_feedback_event(
        self,
        project_id: str,
        *,
        event_type: BobaCreatorFeedbackEventType,
        target_type: BobaCreatorFeedbackTargetType,
        target_id: str,
        user_action: BobaCreatorUserAction,
        rating: float | None = None,
        note: str = "",
        tags: list[str] | None = None,
        reversible: bool = True,
    ) -> BobaCreatorFeedbackEventV1:
        if await self.projects.get(project_id) is None:
            raise NotFoundError("Project was not found.", details={"id": project_id})
        event = self.creator_learning_loop.create_feedback_event(
            project_id=project_id,
            event_type=event_type,
            target_type=target_type,
            target_id=target_id,
            user_action=user_action,
            rating=rating,
            note=note,
            tags=tags,
            reversible=reversible,
            artifacts=self._creator_learning_artifacts(project_id),
        )
        return self.store.record_creator_feedback_event(event)

    async def generate_creator_learning_profile(
        self,
        project_id: str,
        *,
        creator_id: str = "local_creator",
        dry_run: bool = False,
    ) -> BobaCreatorLearningSetV1:
        project = await self.projects.get(project_id)
        if project is None:
            raise NotFoundError("Project was not found.", details={"id": project_id})
        artifacts = self._creator_learning_artifacts(project_id)
        creator_memory = self.store.load_creator_memory(creator_id)
        project_memory = self.store.load_project_memory(project_id)
        learning = self.creator_learning_loop.analyze(
            project_id,
            self.store.list_creator_feedback_events(project_id),
            creator_id=creator_id,
            source_id=project.id,
            boba_memory=creator_memory or project_memory,
            clip_ranking=artifacts["clip_ranking"],
            editorial_decision=artifacts["editorial_decision"],
            explanation=artifacts["explanation"],
            creative_direction=artifacts["creative_direction"],
            clip_briefs=artifacts["clip_briefs"],
            hook_retention=artifacts["hook_retention"],
            caption_motion=artifacts["caption_motion"],
            music_mood=artifacts["music_mood"],
        )
        if dry_run:
            return learning.model_copy(
                update={
                    "warnings": [
                        *learning.warnings,
                        "Dry run: creator learning was not persisted.",
                    ]
                }
            )
        return self.store.save_creator_learning(learning)

    def load_creator_learning_profile(
        self,
        project_id: str,
    ) -> BobaCreatorLearningSetV1 | None:
        return self.store.load_creator_learning_profile(project_id)

    def export_creator_learning_profile(self, project_id: str) -> dict[str, Any]:
        return self.store.export_creator_learning_profile(project_id)

    def reset_creator_learning_profile(self, project_id: str) -> bool:
        return self.store.reset_creator_learning_profile(project_id)

    async def apply_creator_learning_guidance_dry_run(
        self,
        project_id: str,
        *,
        creator_id: str = "local_creator",
    ) -> BobaRecommendationGuidanceV1:
        learning = await self.generate_creator_learning_profile(
            project_id,
            creator_id=creator_id,
            dry_run=True,
        )
        return learning.recommendation_guidance

    async def generate_approval_rejection_learning(
        self,
        project_id: str,
        *,
        creator_id: str = "local_creator",
        dry_run: bool = False,
    ) -> BobaApprovalRejectionLearningSetV1:
        project = await self.projects.get(project_id)
        if project is None:
            raise NotFoundError("Project was not found.", details={"id": project_id})
        artifacts = self._creator_learning_artifacts(project_id)
        creator_memory = self.store.load_creator_memory(creator_id)
        project_memory = self.store.load_project_memory(project_id)
        learning = self.approval_rejection_learning.analyze(
            project_id,
            self.store.list_creator_feedback_events(project_id),
            source_id=project.id,
            creator_learning=self.store.load_creator_learning(project_id),
            boba_memory=creator_memory or project_memory,
            clip_ranking=artifacts["clip_ranking"],
            editorial_decision=artifacts["editorial_decision"],
            explanation=artifacts["explanation"],
            creative_direction=artifacts["creative_direction"],
            clip_briefs=artifacts["clip_briefs"],
            hook_retention=artifacts["hook_retention"],
            caption_motion=artifacts["caption_motion"],
            music_mood=artifacts["music_mood"],
            dry_run=dry_run,
        )
        if dry_run:
            return learning
        return self.store.save_approval_rejection_learning(learning)

    def load_approval_rejection_learning(
        self,
        project_id: str,
    ) -> BobaApprovalRejectionLearningSetV1 | None:
        return self.store.load_approval_rejection_learning(project_id)

    def export_approval_rejection_learning(self, project_id: str) -> dict[str, Any]:
        return self.store.export_approval_rejection_learning(project_id)

    def reset_approval_rejection_learning(self, project_id: str) -> bool:
        return self.store.reset_approval_rejection_learning(project_id)

    async def apply_approval_rejection_guidance_dry_run(
        self,
        project_id: str,
        *,
        creator_id: str = "local_creator",
    ) -> BobaApprovalRejectionModuleGuidanceV1:
        learning = await self.generate_approval_rejection_learning(
            project_id,
            creator_id=creator_id,
            dry_run=True,
        )
        return learning.module_guidance

    async def _json(self, key: str) -> dict[str, Any]:
        if not await self.storage.exists(key):
            return {}
        try:
            raw = json.loads(await self.storage.get(key))
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            return {"_warning": f"Artifact is unreadable: {key}"}
        return raw if isinstance(raw, dict) else {}

    async def _stage(self, engine: str, project_id: str, stage: str) -> dict[str, Any]:
        return await self._json(f"{engine}/{project_id}/stages/{stage}.json")

    async def collect_project_signals(self, project_id: str) -> dict[str, Any]:
        project = await self.projects.get(project_id)
        if project is None:
            raise NotFoundError("Project was not found.", details={"id": project_id})

        speech = await self._stage("analysis", project_id, "speech_transcription")
        video = await self._stage("analysis", project_id, "video_inspection")
        face = await self._stage("analysis", project_id, "face_detection")
        speakers = await self._stage("analysis", project_id, "speaker_segmentation")
        scenes = await self._stage("analysis", project_id, "scene_detection")
        signal_health = await self._stage("analysis", project_id, "signal_health")
        story = await self._stage("story", project_id, "story_analysis_v2")
        story_summary = await self._stage("story", project_id, "story_summary")
        emotions = await self._stage("story", project_id, "emotional_turning_points")
        virality = await self._stage("virality", project_id, "virality_summary")
        trend = await self._stage("virality", project_id, "trend_research")
        scoring = await self._stage("planning", project_id, "clip_scoring")
        ranking = await self._stage("planning", project_id, "ranking")
        planning_summary = await self._stage("planning", project_id, "planning_summary")
        editing = await self._stage("editing", project_id, "timeline_validation")
        render_run = await self._json(f"render/{project_id}/run/index.json")
        render_manifest_stage = await self._json(
            f"render/{project_id}/run/stages/generate_render_manifest.json"
        )
        canonical_manifest = _dict(_data(render_manifest_stage).get("manifest"))
        legacy_manifest = await self._json(f"render/{project_id}/index.json")
        render_manifest = canonical_manifest or legacy_manifest
        optimization = await self._stage("optimization", project_id, "copyright_safety_v2")
        personalization_directives = personalization.load_runtime_directives() or {}

        speech_data = _data(speech)
        segments = _list(speech_data.get("segments"))
        transcript_segments = [
            {
                "start": float(_dict(item).get("start") or 0.0),
                "end": float(_dict(item).get("end") or 0.0),
                "text": " ".join(str(_dict(item).get("text") or "").split())[:240],
            }
            for item in segments[:2000]
            if isinstance(item, dict)
        ]
        analysis_signals = _dict(
            _data(signal_health).get("analysis_signals_v2")
        )
        transcript_available = bool(
            segments
            or speech_data.get("transcript")
            or speech_data.get("text")
            or (speech.get("status") == "completed" and speech_data)
        )
        face_available = face.get("status") == "completed" and bool(_data(face))
        speaker_available = speakers.get("status") == "completed" and bool(_data(speakers))
        speaker_data = _data(speakers)
        speaker_roles = [
            str(
                item.get("role")
                or item.get("name")
                or item.get("label")
                or item.get("speaker_id")
                or item.get("id")
                or ""
            )
            for item in _list(speaker_data.get("speakers"))
            if isinstance(item, dict)
        ]
        visual_available = bool(
            video.get("status") == "completed"
            and (scenes.get("status") == "completed" or face_available)
        )
        trend_data = _data(trend)
        trend_snapshot = _dict(trend_data.get("internet_trend_research_v2"))
        trend_status = str(
            trend_snapshot.get("status")
            or trend_data.get("status")
            or trend.get("status")
            or "unavailable"
        )
        fallback_used = bool(
            trend_snapshot.get("fallback_used")
            or trend_snapshot.get("provider") in {"evergreen", "fallback"}
        )
        safety = _data(optimization)
        if not safety:
            for render in _list(render_manifest.get("renders")):
                metadata = _dict(_dict(render).get("metadata"))
                if metadata.get("copyright_safety_v2"):
                    safety = _dict(metadata.get("copyright_safety_v2"))
                    break
        safety_result = _dict(safety.get("result") or safety.get("overall"))
        manual_review = bool(
            safety_result.get("manual_review_required")
            or _dict(safety.get("manual_review")).get("required")
        )
        safety_status = str(
            safety_result.get("risk_level")
            or safety_result.get("upload_readiness")
            or "unknown"
        )
        story_data = _data(story)
        micro_stories = [_dict(item) for item in _list(story_data.get("micro_stories"))]
        topic_sections = [_dict(item) for item in _list(story_data.get("topic_sections"))]
        plans = [_dict(item) for item in _list(_data(ranking).get("plans"))]
        candidates = [_dict(item) for item in _list(_data(scoring).get("candidates"))]
        timelines = _list(_data(editing).get("timelines"))
        render_stage = next(
            (
                item
                for item in _list(render_run.get("stages"))
                if isinstance(item, dict) and item.get("stage") == "generate_render_manifest"
            ),
            {},
        )
        manifest_available = bool(
            (
                render_manifest.get("status") == "completed"
                and _list(render_manifest.get("renders"))
            )
            or _dict(render_stage).get("status") == "completed"
        )
        warnings = [
            str(value.get("_warning"))
            for value in (
                speech,
                face,
                speakers,
                signal_health,
                story,
                virality,
                ranking,
                render_run,
            )
            if value.get("_warning")
        ]
        render_warnings = [
            str(item)
            for render in _list(render_manifest.get("renders"))
            for item in _list(_dict(_dict(render).get("metadata")).get("warnings"))
        ]
        known_limitations = [
            warning
            for warning in render_warnings
            if any(
                needle in warning.lower()
                for needle in ("sync", "delay", "cut", "face", "music", "speech")
            )
        ]
        if not manifest_available:
            reason = _dict(render_stage).get("reason")
            if reason:
                known_limitations.append(str(reason))
        saved_understanding = None
        try:
            saved_understanding = self.store.load_whole_video_understanding(project_id)
        except ValidationError as exc:
            warnings.append(f"BOBA whole-video artifact is unreadable: {exc}")
        saved_discovery = None
        try:
            saved_discovery = self.store.load_candidate_clip_discovery(project_id)
        except ValidationError as exc:
            warnings.append(f"BOBA candidate-discovery artifact is unreadable: {exc}")
        saved_clip_ranking = None
        try:
            saved_clip_ranking = self.store.load_clip_ranking(project_id)
        except ValidationError as exc:
            warnings.append(f"BOBA clip-ranking artifact is unreadable: {exc}")
        saved_editorial_decisions = None
        try:
            saved_editorial_decisions = self.store.load_editorial_decisions(project_id)
        except ValidationError as exc:
            warnings.append(f"BOBA editorial-decision artifact is unreadable: {exc}")
        saved_explanations = None
        try:
            saved_explanations = self.store.load_explanations(project_id)
        except ValidationError as exc:
            warnings.append(f"BOBA explanation artifact is unreadable: {exc}")
        saved_creative_direction_v2 = None
        try:
            saved_creative_direction_v2 = self.store.load_creative_direction_v2(
                project_id
            )
        except ValidationError as exc:
            warnings.append(f"BOBA Creative Director V2 artifact is unreadable: {exc}")
        saved_clip_briefs = None
        try:
            saved_clip_briefs = self.store.load_clip_briefs(project_id)
        except ValidationError as exc:
            warnings.append(f"BOBA clip-brief artifact is unreadable: {exc}")
        saved_hook_retention = None
        try:
            saved_hook_retention = self.store.load_hook_retention(project_id)
        except ValidationError as exc:
            warnings.append(f"BOBA hook-retention artifact is unreadable: {exc}")
        saved_caption_motion = None
        try:
            saved_caption_motion = self.store.load_caption_motion(project_id)
        except ValidationError as exc:
            warnings.append(f"BOBA caption-motion artifact is unreadable: {exc}")
        saved_music_mood = None
        try:
            saved_music_mood = self.store.load_music_mood(project_id)
        except ValidationError as exc:
            warnings.append(f"BOBA music-mood artifact is unreadable: {exc}")
        face_motion_results: list[dict[str, Any]] = []
        multi_speaker_results: list[dict[str, Any]] = []
        for render in _list(render_manifest.get("renders")):
            render_data = _dict(render)
            metadata = _dict(render_data.get("metadata"))
            clip_id = str(
                render_data.get("clip_id")
                or metadata.get("candidate_id")
                or metadata.get("clip_id")
                or ""
            )
            if not clip_id:
                continue
            face_tracking = _dict(
                metadata.get("face_tracking")
                or metadata.get("face_tracking_plan")
            )
            motion_validation = _dict(metadata.get("motion_render_validation"))
            if face_tracking or motion_validation:
                face_motion_results.append(
                    {
                        "candidate_id": clip_id,
                        "face_tracking_available": bool(
                            face_tracking.get("applied")
                            or face_tracking.get("applied_to_render")
                            or face_tracking.get("keyframes_count")
                        ),
                        "face_cutoff_detected": bool(
                            face_tracking.get("face_cutoff_detected")
                            or motion_validation.get("face_cutoff_detected")
                        ),
                        "face_inside_safe_zone_ratio": face_tracking.get(
                            "face_inside_safe_zone_ratio"
                        ),
                        "motion_render_passed": motion_validation.get("passed"),
                        "warnings": [
                            *(
                                item
                                for item in _list(face_tracking.get("warnings"))
                                if isinstance(item, str)
                            ),
                            *(
                                item
                                for item in _list(motion_validation.get("warnings"))
                                if isinstance(item, str)
                            ),
                        ][:16],
                    }
                )
            layout = _dict(metadata.get("multi_speaker_layout_v2"))
            layout_validation = _dict(metadata.get("multi_speaker_validation"))
            if layout or layout_validation:
                layout_decision = _dict(layout.get("layout_decision"))
                multi_speaker_results.append(
                    {
                        "candidate_id": clip_id,
                        "detected_speaker_count": layout.get("speaker_count"),
                        "face_count_detected": layout.get("face_count"),
                        "layout_strategy": (
                            layout_validation.get("applied_mode")
                            or layout_decision.get("mode")
                            or layout.get("mode")
                        ),
                        "passed": layout_validation.get("passed"),
                        "face_cutoff_detected": layout_validation.get(
                            "face_cutoff_detected"
                        ),
                        "wrong_speaker_focus_warnings": _list(
                            layout_validation.get("wrong_speaker_focus_warnings")
                        )[:8],
                        "warnings": [
                            item
                            for item in _list(layout_validation.get("warnings"))
                            if isinstance(item, str)
                        ][:16],
                    }
                )
        discovery_by_id = {
            item.candidate_id: item
            for item in (saved_discovery.candidates if saved_discovery is not None else [])
        }
        ranked_candidate_clips = [
            discovery_by_id[item.candidate_id].model_dump(mode="json")
            for item in (
                saved_clip_ranking.ranked_candidates
                if saved_clip_ranking is not None
                else []
            )
            if item.tier != "reject" and item.candidate_id in discovery_by_id
        ]
        editorial_candidate_clips = [
            {
                **discovery_by_id[item.candidate_id].model_dump(mode="json"),
                "story_angle": item.final_story_angle,
                "hook_category": item.final_hook_strategy,
                "pacing_level": item.pacing_intensity,
                "caption_style": item.caption_style,
                "motion_style": item.motion_style,
                "music_mood": item.music_mood,
                "editorial_decision": item.model_dump(mode="json"),
            }
            for item in (
                saved_editorial_decisions.decisions
                if saved_editorial_decisions is not None
                else []
            )
            if item.selected
            and item.render_readiness != "blocked"
            and item.candidate_id in discovery_by_id
        ]
        summary_data = _data(story_summary)
        main_topics = [
            str(item.get("title") or item.get("topic") or item.get("summary") or "")
            for item in topic_sections
        ]
        content_niche = str(
            _dict(_data(planning_summary).get("content_niche")).get("niche")
            or trend_snapshot.get("detected_niche")
            or project.content_category
            or "unknown"
        )
        return {
            "project": project.to_dict(),
            "source_type": project.source_type,
            "duration_seconds": project.duration_seconds,
            "transcript_available": transcript_available,
            "visual_signals_available": visual_available,
            "face_signals_available": face_available,
            "speaker_signals_available": speaker_available,
            "trend_signals_available": bool(trend_snapshot or trend_data),
            "safety_signals_available": bool(safety),
            "personalization_signals_available": bool(personalization_directives),
            "trend_fallback_used": fallback_used,
            "trend_provider_status": trend_status,
            "safety_manual_review_required": manual_review,
            "safety_status": safety_status,
            "personalization_status": (
                "available" if personalization_directives else "unavailable"
            ),
            "render_manifest_available": manifest_available,
            "planning_candidates_available": bool(plans or candidates),
            "editing_timelines_available": bool(timelines),
            "content_niche": content_niche,
            "main_topics": [item for item in main_topics if item][:20],
            "story_threads": [
                str(item.get("summary") or item.get("one_sentence_summary") or "")
                for item in micro_stories
                if item
            ][:20],
            "speakers_or_roles": [item for item in speaker_roles if item][:20],
            "emotional_moments": [
                str(item.get("description") or item.get("excerpt") or "")
                for item in _list(_data(emotions).get("turning_points"))
                if isinstance(item, dict)
            ][:20],
            "already_selected_ranges": [
                {"start": float(item.get("start") or 0.0), "end": float(item.get("end") or 0.0)}
                for item in plans
            ],
            "rejected_ranges": [
                {"start": float(item.get("start") or 0.0), "end": float(item.get("end") or 0.0)}
                for item in _list(_data(ranking).get("over_target"))
                if isinstance(item, dict) and (item.get("start") is not None)
            ],
            "rejected_candidates": [
                _dict(item)
                for item in _list(_data(ranking).get("over_target"))
                if _dict(item)
            ],
            "unused_opportunities": [
                str(item.get("summary") or item.get("reason") or "")
                for item in _list(story_data.get("recommended_clip_stories"))
                if isinstance(item, dict)
            ][:20],
            "warnings": warnings,
            "known_limitations": list(dict.fromkeys(known_limitations)),
            "planning_candidates": candidates or plans,
            "selected_plans": plans,
            "planning_summary": _data(planning_summary),
            "analysis_signals_v2": analysis_signals,
            "transcript_segments": transcript_segments,
            "story_analysis_v2": story_data,
            "virality_summary": _data(virality),
            "trend_research": trend_data,
            "safety": safety,
            "creator_profile": _dict(personalization_directives),
            "story_summary": summary_data,
            "editing_summary": {
                "timeline_count": len(timelines),
                "status": editing.get("status"),
            },
            "editing_timelines": [_dict(item) for item in timelines if _dict(item)],
            "render_summary": {
                "manifest_available": manifest_available,
                "render_count": len(_list(render_manifest.get("renders"))),
                "status": render_manifest.get("status"),
            },
            "whole_video_understanding": (
                saved_understanding.model_dump(mode="json")
                if saved_understanding is not None
                else {}
            ),
            "whole_video_understanding_available": saved_understanding is not None,
            "candidate_clip_discovery": (
                saved_discovery.model_dump(mode="json")
                if saved_discovery is not None
                else {}
            ),
            "candidate_clip_discovery_available": saved_discovery is not None,
            "discovered_candidate_clips": (
                [item.model_dump(mode="json") for item in saved_discovery.candidates]
                if saved_discovery is not None
                else []
            ),
            "clip_ranking": (
                saved_clip_ranking.model_dump(mode="json")
                if saved_clip_ranking is not None
                else {}
            ),
            "clip_ranking_available": saved_clip_ranking is not None,
            "ranked_candidate_clips": ranked_candidate_clips,
            "editorial_decisions": (
                saved_editorial_decisions.model_dump(mode="json")
                if saved_editorial_decisions is not None
                else {}
            ),
            "editorial_decisions_available": saved_editorial_decisions is not None,
            "editorial_candidate_clips": editorial_candidate_clips,
            "explanations": (
                saved_explanations.model_dump(mode="json")
                if saved_explanations is not None
                else {}
            ),
            "explanations_available": saved_explanations is not None,
            "creative_direction_v2": (
                saved_creative_direction_v2.model_dump(mode="json")
                if saved_creative_direction_v2 is not None
                else {}
            ),
            "creative_direction_v2_available": saved_creative_direction_v2 is not None,
            "clip_briefs": (
                saved_clip_briefs.model_dump(mode="json")
                if saved_clip_briefs is not None
                else {}
            ),
            "clip_briefs_available": saved_clip_briefs is not None,
            "hook_retention": (
                saved_hook_retention.model_dump(mode="json")
                if saved_hook_retention is not None
                else {}
            ),
            "hook_retention_available": saved_hook_retention is not None,
            "caption_motion": (
                saved_caption_motion.model_dump(mode="json")
                if saved_caption_motion is not None
                else {}
            ),
            "caption_motion_available": saved_caption_motion is not None,
            "music_mood": (
                saved_music_mood.model_dump(mode="json")
                if saved_music_mood is not None
                else {}
            ),
            "music_mood_available": saved_music_mood is not None,
            "face_motion_validation": (
                {"project_id": project_id, "results": face_motion_results}
                if face_motion_results
                else {}
            ),
            "multi_speaker_validation": (
                {"project_id": project_id, "results": multi_speaker_results}
                if multi_speaker_results
                else {}
            ),
        }

    async def collect_clip_signals(self, project_id: str, clip_id: str) -> dict[str, Any]:
        signals = await self.collect_project_signals(project_id)
        candidates = [
            item
            for item in _list(signals.get("planning_candidates"))
            if isinstance(item, dict)
        ]
        clip = next(
            (
                item
                for item in candidates
                if str(item.get("id") or item.get("clip_id") or item.get("candidate_id"))
                == clip_id
            ),
            {},
        )
        return {**signals, "clip": clip, "clip_id": clip_id}

    async def build_boba_context(self, project_id: str) -> dict[str, Any]:
        signals = await self.collect_project_signals(project_id)
        understanding = summarize_project_understanding(signals)
        return {"signals": signals, "understanding": understanding}

    async def generate_boba_for_project(self, project_id: str) -> BobaBrainStateV1:
        signals = await self.collect_project_signals(project_id)
        if signals.get("transcript_segments") and not signals.get(
            "whole_video_understanding_available"
        ):
            try:
                understanding = self._build_and_save_whole_video(project_id, signals)
                signals["whole_video_understanding"] = understanding.model_dump(mode="json")
                signals["whole_video_understanding_available"] = True
            except ValidationError as exc:
                signals["warnings"] = [
                    *_list(signals.get("warnings")),
                    f"Whole-video understanding is unavailable: {exc}",
                ]
        state = self.brain.create_brain_state(project_id, signals)
        memory_application = None
        if self.memory_enabled:
            self._ensure_global_memory()
            build_and_save_project_memory(
                self.store,
                project_id,
                signals,
                decisions=self.store.list_decisions(project_id),
            )
            creator_profile_id = (
                str(_dict(signals.get("creator_profile")).get("profile_id") or "")
                or None
            )
            retrieval = retrieve_for_project(self.store, project_id, creator_profile_id)
            memory_application = create_memory_application(
                project_id, "planning", retrieval
            )
        explanation = summarize_project_understanding(signals)
        decision = BobaDecisionV1(
            decision_id=new_id("decision"),
            project_id=project_id,
            decision_type="whole_video_understanding",
            question="What does BOBA understand about this project?",
            answer=str(explanation["summary"]),
            confidence=float(explanation["confidence"]),
            input_signals={
                "story": _dict(signals.get("story_analysis_v2")),
                "virality": _dict(signals.get("virality_summary")),
                "trend": _dict(signals.get("trend_research")),
                "safety": _dict(signals.get("safety")),
            },
            reasoning=BobaReasoningV1.model_validate(
                {key: value for key, value in explanation.items() if key != "confidence"}
            ),
            output_directive={
                "target_system": "frontend",
                "directive_type": "display_project_understanding",
                "parameters": {"advisory_only": True},
                "priority": 40,
                "constraints": ["Do not present advisory reasoning as applied editing."],
            },
            memory_application_v1=memory_application,
        )
        self.brain.register_decision(project_id, decision)
        if self.memory_enabled:
            build_and_save_project_memory(
                self.store,
                project_id,
                signals,
                decisions=self.store.list_decisions(project_id),
            )
        return self.store.load_brain_state(project_id) or state

    async def build_project_memory(self, project_id: str) -> BobaProjectMemoryV1:
        signals = await self.collect_project_signals(project_id)
        self._ensure_global_memory()
        return build_and_save_project_memory(
            self.store,
            project_id,
            signals,
            decisions=self.store.list_decisions(project_id),
        )

    def _build_and_save_whole_video(
        self, project_id: str, signals: dict[str, Any]
    ) -> BobaWholeVideoUnderstandingV1:
        memory = self.store.load_project_memory(project_id) if self.memory_enabled else None
        understanding = self.whole_video.build_from_signals(
            project_id,
            signals,
            memory=memory,
        )
        self.store.save_whole_video_understanding(understanding)
        if self.memory_enabled:
            summary = build_whole_video_memory_summary(understanding)
            self.store.save_record(whole_video_memory_record(summary))
        return understanding

    async def generate_whole_video_understanding(
        self, project_id: str
    ) -> BobaWholeVideoUnderstandingV1:
        signals = await self.collect_project_signals(project_id)
        return self._build_and_save_whole_video(project_id, signals)

    def _build_and_save_candidate_discovery(
        self, project_id: str, signals: dict[str, Any]
    ) -> BobaCandidateClipDiscoveryV1:
        memory = self.store.load_project_memory(project_id) if self.memory_enabled else None
        discovery = self.candidate_discovery.discover_from_signals(
            project_id,
            signals,
            memory=memory,
        )
        return self.store.save_candidate_clip_discovery(discovery)

    async def discover_candidate_clips(
        self, project_id: str
    ) -> BobaCandidateClipDiscoveryV1:
        signals = await self.collect_project_signals(project_id)
        return self._build_and_save_candidate_discovery(project_id, signals)

    def _build_and_save_clip_ranking(
        self,
        project_id: str,
        signals: dict[str, Any],
        discovery: BobaCandidateClipDiscoveryV1 | None,
    ) -> BobaDiscoveryClipRankingV1:
        memory = self.store.load_project_memory(project_id) if self.memory_enabled else None
        ranking = self.clip_ranking.rank_from_signals(
            project_id,
            signals,
            candidate_discovery=discovery,
            memory=memory,
        )
        return self.store.save_clip_ranking(ranking)

    async def rank_discovered_candidate_clips(
        self, project_id: str
    ) -> BobaDiscoveryClipRankingV1:
        signals = await self.collect_project_signals(project_id)
        discovery = self.store.load_candidate_clip_discovery(project_id)
        return self._build_and_save_clip_ranking(project_id, signals, discovery)

    def _build_and_save_editorial_decisions(
        self,
        project_id: str,
        signals: dict[str, Any],
        ranking: BobaDiscoveryClipRankingV1 | None,
        discovery: BobaCandidateClipDiscoveryV1 | None,
    ) -> BobaEditorialDecisionSetV1:
        memory = self.store.load_project_memory(project_id) if self.memory_enabled else None
        decisions = self.editorial_decision.decide_from_signals(
            project_id,
            signals,
            clip_ranking=ranking,
            candidate_discovery=discovery,
            creative_briefs=self.creative_director.list_briefs(project_id),
            memory=memory,
        )
        return self.store.save_editorial_decisions(decisions)

    async def generate_editorial_decisions(
        self, project_id: str
    ) -> BobaEditorialDecisionSetV1:
        signals = await self.collect_project_signals(project_id)
        ranking = self.store.load_clip_ranking(project_id)
        discovery = self.store.load_candidate_clip_discovery(project_id)
        return self._build_and_save_editorial_decisions(
            project_id,
            signals,
            ranking,
            discovery,
        )

    async def generate_explanations(self, project_id: str) -> BobaExplanationSetV1:
        signals = await self.collect_project_signals(project_id)
        understanding = self.store.load_whole_video_understanding(project_id)
        discovery = self.store.load_candidate_clip_discovery(project_id)
        ranking = self.store.load_clip_ranking(project_id)
        decisions = self.store.load_editorial_decisions(project_id)
        memory = self.store.load_project_memory(project_id) if self.memory_enabled else None
        explanations = self.explanation.explain_from_signals(
            project_id,
            signals,
            whole_video_understanding=understanding,
            candidate_discovery=discovery,
            clip_ranking=ranking,
            editorial_decisions=decisions,
            creative_briefs=self.creative_director.list_briefs(project_id),
            memory=memory,
        )
        return self.store.save_explanations(explanations)

    async def generate_creative_direction_v2(
        self, project_id: str
    ) -> BobaCreativeDirectionSetV2:
        signals = await self.collect_project_signals(project_id)
        decisions = self.store.load_editorial_decisions(project_id)
        ranking = self.store.load_clip_ranking(project_id)
        discovery = self.store.load_candidate_clip_discovery(project_id)
        understanding = self.store.load_whole_video_understanding(project_id)
        explanations = self.store.load_explanations(project_id)
        memory = self.store.load_project_memory(project_id) if self.memory_enabled else None
        direction = self.creative_director_v2.direct_from_signals(
            project_id,
            signals,
            editorial_decisions=decisions,
            clip_ranking=ranking,
            candidate_discovery=discovery,
            whole_video_understanding=understanding,
            explanations=explanations,
            memory=memory,
        )
        return self.store.save_creative_direction_v2(direction)

    async def generate_clip_briefs(self, project_id: str) -> BobaClipBriefSetV1:
        signals = await self.collect_project_signals(project_id)
        direction = self.store.load_creative_direction_v2(project_id)
        decisions = self.store.load_editorial_decisions(project_id)
        ranking = self.store.load_clip_ranking(project_id)
        discovery = self.store.load_candidate_clip_discovery(project_id)
        explanations = self.store.load_explanations(project_id)
        understanding = self.store.load_whole_video_understanding(project_id)
        memory = self.store.load_project_memory(project_id) if self.memory_enabled else None
        briefs = self.clip_brief_generator.generate_from_signals(
            project_id,
            signals,
            creative_direction_v2=direction,
            editorial_decisions=decisions,
            clip_ranking=ranking,
            candidate_discovery=discovery,
            explanations=explanations,
            whole_video_understanding=understanding,
            memory=memory,
        )
        return self.store.save_clip_briefs(briefs)

    async def generate_hook_retention(
        self, project_id: str
    ) -> BobaHookRetentionSetV1:
        signals = await self.collect_project_signals(project_id)
        briefs = self.store.load_clip_briefs(project_id)
        creative = self.store.load_creative_direction_v2(project_id)
        decisions = self.store.load_editorial_decisions(project_id)
        ranking = self.store.load_clip_ranking(project_id)
        discovery = self.store.load_candidate_clip_discovery(project_id)
        understanding = self.store.load_whole_video_understanding(project_id)
        explanations = self.store.load_explanations(project_id)
        memory = self.store.load_project_memory(project_id) if self.memory_enabled else None
        analysis = self.hook_retention_brain.analyze_from_signals(
            project_id,
            signals,
            clip_briefs=briefs,
            creative_direction_v2=creative,
            editorial_decisions=decisions,
            clip_ranking=ranking,
            candidate_discovery=discovery,
            whole_video_understanding=understanding,
            explanations=explanations,
            virality=_dict(signals.get("virality_summary")),
            memory=memory,
        )
        return self.store.save_hook_retention(analysis)

    async def generate_caption_motion(
        self,
        project_id: str,
    ) -> BobaCaptionMotionRecommendationSetV1:
        signals = await self.collect_project_signals(project_id)
        recommendations = self.caption_motion_brain.analyze_from_signals(
            project_id,
            signals,
            clip_briefs=self.store.load_clip_briefs(project_id),
            hook_retention=self.store.load_hook_retention(project_id),
            creative_direction_v2=self.store.load_creative_direction_v2(project_id),
            editorial_decisions=self.store.load_editorial_decisions(project_id),
            clip_ranking=self.store.load_clip_ranking(project_id),
            candidate_discovery=self.store.load_candidate_clip_discovery(project_id),
            whole_video_understanding=self.store.load_whole_video_understanding(
                project_id
            ),
            explanations=self.store.load_explanations(project_id),
            face_motion_validation=_dict(signals.get("face_motion_validation")),
            multi_speaker_validation=_dict(
                signals.get("multi_speaker_validation")
            ),
            analysis_signals=_dict(signals.get("analysis_signals_v2")),
            memory=(
                self.store.load_project_memory(project_id)
                if self.memory_enabled
                else None
            ),
        )
        return self.store.save_caption_motion(recommendations)

    async def generate_music_mood(
        self,
        project_id: str,
    ) -> BobaMusicMoodRecommendationSetV1:
        signals = await self.collect_project_signals(project_id)
        try:
            registry = load_music_assets(get_settings().rendering.asset_root)
        except (OSError, ValueError):
            manifest_metadata: dict[str, Any] = {}
        else:
            manifest_metadata = music_manifest_awareness(registry)
        recommendations = self.music_mood_brain.analyze_from_signals(
            project_id,
            signals,
            clip_briefs=self.store.load_clip_briefs(project_id),
            hook_retention=self.store.load_hook_retention(project_id),
            caption_motion=self.store.load_caption_motion(project_id),
            creative_direction_v2=self.store.load_creative_direction_v2(project_id),
            editorial_decisions=self.store.load_editorial_decisions(project_id),
            clip_ranking=self.store.load_clip_ranking(project_id),
            candidate_discovery=self.store.load_candidate_clip_discovery(project_id),
            whole_video_understanding=self.store.load_whole_video_understanding(
                project_id
            ),
            explanations=self.store.load_explanations(project_id),
            music_manifest_metadata=manifest_metadata,
            memory=(
                self.store.load_project_memory(project_id)
                if self.memory_enabled
                else None
            ),
        )
        return self.store.save_music_mood(recommendations)

    async def generate_experimentation_plan(
        self,
        project_id: str,
        *,
        creator_id: str = "local_creator",
        dry_run: bool = False,
    ) -> BobaExperimentationSetV1:
        project = await self.projects.get(project_id)
        if project is None:
            raise NotFoundError("Project was not found.", details={"id": project_id})
        experimentation = self.experimentation_system.analyze(
            project_id,
            source_id=project.link_ingestion_id or project_id,
            clip_briefs=self.store.load_clip_briefs(project_id),
            hook_retention=self.store.load_hook_retention(project_id),
            caption_motion=self.store.load_caption_motion(project_id),
            music_mood=self.store.load_music_mood(project_id),
            creative_direction=self.store.load_creative_direction_v2(project_id),
            editorial_decision=self.store.load_editorial_decisions(project_id),
            explanation=self.store.load_explanations(project_id),
            creator_learning=self.store.load_creator_learning(project_id),
            approval_rejection_learning=(
                self.store.load_approval_rejection_learning(project_id)
            ),
            boba_memory=(
                self.store.load_project_memory(project_id)
                if self.memory_enabled
                else None
            ),
            dry_run=dry_run,
        )
        if creator_id != "local_creator":
            experimentation.warnings = list(
                dict.fromkeys(
                    [
                        *experimentation.warnings,
                        (
                            "Creator identifier selected the local advisory context; "
                            "no cross-project profile data was copied."
                        ),
                    ]
                )
            )
        if dry_run:
            return experimentation
        return self.store.save_experimentation_plan(experimentation)

    def load_experimentation_plan(
        self,
        project_id: str,
    ) -> BobaExperimentationSetV1 | None:
        return self.store.load_experimentation_plan(project_id)

    def export_experimentation_plan(self, project_id: str) -> dict[str, Any]:
        return self.store.export_experimentation_plan(project_id)

    def reset_experimentation_plan(self, project_id: str) -> bool:
        return self.store.reset_experimentation_plan(project_id)

    def record_manual_experiment_result(
        self,
        project_id: str,
        *,
        experiment_id: str,
        selected_variant_id: str,
        manual_rating: float,
        outcome_label: BobaExperimentOutcomeLabel,
        creator_note: str = "",
        should_feed_learning: bool = False,
    ) -> BobaExperimentManualResultV1:
        experimentation = self.store.load_experimentation_plan(project_id)
        if experimentation is None:
            raise ValidationError(
                "BOBA experimentation plan is not available.",
                details={"project_id": project_id},
            )
        experiment = next(
            (
                item
                for item in experimentation.experiment_plans
                if item.experiment_id == experiment_id
            ),
            None,
        )
        if experiment is None:
            raise ValidationError(
                "BOBA experiment was not found.",
                details={
                    "project_id": project_id,
                    "experiment_id": experiment_id,
                },
            )
        try:
            result = self.experimentation_system.create_manual_result(
                experiment,
                selected_variant_id=selected_variant_id,
                manual_rating=manual_rating,
                outcome_label=outcome_label,
                creator_note=creator_note,
                should_feed_learning=should_feed_learning,
            )
        except ValueError as exc:
            raise ValidationError(
                "BOBA manual experiment result is invalid.",
                details={"reason": str(exc)},
            ) from exc
        return self.store.record_manual_experiment_result(project_id, result)

    async def apply_experiment_guidance_dry_run(
        self,
        project_id: str,
        *,
        creator_id: str = "local_creator",
    ) -> BobaExperimentationSetV1:
        return await self.generate_experimentation_plan(
            project_id,
            creator_id=creator_id,
            dry_run=True,
        )

    async def record_performance_feedback_event(
        self,
        project_id: str,
        *,
        event_type: BobaPerformanceEventType,
        target_type: BobaPerformanceTargetType,
        target_id: str,
        candidate_id: str = "",
        brief_id: str = "",
        experiment_id: str = "",
        variant_id: str = "",
        manual_rating: float | None = None,
        creator_note: str = "",
        platform: str = "",
        source_label: str = "manual_entry",
        metrics: BobaManualPerformanceMetricsV1 | None = None,
        retention_notes: str = "",
        creator_interpretation: str = "",
        outcome_label: BobaPerformanceOutcomeLabel | None = None,
        baseline_id: str = "",
        selected_variant_id: str = "",
        should_feed_learning: bool = False,
    ) -> tuple[BobaPerformanceFeedbackEventV1, BobaPerformanceFeedbackSetV1]:
        project = await self.projects.get(project_id)
        if project is None:
            raise NotFoundError("Project was not found.", details={"id": project_id})
        experimentation = self.store.load_experimentation_plan(project_id)
        if event_type == "manual_experiment_result":
            if experimentation is None:
                raise ValidationError(
                    "BOBA experimentation plan is required for experiment results.",
                    details={"project_id": project_id},
                )
            experiment = next(
                (
                    item
                    for item in experimentation.experiment_plans
                    if item.experiment_id == experiment_id
                ),
                None,
            )
            if experiment is None:
                raise ValidationError(
                    "BOBA experiment was not found.",
                    details={
                        "project_id": project_id,
                        "experiment_id": experiment_id,
                    },
                )
            valid_targets = {
                experiment.baseline.baseline_id,
                *(variant.variant_id for variant in experiment.variants),
            }
            chosen_id = selected_variant_id or variant_id
            if chosen_id and chosen_id not in valid_targets:
                raise ValidationError(
                    "Selected experiment baseline or variant was not found.",
                    details={"selected_variant_id": chosen_id},
                )
            candidate_id = candidate_id or experiment.candidate_id
            brief_id = brief_id or experiment.brief_id
            baseline_id = baseline_id or experiment.baseline.baseline_id
        event = self.performance_feedback_brain.create_event(
            project_id,
            event_type=event_type,
            target_type=target_type,
            target_id=target_id,
            candidate_id=candidate_id,
            brief_id=brief_id,
            experiment_id=experiment_id,
            variant_id=variant_id,
            manual_rating=manual_rating,
            creator_note=creator_note,
            platform=platform,
            source_label=source_label,
            metrics=metrics,
            retention_notes=retention_notes,
            creator_interpretation=creator_interpretation,
            outcome_label=outcome_label,
            baseline_id=baseline_id,
            selected_variant_id=selected_variant_id,
            should_feed_learning=should_feed_learning,
        )
        saved_event = self.store.record_performance_feedback_event(event)
        feedback = await self.generate_performance_feedback(project_id)
        return saved_event, feedback

    async def generate_content_scout_v2(
        self,
        project_id: str,
        *,
        manual_items: list[dict[str, Any]] | None = None,
        import_paths: list[str] | None = None,
        source_label: str = "manual",
        dry_run: bool = False,
    ) -> BobaContentScoutSetV2:
        project = await self.projects.get(project_id)
        if project is None:
            raise NotFoundError("Project was not found.", details={"id": project_id})
        scout = self.content_scout_v2.analyze(
            project_id,
            source_id=project.link_ingestion_id or project_id,
            manual_items=manual_items or [],
            import_paths=import_paths or [],
            source_label=source_label,
            creator_learning=self.store.load_creator_learning(project_id),
            approval_rejection_learning=(
                self.store.load_approval_rejection_learning(project_id)
            ),
            performance_feedback=self.store.load_performance_feedback(project_id),
            boba_memory=(
                self.store.load_project_memory(project_id)
                if self.memory_enabled
                else None
            ),
            scout_v1=self.scout.list_candidates(),
            dry_run=dry_run,
        )
        if dry_run:
            return scout
        return self.store.save_content_scout_v2(scout)

    def load_content_scout_v2(
        self,
        project_id: str,
    ) -> BobaContentScoutSetV2 | None:
        return self.store.load_content_scout_v2(project_id)

    def export_content_scout_v2(self, project_id: str) -> dict[str, Any]:
        return self.store.export_content_scout_v2(project_id)

    def reset_content_scout_v2(self, project_id: str) -> bool:
        return self.store.reset_content_scout_v2(project_id)

    async def generate_research_brain(
        self,
        project_id: str,
        *,
        manual_sources: list[dict[str, Any]] | None = None,
        pasted_text_entries: list[str | dict[str, Any]] | None = None,
        import_paths: list[str] | None = None,
        source_label: str = "manual",
        dry_run: bool = False,
    ) -> BobaResearchBrainSetV1:
        project = await self.projects.get(project_id)
        if project is None:
            raise NotFoundError("Project was not found.", details={"id": project_id})
        research = self.research_brain.analyze(
            project_id,
            source_id=project.link_ingestion_id or project_id,
            manual_sources=manual_sources or [],
            pasted_text_entries=pasted_text_entries or [],
            import_paths=import_paths or [],
            source_label=source_label,
            content_scout=self.store.load_content_scout_v2(project_id),
            creator_learning=self.store.load_creator_learning(project_id),
            approval_rejection_learning=(
                self.store.load_approval_rejection_learning(project_id)
            ),
            performance_feedback=self.store.load_performance_feedback(project_id),
            boba_memory=(
                self.store.load_project_memory(project_id)
                if self.memory_enabled
                else None
            ),
            dry_run=dry_run,
        )
        if dry_run:
            return research
        return self.store.save_research_brain(research)

    def load_research_brain(
        self,
        project_id: str,
    ) -> BobaResearchBrainSetV1 | None:
        return self.store.load_research_brain(project_id)

    def export_research_brain(self, project_id: str) -> dict[str, Any]:
        return self.store.export_research_brain(project_id)

    def reset_research_brain(self, project_id: str) -> bool:
        return self.store.reset_research_brain(project_id)

    async def generate_trend_topic_watcher(
        self,
        project_id: str,
        *,
        manual_snapshots: list[dict[str, Any]] | None = None,
        pasted_topic_lists: list[str | dict[str, Any]] | None = None,
        import_paths: list[str] | None = None,
        source_label: str = "manual",
        dry_run: bool = False,
    ) -> BobaTrendTopicWatcherSetV1:
        project = await self.projects.get(project_id)
        if project is None:
            raise NotFoundError("Project was not found.", details={"id": project_id})
        watcher = self.trend_topic_watcher.analyze(
            project_id,
            source_id=project.link_ingestion_id or project_id,
            manual_snapshots=manual_snapshots or [],
            pasted_topic_lists=pasted_topic_lists or [],
            import_paths=import_paths or [],
            source_label=source_label,
            research_brain=self.store.load_research_brain(project_id),
            content_scout=self.store.load_content_scout_v2(project_id),
            creator_learning=self.store.load_creator_learning(project_id),
            performance_feedback=self.store.load_performance_feedback(project_id),
            boba_memory=(
                self.store.load_project_memory(project_id)
                if self.memory_enabled
                else None
            ),
            dry_run=dry_run,
        )
        if dry_run:
            return watcher
        return self.store.save_trend_topic_watcher(watcher)

    def load_trend_topic_watcher(
        self,
        project_id: str,
    ) -> BobaTrendTopicWatcherSetV1 | None:
        return self.store.load_trend_topic_watcher(project_id)

    def export_trend_topic_watcher(self, project_id: str) -> dict[str, Any]:
        return self.store.export_trend_topic_watcher(project_id)

    def reset_trend_topic_watcher(self, project_id: str) -> bool:
        return self.store.reset_trend_topic_watcher(project_id)

    async def generate_candidate_video_scorer(
        self,
        project_id: str,
        *,
        manual_candidates: list[dict[str, Any]] | None = None,
        import_paths: list[str] | None = None,
        source_label: str = "manual",
        dry_run: bool = False,
    ) -> BobaCandidateVideoScorerSetV1:
        project = await self.projects.get(project_id)
        if project is None:
            raise NotFoundError(
                "Project was not found.",
                details={"id": project_id},
            )
        scorer = self.candidate_video_scorer.analyze(
            project_id,
            source_id=project.link_ingestion_id or project_id,
            manual_candidates=manual_candidates or [],
            import_paths=import_paths or [],
            source_label=source_label,
            content_scout=self.store.load_content_scout_v2(project_id),
            research_brain=self.store.load_research_brain(project_id),
            trend_topic_watcher=self.store.load_trend_topic_watcher(project_id),
            creator_learning=self.store.load_creator_learning(project_id),
            approval_rejection_learning=(
                self.store.load_approval_rejection_learning(project_id)
            ),
            performance_feedback=self.store.load_performance_feedback(project_id),
            boba_memory=(
                self.store.load_project_memory(project_id)
                if self.memory_enabled
                else None
            ),
            dry_run=dry_run,
        )
        if dry_run:
            return scorer
        return self.store.save_candidate_video_scorer(scorer)

    def load_candidate_video_scorer(
        self,
        project_id: str,
    ) -> BobaCandidateVideoScorerSetV1 | None:
        return self.store.load_candidate_video_scorer(project_id)

    def export_candidate_video_scorer(self, project_id: str) -> dict[str, Any]:
        return self.store.export_candidate_video_scorer(project_id)

    def reset_candidate_video_scorer(self, project_id: str) -> bool:
        return self.store.reset_candidate_video_scorer(project_id)

    async def generate_rights_permission_gate(
        self,
        project_id: str,
        *,
        manual_items: list[dict[str, Any]] | None = None,
        source_label: str = "manual",
        dry_run: bool = False,
    ) -> BobaRightsPermissionGateSetV1:
        project = await self.projects.get(project_id)
        if project is None:
            raise NotFoundError(
                "Project was not found.",
                details={"id": project_id},
            )
        gate = self.rights_permission_gate.analyze(
            project_id,
            source_id=project.link_ingestion_id or project_id,
            manual_items=manual_items or [],
            source_label=source_label,
            candidate_video_scorer=(
                self.store.load_candidate_video_scorer(project_id)
            ),
            content_scout=self.store.load_content_scout_v2(project_id),
            research_brain=self.store.load_research_brain(project_id),
            trend_topic_watcher=self.store.load_trend_topic_watcher(project_id),
            clip_briefs=self.store.load_clip_briefs(project_id),
            music_mood=self.store.load_music_mood(project_id),
            boba_memory=(
                self.store.load_project_memory(project_id)
                if self.memory_enabled
                else None
            ),
            dry_run=dry_run,
        )
        if dry_run:
            return gate
        return self.store.save_rights_permission_gate(gate)

    def load_rights_permission_gate(
        self,
        project_id: str,
    ) -> BobaRightsPermissionGateSetV1 | None:
        return self.store.load_rights_permission_gate(project_id)

    def export_rights_permission_gate(
        self,
        project_id: str,
    ) -> dict[str, Any]:
        return self.store.export_rights_permission_gate(project_id)

    def reset_rights_permission_gate(self, project_id: str) -> bool:
        return self.store.reset_rights_permission_gate(project_id)

    async def generate_observer_report(
        self,
        project_id: str,
        *,
        workflow_context: dict[str, Any] | None = None,
        dry_run: bool = False,
    ) -> BobaObserverSetV1:
        project = await self.projects.get(project_id)
        if project is None:
            raise NotFoundError(
                "Project was not found.",
                details={"id": project_id},
            )
        report = self.observer.analyze(
            project_id,
            source_id=project.link_ingestion_id or project_id,
            workflow_context=workflow_context,
            dry_run=dry_run,
        )
        if dry_run:
            return report
        return self.store.save_observer_report(report)

    def load_observer_report(
        self,
        project_id: str,
    ) -> BobaObserverSetV1 | None:
        return self.store.load_observer_report(project_id)

    def export_observer_report(self, project_id: str) -> dict[str, Any]:
        return self.store.export_observer_report(project_id)

    def reset_observer_report(self, project_id: str) -> bool:
        return self.store.reset_observer_report(project_id)

    async def generate_boba_error_doctor(
        self,
        project_id: str,
        *,
        diagnostic_context: dict[str, Any] | None = None,
        error_summaries: list[str | dict[str, Any]] | None = None,
        dry_run: bool = False,
    ) -> BobaErrorDoctorSetV1:
        project = await self.projects.get(project_id)
        if project is None:
            raise NotFoundError(
                "Project was not found.",
                details={"id": project_id},
            )
        report = self.error_doctor.analyze(
            project_id,
            self.store.load_observer_report(project_id),
            source_id=project.link_ingestion_id or project_id,
            manual_context=diagnostic_context,
            error_summaries=error_summaries,
            dry_run=dry_run,
        )
        if dry_run:
            return report
        return self.store.save_boba_error_doctor(report)

    def load_boba_error_doctor(
        self,
        project_id: str,
    ) -> BobaErrorDoctorSetV1 | None:
        return self.store.load_boba_error_doctor(project_id)

    def export_boba_error_doctor(self, project_id: str) -> dict[str, Any]:
        return self.store.export_boba_error_doctor(project_id)

    def reset_boba_error_doctor(self, project_id: str) -> bool:
        return self.store.reset_boba_error_doctor(project_id)

    async def generate_performance_feedback(
        self,
        project_id: str,
        *,
        dry_run: bool = False,
    ) -> BobaPerformanceFeedbackSetV1:
        project = await self.projects.get(project_id)
        if project is None:
            raise NotFoundError("Project was not found.", details={"id": project_id})
        feedback = self.performance_feedback_brain.analyze(
            project_id,
            self.store.list_performance_feedback_events(project_id),
            source_id=project.link_ingestion_id or project_id,
            experimentation=self.store.load_experimentation_plan(project_id),
            experiment_manual_results=(
                self.store.list_manual_experiment_results(project_id)
            ),
            creator_learning=self.store.load_creator_learning(project_id),
            approval_rejection_learning=(
                self.store.load_approval_rejection_learning(project_id)
            ),
            clip_briefs=self.store.load_clip_briefs(project_id),
            hook_retention=self.store.load_hook_retention(project_id),
            caption_motion=self.store.load_caption_motion(project_id),
            music_mood=self.store.load_music_mood(project_id),
            clip_ranking=self.store.load_clip_ranking(project_id),
            editorial_decision=self.store.load_editorial_decisions(project_id),
            boba_memory=(
                self.store.load_project_memory(project_id)
                if self.memory_enabled
                else None
            ),
            dry_run=dry_run,
        )
        if dry_run:
            return feedback
        return self.store.save_performance_feedback(feedback)

    def load_performance_feedback(
        self,
        project_id: str,
    ) -> BobaPerformanceFeedbackSetV1 | None:
        return self.store.load_performance_feedback(project_id)

    def export_performance_feedback(self, project_id: str) -> dict[str, Any]:
        return self.store.export_performance_feedback(project_id)

    def reset_performance_feedback(self, project_id: str) -> bool:
        return self.store.reset_performance_feedback(project_id)

    async def apply_performance_guidance_dry_run(
        self,
        project_id: str,
    ) -> BobaPerformanceFeedbackSetV1:
        return await self.generate_performance_feedback(
            project_id,
            dry_run=True,
        )

    async def generate_creative_briefs(
        self, project_id: str
    ) -> list[BobaCreativeBriefV1]:
        signals = await self.collect_project_signals(project_id)
        if not signals.get("whole_video_understanding") and signals.get(
            "transcript_segments"
        ):
            understanding = self._build_and_save_whole_video(project_id, signals)
            signals["whole_video_understanding"] = understanding.model_dump(mode="json")
            signals["whole_video_understanding_available"] = True
        creator_profile_id = (
            str(_dict(signals.get("creator_profile")).get("profile_id") or "")
            or None
        )
        return self.creative_director.create_briefs(
            project_id,
            signals,
            creator_profile_id=creator_profile_id,
        )

    async def rank_project_candidates(self, project_id: str) -> BobaClipRankingV1:
        signals = await self.collect_project_signals(project_id)
        candidates = [
            _dict(item) for item in _list(signals.get("planning_candidates")) if _dict(item)
        ]
        ranking = rank_candidates(
            project_id,
            candidates,
            used_source_ranges=_list(signals.get("already_selected_ranges")),
        )
        if self.memory_enabled:
            self._ensure_global_memory()
            if self.store.load_project_memory(project_id) is None:
                build_and_save_project_memory(
                    self.store,
                    project_id,
                    signals,
                    decisions=self.store.list_decisions(project_id),
                )
            creator_profile_id = (
                str(_dict(signals.get("creator_profile")).get("profile_id") or "")
                or None
            )
            clip_traits = [
                str(signals.get("content_niche") or "unknown"),
                *[str(item) for item in _list(signals.get("main_topics"))[:8]],
            ]
            retrieval = retrieve_for_clip_decision(
                self.store, project_id, clip_traits, creator_profile_id
            )
            application = create_memory_application(project_id, "ranking", retrieval)
            if any(
                item.get("field") == "emotional_payoff_advisory"
                for item in application.adjustments
            ):
                for insight in ranking.ranked_candidates:
                    delta = min(0.08, 0.08 * insight.emotional_strength)
                    insight.overall_recommendation = round(
                        min(1.0, insight.overall_recommendation + delta), 3
                    )
                    insight.reasons = list(
                        dict.fromkeys(
                            [
                                *insight.reasons,
                                "bounded creator-memory emotional-payoff advisory",
                            ]
                        )
                    )
                ranking.ranked_candidates.sort(
                    key=lambda item: item.overall_recommendation, reverse=True
                )
            ranking.memory_application_v1 = application
            if application.memory_used:
                ranking.reasoning_summary = (
                    f"{ranking.reasoning_summary} BOBA consulted "
                    f"{len(application.memory_used)} local memory record(s); "
                    "only bounded advisory adjustments were allowed."
                )[:800]
        self.store.save_candidate_ranking(ranking)
        return ranking

    async def generate_boba_for_clip(
        self, project_id: str, clip_id: str
    ) -> BobaEditorialPolicyV1:
        signals = await self.collect_clip_signals(project_id, clip_id)
        clip = _dict(signals.get("clip"))
        policy = create_editorial_policy(
            project_id,
            clip_id,
            clip,
            {
                "content_niche": signals.get("content_niche"),
                "transcript_available": signals.get("transcript_available"),
                "face_layout_available": signals.get("face_signals_available"),
                "music_available": True,
                "safety_status": signals.get("safety_status"),
                "manual_review_required": signals.get("safety_manual_review_required"),
            },
        )
        memory_application = None
        if self.memory_enabled:
            self._ensure_global_memory()
            if self.store.load_project_memory(project_id) is None:
                build_and_save_project_memory(
                    self.store,
                    project_id,
                    signals,
                    decisions=self.store.list_decisions(project_id),
                )
            creator_profile_id = (
                str(_dict(signals.get("creator_profile")).get("profile_id") or "")
                or None
            )
            retrieval = retrieve_for_editorial_policy(
                self.store, project_id, clip_id, creator_profile_id
            )
            memory_application = create_memory_application(
                project_id,
                "editorial_policy",
                retrieval,
                clip_id=clip_id,
            )
            policy.memory_application_v1 = memory_application
            if any(
                item.get("field") == "ending_hold_advisory"
                for item in memory_application.adjustments
            ):
                policy.ending_directives = {
                    **policy.ending_directives,
                    "memory_advisory": "preserve_payoff_tail",
                }
        self.store.save_editorial_policy(policy)
        explanation = explain_clip_selection(
            {
                **clip,
                "hook_strength": _dict(clip.get("scores")).get("hook"),
                "story_completeness": _dict(clip.get("scores")).get("story_completion"),
                "payoff_strength": _dict(clip.get("scores")).get("payoff"),
            },
            {
                "missing_signals": self.brain.assess_source_understanding(
                    project_id, signals
                ).missing_signals
            },
        )
        decision = BobaDecisionV1(
            decision_id=new_id("decision"),
            project_id=project_id,
            clip_id=clip_id,
            decision_type="editing_policy",
            question="How should this selected clip be edited?",
            answer=policy.explanation,
            confidence=policy.confidence,
            input_signals={
                "planning": clip,
                "story": _dict(signals.get("story_analysis_v2")),
                "virality": _dict(signals.get("virality_summary")),
                "safety": _dict(signals.get("safety")),
            },
            reasoning=BobaReasoningV1.model_validate(
                {key: value for key, value in explanation.items() if key != "confidence"}
            ),
            output_directive={
                "target_system": "editing",
                "directive_type": "editorial_policy_advisory",
                "parameters": policy.model_dump(mode="json"),
                "priority": 60,
                "constraints": policy.safety_constraints,
            },
            memory_application_v1=memory_application,
        )
        self.bus.register_decision(project_id, decision)
        return policy

    def attach_boba_to_unified_clip_intelligence(
        self,
        project_id: str,
        clip_id: str,
        unified: dict[str, Any],
    ) -> dict[str, Any]:
        brain = self.store.load_brain_state(project_id)
        ranking = self.store.load_candidate_ranking(project_id)
        policy = self.store.load_editorial_policy(project_id, clip_id)
        return {
            **unified,
            "boba": compact_boba_summary(
                brain=brain.model_dump(mode="json") if brain else None,
                ranking=ranking.model_dump(mode="json") if ranking else None,
                policy=policy.model_dump(mode="json") if policy else None,
            ),
        }
