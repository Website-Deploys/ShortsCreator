"""Run one offline R&D scenario across BOBA Core and Memory V1."""

from __future__ import annotations

import argparse
import asyncio
import json
import socket
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, NoReturn
from unittest.mock import patch

from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from olympus.api.v1.routes import boba as boba_routes  # noqa: E402
from olympus.boba import (  # noqa: E402
    BobaBrainStateV1,
    BobaDecisionV1,
    BobaIntegration,
    BobaMemoryStore,
    BobaObservationV1,
)
from olympus.boba.contracts import BobaReasoningV1  # noqa: E402
from olympus.boba.creator_memory import build_and_save_creator_memory  # noqa: E402
from olympus.boba.global_memory import build_and_save_global_memory  # noqa: E402
from olympus.boba.memory_application import create_memory_application  # noqa: E402
from olympus.boba.memory_contracts import (  # noqa: E402
    BobaMemoryQueryV1,
    BobaMemoryRecordV1,
)
from olympus.boba.memory_learning import BobaMemoryLearner  # noqa: E402
from olympus.boba.memory_validation import (  # noqa: E402
    truncate_safe_excerpt,
    validate_memory_record,
)
from olympus.boba.reasoning import explain_clip_selection  # noqa: E402
from olympus.boba.validation import validate_constitution  # noqa: E402
from olympus.data.repositories import StorageProjectRepository  # noqa: E402
from olympus.data.storage.local import LocalStorage  # noqa: E402
from olympus.domain.entities.project import Project, ProjectStatus  # noqa: E402
from olympus.personalization import apply as personalization_apply  # noqa: E402
from olympus.personalization.contracts import (  # noqa: E402
    ClipFeedbackV2,
    FeedbackLabels,
    FeedbackRating,
    SafeLearning,
)
from olympus.personalization.presets import profile_from_preset  # noqa: E402
from olympus.platform.config import Settings  # noqa: E402
from olympus.platform.config.settings import Environment  # noqa: E402
from olympus.platform.errors import ValidationError  # noqa: E402
from olympus.utils import utc_now  # noqa: E402

REPORT_DIRECTORY = Path("work/rnd_validation/boba_integrated")
REPORT_JSON = "rnd_boba_integrated_report.json"
REPORT_MARKDOWN = "rnd_boba_integrated_summary.md"
CREATOR_PROFILE_ID = "rnd_creator"
TOP_CLIP_ID = "rnd_clip_top"


class RndBobaIntegratedReport(BaseModel):
    """JSON-safe truth report for the single integrated R&D scenario."""

    model_config = ConfigDict(extra="forbid")

    passed: bool = False
    mode: str = "rnd_integrated"
    project_id: str
    brain_created: bool = False
    decision_bus_checked: bool = False
    ranking_checked: bool = False
    editorial_policy_checked: bool = False
    project_memory_checked: bool = False
    creator_memory_checked: bool = False
    global_memory_checked: bool = False
    retrieval_checked: bool = False
    learning_checked: bool = False
    memory_application_checked: bool = False
    integration_checked: bool = False
    api_surface_checked: bool = False
    frontend_types_checked: bool = False
    unsafe_content_blocked: bool = False
    external_calls_made: bool = False
    real_media_used: bool = False
    production_projects_modified: bool = False
    constitution_checked: bool = False
    contracts_checked: bool = False
    reasoning_checked: bool = False
    observations_created: int = Field(default=0, ge=0)
    decisions_created: int = Field(default=0, ge=0)
    compact_truth_attached: bool = False
    long_excerpt_truncated: bool = False
    cli_surface_checked: bool = False
    subsystem_results: dict[str, bool] = Field(default_factory=dict)
    report_paths: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


def _project_id() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
    return f"rnd_boba_project_{stamp}"


def _synthetic_project(project_id: str) -> Project:
    now = utc_now()
    return Project(
        id=project_id,
        name="BOBA Integrated R&D Scenario",
        source_filename="synthetic_rnd_source.json",
        storage_key=f"rnd_sources/{project_id}/synthetic_rnd_source.json",
        size_bytes=0,
        video_format="synthetic",
        content_type="application/json",
        duration_seconds=180.0,
        width=None,
        height=None,
        status=ProjectStatus.ANALYZED,
        created_at=now,
        updated_at=now,
        source_type="rnd_synthetic",
        content_category="education",
    )


