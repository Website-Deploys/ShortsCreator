"""BOBA Creative Director V2 contracts, behavior, persistence, API, and validator tests."""

from __future__ import annotations

import asyncio
import copy
import json
import socket
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tools.validate_boba_creative_director_v2 import (
    REPORT_DIR,
    SCENARIO_NAMES,
    build_synthetic_creative_direction,
    build_synthetic_creative_direction_inputs,
)

from olympus.api.dependencies import boba_integration_provider
from olympus.boba import (
    BobaAudioDirectionV2,
    BobaCaptionDirectionV2,
    BobaClipCreativeDirectionV2,
    BobaCreativeDirectionSetV2,
    BobaCreativeDirector,
    BobaCreativeDirectorSignalUsageV2,
    BobaCreativeDirectorV2Engine,
    BobaCreativeQualityScoreV2,
    BobaEmotionalArcV2,
    BobaHookTreatmentV2,
    BobaIntegration,
    BobaMemoryStore,
    BobaMotionDirectionV2,
    BobaPacingMapV2,
    BobaProjectCreativeDirectionV2,
    BobaRetentionPlanV2,
)
from olympus.data.repositories import StorageProjectRepository
from olympus.data.storage.local import LocalStorage
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.platform.errors import ValidationError
from olympus.utils import utc_now

ROOT = Path(__file__).resolve().parents[2]
PROJECT_ID = "proj_creative_director_v2"


def _result(project_id: str = PROJECT_ID) -> BobaCreativeDirectionSetV2:
    return build_synthetic_creative_direction(project_id)


def _project(project_id: str = PROJECT_ID) -> Project:
    now = utc_now()
    return Project(
        id=project_id,
        name="BOBA Creative Director V2 Test",
        source_filename="source.mp4",
        storage_key=f"uploads/{project_id}/source.mp4",
        size_bytes=12,
        video_format="mp4",
        content_type="video/mp4",
        duration_seconds=340.0,
        width=1920,
        height=1080,
        status=ProjectStatus.ANALYZED,
        created_at=now,
        updated_at=now,
    )


def _clip(
    candidate_id: str,
    result: BobaCreativeDirectionSetV2 | None = None,
) -> BobaClipCreativeDirectionV2:
    direction = result or _result()
    return next(item for item in direction.clip_directions if item.candidate_id == candidate_id)


def _direct_with_analysis(
    *,
    face: bool,
    visual: bool,
    project_id: str = "proj_creative_direction_analysis",
) -> BobaCreativeDirectionSetV2:
    understanding, discovery, ranking, decisions, explanations, memory, signals = (
        build_synthetic_creative_direction_inputs(project_id)
    )
    signals.update(
        {
            "face_signals_available": face,
            "visual_signals_available": visual,
            "analysis_signals_v2": {
                "speech": {"available": True},
                "face": {"available": face},
                "visual": {"available": visual},
            },
        }
    )
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


def test_01_direction_set_contract_serializes() -> None:
    result = _result()
    assert BobaCreativeDirectionSetV2.model_validate_json(result.model_dump_json()) == result
    assert result.schema_version == "boba_creative_director_v2"


def test_02_project_direction_contract_serializes() -> None:
    project = _result().project_direction
    assert BobaProjectCreativeDirectionV2.model_validate(project.model_dump()) == project


def test_03_clip_direction_contract_serializes() -> None:
    clip = _result().clip_directions[0]
    assert BobaClipCreativeDirectionV2.model_validate(clip.model_dump()) == clip


def test_04_hook_treatment_serializes() -> None:
    value = _result().clip_directions[0].hook_treatment
    assert BobaHookTreatmentV2.model_validate(value.model_dump()) == value


def test_05_pacing_map_serializes() -> None:
    value = _result().clip_directions[0].pacing_map
    assert BobaPacingMapV2.model_validate(value.model_dump()) == value


def test_06_caption_direction_serializes() -> None:
    value = _result().clip_directions[0].caption_direction
    assert BobaCaptionDirectionV2.model_validate(value.model_dump()) == value


def test_07_motion_direction_serializes() -> None:
    value = _result().clip_directions[0].motion_direction
    assert BobaMotionDirectionV2.model_validate(value.model_dump()) == value


def test_08_audio_direction_serializes() -> None:
    value = _result().clip_directions[0].audio_direction
    assert BobaAudioDirectionV2.model_validate(value.model_dump()) == value


def test_09_retention_plan_serializes() -> None:
    value = _result().clip_directions[0].retention_plan
    assert BobaRetentionPlanV2.model_validate(value.model_dump()) == value


def test_10_emotional_arc_serializes() -> None:
    value = _result().clip_directions[0].emotional_arc
    assert BobaEmotionalArcV2.model_validate(value.model_dump()) == value


