"""BOBA Creative Director V2 contracts, behavior, persistence, API, and validator tests."""

from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tools.validate_boba_creative_director_v2 import (
    REPORT_DIR,
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