def _candidates() -> list[dict[str, Any]]:
    return [
        {
            "candidate_id": TOP_CLIP_ID,
            "clip_id": TOP_CLIP_ID,
            "start": 12.0,
            "end": 44.0,
            "source_start": 12.0,
            "source_end": 44.0,
            "hook_line": "The mistake is not a lack of discipline.",
            "payoff_line": "Make the first useful action easier than the distraction.",
            "hook_type": "curiosity_gap",
            "hook_category": "contrarian_insight",
            "story_shape": "problem_turn_solution",
            "content_niche": "education",
            "music_mood": "warm_motivational",
            "hook_strength": 0.94,
            "emotional_strength": 0.82,
            "emotion": 0.82,
            "context_requirement": 0.08,
            "editing_opportunity": 0.88,
            "boundary_quality": 0.94,
            "scores": {
                "hook": 0.94,
                "story_completion": 0.93,
                "payoff": 0.92,
                "curiosity": 0.87,
                "emotion": 0.82,
                "creator_fit": 0.83,
                "trend_fit": 0.62,
            },
            "blueprint": {
                "hook_analysis_v2": {
                    "hook_line": "The mistake is not a lack of discipline.",
                    "score": 0.94,
                    "curiosity_strength": 0.87,
                },
                "story_v2_guidance": {
                    "completeness_score": 0.93,
                    "payoff_strength": 0.92,
                    "context_risk": 0.08,
                    "payoff": "A practical environment-design lesson.",
                },
            },
        },
        {
            "candidate_id": "rnd_clip_weak",
            "clip_id": "rnd_clip_weak",
            "start": 55.0,
            "end": 75.0,
            "source_start": 55.0,
            "source_end": 75.0,
            "hook_line": "There is another detail.",
            "payoff_line": "",
            "hook_type": "generic_statement",
            "story_shape": "fragment",
            "content_niche": "education",
            "hook_strength": 0.38,
            "emotional_strength": 0.25,
            "context_requirement": 0.82,
            "editing_opportunity": 0.35,
            "boundary_quality": 0.25,
            "boundary_risk": True,
            "ends_mid_sentence": True,
            "scores": {
                "hook": 0.38,
                "story_completion": 0.24,
                "payoff": 0.08,
                "curiosity": 0.3,
                "emotion": 0.25,
                "creator_fit": 0.35,
                "trend_fit": 0.2,
            },
        },
    ]


async def _put_stage(
    storage: LocalStorage,
    engine: str,
    project_id: str,
    stage: str,
    *,
    status: str,
    data: dict[str, Any],
    warnings: list[str] | None = None,
) -> None:
    payload = {
        "stage": stage,
        "status": status,
        "data": data,
        "warnings": warnings or [],
    }
    await storage.put(
        f"{engine}/{project_id}/stages/{stage}.json",
        json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        content_type="application/json",
    )