def test_11_creative_quality_score_serializes() -> None:
    value = _result().clip_directions[0].creative_quality_score
    assert BobaCreativeQualityScoreV2.model_validate(value.model_dump()) == value


def test_12_signal_usage_serializes() -> None:
    value = _result().signal_usage
    assert BobaCreativeDirectorSignalUsageV2.model_validate(value.model_dump()) == value


def test_13_must_make_motivational_clip_gets_strong_hook_treatment() -> None:
    clip = _clip("must_make_truth")
    assert clip.hook_treatment.hook_type == "motivational_payoff"
    assert "transformation" in clip.hook_treatment.first_visual_emphasis.casefold()
    assert clip.creative_quality_score.hook_quality >= 80.0


def test_14_educational_clip_gets_keyword_or_clean_caption_direction() -> None:
    clip = _clip("strong_educational")
    assert clip.caption_direction.style in {"keyword_highlight", "clean_subtitles"}
    assert clip.caption_direction.emphasis_words
    assert "readable" in " ".join(clip.caption_direction.readability_notes).casefold()


def test_15_visual_layout_risk_chooses_safer_motion() -> None:
    project_id = "proj_creative_direction_layout_risk"
    understanding, discovery, ranking, decisions, explanations, memory, signals = (
        build_synthetic_creative_direction_inputs(project_id)
    )
    first = decisions.decisions[0]
    safer_risk = first.risk_review.model_copy(update={"visual_layout_risk": True})
    decisions = decisions.model_copy(
        update={
            "decisions": [
                first.model_copy(update={"risk_review": safer_risk}),
                *decisions.decisions[1:],
            ]
        }
    )
    result = BobaCreativeDirectorV2Engine().direct_from_signals(
        project_id,
        signals,
        editorial_decisions=decisions,
        clip_ranking=ranking,
        candidate_discovery=discovery,
        whole_video_understanding=understanding,
        explanations=explanations,
        memory=memory,
    )
    assert result.clip_directions[0].motion_direction.style == "layout_safe"


def test_16_unavailable_face_layout_signals_create_warning() -> None:
    result = _direct_with_analysis(face=False, visual=True)
    assert "face_layout_signals" in result.signal_usage.unavailable_signals
    assert any(
        "face/layout signals are unavailable" in warning.casefold()
        for item in result.clip_directions
        for warning in item.warnings + item.motion_direction.safety_warnings
    )


def test_17_high_energy_clip_gets_faster_pacing() -> None:
    clip = _clip("must_make_truth")
    assert clip.pacing_map.pacing_intensity == "aggressive"
    assert "momentum" in clip.pacing_map.middle_section.casefold()


def test_18_emotional_clip_gets_emotional_cinematic_direction() -> None:
    clip = _clip("strong_emotional")
    assert clip.hook_treatment.hook_type == "emotional_reveal"
    assert clip.audio_direction.music_mood == "cinematic"
    assert clip.caption_direction.style == "emotional_emphasis"


def test_19_audio_direction_never_includes_copyrighted_track_path() -> None:
    for clip in _result().clip_directions:
        payload = clip.audio_direction.model_dump(mode="json")
        assert set(payload) == {
            "music_mood",
            "sfx_intensity",
            "ducking_guidance",
            "silence_notes",
            "speech_clarity_notes",
            "warnings",
        }
        mood = clip.audio_direction.music_mood.casefold()
        assert not any(value in mood for value in ("/", "\\", ".mp3", ".wav", ".m4a"))


def test_20_opening_three_second_plan_exists_for_selected_clips() -> None:
    result = _result()
    assert result.clip_directions
    assert all(item.selected for item in result.clip_directions)
    assert all(
        item.opening_three_second_plan.what_viewer_sees_first
        and item.opening_three_second_plan.caption_implication
        and item.opening_three_second_plan.curiosity_gap
        for item in result.clip_directions
    )


def test_21_risk_fixes_include_missing_context_when_needed() -> None:
    project_id = "proj_creative_direction_context"
    understanding, discovery, ranking, decisions, explanations, memory, signals = (
        build_synthetic_creative_direction_inputs(project_id)
    )
    updated = [
        item.model_copy(update={"selected": True})
        if item.candidate_id == "needs_context"
        else item
        for item in decisions.decisions
    ]
    decisions = decisions.model_copy(update={"decisions": updated})
    result = BobaCreativeDirectorV2Engine().direct_from_signals(
        project_id,
        signals,
        editorial_decisions=decisions,
        clip_ranking=ranking,
        candidate_discovery=discovery,
        whole_video_understanding=understanding,
        explanations=explanations,
        memory=memory,
    )
    context_clip = _clip("needs_context", result)
    assert any("missing context" in item.casefold() for item in context_clip.risk_fixes)


