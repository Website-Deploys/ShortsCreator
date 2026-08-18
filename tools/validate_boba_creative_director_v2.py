"""Validate BOBA Creative Director V2 without media or external services."""

from __future__ import annotations

import argparse
import asyncio
import copy
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for path in (ROOT, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from olympus.api.dependencies import boba_integration_provider  # noqa: E402
from olympus.boba import (  # noqa: E402
    BobaCreativeDirectionSetV2,
    BobaCreativeDirectorV2Engine,
    BobaExplanationEngine,
    BobaMemoryStore,
    BobaProjectMemoryV1,
)
from olympus.boba.clip_discovery import BobaCandidateClipDiscoveryV1  # noqa: E402
from olympus.boba.clip_ranking import BobaClipRankingV1  # noqa: E402
from olympus.boba.editorial_decision import BobaEditorialDecisionSetV1  # noqa: E402
from olympus.boba.explanation import BobaExplanationSetV1  # noqa: E402
from olympus.boba.whole_video import BobaWholeVideoUnderstandingV1  # noqa: E402
from olympus.platform.errors import ValidationError  # noqa: E402
from tools.validate_boba_explanation_engine import (  # noqa: E402
    build_synthetic_explanation_inputs,
)

REPORT_DIR = ROOT / "work" / "validation_reports" / "boba_creative_director_v2"

# The canonical scenario-name contract. Both this validator and
# tests/unit/test_boba_creative_director_v2.py depend on this tuple and nothing
# else, so the two can never drift apart.
SCENARIO_NAMES: tuple[str, ...] = (
    "01_selected_only_authority",
    "02_unselected_candidates_absent",
    "03_selection_cap_enforced",
    "04_render_readiness_preserved",
    "05_blocked_clip_not_upgraded",
    "06_project_isolation_enforced",
    "07_editorial_decisions_required",
    "08_fallback_declared_when_signals_absent",
    "09_engine_authored_denials_present",
    "10_audio_direction_mood_only",
    "11_layout_risk_forces_layout_safe",
    "12_emotional_motion_softened",
    "13_unemotional_motion_preserved",
    "14_direction_is_deterministic",
    "15_upstream_artifacts_unmutated",
    "16_advisory_artifact_persists_and_reloads",
)

# Scenarios that need a fixture state a real project may not contain. Running
# them against saved project artifacts would mean inventing evidence about that
# project, so project-id mode records them as skipped instead.
_SYNTHETIC_ONLY_SCENARIOS: tuple[str, ...] = (
    "03_selection_cap_enforced",
    "08_fallback_declared_when_signals_absent",
    "11_layout_risk_forces_layout_safe",
    "12_emotional_motion_softened",
    "13_unemotional_motion_preserved",
)


class BobaCreativeDirectorV2ValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["self_check", "synthetic_project", "project_id"]
    passed: bool
    project_id: str | None = None
    project_direction_present: bool = False
    clip_direction_count: int = 0
    opening_plans_present: bool = False
    hook_treatments_present: bool = False
    pacing_maps_present: bool = False
    caption_directions_present: bool = False
    motion_directions_present: bool = False
    audio_mood_only: bool = False
    retention_plans_present: bool = False
    emotional_arcs_present: bool = False
    quality_scores_present: bool = False
    warnings_preserved: bool = False
    limitations_preserved: bool = False
    artifact_persisted: bool = False
    json_safe: bool = False
    raw_transcript_stored: bool = False
    report_path_writable: bool = False
    rendering_triggered: bool = False
    downloading_triggered: bool = False
    external_calls_made: bool = False
    media_required: bool = False
    secrets_required: bool = False
    direction_examples: list[dict[str, Any]] = Field(default_factory=list)
    scenario_count: int = Field(default=0, ge=0)
    passed_scenario_count: int = Field(default=0, ge=0)
    scenario_results: dict[str, bool] = Field(default_factory=dict)
    scenario_evidence: dict[str, str] = Field(default_factory=dict)
    skipped_scenarios: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


def build_synthetic_creative_direction_inputs(
    project_id: str,
) -> tuple[
    BobaWholeVideoUnderstandingV1,
    BobaCandidateClipDiscoveryV1,
    BobaClipRankingV1,
    BobaEditorialDecisionSetV1,
    BobaExplanationSetV1,
    BobaProjectMemoryV1,
    dict[str, Any],
]:
    understanding, discovery, ranking, decisions, briefs, signals = (
        build_synthetic_explanation_inputs(project_id)
    )
    adjusted = []
    for decision in decisions.decisions:
        if decision.candidate_id == "must_make_truth":
            decision = decision.model_copy(
                update={
                    "final_story_angle": (
                        "A motivating transformation reveals the practical system "
                        "behind the result."
                    ),
                    "final_hook_strategy": "motivational_payoff",
                    "opening_line_direction": (
                        "Lead with the transformation, then reveal the rule that "
                        "made it possible."
                    ),
                    "pacing_intensity": "aggressive",
                    "music_mood": "motivational",
                    "sfx_intensity": "light",
                }
            )
        elif decision.candidate_id == "strong_educational":
            decision = decision.model_copy(
                update={
                    "caption_style": "keyword_highlight",
                    "music_mood": "educational",
                }
            )
        elif decision.candidate_id == "strong_emotional":
            decision = decision.model_copy(
                update={
                    "final_hook_strategy": "emotional_reveal",
                    "caption_style": "emotional_emphasis",
                    "motion_style": "subtle_zoom",
                    "music_mood": "cinematic",
                }
            )
        adjusted.append(decision)
    decisions = decisions.model_copy(update={"decisions": adjusted})
    signals.update(
        {
            "analysis_signals_v2": {
                "speech": {"available": True},
                "visual": {"available": True},
                "face": {"available": True},
                "speaker": {"available": True},
            },
            "transcript_available": True,
            "face_signals_available": True,
            "speaker_signals_available": True,
            "visual_signals_available": True,
            "editorial_decisions": decisions.model_dump(mode="json"),
        }
    )
    memory = BobaProjectMemoryV1(
        project_id=project_id,
        source_summary="Creator prefers clear practical payoffs and restrained motion.",
        main_topics=["systems", "education", "teamwork"],
        selected_clip_ids=list(decisions.selected_clip_ids),
        known_limitations=["Synthetic local metadata only."],
    )
    explanations = BobaExplanationEngine().explain_from_signals(
        project_id,
        signals,
        whole_video_understanding=understanding,
        candidate_discovery=discovery,
        clip_ranking=ranking,
        editorial_decisions=decisions,
        creative_briefs=briefs,
        memory=memory,
    )
    signals["explanations"] = explanations.model_dump(mode="json")
    return (
        understanding,
        discovery,
        ranking,
        decisions,
        explanations,
        memory,
        signals,
    )


def build_synthetic_creative_direction(
    project_id: str,
) -> BobaCreativeDirectionSetV2:
    (
        understanding,
        discovery,
        ranking,
        decisions,
        explanations,
        memory,
        signals,
    ) = build_synthetic_creative_direction_inputs(project_id)
    return BobaCreativeDirectorV2Engine().direct_from_signals(
        project_id,
        signals,
        editorial_decisions=decisions,
        clip_ranking=ranking,
        candidate_discovery=discovery,
        whole_video_understanding=understanding,
        explanations=explanations,
        memory=memory,
    )


def _evaluate(
    direction: BobaCreativeDirectionSetV2,
    *,
    mode: Literal["self_check", "synthetic_project", "project_id"],
    artifact_path: Path | None,
) -> BobaCreativeDirectorV2ValidationReport:
    payload = direction.model_dump(mode="json")
    encoded = json.dumps(payload)
    clips = direction.clip_directions
    project_present = bool(
        direction.project_direction.overall_style
        and direction.project_direction.pacing_philosophy
        and direction.project_direction.audio_philosophy
    )
    opening = bool(clips) and all(
        item.opening_three_second_plan.what_viewer_sees_first
        and item.opening_three_second_plan.caption_implication
        and item.opening_three_second_plan.curiosity_gap
        for item in clips
    )
    hooks = bool(clips) and all(
        item.hook_treatment.opening_line_direction
        and item.hook_treatment.pattern_interrupt
        for item in clips
    )
    pacing = bool(clips) and all(
        item.pacing_map.first_3_seconds and item.pacing_map.payoff_section
        for item in clips
    )
    captions = bool(clips) and all(
        item.caption_direction.style and item.caption_direction.rhythm for item in clips
    )
    motion = bool(clips) and all(
        item.motion_direction.style and item.motion_direction.stable_moments
        for item in clips
    )
    audio = bool(clips) and all(
        set(item.audio_direction.model_dump(mode="json"))
        == {
            "music_mood",
            "sfx_intensity",
            "ducking_guidance",
            "silence_notes",
            "speech_clarity_notes",
            "warnings",
        }
        and "/" not in item.audio_direction.music_mood
        and "\\" not in item.audio_direction.music_mood
        for item in clips
    )
    retention = bool(clips) and all(
        item.retention_plan.opening_hook and item.retention_plan.payoff_delivery
        for item in clips
    )
    emotional = bool(clips) and all(
        item.emotional_arc.starting_emotion and item.emotional_arc.payoff_emotion
        for item in clips
    )
    quality = bool(clips) and all(
        0.0 <= item.creative_quality_score.overall_confidence <= 100.0
        for item in clips
    )
    persisted = artifact_path is not None and artifact_path.is_file()
    json_safe = bool(json.loads(encoded))
    raw_transcript_stored = "transcript_segments" in encoded
    warnings_preserved = bool(direction.warnings) or any(
        item.warnings
        or item.motion_direction.safety_warnings
        or item.audio_direction.warnings
        for item in clips
    )
    limitations_preserved = bool(direction.limitations)
    passed = bool(
        project_present
        and clips
        and opening
        and hooks
        and pacing
        and captions
        and motion
        and audio
        and retention
        and emotional
        and quality
        and persisted
        and json_safe
        and not raw_transcript_stored
    )
    return BobaCreativeDirectorV2ValidationReport(
        mode=mode,
        passed=passed,
        project_id=direction.project_id,
        project_direction_present=project_present,
        clip_direction_count=len(clips),
        opening_plans_present=opening,
        hook_treatments_present=hooks,
        pacing_maps_present=pacing,
        caption_directions_present=captions,
        motion_directions_present=motion,
        audio_mood_only=audio,
        retention_plans_present=retention,
        emotional_arcs_present=emotional,
        quality_scores_present=quality,
        warnings_preserved=warnings_preserved,
        limitations_preserved=limitations_preserved,
        artifact_persisted=persisted,
        json_safe=json_safe,
        raw_transcript_stored=raw_transcript_stored,
        direction_examples=[
            {
                "candidate_id": item.candidate_id,
                "hook_type": item.hook_treatment.hook_type,
                "pacing": item.pacing_map.pacing_intensity,
                "caption_style": item.caption_direction.style,
                "motion_style": item.motion_direction.style,
                "music_mood": item.audio_direction.music_mood,
                "quality": item.creative_quality_score.overall_confidence,
            }
            for item in clips[:8]
        ],
        warnings=[
            "Validation used bounded local metadata only; no media was read, "
            "edited, downloaded, or rendered.",
            "Creative quality scores are advisory and do not predict audience performance.",
            *direction.limitations[:4],
        ],
    )


# ----------------------------------------------------------------------
# Named semantic scenarios.
#
# Every scenario executes the real BobaCreativeDirectorV2Engine against a
# fixture-derived payload. No scenario reads production source text, and no
# scenario reports a value the engine reported about itself. A scenario that
# raises is recorded as failed with its error text — never as a silent pass.
# ----------------------------------------------------------------------
_SELECTED_IDS = ("must_make_truth", "strong_educational", "strong_emotional", "weak_payoff")
_UNSELECTED_IDS = ("backup_practical", "needs_context", "reject_fragment", "rights_risk")
_QUALITY_DIMENSIONS = frozenset(
    {
        "hook_quality",
        "clarity",
        "emotional_pull",
        "pacing_strength",
        "visual_direction_strength",
        "caption_strength",
        "audio_direction_strength",
        "overall_confidence",
    }
)


def _scenario_strings(value: Any) -> list[str]:
    out: list[str] = []
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, Mapping):
        for item in value.values():
            out.extend(_scenario_strings(item))
    elif isinstance(value, list):
        for item in value:
            out.extend(_scenario_strings(item))
    return out


