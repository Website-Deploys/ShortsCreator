from __future__ import annotations

import json
import runpy
import subprocess
import sys
from pathlib import Path

from olympus.integration.clip_intelligence import unified_clip_intelligence
from olympus.music import (
    build_music_validation,
    load_music_assets,
    plan_music_intelligence,
    resolve_music_intelligence,
)
from olympus.rendering.command import filter_complex


def _blueprint(niche: str, story_shape: str = "problem_solution") -> dict[str, object]:
    return {
        "content_niche": {"primary": niche},
        "storytelling_v2": {"story_shape": story_shape},
        "hook_analysis_v2": {"category": "curiosity_question"},
        "ending_payoff_v2": {"ending_type": "lesson"},
        "music_decision_v2": {"status": "unavailable", "category": niche},
        "viral_score_v2": {"overall": 0.8},
    }


def _bundle() -> dict[str, object]:
    return {
        "caption_timing": {
            "captions": [
                {"start": 0.0, "end": 5.0},
                {"start": 5.3, "end": 10.0},
                {"start": 10.2, "end": 16.0},
                {"start": 16.2, "end": 23.0},
                {"start": 23.2, "end": 29.0},
            ]
        },
        "silence_detection": {"silences": [{"start": 5.0, "end": 5.3}]},
    }


def _plan(niche: str, story_shape: str = "problem_solution") -> dict[str, object]:
    return plan_music_intelligence(
        clip={"clip_id": "clip_a", "duration": 30.0},
        blueprint=_blueprint(niche, story_shape),
        bundle=_bundle(),
        project_id="project_a",
    )


def _asset(asset_id: str, **overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "asset_id": asset_id,
        "path": f"C:/{asset_id}.wav",
        "filename": f"music/generated/{asset_id}.wav",
        "title": asset_id,
        "duration": 36.0,
        "bpm": 110.0,
        "mood_tags": ["motivational"],
        "energy_level": 0.72,
        "intensity": 0.68,
        "genre_tags": ["cinematic"],
        "niche_tags": ["motivational"],
        "loopable": True,
        "has_vocals": False,
        "speech_safe": True,
        "license": "project_generated_safe",
        "license_verified": True,
        "safe_default": True,
        "source": "generated_validation_asset",
        "folder_type": "generated",
        "quality_status": "passed",
        "quality": "validation_quality",
        "recommended_gain_db": -18.0,
        "automatic_use_allowed": True,
    }
    value.update(overrides)
    return value