async def _seed_synthetic_artifacts(storage: LocalStorage, project_id: str) -> None:
    candidates = _candidates()
    await StorageProjectRepository(storage).save(_synthetic_project(project_id))
    await _put_stage(
        storage,
        "analysis",
        project_id,
        "speech_transcription",
        status="completed",
        data={
            "summary": "A synthetic lesson about reducing friction around useful habits.",
            "segments": [
                {
                    "start": 12.0,
                    "end": 18.0,
                    "text": "The mistake is not a lack of discipline.",
                },
                {
                    "start": 36.0,
                    "end": 44.0,
                    "text": "Make the first useful action easier than the distraction.",
                },
            ],
            "language": "en",
        },
    )
    await _put_stage(
        storage,
        "analysis",
        project_id,
        "video_inspection",
        status="completed",
        data={"duration": 180.0, "width": 1920, "height": 1080, "synthetic": True},
    )
    await _put_stage(
        storage,
        "analysis",
        project_id,
        "scene_detection",
        status="completed",
        data={"scenes": [{"start": 0.0, "end": 90.0}, {"start": 90.0, "end": 180.0}]},
    )
    await _put_stage(
        storage,
        "analysis",
        project_id,
        "face_detection",
        status="unavailable",
        data={},
        warnings=["Synthetic R&D scenario intentionally omits face detections."],
    )
    await _put_stage(
        storage,
        "analysis",
        project_id,
        "speaker_segmentation",
        status="unavailable",
        data={},
        warnings=["Synthetic R&D scenario intentionally omits speaker segmentation."],
    )
    await _put_stage(
        storage,
        "story",
        project_id,
        "story_analysis_v2",
        status="completed",
        data={
            "topic_sections": [
                {
                    "title": "Why habits fail",
                    "start": 0.0,
                    "end": 88.0,
                    "summary": "Friction shapes behavior more reliably than motivation.",
                },
                {
                    "title": "A practical redesign",
                    "start": 88.0,
                    "end": 180.0,
                    "summary": "Change the environment to make the useful action easier.",
                },
            ],
            "micro_stories": [
                {
                    "story_id": "rnd_story_complete",
                    "start": 12.0,
                    "end": 44.0,
                    "one_sentence_summary": "A false belief turns into a practical solution.",
                    "setup": "People blame discipline.",
                    "tension": "Willpower keeps failing.",
                    "turning_point": "The environment creates the real friction.",
                    "payoff": "Make the useful action easier than the distraction.",
                    "ending": "A complete actionable lesson.",
                    "completeness_score": 0.93,
                    "context_risk": 0.08,
                }
            ],
            "recommended_clip_stories": [
                {
                    "story_id": "rnd_story_followup",
                    "start": 112.0,
                    "end": 145.0,
                    "summary": "A second synthetic example remains available.",
                }
            ],
        },
    )
    await _put_stage(
        storage,
        "story",
        project_id,
        "story_summary",
        status="completed",
        data={
            "summary": "A problem-turn-solution explanation about designing better habits.",
            "primary_story_shape": "problem_turn_solution",
        },
    )
    await _put_stage(
        storage,
        "story",
        project_id,
        "emotional_turning_points",
        status="completed",
        data={
            "turning_points": [
                {
                    "time": 29.0,
                    "description": "Blame shifts from willpower to environmental friction.",
                }
            ]
        },
    )
    await _put_stage(
        storage,
        "virality",
        project_id,
        "virality_summary",
        status="completed",
        data={
            "overall_score": 0.84,
            "hook_score": 0.94,
            "retention_score": 0.82,
            "story_score": 0.93,
            "payoff_score": 0.92,
            "why_this_can_work": "A contrarian opening resolves into a specific action.",
            "confidence": 0.78,
        },
    )
    await _put_stage(
        storage,
        "virality",
        project_id,
        "trend_research",
        status="completed",
        data={
            "internet_trend_research_v2": {
                "status": "fallback",
                "fallback_used": True,
                "provider": "evergreen",
                "detected_niche": "education",
                "patterns": ["contrarian lesson", "practical payoff"],
            }
        },
        warnings=["No internet trend provider was called; deterministic fallback used."],
    )
    await _put_stage(
        storage,
        "planning",
        project_id,
        "clip_scoring",
        status="completed",
        data={"candidates": candidates},
    )
    await _put_stage(
        storage,
        "planning",
        project_id,
        "ranking",
        status="completed",
        data={
            "plans": [
                {
                    "plan_id": "rnd_prior_plan",
                    "clip_id": "rnd_prior_clip",
                    "start": 120.0,
                    "end": 145.0,
                    "hook_line": "A separate synthetic example.",
                    "selected_reason": "Maintains timeline diversity in the scenario.",
                    "story_shape": "example_lesson",
                    "hook_category": "specific_example",
                    "content_niche": "education",
                    "confidence": 0.72,
                }
            ],
            "over_target": [
                {
                    **candidates[1],
                    "reason": "Missing payoff and dependent on outside context.",
                    "confidence": 0.82,
                }
            ],
        },
    )
    await _put_stage(
        storage,
        "planning",
        project_id,
        "planning_summary",
        status="completed",
        data={
            "content_niche": {"niche": "education", "confidence": 0.88},
            "planned_clip_count": 1,
            "expected_output_reason": "One complete candidate and one weak fragment.",
        },
    )
    await _put_stage(
        storage,
        "editing",
        project_id,
        "timeline_validation",
        status="completed",
        data={
            "timelines": [
                {
                    "timeline_id": "rnd_timeline_top",
                    "clip_id": TOP_CLIP_ID,
                    "duration": 32.0,
                    "hook_treatment": "clean_punch_in",
                    "caption_style": "bold_hook_then_clean",
                    "music_mood": "warm_motivational",
                    "ending_hold": 0.5,
                    "applied": False,
                }
            ],
            "validation": {"passed": True, "synthetic_only": True},
        },
    )
    await _put_stage(
        storage,
        "optimization",
        project_id,
        "copyright_safety_v2",
        status="completed",
        data={
            "result": {
                "risk_level": "medium",
                "manual_review_required": True,
                "upload_readiness": "manual_review",
            },
            "manual_review": {"required": True},
            "warnings": ["Synthetic rights status is intentionally not declared safe."],
        },
    )