def test_22_v1_creative_director_compatibility_remains_intact(tmp_path: Path) -> None:
    _, discovery, _, _, _, _, _ = build_synthetic_creative_direction_inputs(
        "proj_creative_v1_compatibility"
    )
    store = BobaMemoryStore(tmp_path / "boba")
    briefs = BobaCreativeDirector(store).create_briefs(
        "proj_creative_v1_compatibility",
        {
            "discovered_candidate_clips": [
                discovery.candidates[0].model_dump(mode="json")
            ],
            "analysis_signals_v2": {"dominant_emotion": "motivational"},
            "transcript_available": True,
            "safety_status": "low",
        },
    )
    assert len(briefs) == 1
    assert store.list_creative_briefs("proj_creative_v1_compatibility") == briefs


def test_23_missing_editorial_decisions_fails_clearly() -> None:
    with pytest.raises(ValidationError, match="requires saved editorial decisions"):
        BobaCreativeDirectorV2Engine().direct(
            project_id="proj_missing_editorial",
            editorial_decisions=None,
        )


def test_24_artifact_persistence_writes_json_safe_output(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    result = store.save_creative_direction_v2(_result())
    path = store.creative_direction_v2_path(PROJECT_ID)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert path.as_posix().endswith(f"projects/{PROJECT_ID}/creative_direction_v2/index.json")
    assert store.load_creative_direction_v2(PROJECT_ID) == result
    assert payload["schema_version"] == "boba_creative_director_v2"
    assert "transcript_segments" not in payload


def test_25_api_routes_return_saved_direction_and_frontend_exposes_it(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    storage = LocalStorage(root=str(tmp_path / "storage"))
    store = BobaMemoryStore(tmp_path / "boba")
    understanding, discovery, ranking, decisions, explanations, memory, _signals = (
        build_synthetic_creative_direction_inputs(PROJECT_ID)
    )
    asyncio.run(StorageProjectRepository(storage).save(_project()))
    store.save_whole_video_understanding(understanding)
    store.save_candidate_clip_discovery(discovery)
    store.save_clip_ranking(ranking)
    store.save_editorial_decisions(decisions)
    store.save_explanations(explanations)
    store.save_project_memory(memory)
    integration = BobaIntegration(storage, store)
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        created = client.post(
            f"/api/v1/boba/projects/{PROJECT_ID}/creative-direction-v2"
        )
        saved = client.get(
            f"/api/v1/boba/projects/{PROJECT_ID}/creative-direction-v2"
        )
    assert created.status_code == 200
    assert saved.status_code == 200
    assert created.json()["clip_directions"] == saved.json()["clip_directions"]
    panel = (
        ROOT / "frontend" / "src" / "components" / "project" / "ResultsSection.tsx"
    ).read_text(encoding="utf-8")
    assert "BOBA Creative Director V2" in panel
    assert "Opening three seconds" in panel
    assert "metadata only; no track selected" in panel


def test_26_validator_self_check_passes() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "validate_boba_creative_director_v2.py"),
            "--self-check",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert '"passed": true' in result.stdout.casefold()
    assert '"rendering_triggered": false' in result.stdout.casefold()


def test_27_validator_synthetic_project_passes() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "validate_boba_creative_director_v2.py"),
            "--synthetic-project",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert '"audio_mood_only": true' in result.stdout.casefold()
    assert '"artifact_persisted": true' in result.stdout.casefold()


