"""Tests for Curated Music Library Tool V2."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from tools import install_music_assets, manage_music_library

from olympus.music import (
    MusicLibraryError,
    MusicLibraryManager,
    load_music_assets,
    plan_music_intelligence,
    resolve_music_intelligence,
)
from olympus.music import library as music_library


def _analysis(**overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "passed": True,
        "duration_seconds": 45.0,
        "sample_rate": 48000,
        "channels": 2,
        "codec": "pcm_s16le",
        "container": "wav",
        "bitrate": 1536000,
        "bpm": None,
        "bpm_confidence": "unknown",
        "key": None,
        "key_confidence": "unknown",
        "loudness_lufs": -18.0,
        "loudness_method": "ffmpeg_ebur128",
        "peak_db": -2.0,
        "rms_db": -20.0,
        "dynamic_range": 9.0,
        "clipping_detected": False,
        "silence_ratio": 0.02,
        "energy_level": "medium",
        "energy_score": 0.56,
        "tempo_category": "unknown",
        "loopable_hint": True,
        "intro_seconds": None,
        "outro_seconds": None,
        "quality_status": "passed",
        "warnings": [],
        "errors": [],
    }
    value.update(overrides)
    return value


def _source(path: Path, content: bytes = b"RIFF-owned-music") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _import_safe(
    manager: MusicLibraryManager,
    source_path: Path,
    **overrides: Any,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "title": "Licensed Drive",
        "license_name": "CC0",
        "license_verified": True,
        "source": "User provided licensed file",
        "moods": ["motivational"],
        "use_cases": ["motivational_speech"],
        "energy": "medium_high",
        "intensity": "balanced",
        "instrumental": True,
        "speech_safe": True,
        "loopable": True,
    }
    metadata.update(overrides)
    return manager.import_file(source_path, **metadata)


def _selection_plan() -> dict[str, Any]:
    return plan_music_intelligence(
        clip={"clip_id": "clip_a", "duration": 30.0},
        blueprint={
            "content_niche": {"primary": "motivational"},
            "storytelling_v2": {"story_shape": "pain_transformation"},
            "music_decision_v2": {"status": "unavailable"},
        },
        bundle={
            "caption_timing": {
                "captions": [
                    {"start": 0.0, "end": 10.0},
                    {"start": 10.2, "end": 20.0},
                    {"start": 20.2, "end": 29.5},
                ]
            }
        },
        project_id="project_a",
    )


def _selectable_asset(asset_id: str, folder_type: str) -> dict[str, Any]:
    return {
        "asset_id": asset_id,
        "title": asset_id,
        "path": f"C:/{asset_id}.wav",
        "filename": f"music/{folder_type}/{asset_id}.wav",
        "relative_path": f"{folder_type}/{asset_id}.wav",
        "folder_type": folder_type,
        "duration": 45.0,
        "duration_seconds": 45.0,
        "bpm": 110.0,
        "mood_tags": ["motivational"],
        "genre_tags": ["cinematic"],
        "niche_tags": ["motivational"],
        "energy_level": 0.74,
        "intensity": 0.58,
        "loopable": True,
        "has_vocals": False,
        "instrumental": True,
        "speech_safe": True,
        "license": "cc0",
        "license_verified": True,
        "safe_default": True,
        "quality_status": "passed",
        "automatic_use_allowed": True,
        "source": "local",
        "usage_count": 0,
    }


def test_init_creates_safe_folder_structure_and_manifest(tmp_path: Path) -> None:
    manager = MusicLibraryManager(tmp_path / "music")

    library = manager.initialize()

    for folder in music_library.LIBRARY_FOLDERS:
        assert (manager.root / folder).is_dir()
    payload = json.loads(manager.manifest_path.read_text(encoding="utf-8"))
    assert payload["music_library_v2"]["version"] == "2.0"
    assert library["assets"] == []


def test_flat_manifest_migrates_without_deleting_generated_asset(tmp_path: Path) -> None:
    root = tmp_path / "music"
    _source(root / "generated" / "starter.wav")
    root.mkdir(exist_ok=True)
    (root / "music_manifest.json").write_text(
        json.dumps(
            {
                "version": "2",
                "assets": [
                    {
                        "asset_id": "starter",
                        "path": "music/generated/starter.wav",
                        "duration": 36.0,
                        "mood_tags": ["focused"],
                        "energy_level": 0.4,
                        "speech_safe": True,
                        "has_vocals": False,
                        "license": "project_generated_safe",
                        "license_verified": True,
                        "safe_default": True,
                        "usage_allowed": True,
                        "source": "generated_validation_asset",
                        "quality": "validation_quality",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    manager = MusicLibraryManager(root)
    library = manager.initialize()

    assert len(library["assets"]) == 1
    assert library["assets"][0]["folder_type"] == "generated"
    payload = json.loads(manager.manifest_path.read_text(encoding="utf-8"))
    assert "music_library_v2" in payload
    assert (root / "generated" / "starter.wav").exists()


def test_invalid_manifest_is_reported_without_overwrite(tmp_path: Path) -> None:
    root = tmp_path / "music"
    root.mkdir()
    manifest = root / "music_manifest.json"
    manifest.write_text("{", encoding="utf-8")

    with pytest.raises(MusicLibraryError, match="could not be read"):
        MusicLibraryManager(root).initialize()

    assert manifest.read_text(encoding="utf-8") == "{"


def test_registry_rejects_path_traversal_and_missing_file(tmp_path: Path) -> None:
    asset_root = tmp_path / "assets"
    music_root = asset_root / "music"
    music_root.mkdir(parents=True)
    library = {
        "version": "2.0",
        "updated_at": music_library.utc_now_iso(),
        "library_root": str(music_root),
        "assets": [
            {
                "asset_id": "escape",
                "title": "Escape",
                "relative_path": "../outside.wav",
                "duration_seconds": 30.0,
                "mood_tags": ["focused"],
                "energy_level": "medium",
                "speech_safe": True,
                "license": "cc0",
                "license_verified": True,
                "safe_default": True,
                "auto_select_allowed": True,
                "manual_review_required": False,
                "quality_status": "passed",
                "source": "user",
            }
        ],
        "rejected_assets": [],
        "warnings": [],
        "stats": {},
    }
    music_library.save_library_manifest(music_root, library)

    registry = load_music_assets(asset_root)

    reasons = registry["unsafe_assets"][0]["rejection_reasons"]
    assert "invalid_asset_path" in reasons


@pytest.mark.parametrize("extension", [".wav", ".mp3"])
def test_verified_import_becomes_curated_and_selectable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    extension: str,
) -> None:
    monkeypatch.setattr(music_library, "analyze_audio", lambda *_args, **_kwargs: _analysis())
    manager = MusicLibraryManager(tmp_path / "music")
    source = _source(tmp_path / "incoming" / f"drive{extension}")

    result = _import_safe(manager, source)

    asset = result["asset"]
    assert result["status"] == "imported"
    assert asset["folder_type"] == "curated"
    assert asset["license_verified"] is True
    assert asset["safe_default"] is True
    assert asset["auto_select_allowed"] is True
    assert Path(asset["absolute_path"]).is_file()


@pytest.mark.parametrize("license_name", [None, "unknown", "copyrighted_unknown"])
def test_missing_or_unknown_license_is_quarantined(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    license_name: str | None,
) -> None:
    monkeypatch.setattr(music_library, "analyze_audio", lambda *_args, **_kwargs: _analysis())
    manager = MusicLibraryManager(tmp_path / "music")
    source = _source(tmp_path / "incoming" / "track.wav")

    result = manager.import_file(
        source,
        license_name=license_name,
        license_verified=True,
        source="User provided",
        moods=["calm"],
        energy="low",
        instrumental=True,
        speech_safe=True,
    )

    asset = result["asset"]
    assert result["status"] == "quarantine"
    assert asset["folder_type"] == "quarantine"
    assert asset["auto_select_allowed"] is False
    assert asset["manual_review_required"] is True


def test_safe_default_is_blocked_without_verified_license(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(music_library, "analyze_audio", lambda *_args, **_kwargs: _analysis())
    manager = MusicLibraryManager(tmp_path / "music")

    result = manager.import_file(
        _source(tmp_path / "incoming" / "track.wav"),
        license_name="CC0",
        license_verified=False,
        source="User provided",
        moods=["calm"],
        energy="low",
        instrumental=True,
        speech_safe=True,
        safe_default=True,
    )

    assert result["asset"]["safe_default"] is False
    assert result["asset"]["auto_select_allowed"] is False
    assert "license_not_verified" in result["asset"]["rejection_reasons"]


def test_attribution_requirement_blocks_automatic_use(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(music_library, "analyze_audio", lambda *_args, **_kwargs: _analysis())
    manager = MusicLibraryManager(tmp_path / "music")

    result = _import_safe(
        manager,
        _source(tmp_path / "incoming" / "track.wav"),
        attribution_required=True,
        attribution_text=None,
    )

    assert result["asset"]["auto_select_allowed"] is False
    assert "attribution_text_missing" in result["asset"]["rejection_reasons"]


def test_streaming_platform_source_is_never_auto_selected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(music_library, "analyze_audio", lambda *_args, **_kwargs: _analysis())
    manager = MusicLibraryManager(tmp_path / "music")

    result = _import_safe(
        manager,
        _source(tmp_path / "incoming" / "track.wav"),
        source="YouTube rip",
    )

    assert result["asset"]["auto_select_allowed"] is False
    assert "streaming_platform_source_requires_review" in (
        result["asset"]["rejection_reasons"]
    )


def test_invalid_extension_is_rejected_without_copy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        music_library,
        "analyze_audio",
        lambda *_args, **_kwargs: pytest.fail("analysis should not run"),
    )
    manager = MusicLibraryManager(tmp_path / "music")

    result = manager.import_file(_source(tmp_path / "incoming" / "video.mp4"))

    assert result["status"] == "rejected"
    assert result["asset"]["rejection_reasons"] == ["unsupported_audio_extension"]
    assert not list((manager.root / "curated").glob("*"))


def test_duplicate_filename_never_overwrites(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(music_library, "analyze_audio", lambda *_args, **_kwargs: _analysis())
    manager = MusicLibraryManager(tmp_path / "music")
    first = _source(tmp_path / "one" / "track.wav", b"first")
    second = _source(tmp_path / "two" / "track.wav", b"second")

    first_result = _import_safe(manager, first, title="Same Track")
    second_result = _import_safe(manager, second, title="Same Track")

    first_path = Path(first_result["asset"]["absolute_path"])
    second_path = Path(second_result["asset"]["absolute_path"])
    assert first_path != second_path
    assert first_path.read_bytes() == b"first"
    assert second_path.read_bytes() == b"second"


def test_exact_hash_import_returns_existing_asset(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(music_library, "analyze_audio", lambda *_args, **_kwargs: _analysis())
    manager = MusicLibraryManager(tmp_path / "music")
    first = _source(tmp_path / "one" / "track.wav", b"same")
    second = _source(tmp_path / "two" / "copy.wav", b"same")

    original = _import_safe(manager, first)
    duplicate = _import_safe(manager, second)

    assert duplicate["status"] == "duplicate"
    assert duplicate["asset"]["asset_id"] == original["asset"]["asset_id"]
    assert len(manager.load()["assets"]) == 1


def test_ffprobe_and_ffmpeg_analysis_parses_quality(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = _source(tmp_path / "track.wav")
    monkeypatch.setattr(music_library, "_resolve_binary", lambda binary: binary)
    responses = iter(
        [
            subprocess.CompletedProcess(
                [],
                0,
                stdout=json.dumps(
                    {
                        "format": {
                            "duration": "45.0",
                            "bit_rate": "1536000",
                            "format_name": "wav",
                        },
                        "streams": [
                            {
                                "codec_type": "audio",
                                "codec_name": "pcm_s16le",
                                "sample_rate": "48000",
                                "channels": 2,
                            }
                        ],
                    }
                ),
                stderr="",
            ),
            subprocess.CompletedProcess(
                [],
                0,
                stdout="",
                stderr="Summary:\n I: -18.2 LUFS\n Peak: -2.1 dBFS\n",
            ),
            subprocess.CompletedProcess(
                [],
                0,
                stdout="",
                stderr=(
                    "RMS level dB: -20.0\nPeak level dB: -2.0\n"
                    "Dynamic range: 8.5\nsilence_duration: 1.5\n"
                ),
            ),
        ]
    )
    monkeypatch.setattr(music_library.subprocess, "run", lambda *_args, **_kwargs: next(responses))

    result = music_library.analyze_audio(source)

    assert result["passed"] is True
    assert result["duration_seconds"] == 45.0
    assert result["loudness_lufs"] == -18.2
    assert result["rms_db"] == -20.0
    assert result["silence_ratio"] == pytest.approx(1.5 / 45.0, abs=0.0001)
    assert result["bpm"] is None
    assert result["bpm_confidence"] == "unknown"


def test_ffprobe_failure_is_honest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = _source(tmp_path / "broken.wav")
    monkeypatch.setattr(music_library, "_resolve_binary", lambda binary: binary)
    monkeypatch.setattr(
        music_library.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            [],
            1,
            stdout="",
            stderr="invalid data",
        ),
    )

    result = music_library.analyze_audio(source)

    assert result["passed"] is False
    assert result["quality_status"] == "failed"
    assert result["errors"] == ["invalid data"]


def test_clipping_marks_quality_for_review(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = _source(tmp_path / "clipped.wav")
    monkeypatch.setattr(music_library, "_resolve_binary", lambda binary: binary)
    responses = iter(
        [
            subprocess.CompletedProcess(
                [],
                0,
                stdout=json.dumps(
                    {
                        "format": {"duration": "30", "format_name": "wav"},
                        "streams": [
                            {
                                "codec_type": "audio",
                                "codec_name": "pcm_s16le",
                                "sample_rate": "48000",
                                "channels": 2,
                            }
                        ],
                    }
                ),
                stderr="",
            ),
            subprocess.CompletedProcess(
                [],
                0,
                stdout="",
                stderr="I: -4.0 LUFS\nPeak: 0.0 dBFS\n",
            ),
            subprocess.CompletedProcess(
                [],
                0,
                stdout="",
                stderr="RMS level dB: -5.0\nPeak level dB: 0.0\n",
            ),
        ]
    )
    monkeypatch.setattr(music_library.subprocess, "run", lambda *_args, **_kwargs: next(responses))

    result = music_library.analyze_audio(source)

    assert result["clipping_detected"] is True
    assert result["quality_status"] == "review"
    assert "clipping_detected" in result["warnings"]


def test_duplicate_report_disables_secondary_exact_hash(tmp_path: Path) -> None:
    manager = MusicLibraryManager(tmp_path / "music")
    library = manager.initialize()
    first_path = _source(manager.root / "curated" / "first.wav", b"same")
    _source(manager.root / "generated" / "second.wav", b"same")
    fingerprint = music_library.file_fingerprint(first_path)
    base = _selectable_asset("first", "curated")
    base.update(
        {
            "relative_path": "curated/first.wav",
            "fingerprint": fingerprint,
            "auto_select_allowed": True,
        }
    )
    second = _selectable_asset("second", "generated")
    second.update(
        {
            "relative_path": "generated/second.wav",
            "fingerprint": fingerprint,
            "auto_select_allowed": True,
        }
    )
    library["assets"] = [base, second]
    manager.save(library)

    report = manager.find_duplicates()

    assert report["exact_duplicate_count"] == 1
    reloaded = manager.load()["assets"]
    secondary = next(item for item in reloaded if item["asset_id"] == "second")
    assert secondary["duplicate_primary"] is False
    assert secondary["auto_select_allowed"] is False


def test_title_and_duration_similarity_is_only_a_warning(tmp_path: Path) -> None:
    manager = MusicLibraryManager(tmp_path / "music")
    library = manager.initialize()
    first = _selectable_asset("first", "curated")
    second = _selectable_asset("second", "curated")
    first.update(
        {
            "title": "Focus Bed",
            "duration_seconds": 45.0,
            "fingerprint": "sha256:first",
        }
    )
    second.update(
        {
            "title": "Focus Bed",
            "duration_seconds": 45.5,
            "fingerprint": "sha256:second",
        }
    )
    library["assets"] = [first, second]
    manager.save(library)

    report = manager.find_duplicates()

    assert report["duplicate_groups"] == []
    assert report["similarity_warnings"][0]["reason"] == (
        "same_normalized_title_and_similar_duration"
    )


def test_curated_asset_beats_generated_asset_for_same_mood() -> None:
    generated = _selectable_asset("generated", "generated")
    curated = _selectable_asset("curated", "curated")

    resolved = resolve_music_intelligence(
        _selection_plan(),
        [generated, curated],
        library_metadata={"version": "2.0"},
    )

    assert resolved["selected_asset"]["asset_id"] == "curated"
    selection = resolved["music_library_selection"]
    assert selection["selected_priority_tier"] == "curated"
    assert selection["curated_assets_available"] == 1


def test_generated_asset_is_honest_fallback_when_no_curated_match() -> None:
    generated = _selectable_asset("generated", "generated")

    resolved = resolve_music_intelligence(
        _selection_plan(),
        [generated],
        library_metadata={"version": "2.0"},
    )

    selection = resolved["music_library_selection"]
    assert selection["selected_priority_tier"] == "generated"
    assert "fallback" in selection["selection_reason"]
    assert any("Generated validation asset" in item for item in resolved["mix_plan"]["warnings"])


def test_persistent_usage_count_penalizes_repetition() -> None:
    repeated = _selectable_asset("repeated", "curated")
    repeated["usage_count"] = 5
    fresh = _selectable_asset("fresh", "curated")

    resolved = resolve_music_intelligence(_selection_plan(), [repeated, fresh])

    assert resolved["selected_asset"]["asset_id"] == "fresh"
    repeated_score = next(
        item for item in resolved["asset_scores"] if item["asset_id"] == "repeated"
    )
    assert repeated_score["repetition_penalty"] > 0


def test_tag_disable_and_verified_enable_workflow(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(music_library, "analyze_audio", lambda *_args, **_kwargs: _analysis())
    manager = MusicLibraryManager(tmp_path / "music")
    imported = manager.import_file(
        _source(tmp_path / "incoming" / "track.wav"),
        license_name="CC0",
        license_verified=False,
        source="User provided",
        moods=["calm"],
        energy="low",
        instrumental=True,
        speech_safe=True,
    )
    asset_id = imported["asset"]["asset_id"]

    tagged = manager.tag(
        asset_id,
        moods=["emotional"],
        use_cases=["podcast_bed"],
        energy="medium_low",
        bpm=82,
    )
    assert "emotional" in tagged["mood_tags"]
    assert tagged["bpm_confidence"] == "manual"

    enabled = manager.enable(
        asset_id,
        safe_default=True,
        license_verified=True,
    )
    assert enabled["auto_select_allowed"] is True

    disabled = manager.disable(asset_id, "too repetitive")
    assert disabled["auto_select_allowed"] is False
    assert "manually_disabled" in disabled["rejection_reasons"]


def test_summary_and_validation_reports_are_written(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(music_library, "analyze_audio", lambda *_args, **_kwargs: _analysis())
    manager = MusicLibraryManager(tmp_path / "music")
    _import_safe(manager, _source(tmp_path / "incoming" / "track.wav"))

    summary = manager.summary()
    validation = manager.validate()
    duplicates = manager.find_duplicates()

    assert summary["curated_assets"] == 1
    assert validation["safe_automatic_assets"] == 1
    assert duplicates["duplicate_groups"] == []
    assert (manager.report_root / "music_library_summary.json").exists()
    assert (manager.report_root / "music_library_summary.md").exists()
    assert (manager.report_root / "music_validation_report.json").exists()
    assert (manager.report_root / "duplicate_report.json").exists()


def test_generated_installer_preserves_curated_manifest_entries(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    asset_root = tmp_path / "assets"
    manager = MusicLibraryManager(asset_root / "music")
    library = manager.initialize()
    curated_path = _source(manager.root / "curated" / "licensed.wav", b"licensed")
    curated = _selectable_asset("licensed", "curated")
    curated.update(
        {
            "relative_path": "curated/licensed.wav",
            "absolute_path": str(curated_path),
            "fingerprint": music_library.file_fingerprint(curated_path),
            "auto_select_allowed": True,
        }
    )
    library["assets"] = [curated]
    manager.save(library)

    def fake_generate(
        path: Path,
        _frequencies: tuple[int, int, int],
        *,
        force: bool,
    ) -> None:
        del force
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(path.name.encode())

    monkeypatch.setattr(install_music_assets, "_generate", fake_generate)
    monkeypatch.setattr(
        install_music_assets,
        "_measure_loudness",
        lambda _path: (-18.0, -2.0),
    )

    installed = install_music_assets.install(asset_root)

    assert any(item["asset_id"] == "licensed" for item in installed["assets"])
    assert sum(item["folder_type"] == "generated" for item in installed["assets"]) == 6
    assert all(
        item["bpm"] is None
        for item in installed["assets"]
        if item["folder_type"] == "generated"
    )
    payload = json.loads(manager.manifest_path.read_text(encoding="utf-8"))
    assert "music_library_v2" in payload


def test_cli_init_import_quarantine_and_reports(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(music_library, "analyze_audio", lambda *_args, **_kwargs: _analysis())
    root = tmp_path / "music"
    source = _source(tmp_path / "incoming" / "track.wav")

    assert manage_music_library.main(["--init", "--library-root", str(root)]) == 0
    assert manage_music_library.main(["--list", "--library-root", str(root)]) == 0
    assert (
        manage_music_library.main(
            [
                "--import-file",
                str(source),
                "--library-root",
                str(root),
                "--source",
                "User provided",
                "--mood",
                "calm",
                "--energy",
                "low",
                "--instrumental",
                "--speech-safe",
            ]
        )
        == 0
    )
    assert manage_music_library.main(["--summary", "--library-root", str(root)]) == 0
    assert manage_music_library.main(["--rejected", "--library-root", str(root)]) == 0
    assert manage_music_library.main(["--validate", "--library-root", str(root)]) == 0
    assert (
        manage_music_library.main(
            ["--find-duplicates", "--library-root", str(root)]
        )
        == 0
    )

    payloads = [
        json.loads(line)
        for line in _json_documents(capsys.readouterr().out)
    ]
    import_payload = next(
        payload["curated_music_library_v2"]
        for payload in payloads
        if payload["curated_music_library_v2"].get("command") == "import_file"
    )
    assert import_payload["result"]["status"] == "quarantine"
    assert (root / "reports" / "music_import_report.json").exists()
    assert (root / "reports" / "music_validation_report.json").exists()
    assert (root / "reports" / "duplicate_report.json").exists()


def test_enable_requires_explicit_verified_review(tmp_path: Path) -> None:
    manager = MusicLibraryManager(tmp_path / "music")
    manager.initialize()

    with pytest.raises(MusicLibraryError, match="requires --safe-default"):
        manager.enable(
            "missing",
            safe_default=False,
            license_verified=False,
        )


def _json_documents(output: str) -> list[str]:
    documents: list[str] = []
    depth = 0
    start: int | None = None
    in_string = False
    escaped = False
    for index, character in enumerate(output):
        if escaped:
            escaped = False
            continue
        if character == "\\" and in_string:
            escaped = True
            continue
        if character == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if character == "{":
            if depth == 0:
                start = index
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0 and start is not None:
                documents.append(output[start : index + 1])
                start = None
    return documents