def _feedback(project_id: str) -> ClipFeedbackV2:
    return ClipFeedbackV2(
        feedback_id="rnd_feedback_explicit",
        profile_id=CREATOR_PROFILE_ID,
        project_id=project_id,
        clip_id=TOP_CLIP_ID,
        rating=FeedbackRating(overall="like", music="dislike"),
        labels=FeedbackLabels(liked=True, music_bad=True),
        notes="The emotional payoff works; keep music lower than speech.",
        extracted_safe_learning=SafeLearning(
            liked_clip_traits=["emotional_payoff"],
            disliked_music_moods=["high_intensity"],
        ),
    )


@contextmanager
def _network_guard(attempts: list[str]) -> Iterator[None]:
    def blocked_connect(_sock: socket.socket, address: object) -> NoReturn:
        attempts.append(str(address))
        raise RuntimeError("External network access is blocked in BOBA R&D validation.")

    def blocked_create_connection(address: object, *_args: Any, **_kwargs: Any) -> NoReturn:
        attempts.append(str(address))
        raise RuntimeError("External network access is blocked in BOBA R&D validation.")

    with (
        patch.object(socket.socket, "connect", blocked_connect),
        patch.object(socket.socket, "connect_ex", blocked_connect),
        patch("socket.create_connection", blocked_create_connection),
    ):
        yield


def _set_check(
    report: RndBobaIntegratedReport,
    field: str,
    passed: bool,
    failure: str,
) -> None:
    value = bool(passed)
    setattr(report, field, value)
    report.subsystem_results[field] = value
    if not value:
        report.errors.append(failure)


def _frontend_surface_checked(source_root: Path) -> bool:
    types_path = source_root / "frontend/src/lib/types.ts"
    panel_path = source_root / "frontend/src/components/project/ResultsSection.tsx"
    if not types_path.is_file() or not panel_path.is_file():
        return False
    types = types_path.read_text(encoding="utf-8")
    panel = panel_path.read_text(encoding="utf-8")
    return all(
        marker in types
        for marker in ("BobaProjectMemoryV1", "BobaCreatorMemoryV1", "BobaGlobalMemoryV1")
    ) and all(marker in panel for marker in ("BOBA Brain Summary", "BOBA Memory", "Memory used:"))


def _cli_surface_checked(source_root: Path) -> bool:
    parsed = _parser().parse_args(["--all"])
    return bool(
        parsed.all
        and (source_root / "tools/validate_boba_core.py").is_file()
        and (source_root / "tools/validate_boba_memory.py").is_file()
        and Path(__file__).name == "validate_rnd_boba_integrated.py"
    )