def test_28_creative_direction_generation_does_not_trigger_rendering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_subprocess(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("rendering or subprocess execution is forbidden")

    monkeypatch.setattr(subprocess, "run", fail_subprocess)
    assert _result().clip_directions


def test_29_creative_direction_generation_makes_no_external_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_network(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("network access is forbidden")

    monkeypatch.setattr(socket, "create_connection", fail_network)
    assert _result().signal_usage.editorial_decisions_used is True


def test_30_reports_and_media_are_not_staged() -> None:
    assert REPORT_DIR == ROOT / "work" / "validation_reports" / "boba_creative_director_v2"
    assert "media" not in REPORT_DIR.parts
    assert "storage_data" not in REPORT_DIR.parts
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    ).stdout.splitlines()
    assert not any(
        path.startswith(("work/", "media/", "storage_data/")) for path in staged
    )

# ---------------------------------------------------------------------------
# Helpers for the behavioural proof (test_31 onward).
#
# Every mutation is a pure function returning a NEW payload, so no test can
# leak state into another. Mutations are applied to `model_dump(mode="json")`
# dictionaries rather than Pydantic models: `direct()` accepts
# `Mapping | BaseModel | None` and normalises through `_v2_dict`, so a dict is a
# first-class input, and a dict lets a negative test construct states the
# editorial engine would never emit.
# ---------------------------------------------------------------------------
SELECTED_IDS = ["must_make_truth", "strong_educational", "strong_emotional", "weak_payoff"]
UNSELECTED_IDS = ["backup_practical", "needs_context", "reject_fragment", "rights_risk"]
QUALITY_DIMENSIONS = {
    "hook_quality",
    "clarity",
    "emotional_pull",
    "pacing_strength",
    "visual_direction_strength",
    "caption_strength",
    "audio_direction_strength",
    "overall_confidence",
}
ENGINE_LIMITATIONS = [
    "Creative Director V2 is advisory and does not modify editing timelines or render media.",
    "Music direction is mood metadata only; no song, asset path, or copyright-safety claim "
    "is produced.",
    "Creative quality scores summarize saved evidence and do not predict audience performance.",
    "Human review remains required for source meaning, rights, framing, speech clarity, and "
    "final edit quality.",
]
PREDICTION_CLAIMS = (
    "will get",
    "expected views",
    "predicted engagement",
    "forecast",
    "guaranteed",
)
HYPOTHESIS_SUFFIX = (
    "This is an evidence-bound creative hypothesis, not audience-performance proof."
)


def _upstreams(project_id: str = PROJECT_ID) -> dict[str, Any]:
    """The six optional upstream artifacts from the shared fixture builder."""
    understanding, discovery, ranking, _, explanations, memory, signals = (
        build_synthetic_creative_direction_inputs(project_id)
    )
    return {
        "clip_ranking": ranking,
        "candidate_discovery": discovery,
        "whole_video_understanding": understanding,
        "explanations": explanations,
        "memory": memory,
        "analysis_signal_health": signals,
    }


def _editorial_payload(project_id: str = PROJECT_ID) -> dict[str, Any]:
    """The fixture's editorial decision set as a mutable JSON-safe dict."""
    _, _, _, decisions, _, _, _ = build_synthetic_creative_direction_inputs(project_id)
    payload = decisions.model_dump(mode="json")
    assert isinstance(payload, dict)
    return payload


def _direct_with_editorial(
    payload: Mapping[str, Any] | None,
    *,
    project_id: str = PROJECT_ID,
    include_optional: bool = True,
) -> BobaCreativeDirectionSetV2:
    """Run `direct()` with a (possibly mutated) editorial payload.

    `project_id` is keyword-only on `direct()`, so every argument is passed by
    keyword.
    """
    optional = _upstreams(project_id) if include_optional else {}
    return BobaCreativeDirectorV2Engine().direct(
        project_id=project_id,
        editorial_decisions=payload,
        **optional,
    )


def _created_at_paths(value: Any, path: str = "") -> list[str]:
    """Every dotted path at which a `created_at` key appears, at any depth."""
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key == "created_at":
                found.append(f"{path}.{key}" if path else key)
            found.extend(_created_at_paths(item, f"{path}.{key}" if path else str(key)))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_created_at_paths(item, f"{path}[{index}]"))
    return found


def _canonical(direction: BobaCreativeDirectionSetV2) -> str:
    """Sorted-key JSON of a direction set with ONLY the root `created_at` removed.

    The root timestamp is documented wall-clock metadata. Anything else named
    `created_at` would be an inherited upstream evidence timestamp, so this
    asserts the root is the only one rather than stripping recursively — a
    future inherited timestamp must fail loudly, not be silently excluded.
    """
    payload = direction.model_dump(mode="json")
    assert _created_at_paths(payload) == ["created_at"], (
        "only the root created_at may exist; an inherited upstream timestamp must "
        "not be silently excluded from the determinism comparison"
    )
    payload.pop("created_at", None)
    return json.dumps(payload, sort_keys=True, ensure_ascii=False)


def _strings(value: Any) -> list[str]:
    """Every string value anywhere in a nested structure."""
    out: list[str] = []
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, Mapping):
        for item in value.values():
            out.extend(_strings(item))
    elif isinstance(value, list):
        for item in value:
            out.extend(_strings(item))
    return out


def _decision(payload: Mapping[str, Any], candidate_id: str) -> dict[str, Any]:
    return next(
        item for item in payload["decisions"] if item["candidate_id"] == candidate_id
    )


def _select(payload: Mapping[str, Any], ids: list[str]) -> dict[str, Any]:
    out = copy.deepcopy(dict(payload))
    for item in out["decisions"]:
        item["selected"] = item["candidate_id"] in ids
    return out


def _deselect_all(payload: Mapping[str, Any]) -> dict[str, Any]:
    return _select(payload, [])


def _falsy_selected(
    payload: Mapping[str, Any], candidate_id: str, value: Any
) -> dict[str, Any]:
    out = copy.deepcopy(dict(payload))
    _decision(out, candidate_id)["selected"] = value
    return out


