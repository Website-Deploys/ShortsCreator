"""Stateful, offline advisory brain for BOBA Core Brain V1."""

from __future__ import annotations

from typing import Any

from olympus.boba.constitution import get_boba_constitution
from olympus.boba.contracts import (
    BobaBrainResultV1,
    BobaBrainStateV1,
    BobaDecisionContextV1,
    BobaDecisionV1,
    BobaGoalV1,
    BobaMode,
    BobaObservationV1,
    BobaProjectMemorySummaryV1,
    BobaSourceUnderstandingV1,
    now_iso,
)
from olympus.boba.memory import compact_strings
from olympus.boba.store import BobaMemoryStore
from olympus.platform.errors import NotFoundError
from olympus.utils import new_id


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _items(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


class BobaBrain:
    """Creates and updates explainable BOBA project state without executing edits."""

    def __init__(self, store: BobaMemoryStore, *, mode: BobaMode = "advise") -> None:
        self.store = store
        self.mode = mode
        self.constitution = get_boba_constitution()

    def assess_source_understanding(
        self, project_id: str, signals: dict[str, Any]
    ) -> BobaSourceUnderstandingV1:
        del project_id
        project = _dict(signals.get("project"))
        transcript = bool(signals.get("transcript_available"))
        visual = bool(signals.get("visual_signals_available"))
        speakers = bool(signals.get("speaker_signals_available"))
        trend = bool(signals.get("trend_signals_available"))
        safety = bool(signals.get("safety_signals_available"))
        personalization = bool(signals.get("personalization_signals_available"))
        availability = {
            "transcript": transcript,
            "visual_signals": visual,
            "face_detection": bool(signals.get("face_signals_available")),
            "speaker_segmentation": speakers,
            "trend_signals": trend,
            "safety_signals": safety,
            "personalization_signals": personalization,
        }
        missing = [name for name, available in availability.items() if not available]
        warnings = compact_strings(signals.get("warnings"), limit=24, max_chars=260)
        if signals.get("trend_fallback_used"):
            warnings.append("Trend research used a fallback rather than current live evidence.")
        if signals.get("safety_manual_review_required"):
            warnings.append("Safety metadata requires manual review; BOBA cannot override it.")
        if signals.get("render_manifest_available") is False:
            warnings.append("A validated render manifest is not available.")
        return BobaSourceUnderstandingV1(
            source_type=str(project.get("source_type") or signals.get("source_type") or "unknown"),
            duration_seconds=project.get("duration_seconds") or signals.get("duration_seconds"),
            transcript_available=transcript,
            visual_signals_available=visual,
            speaker_signals_available=speakers,
            trend_signals_available=trend,
            safety_signals_available=safety,
            personalization_signals_available=personalization,
            missing_signals=missing,
            warnings=list(dict.fromkeys(warnings)),
        )

    def build_decision_context(
        self, project_id: str, signals: dict[str, Any]
    ) -> BobaDecisionContextV1:
        del project_id
        profile = _dict(signals.get("creator_profile"))
        known = compact_strings(signals.get("known_limitations"), limit=24, max_chars=260)
        return BobaDecisionContextV1(
            creator_profile_id=str(profile.get("profile_id") or "") or None,
            creator_profile_name=str(profile.get("profile_name") or "") or None,
            content_niche=str(signals.get("content_niche") or "unknown"),
            target_platforms=compact_strings(
                signals.get("target_platforms") or ["youtube_shorts", "instagram_reels", "tiktok"],
                limit=8,
                max_chars=40,
            ),
            safety_status=str(signals.get("safety_status") or "unknown"),
            trend_provider_status=str(signals.get("trend_provider_status") or "unavailable"),
            personalization_status=str(
                signals.get("personalization_status") or "unavailable"
            ),
            known_limitations=known,
        )

    def create_active_goals(self, project_id: str, mode: BobaMode) -> list[BobaGoalV1]:
        goals = [
            (
                "complete_clips",
                "Find complete, high-retention Shorts without inventing evidence.",
                90,
                ["Preserve setup and payoff", "Reject unsupported fragments"],
            ),
            (
                "clip_diversity",
                "Avoid duplicate clips and repeated source information.",
                80,
                ["Detect overlaps", "Cover distinct source regions"],
            ),
            (
                "edit_readability",
                "Protect speech clarity and caption readability.",
                85,
                ["Speech remains primary", "Captions remain faithful"],
            ),
            (
                "safe_output",
                "Respect source rights, safety blockers, and manual review.",
                100,
                ["Never override blockers", "Never claim copyright safety"],
            ),
            (
                "explainability",
                f"Explain every material recommendation while operating in {mode} mode.",
                75,
                ["Include evidence", "Include confidence and risks"],
            ),
        ]
        return [
            BobaGoalV1(
                goal_id=f"{project_id}:{goal_type}",
                goal_type=goal_type,
                description=description,
                priority=priority,
                success_criteria=criteria,
            )
            for goal_type, description, priority, criteria in goals
        ]

    def _memory_summary(self, signals: dict[str, Any]) -> BobaProjectMemorySummaryV1:
        ranges = [
            {"start": float(item.get("start", 0.0)), "end": float(item.get("end", 0.0))}
            for item in _items(signals.get("already_selected_ranges"))
            if isinstance(item, dict)
        ][:100]
        rejected = [
            {"start": float(item.get("start", 0.0)), "end": float(item.get("end", 0.0))}
            for item in _items(signals.get("rejected_ranges"))
            if isinstance(item, dict)
        ][:100]
        return BobaProjectMemorySummaryV1(
            main_topics=compact_strings(signals.get("main_topics"), limit=20),
            speakers_or_roles=compact_strings(signals.get("speakers_or_roles"), limit=20),
            story_threads=compact_strings(signals.get("story_threads"), limit=20),
            emotional_moments=compact_strings(signals.get("emotional_moments"), limit=20),
            repeated_information=compact_strings(
                signals.get("repeated_information"), limit=20
            ),
            callbacks=compact_strings(signals.get("callbacks"), limit=20),
            unused_opportunities=compact_strings(
                signals.get("unused_opportunities"), limit=20
            ),
            already_selected_ranges=ranges,
            rejected_ranges=rejected,
            warnings=compact_strings(signals.get("memory_warnings"), limit=24),
        )

    def create_brain_state(
        self,
        project_id: str,
        signals: dict[str, Any],
    ) -> BobaBrainStateV1:
        source = self.assess_source_understanding(project_id, signals)
        context = self.build_decision_context(project_id, signals)
        safety_blocked = context.safety_status == "blocked"
        plans_available = bool(signals.get("planning_candidates_available"))
        editing_available = bool(signals.get("editing_timelines_available"))
        render_available = bool(signals.get("render_manifest_available"))
        blockers: list[str] = []
        if not source.transcript_available:
            blockers.append("Transcript evidence is unavailable for evidence-based clip planning.")
        if safety_blocked:
            blockers.append("Safety status is blocked and cannot be overridden by BOBA.")
        warnings = list(
            dict.fromkeys(
                [
                    *source.warnings,
                    *context.known_limitations,
                    "BOBA Core Brain V1 is advisory and does not execute or render edits.",
                ]
            )
        )
        readiness = BobaBrainResultV1(
            ready_for_planning=source.transcript_available and not safety_blocked,
            ready_for_editing=plans_available and not safety_blocked,
            ready_for_rendering=editing_available and render_available and not safety_blocked,
            blockers=blockers,
            warnings=warnings,
        )
        available_count = 7 - len(source.missing_signals)
        state = BobaBrainStateV1(
            brain_id=new_id("brain"),
            project_id=project_id,
            mode=self.mode,
            confidence=round(max(0.05, available_count / 7), 3),
            source_understanding=source,
            project_memory_summary=self._memory_summary(signals),
            decision_context=context,
            active_goals=self.create_active_goals(project_id, self.mode),
            observations=[
                BobaObservationV1(
                    observation_id=new_id("obs"),
                    project_id=project_id,
                    source="boba_brain",
                    observation_type="missing_signal",
                    summary=f"Missing signal: {name}",
                    evidence=["Persisted Olympus artifacts did not provide this signal."],
                    confidence=1.0,
                    safe_to_learn=False,
                )
                for name in source.missing_signals
            ],
            result=readiness,
        )
        self.store.save_brain_state(state)
        for observation in state.observations:
            self.store.append_observation(observation)
        return state

    def update_brain_state(
        self, project_id: str, observations: list[BobaObservationV1]
    ) -> BobaBrainStateV1:
        state = self.store.load_brain_state(project_id)
        if state is None:
            raise NotFoundError("BOBA brain state was not found.", details={"id": project_id})
        state.observations = [*state.observations, *observations][-500:]
        state.updated_at = now_iso()
        for observation in observations:
            self.store.append_observation(observation)
        self.store.save_brain_state(state)
        return state

    def register_decision(
        self, project_id: str, decision: BobaDecisionV1
    ) -> BobaBrainStateV1:
        state = self.store.load_brain_state(project_id)
        if state is None:
            raise NotFoundError("BOBA brain state was not found.", details={"id": project_id})
        state.decisions = [*state.decisions, decision][-500:]
        state.updated_at = now_iso()
        self.store.append_decision(decision)
        self.store.save_brain_state(state)
        return state

    def register_observation(
        self, project_id: str, observation: BobaObservationV1
    ) -> BobaBrainStateV1:
        return self.update_brain_state(project_id, [observation])

    def summarize_current_state(self, project_id: str) -> dict[str, Any]:
        state = self.store.load_brain_state(project_id)
        if state is None:
            raise NotFoundError("BOBA brain state was not found.", details={"id": project_id})
        return {
            "brain_id": state.brain_id,
            "project_id": state.project_id,
            "version": state.version,
            "mode": state.mode,
            "confidence": state.confidence,
            "understanding": (
                f"{len(state.project_memory_summary.main_topics)} topic(s), "
                f"{len(state.source_understanding.missing_signals)} missing signal(s)"
            ),
            "missing_signals": state.source_understanding.missing_signals,
            "ready": state.result.model_dump(mode="json"),
            "decision_count": len(self.store.list_decisions(project_id)),
            "observation_count": len(self.store.list_observations(project_id)),
            "constitution_version": self.constitution["version"],
        }