async def _run_scenario(
    report: RndBobaIntegratedReport,
    scenario_root: Path,
    source_root: Path,
) -> None:
    network_attempts: list[str] = []
    storage = LocalStorage(root=str(scenario_root / "storage"))
    store = BobaMemoryStore(
        scenario_root / "boba",
        memory_root=scenario_root / "boba_memory",
        max_excerpt_chars=120,
    )
    integration = BobaIntegration(storage, store, memory_enabled=False)
    profile = profile_from_preset(
        "balanced_default",
        profile_id=CREATOR_PROFILE_ID,
        profile_name="R&D Synthetic Creator",
        learning_enabled=True,
    )
    personalization_directives = {
        "profile_id": profile.profile_id,
        "profile_name": profile.profile_name,
        "confidence": 0.65,
        "feedback_count": 1,
        "learning_enabled": True,
        "clip_selection": {"prefer_emotional_payoff": True},
        "music": {"music_presence": "low", "max_loudness": -20.0},
        "privacy": {
            "local_only": True,
            "explicit_feedback_only": True,
            "no_cloud_sync": True,
        },
    }

    try:
        with (
            _network_guard(network_attempts),
            patch.object(
                personalization_apply,
                "load_runtime_directives",
                return_value=personalization_directives,
            ),
        ):
            await _seed_synthetic_artifacts(storage, report.project_id)
            signals = await integration.collect_project_signals(report.project_id)

            _set_check(
                report,
                "constitution_checked",
                not validate_constitution(),
                "BOBA Constitution validation failed.",
            )

            brain = await integration.generate_boba_for_project(report.project_id)
            brain_round_trip = BobaBrainStateV1.model_validate_json(brain.model_dump_json())
            query_round_trip = BobaMemoryQueryV1.model_validate_json(
                BobaMemoryQueryV1(
                    project_id=report.project_id,
                    target_system="planning",
                    reason="R&D contract round trip.",
                ).model_dump_json()
            )
            _set_check(
                report,
                "contracts_checked",
                brain_round_trip.project_id == report.project_id
                and query_round_trip.project_id == report.project_id,
                "BOBA Core or Memory contract JSON round trip failed.",
            )
            _set_check(
                report,
                "brain_created",
                bool(
                    brain.brain_id
                    and brain.project_id == report.project_id
                    and "face_detection" in brain.source_understanding.missing_signals
                    and "speaker_segmentation" in brain.source_understanding.missing_signals
                    and brain.source_understanding.transcript_available
                ),
                "Integrated brain state was not created with honest missing-signal warnings.",
            )

            observation = BobaObservationV1(
                observation_id="rnd_observation_story_payoff",
                project_id=report.project_id,
                source="rnd_integrated_validator",
                observation_type="candidate_pattern",
                summary="The complete synthetic candidate preserves its practical payoff.",
                evidence=["Story completeness 0.93", "Payoff strength 0.92"],
                confidence=0.9,
                safe_to_learn=True,
            )
            integration.brain.register_observation(report.project_id, observation)
            report.observations_created = len(store.list_observations(report.project_id))
            report.subsystem_results["observations_created"] = report.observations_created >= 3
            if report.observations_created < 3:
                report.errors.append(
                    "Expected missing-signal and explicit observations were absent."
                )

            reasoning_payload = explain_clip_selection(
                {
                    "hook_strength": 0.94,
                    "story_completeness": 0.93,
                    "payoff_strength": 0.92,
                    "duplicate_risk": 0.0,
                },
                {"missing_signals": brain.source_understanding.missing_signals},
            )
            reasoning = BobaReasoningV1.model_validate(
                {key: value for key, value in reasoning_payload.items() if key != "confidence"}
            )
            _set_check(
                report,
                "reasoning_checked",
                bool(reasoning.evidence and reasoning.tradeoffs and reasoning.risks),
                "BOBA reasoning did not preserve evidence, tradeoffs, and missing-signal risks.",
            )

            decision = BobaDecisionV1(
                decision_id="rnd_decision_rank_top",
                project_id=report.project_id,
                clip_id=TOP_CLIP_ID,
                decision_type="clip_candidate_ranking",
                question="Which synthetic candidate should BOBA recommend?",
                answer="Recommend the complete story candidate while keeping advice non-executing.",
                confidence=0.9,
                input_signals={
                    "story": {"completeness": 0.93, "payoff": 0.92},
                    "planning": {"candidate_id": TOP_CLIP_ID},
                },
                reasoning=reasoning,
                output_directive={
                    "target_system": "planning",
                    "directive_type": "candidate_ranking_advisory",
                    "parameters": {"candidate_id": TOP_CLIP_ID, "advisory_only": True},
                    "priority": 70,
                    "constraints": ["Do not execute edits", "Never override safety"],
                },
            )
            route = integration.bus.register_decision(report.project_id, decision)
            report.decisions_created = len(store.list_decisions(report.project_id))
            _set_check(
                report,
                "decision_bus_checked",
                route.get("delivery") == "advisory"
                and route.get("consumed") is False
                and report.decisions_created >= 2,
                "BOBA Decision Bus did not validate, persist, and route advisory-only output.",
            )

            project_memory = await integration.build_project_memory(report.project_id)
            _set_check(
                report,
                "project_memory_checked",
                bool(
                    project_memory.project_id == report.project_id
                    and project_memory.candidate_count == 2
                    and project_memory.selected_clip_ids
                    and project_memory.rejected_clip_ids
                    and store.load_project_memory(report.project_id) is not None
                ),
                "BOBA Project Memory did not preserve synthetic planning outcomes.",
            )

            feedback = _feedback(report.project_id)
            learned = BobaMemoryLearner(store).learn_from_feedback(feedback)
            _set_check(
                report,
                "learning_checked",
                learned.source == "explicit_user_feedback"
                and learned.creator_profile_id == CREATOR_PROFILE_ID,
                "BOBA Learning did not create a record from explicit fake feedback.",
            )
            creator_memory = build_and_save_creator_memory(store, profile, [feedback])
            _set_check(
                report,
                "creator_memory_checked",
                bool(
                    creator_memory.explicit_feedback_only
                    and creator_memory.feedback_count == 1
                    and store.load_creator_memory(CREATOR_PROFILE_ID) is not None
                ),
                "BOBA Creator Memory was not built from explicit fake feedback.",
            )
            global_memory = build_and_save_global_memory(store)
            _set_check(
                report,
                "global_memory_checked",
                bool(
                    global_memory.principles
                    and global_memory.safety_principles
                    and store.load_global_memory() is not None
                ),
                "BOBA Global Memory safe seed was not created.",
            )

            retrieval = store.query_memory(
                BobaMemoryQueryV1(
                    project_id=report.project_id,
                    creator_profile_id=CREATOR_PROFILE_ID,
                    content_niche="education",
                    clip_traits=["emotional_payoff", "practical lesson"],
                    target_system="ranking",
                    tags=["education"],
                    reason="Integrated R&D ranking advice.",
                )
            )
            _set_check(
                report,
                "retrieval_checked",
                bool(
                    retrieval.records
                    and any(item.scope == "project" for item in retrieval.records)
                    and any(item.scope == "creator" for item in retrieval.records)
                    and any(item.scope == "global" for item in retrieval.records)
                ),
                "BOBA Retrieval did not combine project, creator, and global memory.",
            )
            direct_application = create_memory_application(
                report.project_id,
                "ranking",
                retrieval,
                clip_id=TOP_CLIP_ID,
            )
            _set_check(
                report,
                "memory_application_checked",
                bool(
                    direct_application.memory_used
                    and any(
                        adjustment.get("field") == "emotional_payoff_advisory"
                        for adjustment in direct_application.adjustments
                    )
                ),
                "BOBA Memory Application did not produce bounded emotional-payoff advice.",
            )

            integration.memory_enabled = True
            ranking = await integration.rank_project_candidates(report.project_id)
            _set_check(
                report,
                "ranking_checked",
                bool(
                    ranking.ranked_candidates
                    and ranking.ranked_candidates[0].candidate_id == TOP_CLIP_ID
                    and ranking.memory_application_v1 is not None
                    and ranking.memory_application_v1.memory_used
                    and ranking.rejected_candidates
                ),
                "Integrated BOBA Ranking did not prefer the complete synthetic candidate.",
            )
            policy = await integration.generate_boba_for_clip(report.project_id, TOP_CLIP_ID)
            _set_check(
                report,
                "editorial_policy_checked",
                bool(
                    policy.clip_id == TOP_CLIP_ID
                    and policy.ending_directives.get("avoid_cutting_final_word") is True
                    and policy.ending_directives.get("memory_advisory")
                    == "preserve_payoff_tail"
                    and policy.memory_application_v1 is not None
                    and policy.memory_application_v1.memory_used
                ),
                "Integrated Editorial Policy did not consume bounded payoff-tail memory advice.",
            )

            attached = integration.attach_boba_to_unified_clip_intelligence(
                report.project_id,
                TOP_CLIP_ID,
                {
                    "clip_id": TOP_CLIP_ID,
                    "story": {"story_shape": "problem_turn_solution"},
                    "virality": {"overall_score": 0.84},
                    "planning": {"selected_reason": "Complete setup and payoff."},
                    "editing": {"applied": False, "reason": "R&D metadata only"},
                    "rendering": {"applied": False, "reason": "Rendering not invoked"},
                },
            )
            compact = attached.get("boba", {})
            report.compact_truth_attached = bool(
                compact.get("advisory_only") is True
                and compact.get("applied") is False
                and compact.get("decisions_present") is True
                and compact.get("memory_used")
            )
            report.subsystem_results["compact_truth_attached"] = report.compact_truth_attached
            if not report.compact_truth_attached:
                report.errors.append("Compact BOBA truth was not attached honestly.")

            settings = Settings.model_validate({"environment": Environment.TESTING})
            brain_api = await boba_routes.get_brain(report.project_id, integration, settings)
            project_memory_api = await boba_routes.get_project_memory(
                report.project_id, integration, settings
            )
            query_api = boba_routes.query_memory(
                BobaMemoryQueryV1(
                    project_id=report.project_id,
                    creator_profile_id=CREATOR_PROFILE_ID,
                    target_system="ranking",
                    reason="Integrated R&D API handler check.",
                ),
                integration,
                settings,
            )
            route_paths = {
                route.path
                for route in boba_routes.router.routes
                if isinstance(route, APIRoute)
            }
            _set_check(
                report,
                "api_surface_checked",
                bool(
                    brain_api.get("project_id") == report.project_id
                    and project_memory_api.get("project_id") == report.project_id
                    and query_api.get("records")
                    and "/boba/projects/{project_id}/brain" in route_paths
                    and "/boba/memory/query" in route_paths
                ),
                "BOBA API route handlers did not expose integrated brain and memory truth.",
            )

            _set_check(
                report,
                "frontend_types_checked",
                _frontend_surface_checked(source_root),
                "BOBA frontend memory types or result panels were not found.",
            )
            _set_check(
                report,
                "cli_surface_checked",
                _cli_surface_checked(source_root),
                "BOBA integrated/core/memory CLI validation surface was incomplete.",
            )

            base_record = BobaMemoryRecordV1(
                memory_id="rnd_memory_safety",
                scope="project",
                record_type="project_summary",
                source="rnd_integrated_validator",
                project_id=report.project_id,
                summary="A bounded synthetic memory record.",
                safe_excerpt="A short synthetic excerpt.",
                applies_to=["frontend"],
            )
            secret_blocked = False
            try:
                validate_memory_record(
                    base_record.model_copy(update={"summary": "api_key=blocked"})
                )
            except ValidationError:
                secret_blocked = True
            long_text_blocked = False
            copied_lines = "\n".join(
                f"SPEAKER {index}: synthetic copied line for safety validation"
                for index in range(32)
            )
            try:
                truncate_safe_excerpt(copied_lines, max_chars=120)
            except ValidationError:
                long_text_blocked = True
            truncated = validate_memory_record(
                base_record.model_copy(
                    update={
                        "memory_id": "rnd_memory_truncation",
                        "safe_excerpt": "bounded synthetic phrase " * 20,
                    }
                ),
                max_excerpt_chars=120,
            )
            report.long_excerpt_truncated = bool(
                len(truncated.safe_excerpt) <= 120
                and "safe_excerpt_truncated" in truncated.warnings
            )
            report.subsystem_results["long_excerpt_truncated"] = (
                report.long_excerpt_truncated
            )
            _set_check(
                report,
                "unsafe_content_blocked",
                secret_blocked and long_text_blocked and report.long_excerpt_truncated,
                "BOBA Memory safety did not reject secrets/large copied text or truncate safely.",
            )

            _set_check(
                report,
                "integration_checked",
                bool(
                    signals.get("transcript_available")
                    and signals.get("trend_fallback_used")
                    and signals.get("personalization_signals_available")
                    and signals.get("render_manifest_available") is False
                    and report.compact_truth_attached
                ),
                "BOBA Integration did not connect the synthetic signals and compact truth.",
            )
    except Exception as exc:
        report.errors.append(f"{type(exc).__name__}: {exc}")
    finally:
        report.external_calls_made = bool(network_attempts)
        report.subsystem_results["external_calls_made"] = report.external_calls_made
        if network_attempts:
            report.errors.append(
                "External network call attempted: " + ", ".join(network_attempts[:5])
            )
        media_extensions = {
            ".mp4",
            ".mov",
            ".mkv",
            ".avi",
            ".webm",
            ".mp3",
            ".wav",
            ".aac",
            ".flac",
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
        }
        media_files = [
            path
            for path in scenario_root.rglob("*")
            if path.is_file() and path.suffix.lower() in media_extensions
        ]
        report.real_media_used = bool(media_files)
        report.subsystem_results["real_media_used"] = report.real_media_used
        if media_files:
            report.errors.append("R&D scenario wrote media files, which is forbidden.")