def _clone_selected(payload: Mapping[str, Any], total: int) -> dict[str, Any]:
    out = copy.deepcopy(dict(payload))
    template = _decision(out, "must_make_truth")
    existing = [item for item in out["decisions"] if item["selected"]]
    index = 0
    while len(existing) < total:
        clone = copy.deepcopy(template)
        clone["candidate_id"] = f"cloned_selected_{index}"
        clone["selected"] = True
        out["decisions"].append(clone)
        existing.append(clone)
        index += 1
    return out


def _set_project_id(payload: Mapping[str, Any], value: str | None) -> dict[str, Any]:
    out = copy.deepcopy(dict(payload))
    if value is None:
        out.pop("project_id", None)
    else:
        out["project_id"] = value
    return out


def _set_readiness(
    payload: Mapping[str, Any], candidate_id: str, value: str | None
) -> dict[str, Any]:
    out = copy.deepcopy(dict(payload))
    decision = _decision(out, candidate_id)
    if value is None:
        decision.pop("render_readiness", None)
    else:
        decision["render_readiness"] = value
    return out


def _set_motion(
    payload: Mapping[str, Any], candidate_id: str, style: str
) -> dict[str, Any]:
    out = copy.deepcopy(dict(payload))
    _decision(out, candidate_id)["motion_style"] = style
    return out


