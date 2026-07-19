"""Tests for optional dependency availability and validator self-checks."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from tools import validate_test_assets_dependencies as validator

from olympus import dependencies
from olympus.ai import transcription
from olympus.platform.errors import ConfigurationError

ROOT = Path(__file__).resolve().parents[2]


def test_optional_dependency_status_is_json_safe(monkeypatch: Any) -> None:
    monkeypatch.setattr(dependencies.importlib.util, "find_spec", lambda _name: None)

    status = dependencies.get_optional_dependency_status()

    assert status["faster_whisper"]["available"] is False
    assert status["ctranslate2"]["extra"] == "transcription"
    assert status["cv2"]["extra"] == "vision"
    assert json.loads(json.dumps(status))["easyocr"]["required"] is False


def test_transcription_adapters_import_without_optional_packages() -> None:
    assert transcription.FasterWhisperTranscriptionProvider.__name__ == (
        "FasterWhisperTranscriptionProvider"
    )
    assert transcription.NoopTranscriptionProvider.__name__ == "NoopTranscriptionProvider"


def test_pyproject_declares_transcription_and_vision_extras() -> None:
    payload = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    extras = payload["project"]["optional-dependencies"]

    assert any(item.startswith("faster-whisper") for item in extras["transcription"])
    assert any(item.startswith("ctranslate2") for item in extras["transcription"])
    assert any(item.startswith("opencv-python") for item in extras["vision"])


def test_missing_optional_dependency_raises_actionable_error(monkeypatch: Any) -> None:
    def missing(_name: str) -> ModuleType:
        raise ModuleNotFoundError("not installed")

    monkeypatch.setattr(dependencies.importlib, "import_module", missing)

    with pytest.raises(ConfigurationError) as captured:
        dependencies.require_optional_dependency(
            "faster_whisper",
            "Real local transcription",
        )

    assert "faster-whisper" in captured.value.message
    assert ".[transcription]" in captured.value.message
    assert captured.value.details["available"] is False


def test_available_optional_dependency_is_returned(monkeypatch: Any) -> None:
    module = ModuleType("optional_fixture")
    monkeypatch.setattr(dependencies.importlib, "import_module", lambda _name: module)

    assert (
        dependencies.require_optional_dependency("optional_fixture", "Fixture feature")
        is module
    )


def test_self_check_warns_but_passes_when_ml_dependencies_are_missing(
    monkeypatch: Any,
    tmp_path: Any,
) -> None:
    missing = {
        name: {**details, "available": False}
        for name, details in dependencies.get_optional_dependency_status().items()
    }
    monkeypatch.setattr(validator, "get_optional_dependency_status", lambda: missing)
    monkeypatch.setattr(
        validator.shutil,
        "which",
        lambda name: f"C:/tools/{name}.exe" if name in {"ffmpeg", "ffprobe"} else None,
    )
    monkeypatch.setattr(validator, "_tracked_media", lambda _root: ([], None))

    result = validator.self_check(root=validator.ROOT, report_dir=tmp_path)

    assert result["passed"] is True
    assert result["errors"] == []
    assert any("faster_whisper unavailable" in item for item in result["warnings"])


def test_self_check_fails_clearly_when_ffmpeg_is_missing(
    monkeypatch: Any,
    tmp_path: Any,
) -> None:
    monkeypatch.setattr(
        validator.shutil,
        "which",
        lambda name: "C:/tools/ffprobe.exe" if name == "ffprobe" else None,
    )
    monkeypatch.setattr(validator, "_tracked_media", lambda _root: ([], None))

    result = validator.self_check(root=validator.ROOT, report_dir=tmp_path)

    assert result["passed"] is False
    assert "Required local tool ffmpeg is unavailable." in result["errors"]