def _required_checks(report: RndBobaIntegratedReport) -> list[bool]:
    return [
        report.brain_created,
        report.decision_bus_checked,
        report.ranking_checked,
        report.editorial_policy_checked,
        report.project_memory_checked,
        report.creator_memory_checked,
        report.global_memory_checked,
        report.retrieval_checked,
        report.learning_checked,
        report.memory_application_checked,
        report.integration_checked,
        report.api_surface_checked,
        report.frontend_types_checked,
        report.unsafe_content_blocked,
        report.constitution_checked,
        report.contracts_checked,
        report.reasoning_checked,
        report.observations_created >= 3,
        report.decisions_created >= 2,
        report.compact_truth_attached,
        report.long_excerpt_truncated,
        report.cli_surface_checked,
        not report.external_calls_made,
        not report.real_media_used,
        not report.production_projects_modified,
    ]


def _write_reports(report: RndBobaIntegratedReport, output_directory: Path) -> None:
    json_path = output_directory / REPORT_JSON
    markdown_path = output_directory / REPORT_MARKDOWN
    report.report_paths = [
        (REPORT_DIRECTORY / REPORT_JSON).as_posix(),
        (REPORT_DIRECTORY / REPORT_MARKDOWN).as_posix(),
    ]
    payload = report.model_dump(mode="json")
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    checks = [
        ("Brain created", report.brain_created),
        ("Decision Bus", report.decision_bus_checked),
        ("Ranking", report.ranking_checked),
        ("Editorial policy", report.editorial_policy_checked),
        ("Project memory", report.project_memory_checked),
        ("Creator memory", report.creator_memory_checked),
        ("Global memory", report.global_memory_checked),
        ("Retrieval", report.retrieval_checked),
        ("Explicit learning", report.learning_checked),
        ("Memory application", report.memory_application_checked),
        ("Integration", report.integration_checked),
        ("API surface", report.api_surface_checked),
        ("Frontend types/panels", report.frontend_types_checked),
        ("Memory safety", report.unsafe_content_blocked),
    ]
    lines = [
        "# Integrated BOBA R&D Validation",
        "",
        f"- Passed: `{str(report.passed).lower()}`",
        f"- Mode: `{report.mode}`",
        f"- Synthetic project: `{report.project_id}`",
        f"- External calls made: `{str(report.external_calls_made).lower()}`",
        f"- Real media used: `{str(report.real_media_used).lower()}`",
        f"- Production projects modified: `{str(report.production_projects_modified).lower()}`",
        "",
        "## Integrated Checks",
        *[f"- {name}: `{'passed' if passed else 'failed'}`" for name, passed in checks],
        "",
        "## Boundaries",
        "- This was one synthetic, offline Core + Memory scenario.",
        "- No production workflow, download, render, publishing, or external API ran.",
        "- Advisory metadata remained unapplied; this does not prove production readiness.",
    ]
    if report.warnings:
        lines.extend(["", "## Warnings", *[f"- {item}" for item in report.warnings]])
    if report.errors:
        lines.extend(["", "## Errors", *[f"- {item}" for item in report.errors]])
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_integrated_rnd_validation(
    workspace_root: str | Path = ROOT,
    *,
    source_root: str | Path = ROOT,
) -> RndBobaIntegratedReport:
    """Run the one integrated scenario and always emit its two truth reports."""

    workspace = Path(workspace_root).resolve()
    source = Path(source_root).resolve()
    output_directory = (workspace / REPORT_DIRECTORY).resolve()
    output_directory.mkdir(parents=True, exist_ok=True)
    report = RndBobaIntegratedReport(
        project_id=_project_id(),
        warnings=[
            "R&D-only synthetic scenario; no production workflow or media validation occurred.",
            "Face and speaker signals were intentionally unavailable.",
            "Trend research used deterministic fallback metadata; no internet research ran.",
            "Rendering was intentionally not invoked.",
        ],
    )
    try:
        with TemporaryDirectory(dir=output_directory, prefix=".scenario_") as temporary:
            scenario_root = Path(temporary).resolve()
            report.production_projects_modified = not scenario_root.is_relative_to(
                output_directory
            )
            asyncio.run(_run_scenario(report, scenario_root, source))
    except Exception as exc:
        report.errors.append(f"{type(exc).__name__}: {exc}")
    report.passed = all(_required_checks(report)) and not report.errors
    _write_reports(report, output_directory)
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument(
        "--all",
        action="store_true",
        help="Run the single integrated, synthetic, offline BOBA R&D scenario.",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    if not args.all:
        return 2
    report = run_integrated_rnd_validation()
    print(json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