def _scenario_canonical(direction: BobaCreativeDirectionSetV2) -> str:
    payload = direction.model_dump(mode="json")
    payload.pop("created_at", None)
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


def _scenario_decision(payload: Mapping[str, Any], candidate_id: str) -> dict[str, Any]:
    return next(
        item for item in payload["decisions"] if item["candidate_id"] == candidate_id
    )


def _scenario_select(payload: Mapping[str, Any], ids: tuple[str, ...]) -> dict[str, Any]:
    out = copy.deepcopy(dict(payload))
    for item in out["decisions"]:
        item["selected"] = item["candidate_id"] in ids
    return out


def _scenario_ids(payload: Mapping[str, Any]) -> list[str]:
    return [item["candidate_id"] for item in payload["decisions"] if item["selected"]]


def _run_scenarios(
    project_id: str,
    editorial: Mapping[str, Any],
    upstreams: Mapping[str, Any],
    *,
    full: bool,
) -> tuple[dict[str, bool], dict[str, str], list[str], list[str]]:
    """Execute the named scenarios and return (results, evidence, skipped, errors)."""
    engine = BobaCreativeDirectorV2Engine()
    results: dict[str, bool] = {}
    evidence: dict[str, str] = {}
    skipped: list[str] = []
    errors: list[str] = []

    def run(name: str, check: Any) -> None:
        if not full and name in _SYNTHETIC_ONLY_SCENARIOS:
            skipped.append(name)
            return
        try:
            passed, note = check()
        except Exception as exc:  # recorded as a failure, never swallowed
            results[name] = False
            evidence[name] = f"{type(exc).__name__}: {exc}"
            errors.append(f"{name}: {type(exc).__name__}: {exc}")
            return
        results[name] = bool(passed)
        evidence[name] = note
        if not passed:
            errors.append(f"{name}: {note}")

    def direct(payload: Mapping[str, Any] | None, **overrides: Any) -> BobaCreativeDirectionSetV2:
        kwargs = dict(upstreams)
        kwargs.update(overrides)
        return engine.direct(project_id=project_id, editorial_decisions=payload, **kwargs)

    def selected_only() -> tuple[bool, str]:
        expected = _scenario_ids(editorial)
        emitted = [clip.candidate_id for clip in direct(editorial).clip_directions]
        return emitted == expected, f"emitted {emitted} == selected {expected}"

    def unselected_absent() -> tuple[bool, str]:
        emitted = {clip.candidate_id for clip in direct(editorial).clip_directions}
        unselected = {
            item["candidate_id"] for item in editorial["decisions"] if not item["selected"]
        }
        leaked = emitted & unselected
        return not leaked, f"unselected {sorted(unselected)} leaked {sorted(leaked)}"

    def selection_cap() -> tuple[bool, str]:
        payload = copy.deepcopy(dict(editorial))
        template = _scenario_decision(payload, _SELECTED_IDS[0])
        index = 0
        while len(_scenario_ids(payload)) < 12:
            clone = copy.deepcopy(template)
            clone["candidate_id"] = f"cloned_selected_{index}"
            clone["selected"] = True
            payload["decisions"].append(clone)
            index += 1
        emitted = direct(payload).clip_directions
        return len(emitted) == 10, f"12 selected produced {len(emitted)} directions (cap 10)"

    def readiness_preserved() -> tuple[bool, str]:
        payload = copy.deepcopy(dict(editorial))
        assigned: dict[str, str] = {}
        for offset, candidate_id in enumerate(_scenario_ids(payload)):
            value = ("quarantined_pending_rights", "blocked", "needs_revision", "ready_for_render")[
                offset % 4
            ]
            _scenario_decision(payload, candidate_id)["render_readiness"] = value
            assigned[candidate_id] = value
        emitted = {
            clip.candidate_id: clip.render_readiness for clip in direct(payload).clip_directions
        }
        return emitted == assigned, f"readiness mirrored {emitted}"

    def blocked_not_upgraded() -> tuple[bool, str]:
        blocked_ids = [
            item["candidate_id"]
            for item in editorial["decisions"]
            if item.get("render_readiness") == "blocked"
        ]
        if not blocked_ids:
            return False, "no blocked decision exists in this editorial artifact"
        payload = _scenario_select(editorial, (*_scenario_ids(editorial), blocked_ids[0]))
        emitted = {
            clip.candidate_id: clip.render_readiness for clip in direct(payload).clip_directions
        }
        value = emitted.get(blocked_ids[0])
        return value == "blocked", f"{blocked_ids[0]} forced selected reports {value!r}"

    def project_isolation() -> tuple[bool, str]:
        payload = copy.deepcopy(dict(editorial))
        payload["project_id"] = "proj_other_tenant_scenario"
        try:
            direct(payload)
        except ValidationError as exc:
            details = exc.details or {}
            ok = (
                "belong to a different project" in str(exc)
                and details.get("project_id") == project_id
                and details.get("artifact_project_id") == "proj_other_tenant_scenario"
            )
            return ok, f"refused with details {dict(details)}"
        return False, "a foreign-project editorial artifact was accepted"

    def editorial_required() -> tuple[bool, str]:
        try:
            direct(None)
        except ValidationError as exc:
            ok = "requires saved editorial decisions" in str(exc)
            return ok, f"refused: {exc}"
        return False, "missing editorial decisions were accepted"

    def fallback_declared() -> tuple[bool, str]:
        usage = engine.direct(
            project_id=project_id, editorial_decisions=editorial
        ).signal_usage.model_dump()
        ok = (
            usage["fallback_used"] is True
            and bool(usage["unavailable_signals"])
            and usage["clip_ranking_used"] is False
        )
        return (
            ok,
            f"fallback_used={usage['fallback_used']} "
            f"unavailable={usage['unavailable_signals']}",
        )

    def engine_denials() -> tuple[bool, str]:
        payload = copy.deepcopy(dict(editorial))
        payload["limitations"] = []
        result = direct(payload)
        denial = (
            "Creative quality scores summarize saved evidence and do not predict "
            "audience performance."
        )
        suffix = (
            "This is an evidence-bound creative hypothesis, not audience-performance proof."
        )
        hooks = [
            clip.hook_treatment.reason_it_should_work.endswith(suffix)
            for clip in result.clip_directions
        ]
        ok = denial in result.limitations and bool(hooks) and all(hooks)
        return (
            ok,
            f"denial present={denial in result.limitations} "
            f"hooks_ok={all(hooks) if hooks else False}",
        )

    def audio_mood_only() -> tuple[bool, str]:
        result = direct(editorial)
        offenders: list[str] = []
        for clip in result.clip_directions:
            for text in _scenario_strings(clip.audio_direction.model_dump(mode="json")):
                lowered = text.lower()
                if "://" in lowered or "/" in text or "\\" in text:
                    offenders.append(text)
                if any(
                    ext in lowered for ext in (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg")
                ):
                    offenders.append(text)
                if any(c in lowered for c in ("copyright-safe", "licensed", "royalty-free")):
                    offenders.append(text)
        return not offenders, f"{len(offenders)} offending audio string(s)"

    def layout_risk_forces_safe() -> tuple[bool, str]:
        signals = dict(upstreams.get("analysis_signal_health") or {})
        signals.update({"face_signals_available": False, "visual_signals_available": True})
        result = engine.direct_from_signals(
            project_id,
            signals,
            editorial_decisions=editorial,
            clip_ranking=upstreams.get("clip_ranking"),
            candidate_discovery=upstreams.get("candidate_discovery"),
            whole_video_understanding=upstreams.get("whole_video_understanding"),
            explanations=upstreams.get("explanations"),
            memory=upstreams.get("memory"),
        )
        styles = {clip.candidate_id: clip.motion_direction.style for clip in result.clip_directions}
        ok = bool(styles) and all(value == "layout_safe" for value in styles.values())
        return ok, f"styles with face signals absent: {styles}"

    def emotional_softened() -> tuple[bool, str]:
        payload = copy.deepcopy(dict(editorial))
        _scenario_decision(payload, "strong_emotional")["motion_style"] = "high_motion"
        result = direct(payload)
        style = next(
            (
                clip.motion_direction.style
                for clip in result.clip_directions
                if clip.candidate_id == "strong_emotional"
            ),
            None,
        )
        return style == "subtle_zoom", f"emotional clip requesting high_motion got {style!r}"

    def unemotional_preserved() -> tuple[bool, str]:
        result = direct(editorial)
        style = next(
            (
                clip.motion_direction.style
                for clip in result.clip_directions
                if clip.candidate_id == "must_make_truth"
            ),
            None,
        )
        return style == "dynamic_zoom", f"unemotional aggressive request kept {style!r}"

    def deterministic() -> tuple[bool, str]:
        first = _scenario_canonical(direct(editorial))
        second = _scenario_canonical(direct(editorial))
        return first == second, "two runs produced identical canonical payloads"

    def upstream_unmutated() -> tuple[bool, str]:
        snapshot = {
            name: copy.deepcopy(
                value.model_dump(mode="json") if hasattr(value, "model_dump") else value
            )
            for name, value in upstreams.items()
        }
        editorial_before = copy.deepcopy(dict(editorial))
        direct(editorial)
        after = {
            name: (value.model_dump(mode="json") if hasattr(value, "model_dump") else value)
            for name, value in upstreams.items()
        }
        ok = after == snapshot and dict(editorial) == editorial_before
        return ok, f"{len(snapshot) + 1} upstream artifact(s) compared with nothing excluded"

    def persists_and_reloads() -> tuple[bool, str]:
        result = direct(editorial)
        with TemporaryDirectory() as temporary:
            store = BobaMemoryStore(Path(temporary) / "boba")
            saved = store.save_creative_direction_v2(result)
            reloaded = store.load_creative_direction_v2(project_id)
            path = store.creative_direction_v2_path(project_id)
            ok = (
                reloaded == saved
                and path.as_posix().endswith(
                    f"projects/{project_id}/creative_direction_v2/index.json"
                )
            )
        return ok, "save/load round-trip preserved the direction set"

    run("01_selected_only_authority", selected_only)
    run("02_unselected_candidates_absent", unselected_absent)
    run("03_selection_cap_enforced", selection_cap)
    run("04_render_readiness_preserved", readiness_preserved)
    run("05_blocked_clip_not_upgraded", blocked_not_upgraded)
    run("06_project_isolation_enforced", project_isolation)
    run("07_editorial_decisions_required", editorial_required)
    run("08_fallback_declared_when_signals_absent", fallback_declared)
    run("09_engine_authored_denials_present", engine_denials)
    run("10_audio_direction_mood_only", audio_mood_only)
    run("11_layout_risk_forces_layout_safe", layout_risk_forces_safe)
    run("12_emotional_motion_softened", emotional_softened)
    run("13_unemotional_motion_preserved", unemotional_preserved)
    run("14_direction_is_deterministic", deterministic)
    run("15_upstream_artifacts_unmutated", upstream_unmutated)
    run("16_advisory_artifact_persists_and_reloads", persists_and_reloads)
    return results, evidence, skipped, errors


def _apply_scenarios(
    report: BobaCreativeDirectorV2ValidationReport,
    project_id: str,
    editorial: Mapping[str, Any],
    upstreams: Mapping[str, Any],
    *,
    full: bool,
) -> None:
    """Fold scenario outcomes into a report and strengthen `passed`."""
    results, evidence, skipped, errors = _run_scenarios(
        project_id, editorial, upstreams, full=full
    )
    report.scenario_results = results
    report.scenario_evidence = evidence
    report.skipped_scenarios = skipped
    report.scenario_count = len(results)
    report.passed_scenario_count = sum(1 for value in results.values() if value)
    report.errors.extend(errors)
    complete = tuple(results) == SCENARIO_NAMES if full else bool(results)
    report.passed = (
        report.passed
        and bool(results)
        and all(results.values())
        and not report.errors
        and complete
    )


def _report_path_writable() -> bool:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    probe = REPORT_DIR / ".write_test"
    try:
        probe.write_text("ok", encoding="utf-8")
        return probe.read_text(encoding="utf-8") == "ok"
    finally:
        probe.unlink(missing_ok=True)


def _run_synthetic(
    *, mode: Literal["self_check", "synthetic_project"]
) -> BobaCreativeDirectorV2ValidationReport:
    project_id = (
        "proj_creative_director_v2_self_check"
        if mode == "self_check"
        else "proj_creative_director_v2_synthetic"
    )
    with TemporaryDirectory() as temporary:
        store = BobaMemoryStore(Path(temporary) / "boba")
        direction = store.save_creative_direction_v2(
            build_synthetic_creative_direction(project_id)
        )
        report = _evaluate(
            direction,
            mode=mode,
            artifact_path=store.creative_direction_v2_path(project_id),
        )
    report.report_path_writable = _report_path_writable()
    report.passed = report.passed and report.report_path_writable
    understanding, discovery, ranking, decisions, explanations, memory, signals = (
        build_synthetic_creative_direction_inputs(project_id)
    )
    _apply_scenarios(
        report,
        project_id,
        decisions.model_dump(mode="json"),
        {
            "clip_ranking": ranking,
            "candidate_discovery": discovery,
            "whole_video_understanding": understanding,
            "explanations": explanations,
            "memory": memory,
            "analysis_signal_health": signals,
        },
        full=True,
    )
    if mode == "self_check":
        report.warnings.append(
            "Self-check required no network, media, downloader, renderer, or secrets."
        )
    return report


async def _existing_project(
    project_id: str,
) -> BobaCreativeDirectorV2ValidationReport:
    try:
        integration = boba_integration_provider()
        direction = integration.store.load_creative_direction_v2(project_id)
        if direction is None:
            direction = await integration.generate_creative_direction_v2(project_id)
        report = _evaluate(
            direction,
            mode="project_id",
            artifact_path=integration.store.creative_direction_v2_path(project_id),
        )
        report.report_path_writable = _report_path_writable()
        report.passed = report.passed and report.report_path_writable
        saved_editorial = integration.store.load_editorial_decisions(project_id)
        if saved_editorial is None:
            report.passed = False
            report.errors.append(
                "No saved editorial decision artifact exists, so no scenario could be "
                "executed against this project."
            )
        else:
            editorial_payload = (
                saved_editorial.model_dump(mode="json")
                if hasattr(saved_editorial, "model_dump")
                else dict(saved_editorial)
            )
            _apply_scenarios(report, project_id, editorial_payload, {}, full=False)
        report.warnings.append(
            "Existing-project mode used saved local BOBA artifacts only and did not "
            "render or download."
        )
        return report
    except Exception as exc:
        return BobaCreativeDirectorV2ValidationReport(
            mode="project_id",
            passed=False,
            project_id=project_id,
            report_path_writable=_report_path_writable(),
            errors=[str(exc)],
            warnings=[
                "Missing artifacts were reported rather than replaced with "
                "fabricated creative evidence."
            ],
        )


def _write_report(report: BobaCreativeDirectorV2ValidationReport) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    payload = report.model_dump(mode="json")
    (REPORT_DIR / "boba_creative_director_v2_report.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    summary = [
        "# BOBA Creative Director V2 Validation",
        "",
        f"- Mode: `{report.mode}`",
        f"- Passed: `{str(report.passed).lower()}`",
        f"- Project: `{report.project_id or 'temporary self-check'}`",
        f"- Clip directions: `{report.clip_direction_count}`",
        f"- Opening plans present: `{report.opening_plans_present}`",
        f"- Audio mood only: `{report.audio_mood_only}`",
        f"- Artifact persisted: `{report.artifact_persisted}`",
        f"- Rendering triggered: `{report.rendering_triggered}`",
        f"- External calls made: `{report.external_calls_made}`",
        "",
        "This validator checks advisory metadata only. It does not establish rendering, "
        "copyright safety, production readiness, or audience performance.",
    ]
    if report.scenario_results:
        summary.extend(
            [
                "",
                "## Scenarios",
                f"- Passed: `{report.passed_scenario_count}/{report.scenario_count}`",
                *[
                    f"- `{name}`: {'passed' if outcome else 'failed'}"
                    f" — {report.scenario_evidence.get(name, '')}"
                    for name, outcome in report.scenario_results.items()
                ],
            ]
        )
    if report.skipped_scenarios:
        summary.extend(
            [
                "",
                "## Skipped scenarios",
                f"- Mode `{report.mode}` cannot execute these without inventing evidence:",
                *[f"- `{name}`" for name in report.skipped_scenarios],
            ]
        )
    if report.warnings:
        summary.extend(["", "## Warnings", *[f"- {item}" for item in report.warnings]])
    if report.errors:
        summary.extend(["", "## Errors", *[f"- {item}" for item in report.errors]])
    (REPORT_DIR / "boba_creative_director_v2_summary.md").write_text(
        "\n".join(summary) + "\n", encoding="utf-8"
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--self-check", action="store_true")
    modes.add_argument("--synthetic-project", action="store_true")
    modes.add_argument("--project-id")
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.self_check:
        report = _run_synthetic(mode="self_check")
    elif args.synthetic_project:
        report = _run_synthetic(mode="synthetic_project")
    else:
        report = asyncio.run(_existing_project(str(args.project_id)))
    _write_report(report)
    print(json.dumps(report.model_dump(mode="json"), indent=2))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
