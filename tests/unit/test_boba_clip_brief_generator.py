"""BOBA Clip Brief Generator V1 contracts, behavior, API, and safety tests."""

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
from tools.validate_boba_clip_brief_generator import (
    REPORT_DIR,
    build_synthetic_clip_brief_inputs,
    build_synthetic_clip_briefs,
)

from olympus.api.dependencies import boba_integration_provider
from olympus.boba import (
    BobaBriefInstructionV1,
    BobaClipBriefGeneratorV1,
    BobaClipBriefSetV1,
    BobaClipBriefSignalUsageV1,
    BobaClipBriefV1,
    BobaEditorChecklistItemV1,
    BobaIntegration,
    BobaMemoryStore,
    BobaSourceWindowV1,
)
from olympus.data.repositories import StorageProjectRepository
from olympus.data.storage.local import LocalStorage
from olympus.domain.entities.project import Project, ProjectStatus
from olympus.platform.errors import ValidationError
from olympus.utils import utc_now

ROOT = Path(__file__).resolve().parents[2]
PROJECT_ID = "proj_clip_brief_generator"


def _result(project_id: str = PROJECT_ID) -> BobaClipBriefSetV1:
    return build_synthetic_clip_briefs(project_id)


def _selected(candidate_id: str = "must_make_truth") -> BobaClipBriefV1:
    return next(
        item for item in _result().selected_briefs if item.candidate_id == candidate_id
    )


