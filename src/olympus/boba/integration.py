"""Read existing Olympus artifacts and build bounded BOBA advisory context."""

from __future__ import annotations

import json
from typing import Any

from olympus.boba.approvals import BobaApprovalService
from olympus.boba.brain import BobaBrain
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
from olympus.boba.contracts import (
    BobaBrainStateV1,
    BobaClipRankingV1,
    BobaDecisionV1,
    BobaEditorialPolicyV1,
    BobaReasoningV1,
)
from olympus.boba.creative_director import BobaCreativeBriefV1, BobaCreativeDirector
from olympus.boba.decision_bus import BobaDecisionBus
from olympus.boba.editorial_decision import (
    BobaEditorialDecisionEngine,
    BobaEditorialDecisionSetV1,
)
from olympus.boba.editorial_policy import create_editorial_policy
from olympus.boba.global_memory import build_and_save_global_memory
from olympus.boba.memory_application import create_memory_application
from olympus.boba.memory_contracts import BobaProjectMemoryV1
from olympus.boba.memory_retrieval import (
    retrieve_for_clip_decision,
    retrieve_for_editorial_policy,
    retrieve_for_project,
)
from olympus.boba.project_memory import build_and_save_project_memory
from olympus.boba.ranking import rank_candidates
from olympus.boba.reasoning import explain_clip_selection, summarize_project_understanding
from olympus.boba.scout import BobaScout
from olympus.boba.store import BobaMemoryStore
from olympus.boba.validation import compact_boba_summary
from olympus.boba.whole_video import (
    BobaWholeVideoUnderstandingEngine,
    BobaWholeVideoUnderstandingV1,
    build_whole_video_memory_summary,
    whole_video_memory_record,
)
from olympus.data.repositories.project_repository import StorageProjectRepository
from olympus.domain.contracts.storage import StoragePort
from olympus.personalization import apply as personalization
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
        self.creative_director = BobaCreativeDirector(store)
        self.whole_video = BobaWholeVideoUnderstandingEngine()
        self.candidate_discovery = BobaCandidateClipDiscoveryEngine()
        self.clip_ranking = BobaClipRankingEngine()
        self.editorial_decision = BobaEditorialDecisionEngine()
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
