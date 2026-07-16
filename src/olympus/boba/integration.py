"""Read existing Olympus artifacts and build bounded BOBA advisory context."""

from __future__ import annotations

import json
from typing import Any

from olympus.boba.brain import BobaBrain
from olympus.boba.contracts import (
    BobaBrainStateV1,
    BobaClipRankingV1,
    BobaDecisionV1,
    BobaEditorialPolicyV1,
    BobaReasoningV1,
)
from olympus.boba.decision_bus import BobaDecisionBus
from olympus.boba.editorial_policy import create_editorial_policy
from olympus.boba.ranking import rank_candidates
from olympus.boba.reasoning import explain_clip_selection, summarize_project_understanding
from olympus.boba.store import BobaMemoryStore
from olympus.boba.validation import compact_boba_summary
from olympus.data.repositories.project_repository import StorageProjectRepository
from olympus.domain.contracts.storage import StoragePort
from olympus.personalization import apply as personalization
from olympus.platform.errors import NotFoundError
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
    ) -> None:
        self.storage = storage
        self.projects = StorageProjectRepository(storage)
        self.store = store
        self.brain = BobaBrain(store, mode=mode)  # type: ignore[arg-type]
        self.bus = BobaDecisionBus(store)

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
        transcript_available = bool(
            segments
            or speech_data.get("transcript")
            or speech_data.get("text")
            or (speech.get("status") == "completed" and speech_data)
        )
        face_available = face.get("status") == "completed" and bool(_data(face))
        speaker_available = speakers.get("status") == "completed" and bool(_data(speakers))
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
            "unused_opportunities": [
                str(item.get("summary") or item.get("reason") or "")
                for item in _list(story_data.get("recommended_clip_stories"))
                if isinstance(item, dict)
            ][:20],
            "warnings": warnings,
            "known_limitations": list(dict.fromkeys(known_limitations)),
            "planning_candidates": candidates or plans,
            "selected_plans": plans,
            "story_analysis_v2": story_data,
            "virality_summary": _data(virality),
            "trend_research": trend_data,
            "safety": safety,
            "creator_profile": _dict(personalization_directives),
            "story_summary": summary_data,
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
        state = self.brain.create_brain_state(project_id, signals)
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
        )
        self.brain.register_decision(project_id, decision)
        return self.store.load_brain_state(project_id) or state

    async def rank_project_candidates(self, project_id: str) -> BobaClipRankingV1:
        signals = await self.collect_project_signals(project_id)
        candidates = [
            _dict(item) for item in _list(signals.get("planning_candidates")) if _dict(item)
        ]
        ranking = rank_candidates(
            project_id,
            candidates,
        )
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