def _project(project_id: str = PROJECT_ID) -> Project:
    now = utc_now()
    return Project(
        id=project_id,
        name="BOBA Clip Brief Generator Test",
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


def test_01_brief_set_contract_serializes() -> None:
    result = _result()
    assert BobaClipBriefSetV1.model_validate_json(result.model_dump_json()) == result
    assert result.brief_version == "boba_clip_brief_generator_v1"


def test_02_clip_brief_contract_serializes() -> None:
    brief = _selected()
    assert BobaClipBriefV1.model_validate(brief.model_dump()) == brief


def test_03_source_window_serializes() -> None:
    window = _selected().source_window
    assert BobaSourceWindowV1.model_validate(window.model_dump()) == window
    assert window.duration_seconds == pytest.approx(
        window.end_seconds - window.start_seconds
    )


def test_04_instruction_contract_serializes() -> None:
    instruction = _selected().hook_instruction
    assert BobaBriefInstructionV1.model_validate(instruction.model_dump()) == instruction


def test_05_checklist_item_serializes() -> None:
    item = _selected().editor_checklist[0]
    assert BobaEditorChecklistItemV1.model_validate(item.model_dump()) == item


def test_06_signal_usage_serializes() -> None:
    usage = _result().signal_usage
    assert BobaClipBriefSignalUsageV1.model_validate(usage.model_dump()) == usage


def test_07_selected_creative_direction_creates_selected_brief() -> None:
    result = _result()
    assert "must_make_truth" in {item.candidate_id for item in result.selected_briefs}
    assert "must_make_truth" in result.production_order
    assert result.signal_usage.creative_direction_v2_used is True


def test_08_backup_ranking_creates_backup_brief() -> None:
    result = _result()
    backup = next(
        item for item in result.backup_briefs if item.candidate_id == "backup_practical"
    )
    assert backup.production_priority in {"medium", "low"}
    assert backup.render_readiness != "blocked"


def test_09_blocked_editorial_decision_creates_blocked_brief() -> None:
    result = _result()
    blocked = next(
        item for item in result.blocked_briefs if item.candidate_id == "rights_risk"
    )
    assert blocked.render_readiness == "blocked"
    assert blocked.production_priority == "do_not_produce"
    assert any(item.status == "blocked" for item in blocked.editor_checklist)


def test_10_hook_instruction_includes_do_avoid_and_reason() -> None:
    instruction = _selected().hook_instruction
    assert instruction.do_this
    assert instruction.avoid_this
    assert instruction.reason
    assert instruction.priority == "must_follow"


def test_11_opening_three_second_instruction_exists() -> None:
    instruction = _selected().opening_three_second_instruction
    assert instruction.instruction_type == "opening"
    assert "three" in instruction.avoid_this.casefold()
    assert instruction.summary


def test_12_story_instruction_preserves_context_and_payoff() -> None:
    instruction = _selected().story_instruction
    text = " ".join(
        [instruction.summary, instruction.do_this, instruction.avoid_this, instruction.reason]
    ).casefold()
    assert "context" in text
    assert "payoff" in text


def test_13_cut_instruction_warns_against_abrupt_cuts() -> None:
    instruction = _selected().cut_instruction
    assert "abrupt" in instruction.avoid_this.casefold()
    assert "payoff" in instruction.do_this.casefold()


def test_14_caption_instruction_includes_style_and_readability() -> None:
    instruction = _selected("strong_educational").caption_instruction
    text = " ".join(
        [instruction.summary, instruction.do_this, instruction.avoid_this]
    ).casefold()
    assert "caption" in instruction.summary.casefold()
    assert "readab" in text


def test_15_motion_instruction_respects_layout_and_face_warnings() -> None:
    instruction = _selected().motion_instruction
    text = f"{instruction.do_this} {instruction.avoid_this}".casefold()
    assert "stable" in instruction.summary.casefold()
    assert "face" in text
    assert "layout" in instruction.reason.casefold()


def test_16_audio_instruction_uses_mood_only_without_file_path() -> None:
    for brief in [
        *_result().selected_briefs,
        *_result().backup_briefs,
        *_result().blocked_briefs,
    ]:
        payload = brief.audio_instruction.model_dump_json().casefold()
        assert "mood" in payload
        assert not any(marker in payload for marker in (".mp3", ".wav", ".m4a", "music/"))


def test_17_sfx_instruction_avoids_overpowering_speech() -> None:
    instruction = _selected().sfx_instruction
    text = instruction.avoid_this.casefold()
    assert "static" in text
    assert "important words" in text
    assert "speech" in instruction.reason.casefold()


def test_18_retention_instruction_includes_open_loop_and_payoff() -> None:
    instruction = _selected().retention_instruction
    text = f"{instruction.summary} {instruction.do_this}".casefold()
    assert "curiosity" in text or "loop" in text
    assert "payoff" in text


def test_19_risk_fixes_include_required_reviews() -> None:
    text = " ".join(_selected().risk_fixes).casefold()
    for term in ("rights", "context", "payoff", "hook", "filler", "audio", "motion"):
        assert term in text


def test_20_editor_checklist_includes_required_items() -> None:
    categories = {item.category for item in _selected().editor_checklist}
    assert categories == {
        "hook",
        "context",
        "payoff",
        "pacing",
        "captions",
        "motion",
        "audio",
        "rights",
        "render_safety",
        "human_review",
    }
    assert all(item.required for item in _selected().editor_checklist)


def test_21_missing_creative_direction_v2_fails_clearly() -> None:
    *_, decisions, _explanations, _memory, _signals = (
        build_synthetic_clip_brief_inputs("proj_missing_direction")
    )
    with pytest.raises(ValidationError, match="requires saved Creative Director V2"):
        BobaClipBriefGeneratorV1().generate(
            project_id="proj_missing_direction",
            creative_direction_v2=None,
            editorial_decisions=decisions,
        )


def test_22_missing_editorial_decision_fails_clearly() -> None:
    direction, *_ = build_synthetic_clip_brief_inputs("proj_missing_editorial")
    with pytest.raises(ValidationError, match="requires saved editorial decisions"):
        BobaClipBriefGeneratorV1().generate(
            project_id="proj_missing_editorial",
            creative_direction_v2=direction,
            editorial_decisions=None,
        )


def test_23_artifact_persistence_writes_json_safe_output(tmp_path: Path) -> None:
    store = BobaMemoryStore(tmp_path / "boba")
    result = store.save_clip_briefs(_result())
    path = store.clip_briefs_path(PROJECT_ID)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert path.as_posix().endswith(f"projects/{PROJECT_ID}/clip_briefs/index.json")
    assert store.load_clip_briefs(PROJECT_ID) == result
    assert payload["brief_version"] == "boba_clip_brief_generator_v1"
    assert "transcript_segments" not in payload


def test_24_api_routes_return_saved_briefs_and_frontend_exposes_them(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    storage = LocalStorage(root=str(tmp_path / "storage"))
    store = BobaMemoryStore(tmp_path / "boba")
    (
        direction,
        understanding,
        discovery,
        ranking,
        decisions,
        explanations,
        memory,
        _signals,
    ) = build_synthetic_clip_brief_inputs(PROJECT_ID)
    asyncio.run(StorageProjectRepository(storage).save(_project()))
    store.save_creative_direction_v2(direction)
    store.save_whole_video_understanding(understanding)
    store.save_candidate_clip_discovery(discovery)
    store.save_clip_ranking(ranking)
    store.save_editorial_decisions(decisions)
    store.save_explanations(explanations)
    store.save_project_memory(memory)
    integration = BobaIntegration(storage, store)
    app.dependency_overrides[boba_integration_provider] = lambda: integration
    with TestClient(app) as client:
        created = client.post(f"/api/v1/boba/projects/{PROJECT_ID}/clip-briefs")
        saved = client.get(f"/api/v1/boba/projects/{PROJECT_ID}/clip-briefs")
    assert created.status_code == 200
    assert saved.status_code == 200
    assert created.json()["selected_briefs"] == saved.json()["selected_briefs"]
    panel = (
        ROOT / "frontend" / "src" / "components" / "project" / "ResultsSection.tsx"
    ).read_text(encoding="utf-8")
    assert "BOBA Clip Brief Generator V1" in panel
    assert "One-page editor packet" in panel
    assert "Full instruction packet" in panel


def test_25_validator_self_check_passes() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "validate_boba_clip_brief_generator.py"),
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


def test_26_validator_synthetic_project_passes() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "validate_boba_clip_brief_generator.py"),
            "--synthetic-project",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert '"backup_brief_count": 2' in result.stdout.casefold()
    assert '"blocked_brief_count": 2' in result.stdout.casefold()
    assert '"music_mood_only": true' in result.stdout.casefold()


def test_27_generation_does_not_trigger_rendering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_subprocess(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("rendering or subprocess execution is forbidden")

    monkeypatch.setattr(subprocess, "run", fail_subprocess)
    assert _result().selected_briefs


def test_28_generation_makes_no_external_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_network(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("network access is forbidden")

    monkeypatch.setattr(socket, "create_connection", fail_network)
    assert _result().signal_usage.editorial_decision_used is True


def test_29_reports_and_media_are_not_staged() -> None:
    assert REPORT_DIR == ROOT / "work" / "validation_reports" / "boba_clip_brief_generator"
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