def _clear_limitations(payload: Mapping[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(dict(payload))
    out["limitations"] = []
    return out


def _sentinel_limitation(payload: Mapping[str, Any], text: str) -> dict[str, Any]:
    out = copy.deepcopy(dict(payload))
    out["limitations"] = [text]
    return out


# ---------------------------------------------------------------------------
# Behaviour 1 — selected-only authority (guard creative_director.py:670).
#
# `clip.selected` is hardcoded True by `_clip_direction`, so asserting it proves
# nothing about selection authority. These tests assert candidate-ID equality
# derived from the input payload instead.
# ---------------------------------------------------------------------------
def test_31_clip_directions_cover_exactly_the_selected_candidates() -> None:
    payload = _editorial_payload()
    expected = [item["candidate_id"] for item in payload["decisions"] if item["selected"]]

    result = _direct_with_editorial(payload)
    emitted = [clip.candidate_id for clip in result.clip_directions]

    assert emitted == expected
    assert emitted == SELECTED_IDS


def test_32_unselected_and_falsy_selected_candidates_receive_no_direction() -> None:
    payload = _editorial_payload()
    baseline = {clip.candidate_id for clip in _direct_with_editorial(payload).clip_directions}
    assert baseline.isdisjoint(UNSELECTED_IDS)

    for falsy in (0, "", [], None):
        mutated = _falsy_selected(payload, "must_make_truth", falsy)
        emitted = {
            clip.candidate_id for clip in _direct_with_editorial(mutated).clip_directions
        }
        assert "must_make_truth" not in emitted, f"falsy {falsy!r} was treated as selected"
        assert {"strong_educational", "strong_emotional", "weak_payoff"} <= emitted


def test_33_no_selected_decisions_yields_no_direction_and_does_not_raise() -> None:
    result = _direct_with_editorial(_deselect_all(_editorial_payload()))

    assert result.clip_directions == []
    assert result.project_id == PROJECT_ID
    assert (
        "No selected editorial decisions were available for clip direction."
        in result.warnings
    )


def test_34_selected_direction_count_is_capped_at_ten() -> None:
    payload = _clone_selected(_editorial_payload(), 12)
    selected = {item["candidate_id"] for item in payload["decisions"] if item["selected"]}
    assert len(selected) == 12

    result = _direct_with_editorial(payload)

    assert len(result.clip_directions) == 10
    assert {clip.candidate_id for clip in result.clip_directions} <= selected


# ---------------------------------------------------------------------------
# Behaviour 2 — project isolation (guard creative_director.py:655-656).
# ---------------------------------------------------------------------------
def test_35_cross_project_editorial_artifact_is_refused() -> None:
    mutated = _set_project_id(_editorial_payload(), "proj_other_tenant")

    with pytest.raises(ValidationError, match="belong to a different project") as caught:
        _direct_with_editorial(mutated)

    details = caught.value.details or {}
    assert details.get("project_id") == PROJECT_ID
    assert details.get("artifact_project_id") == "proj_other_tenant"


def test_36_matching_project_id_is_accepted_and_propagated() -> None:
    result = _direct_with_editorial(_editorial_payload())

    assert result.project_id == PROJECT_ID
    assert result.clip_directions
    assert all(clip.project_id == PROJECT_ID for clip in result.clip_directions)


def test_37_editorial_artifact_without_project_id_uses_the_requested_project() -> None:
    result = _direct_with_editorial(_set_project_id(_editorial_payload(), None))

    assert result.project_id == PROJECT_ID
    assert result.clip_directions


# ---------------------------------------------------------------------------
# Behaviour 3 — emotional motion softening (guard creative_director.py:1509).
#
# The fixture already requests `subtle_zoom` for the emotional clip, which is
# why deleting the branch changed nothing. These tests ARM the branch.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("requested", ["high_motion", "dynamic_zoom"])
def test_38_emotional_clip_softens_an_aggressive_motion_request(requested: str) -> None:
    payload = _set_motion(_editorial_payload(), "strong_emotional", requested)

    result = _direct_with_editorial(payload)
    emotional = _clip("strong_emotional", result)

    assert emotional.motion_direction.style == "subtle_zoom"
    assert emotional.motion_direction.style != requested


def test_39_motion_style_is_preserved_only_when_framing_is_safe_and_unemotional() -> None:
    # 1. Unemotional + aggressive + safe framing keeps the requested style. This
    #    is the control against a mutant that always returns subtle_zoom.
    result = _direct_with_editorial(_editorial_payload())
    assert _clip("must_make_truth", result).motion_direction.style == "dynamic_zoom"

    # 2. Missing face signals force layout-safe motion.
    degraded = _direct_with_analysis(face=False, visual=True)
    assert degraded.clip_directions
    assert all(
        clip.motion_direction.style == "layout_safe" for clip in degraded.clip_directions
    )

    # 3. The downgrade is recorded, so a substituted style is distinguishable
    #    from an unmodified request.
    softened = [
        warning
        for clip in degraded.clip_directions
        for warning in clip.motion_direction.safety_warnings
        if "was softened to layout-safe" in warning
    ]
    assert softened


# ---------------------------------------------------------------------------
# Behaviour 4 — determinism.
# ---------------------------------------------------------------------------
def test_40_repeated_direction_is_identical_except_created_at() -> None:
    payload = _editorial_payload()
    first = _direct_with_editorial(payload)
    second = _direct_with_editorial(payload)

    assert _canonical(first) == _canonical(second)
    assert first.created_at and second.created_at
    assert [clip.candidate_id for clip in first.clip_directions] == [
        clip.candidate_id for clip in second.clip_directions
    ]
    assert (
        first.creative_quality_summary.model_dump()
        == second.creative_quality_summary.model_dump()
    )

    left = first.model_dump(mode="json")
    right = second.model_dump(mode="json")
    differing = {key for key in set(left) | set(right) if left.get(key) != right.get(key)}
    assert differing <= {"created_at"}


def test_41_direct_from_signals_is_deterministic() -> None:
    understanding, discovery, ranking, decisions, explanations, memory, signals = (
        build_synthetic_creative_direction_inputs(PROJECT_ID)
    )
    engine = BobaCreativeDirectorV2Engine()

    def run() -> BobaCreativeDirectionSetV2:
        return engine.direct_from_signals(
            PROJECT_ID,
            signals,
            editorial_decisions=decisions,
            clip_ranking=ranking,
            candidate_discovery=discovery,
            whole_video_understanding=understanding,
            explanations=explanations,
            memory=memory,
        )

    assert _canonical(run()) == _canonical(run())


# ---------------------------------------------------------------------------
# Behaviour 5 — no upstream mutation. Nothing is excluded from this comparison:
# re-stamping an input timestamp would itself be a mutation.
# ---------------------------------------------------------------------------
def test_42_direction_does_not_mutate_upstream_artifacts() -> None:
    understanding, discovery, ranking, decisions, explanations, memory, signals = (
        build_synthetic_creative_direction_inputs(PROJECT_ID)
    )
    artifacts = {
        "whole_video_understanding": understanding,
        "candidate_discovery": discovery,
        "clip_ranking": ranking,
        "editorial_decisions": decisions,
        "explanations": explanations,
        "memory": memory,
        "analysis_signal_health": signals,
    }

    def snapshot() -> dict[str, Any]:
        return {
            name: copy.deepcopy(
                value.model_dump(mode="json") if hasattr(value, "model_dump") else value
            )
            for name, value in artifacts.items()
        }

    before = snapshot()
    engine = BobaCreativeDirectorV2Engine()
    first = engine.direct(project_id=PROJECT_ID, **artifacts)
    second = engine.direct(project_id=PROJECT_ID, **artifacts)

    assert snapshot() == before
    assert _canonical(first) == _canonical(second)


def test_43_upstream_artifacts_are_unchanged_when_direction_refuses() -> None:
    payload = _editorial_payload()
    upstreams = _upstreams()
    before_payload = copy.deepcopy(payload)
    before_upstreams = {
        name: copy.deepcopy(
            value.model_dump(mode="json") if hasattr(value, "model_dump") else value
        )
        for name, value in upstreams.items()
    }

    with pytest.raises(ValidationError):
        _direct_with_editorial(_set_project_id(payload, "proj_other_tenant"))
    with pytest.raises(ValidationError, match="requires saved editorial decisions"):
        _direct_with_editorial(None)

    assert payload == before_payload
    assert {
        name: (value.model_dump(mode="json") if hasattr(value, "model_dump") else value)
        for name, value in upstreams.items()
    } == before_upstreams


# ---------------------------------------------------------------------------
# Behaviour 6 — render_readiness is reproduced verbatim, never upgraded.
# ---------------------------------------------------------------------------
def test_44_forcing_a_rights_risk_clip_to_selected_preserves_blocked_readiness() -> None:
    payload = _select(_editorial_payload(), [*SELECTED_IDS, "rights_risk"])
    upstream = _decision(payload, "rights_risk")["render_readiness"]
    assert upstream == "blocked"

    result = _direct_with_editorial(payload)
    rights_risk = _clip("rights_risk", result)

    assert rights_risk.render_readiness == upstream == "blocked"
    assert rights_risk.render_readiness not in {"ready_for_render", "approved", "cleared"}


def test_45_render_readiness_mirrors_each_upstream_value() -> None:
    payload = _editorial_payload()
    assigned = {
        "must_make_truth": "quarantined_pending_rights",
        "strong_educational": "blocked",
        "strong_emotional": "needs_revision",
        "weak_payoff": "ready_for_render",
    }
    for candidate_id, value in assigned.items():
        payload = _set_readiness(payload, candidate_id, value)

    result = _direct_with_editorial(payload)

    assert {
        clip.candidate_id: clip.render_readiness for clip in result.clip_directions
    } == assigned


@pytest.mark.parametrize("value", [None, ""])
def test_46_absent_render_readiness_falls_back_to_needs_revision(value: str | None) -> None:
    payload = _set_readiness(_editorial_payload(), "must_make_truth", value)

    result = _direct_with_editorial(payload)

    assert _clip("must_make_truth", result).render_readiness == "needs_revision"


def test_47_a_blocked_clip_direction_carries_no_other_approval_bearing_field() -> None:
    payload = _select(_editorial_payload(), [*SELECTED_IDS, "rights_risk"])
    result = _direct_with_editorial(payload)
    blocked = _clip("rights_risk", result).model_dump(mode="json")

    # `selected` is excluded deliberately: it is a hardcoded restatement of
    # editorial selection, not an approval — the same reason it is inadmissible
    # as evidence in test_31.
    pattern = ("readiness", "approv", "clear", "authoris", "authoriz", "greenlight", "sign_off")
    bearing = {key for key in blocked if any(token in key.lower() for token in pattern)}
    assert bearing == {"render_readiness"}

    lowered = " ".join(_strings(blocked)).lower()
    for claim in ("approved", "cleared for", "rights cleared", "safe to render", "authorised"):
        assert claim not in lowered


# ---------------------------------------------------------------------------
# Behaviour 7 — the engine's OWN denials.
#
# Editorial limitations are emptied first, so an asserted string cannot have
# arrived from upstream. `human_review_notes[7]` is an editorial pass-through,
# so no test here may assert a fixed note index.
# ---------------------------------------------------------------------------
def test_48_engine_authored_limitations_are_emitted_without_upstream_help() -> None:
    result = _direct_with_editorial(_clear_limitations(_editorial_payload()))

    assert result.limitations == ENGINE_LIMITATIONS
    assert (
        result.limitations[2]
        == "Creative quality scores summarize saved evidence and do not predict "
        "audience performance."
    )


def test_49_hook_reason_declares_a_hypothesis_rather_than_performance_proof() -> None:
    result = _direct_with_editorial(_clear_limitations(_editorial_payload()))
    assert result.clip_directions

    prefixes = []
    for clip in result.clip_directions:
        reason = clip.hook_treatment.reason_it_should_work
        assert reason.endswith(HYPOTHESIS_SUFFIX)
        prefix = reason[: -len(HYPOTHESIS_SUFFIX)].strip()
        assert prefix
        prefixes.append(prefix)

    assert len(set(prefixes)) >= 1


def test_50_editorial_limitations_pass_through_to_human_review_notes() -> None:
    sentinel = "SENTINEL-EDITORIAL-LIMITATION-DO-NOT-AUTHOR-THIS"
    result = _direct_with_editorial(_sentinel_limitation(_editorial_payload(), sentinel))

    assert sentinel in result.project_direction.human_review_notes
    assert sentinel not in result.limitations


def test_51_audience_performance_phrasing_appears_only_inside_denials() -> None:
    payload = _editorial_payload()
    dump = _direct_with_editorial(payload).model_dump(mode="json")
    denial_tokens = ("do not predict", "not audience-performance proof", "does not")

    for text in _strings(dump):
        lowered = text.lower()
        if "audience performance" in lowered or "audience-performance" in lowered:
            assert any(token in lowered for token in denial_tokens), text
        for claim in PREDICTION_CLAIMS:
            assert claim not in lowered, text


def test_52_creative_quality_summary_is_the_same_eight_dimension_score() -> None:
    result = _direct_with_editorial(_editorial_payload())
    summary = result.creative_quality_summary.model_dump()

    assert set(summary) == QUALITY_DIMENSIONS
    for value in summary.values():
        assert isinstance(value, float)
        assert 0.0 <= value <= 100.0

    per_clip = [clip.creative_quality_score.model_dump() for clip in result.clip_directions]
    assert per_clip
    for score in per_clip:
        assert set(score) == QUALITY_DIMENSIONS

    for dimension in QUALITY_DIMENSIONS:
        expected = round(sum(score[dimension] for score in per_clip) / len(per_clip), 2)
        assert summary[dimension] == pytest.approx(expected, abs=0.01)


# ---------------------------------------------------------------------------
# Matrix completion.
# ---------------------------------------------------------------------------
def test_53_audio_direction_values_describe_mood_only() -> None:
    result = _direct_with_editorial(_editorial_payload())
    assert result.clip_directions

    for clip in result.clip_directions:
        for text in _strings(clip.audio_direction.model_dump(mode="json")):
            lowered = text.lower()
            assert "://" not in lowered
            assert "/" not in text
            assert "\\" not in text
            for extension in (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"):
                assert extension not in lowered
            for claim in ("copyright-safe", "licensed", "royalty-free"):
                assert claim not in lowered


def test_54_absent_optional_artifacts_are_declared_not_inferred() -> None:
    result = _direct_with_editorial(_editorial_payload(), include_optional=False)
    usage = result.signal_usage.model_dump()

    assert usage["editorial_decisions_used"] is True
    for flag in (
        "explanations_used",
        "clip_ranking_used",
        "candidate_discovery_used",
        "whole_video_understanding_used",
        "analysis_signals_used",
        "memory_used",
    ):
        assert usage[flag] is False, flag

    assert set(usage["unavailable_signals"]) == {
        "explanations",
        "clip_ranking",
        "candidate_discovery",
        "whole_video_understanding",
        "analysis_signal_health",
        "project_memory",
    }
    assert usage["fallback_used"] is True
    assert usage["warnings"]


def test_55_complete_inputs_declare_no_fallback() -> None:
    usage = _direct_with_editorial(_editorial_payload()).signal_usage.model_dump()

    assert usage["unavailable_signals"] == []
    assert usage["fallback_used"] is False
    for flag in (
        "editorial_decisions_used",
        "explanations_used",
        "clip_ranking_used",
        "candidate_discovery_used",
        "whole_video_understanding_used",
        "analysis_signals_used",
        "memory_used",
    ):
        assert usage[flag] is True, flag


def test_56_persistence_reports_absence_and_isolates_projects(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    other = "proj_creative_director_other"

    assert store.load_creative_direction_v2(PROJECT_ID) is None

    saved_other = store.save_creative_direction_v2(build_synthetic_creative_direction(other))
    other_bytes = store.creative_direction_v2_path(other).read_bytes()

    store.save_creative_direction_v2(build_synthetic_creative_direction(PROJECT_ID))

    assert store.creative_direction_v2_path(other).read_bytes() == other_bytes
    assert store.load_creative_direction_v2(other) == saved_other

    result = _direct_with_editorial(_editorial_payload())
    assert len(result.clip_directions) <= 10
    assert len(result.limitations) <= 32
    assert len(result.warnings) <= 64
    assert len(result.signal_usage.unavailable_signals) <= 32


def test_57_validator_reports_named_scenarios_and_all_pass() -> None:
    """The validator gate must assert semantics, not existence flags.

    `SCENARIO_NAMES` is imported from the validator so the test and the gate
    cannot drift apart. Nothing else is imported from it: this asserts the
    validator's observable output — exit code and report JSON — never its
    internals.
    """
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.validate_boba_creative_director_v2",
            "--synthetic-project",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout[-2000:] + completed.stderr[-2000:]

    start = completed.stdout.index("{")
    report = json.loads(completed.stdout[start:])

    assert tuple(report["scenario_results"]) == SCENARIO_NAMES
    assert all(report["scenario_results"].values())
    assert report["scenario_count"] == len(SCENARIO_NAMES)
    assert report["passed_scenario_count"] == len(SCENARIO_NAMES)
    assert report["skipped_scenarios"] == []
    assert report["passed"] is True
    for name in SCENARIO_NAMES:
        assert report["scenario_evidence"][name].strip()
