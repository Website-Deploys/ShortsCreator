"""Regression tests for the committed rights-safe music manifest."""

from __future__ import annotations

import json
from pathlib import Path

from tools.validate_test_assets_dependencies import inspect_music_manifest

from olympus.music import load_music_assets, load_music_manifest, resolve_music_intelligence

ROOT = Path(__file__).resolve().parents[2]


def _empty_music_intelligence() -> dict[str, object]:
    return {
        "decision": {
            "should_use_music": True,
            "target_mood": "neutral",
            "reason": "A safe local bed was requested.",
        },
        "input_signals": {},
        "mix_plan": {"warnings": []},
        "music_preparation": {"target_duration": 10.0},
    }


def test_committed_music_manifest_is_empty_and_rights_safe() -> None:
    path = ROOT / "assets" / "music" / "music_manifest.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    library = payload["music_library_v2"]

    assert library["assets"] == []
    assert library["rejected_assets"] == []
    assert not any(
        value.startswith(("http://", "https://"))
        for value in library["notes"] + library["warnings"]
    )

    inspection = inspect_music_manifest(ROOT)
    assert inspection["schema_valid"] is True
    assert inspection["absolute_user_paths"] == []
    assert inspection["remote_references"] == []


def test_empty_committed_manifest_loads_without_fake_tracks() -> None:
    registry = load_music_assets(ROOT / "assets")

    assert registry["schema"] == "music_library_v2"
    assert registry["assets"] == []
    assert registry["safe_assets"] == []

    resolved = resolve_music_intelligence(_empty_music_intelligence(), [])
    assert resolved["decision"]["should_use_music"] is False
    assert resolved["decision"]["disabled_reason"] == "no_safe_asset"
    assert resolved["selected_asset"] is None


def test_missing_manifest_returns_honest_empty_fallback(tmp_path: Path) -> None:
    manifest = load_music_manifest(tmp_path)

    assert manifest["schema"] == "missing"
    assert manifest["assets"] == []
    assert "No music manifest found" in manifest["reason"]


def test_music_asset_path_cannot_escape_library_root(tmp_path: Path) -> None:
    music_root = tmp_path / "music"
    music_root.mkdir()
    (tmp_path / "outside.wav").write_bytes(b"synthetic fixture")
    (music_root / "music_manifest.json").write_text(
        json.dumps(
            {
                "version": "2.0",
                "assets": [
                    {
                        "asset_id": "escape",
                        "relative_path": "../outside.wav",
                        "duration_seconds": 1.0,
                        "mood_tags": ["neutral"],
                        "energy_score": 0.2,
                        "license": "project_generated_safe",
                        "license_verified": True,
                        "source": "unit_test_generated_fixture",
                        "safe_default": True,
                        "speech_safe": True,
                        "quality_status": "passed",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    registry = load_music_assets(tmp_path)

    assert registry["safe_assets"] == []
    assert "invalid_asset_path" in registry["unsafe_assets"][0]["rejection_reasons"]