def _write_registry(root: Path, assets: list[dict[str, object]]) -> None:
    music = root / "music"
    music.mkdir(parents=True)
    for asset in assets:
        path = root / str(asset["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        if asset.pop("create_file", True):
            path.write_bytes(b"RIFFmusic")
    (music / "music_manifest.json").write_text(
        json.dumps({"version": "2", "assets": assets}),
        encoding="utf-8",
    )


def test_registry_accepts_safe_generated_asset(tmp_path: Path) -> None:
    _write_registry(
        tmp_path,
        [
            {
                "asset_id": "safe",
                "path": "music/generated/safe.wav",
                "license": "project_generated_safe",
                "license_verified": True,
                "safe_default": True,
                "usage_allowed": True,
                "duration": 36.0,
                "mood_tags": ["focused"],
                "energy_level": 0.4,
                "speech_safe": True,
                "has_vocals": False,
                "source": "generated_validation_asset",
                "quality": "validation_quality",
            }
        ],
    )

    registry = load_music_assets(tmp_path)

    assert len(registry["safe_assets"]) == 1
    assert registry["safe_assets"][0]["automatic_use_allowed"] is True


def test_registry_rejects_unknown_license_and_missing_file(tmp_path: Path) -> None:
    _write_registry(
        tmp_path,
        [
            {
                "asset_id": "unknown",
                "path": "music/user/unknown.wav",
                "license": "",
                "license_verified": False,
                "safe_default": True,
                "create_file": False,
            }
        ],
    )

    registry = load_music_assets(tmp_path)
    reasons = registry["unsafe_assets"][0]["rejection_reasons"]

    assert "license_missing" in reasons
    assert "license_not_verified" in reasons
    assert "missing_asset_file" in reasons


def test_registry_handles_invalid_manifest(tmp_path: Path) -> None:
    (tmp_path / "music").mkdir()
    (tmp_path / "music" / "music_manifest.json").write_text("{", encoding="utf-8")

    registry = load_music_assets(tmp_path)

    assert registry["assets"] == []
    assert "could not be read" in registry["reason"]


def test_motivational_maps_to_drive_with_payoff_swell() -> None:
    plan = _plan("motivational", "pain_transformation")

    assert plan["decision"]["music_role"] == "motivational_drive"
    assert plan["decision"]["target_mood"] == "motivational"
    assert plan["music_story_events"]["payoff_event"]["enabled"] is True


def test_emotional_podcast_education_and_gaming_map_differently() -> None:
    assert _plan("emotional_story")["decision"]["music_role"] == "emotional_bed"
    assert _plan("podcast_interview")["decision"]["music_role"] == "subtle_bed"
    assert _plan("education_tutorial")["decision"]["music_role"] == "educational_focus"
    assert _plan("gaming_stream")["decision"]["music_role"] == "gaming_energy"


def test_singing_disables_background_music() -> None:
    plan = _plan("music_singing")

    assert plan["decision"]["should_use_music"] is False
    assert plan["decision"]["disabled_reason"] == "source_is_music_performance"


def test_no_safe_asset_disables_music_honestly() -> None:
    resolved = resolve_music_intelligence(_plan("motivational"), [])

    assert resolved["decision"]["should_use_music"] is False
    assert resolved["decision"]["disabled_reason"] == "no_safe_asset"
    assert resolved["selected_asset"] is None


def test_best_mood_match_wins_and_unsafe_asset_is_not_considered() -> None:
    resolved = resolve_music_intelligence(
        _plan("motivational"),
        [
            _asset("calm", mood_tags=["calm"], energy_level=0.3),
            _asset("drive"),
        ],
        rejected_assets=[
            _asset(
                "unsafe",
                license_verified=False,
                automatic_use_allowed=False,
                rejection_reasons=["license_not_verified"],
            )
        ],
    )

    assert resolved["selected_asset"]["asset_id"] == "drive"
    assert resolved["selected_asset"]["license_verified"] is True


def test_repeated_asset_is_penalized() -> None:
    assets = [_asset("alpha"), _asset("beta")]
    first = resolve_music_intelligence(_plan("motivational"), assets)
    repeated = str(first["selected_asset"]["asset_id"])
    second = resolve_music_intelligence(
        _plan("motivational"),
        assets,
        usage_counts={repeated: 2},
    )

    assert second["selected_asset"]["asset_id"] != repeated
    score = next(item for item in second["asset_scores"] if item["asset_id"] == repeated)
    assert score["repetition_penalty"] > 0


def test_reuse_penalty_never_promotes_wrong_mood() -> None:
    resolved = resolve_music_intelligence(
        _plan("motivational"),
        [
            _asset("drive"),
            _asset(
                "gaming",
                mood_tags=["intense", "energetic"],
                genre_tags=["electronic"],
                niche_tags=["gaming_stream"],
                energy_level=0.8,
            ),
        ],
        usage_counts={"drive": 20},
    )

    assert resolved["selected_asset"]["asset_id"] == "drive"


def test_mix_plan_is_speech_first_and_bounded() -> None:
    resolved = resolve_music_intelligence(_plan("education_tutorial"), [_asset("focus")])
    mix = resolved["mix_plan"]

    assert -32.0 <= mix["music_gain_db"] <= -14.0
    assert mix["ducking_enabled"] is True
    assert mix["fade_in_seconds"] > 0
    assert mix["fade_out_seconds"] > 0


def test_filter_graph_applies_real_sidechain_ducking_without_shortest() -> None:
    timeline = {
        "source_start": 0.0,
        "source_end": 8.0,
        "duration": 8.0,
        "metadata": {
            "render_assets_v2": {
                "music": {
                    "mixed": True,
                    "path": "music.wav",
                    "gain_db": -22.0,
                    "fade_in_s": 0.35,
                    "fade_out_s": 0.8,
                    "mix_plan": {"ducking_threshold": -24.0, "ducking_ratio": 6.0},
                    "ducking_plan": {
                        "enabled": True,
                        "attack_ms": 120.0,
                        "release_ms": 450.0,
                    },
                    "music_story_events": {},
                },
                "sfx": {"events": []},
            }
        },
    }

    graph = filter_complex(timeline, 1080, 1920, 30, None)

    assert "sidechaincompress=" in graph
    assert "[voice]asplit=2" in graph
    assert "amix=inputs=2:duration=first" in graph
    assert "atrim=0:8.000" in graph
    assert "shortest" not in graph


def test_validation_is_honest_about_audibility_and_clarity() -> None:
    intelligence = resolve_music_intelligence(_plan("motivational"), [_asset("drive")])
    validation = build_music_validation(
        intelligence,
        output_audio_present=True,
        sync_validation={"passed": True},
        duration_validation={"passed": True},
        ffmpeg_completed=True,
    )

    assert validation["mixed"] is True
    assert validation["audible"] == "not_verified"
    assert validation["speech_clarity_passed"] == "not_verified"
    assert validation["license_safe"] is True
    assert validation["asset_safe"] is True
    assert validation["validation_asset"] is True
    assert validation["passed"] is True


def test_unified_metadata_contains_music_intelligence() -> None:
    intelligence = resolve_music_intelligence(_plan("motivational"), [_asset("drive")])
    unified = unified_clip_intelligence(
        clip={"clip_id": "clip_a", "duration": 30.0},
        editing_v2={"music_intelligence_v2": intelligence},
    )

    assert unified["music_intelligence"]["role"] == "motivational_drive"
    assert unified["music_intelligence"]["selected_asset"]["asset_id"] == "drive"
    assert unified["music_intelligence"]["selected_asset"]["folder_type"] == "generated"
    assert (
        unified["music_intelligence"]["library_selection"]["selected_priority_tier"]
        == "generated"
    )


def test_installer_profiles_are_generated_and_license_explicit() -> None:
    namespace = runpy.run_path("tools/install_music_assets.py")
    profiles = namespace["PROFILES"]
    source = Path("tools/install_music_assets.py").read_text(encoding="utf-8")

    assert len(profiles) == 6
    assert "project_generated_safe" in source
    assert "generated_validation_asset" in source
    assert "anoisesrc" not in source
    assert "youtube" not in source.lower()
    assert "spotify" not in source.lower()


def test_cli_lists_assets_as_json(tmp_path: Path) -> None:
    _write_registry(
        tmp_path,
        [
            {
                "asset_id": "safe",
                "path": "music/generated/safe.wav",
                "license": "project_generated_safe",
                "license_verified": True,
                "safe_default": True,
                "usage_allowed": True,
                "duration": 36.0,
                "mood_tags": ["focused"],
                "energy_level": 0.4,
                "speech_safe": True,
                "has_vocals": False,
                "source": "generated_validation_asset",
                "quality": "validation_quality",
            }
        ],
    )
    completed = subprocess.run(
        [
            sys.executable,
            "tools/validate_music_intelligence.py",
            "--list-assets",
            "--asset-root",
            str(tmp_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    report = json.loads(completed.stdout)["music_validation_report"]
    assert completed.returncode == 0
    assert report["mode"] == "list_assets"
    assert report["safe_assets"] == 1
    assert report["generated_assets"] == 1
