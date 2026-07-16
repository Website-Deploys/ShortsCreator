"""Tests for Copyright / Safety Checker V2 risk and reporting contracts."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from olympus.integration.clip_intelligence import unified_clip_intelligence
from olympus.platform.config.settings import CopyrightSafetySettings
from olympus.safety import (
    COPYRIGHT_SAFETY_DISCLAIMER,
    CopyrightSafetyChecker,
    copyright_safety_markdown,
    write_copyright_safety_reports,
)
from olympus.safety.copyright import (
    check_asset_collection,
    check_captions_text,
    check_music,
    check_source_video,
)


def _policy(**updates: object) -> CopyrightSafetySettings:
    return CopyrightSafetySettings(**updates)


def _generated_music() -> dict[str, object]:
    return {
        "asset_id": "music_generated",
        "title": "Generated validation bed",
        "folder_type": "generated",
        "license": "project_generated_safe",
        "license_verified": True,
        "safe_default": True,
        "auto_select_allowed": True,
        "quality_status": "passed",
        "usage_allowed": True,
        "source": "generated_validation_asset",
        "source_url": "generated://olympus/music/v2",
    }


def _curated_music() -> dict[str, object]:
    return {
        "asset_id": "music_curated",
        "title": "Curated bed",
        "folder_type": "curated",
        "license": "royalty_free_verified",
        "license_verified": True,
        "safe_default": True,
        "auto_select_allowed": True,
        "quality_status": "passed",
        "usage_allowed": True,
        "source": "documented_local_library",
    }


def _generated_sfx() -> dict[str, object]:
    return {
        "asset_id": "sfx_pop",
        "type": "sfx",
        "license": {
            "license": "CC0-1.0",
            "source_url": "generated://olympus/editing-assets/v1",
            "usage_allowed": True,
        },
        "safe_default": True,
        "quality_status": "passed",
        "source_url": "generated://olympus/editing-assets/v1",
    }


def test_local_user_owned_source_is_low_risk() -> None:
    result = check_source_video(
        {
            "source_type": "upload",
            "rights_confirmed": True,
            "owner_claimed_by_user": True,
            "rights_basis": "user_owned_upload",
        },
        _policy(),
    )

    assert result["source_risk_level"] == "low"
    assert result["manual_review_required"] is False


def test_youtube_rights_confirmation_never_auto_clears_license() -> None:
    result = check_source_video(
        {
            "source_type": "link",
            "source_url": "https://www.youtube.com/watch?v=allowed-example",
            "rights_confirmed": True,
        },
        _policy(),
    )

    assert result["source_risk_level"] == "medium"
    assert result["manual_review_required"] is True
    assert "not independently verified" in result["warnings"][0]


def test_youtube_without_rights_confirmation_is_blocked() -> None:
    checker = CopyrightSafetyChecker(_policy())
    report = checker.check(
        project={"id": "project"},
        source={
            "source_type": "link",
            "source_url": "https://youtu.be/example",
            "rights_confirmed": False,
        },
        assessment_phase="pre_render",
    )

    assert report["overall"]["risk_level"] == "blocked"
    assert report["overall"]["upload_readiness"] == "blocked"
    assert checker.should_block(report) is True
    assert report["manual_review"]["required"] is True


def test_unknown_source_is_unknown_and_requires_review() -> None:
    result = check_source_video({"source_type": "unknown"}, _policy())

    assert result["source_risk_level"] == "unknown"
    assert result["manual_review_required"] is True


def test_restricted_or_drm_source_is_blocked() -> None:
    result = check_source_video(
        {
            "source_type": "link",
            "source_url": "https://www.youtube.com/watch?v=restricted",
            "rights_confirmed": True,
            "drm_protected": True,
        },
        _policy(),
    )

    assert result["source_risk_level"] == "blocked"


def test_generated_music_is_low_with_validation_quality_warning() -> None:
    result = check_music(_generated_music(), used=True, policy=_policy())

    assert result["risk_level"] == "low"
    assert result["license_verified"] is True
    assert "validation-quality" in result["warnings"][0]


def test_curated_verified_music_is_low_without_warning() -> None:
    result = check_music(_curated_music(), used=True, policy=_policy())

    assert result["risk_level"] == "low"
    assert result["warnings"] == []


def test_unknown_or_missing_music_license_is_blocked() -> None:
    result = check_music(
        {"asset_id": "unknown", "safe_default": True},
        used=True,
        policy=_policy(),
    )

    assert result["risk_level"] == "blocked"


def test_missing_required_music_attribution_is_high_risk() -> None:
    asset = {
        **_curated_music(),
        "attribution_required": True,
        "attribution_text": None,
    }
    result = check_music(asset, used=True, policy=_policy())

    assert result["risk_level"] == "high"


def test_generated_sfx_has_verified_project_provenance() -> None:
    result = check_asset_collection(
        [_generated_sfx()],
        used=True,
        kind="sfx",
        require_verified=True,
    )

    assert result["risk_level"] == "low"
    assert result["all_license_verified"] is True


def test_unlicensed_sfx_and_visual_asset_are_blocked() -> None:
    sfx = check_asset_collection(
        [{"asset_id": "mystery_sfx", "source": "unknown"}],
        used=True,
        kind="sfx",
        require_verified=True,
    )
    visual = check_asset_collection(
        [{"asset_id": "unknown_overlay", "source": "template_pack"}],
        used=True,
        kind="visual asset",
        require_verified=True,
    )

    assert sfx["risk_level"] == "blocked"
    assert visual["risk_level"] == "blocked"


def test_transcript_captions_inherit_source_truth_and_lyric_heuristic_warns() -> None:
    source = check_source_video(
        {"source_type": "upload", "rights_confirmed": True},
        _policy(),
    )
    normal = check_captions_text(
        {"generated_from_transcript": True, "lines": ["This is an original explanation."]},
        source,
    )
    lyric_like = check_captions_text(
        {
            "generated_from_transcript": True,
            "lines": ["repeat this line", "repeat this line", "repeat this line"],
        },
        source,
    )

    assert normal["risk_level"] == "low"
    assert lyric_like["risk_level"] == "medium"
    assert lyric_like["lyric_risk_detected"] is True


def test_copied_text_signal_is_high_without_storing_excerpt() -> None:
    result = check_captions_text(
        {
            "generated_from_transcript": False,
            "copied_text_detected": True,
            "lines": ["third-party script text"],
        },
        {"source_risk_level": "low"},
    )

    assert result["risk_level"] == "high"
    assert "lines" not in result


def test_final_report_aggregates_blocked_component() -> None:
    checker = CopyrightSafetyChecker(_policy())
    report = checker.check(
        project={"id": "project"},
        clip_id="clip",
        source={"source_type": "generated", "rights_confirmed": True},
        music_asset={"asset_id": "unlicensed", "safe_default": True},
        render_output={
            "output_key": "render/project/clips/clip.mp4",
            "duration": 30.0,
            "width": 1080,
            "height": 1920,
        },
    )

    assert report["music"]["risk_level"] == "blocked"
    assert report["final_output"]["risk_level"] == "blocked"
    assert report["overall"]["risk_level"] == "blocked"
    assert report["result"]["passed"] is False


def test_all_verified_components_produce_low_technical_risk() -> None:
    checker = CopyrightSafetyChecker(_policy(warn_on_generated_validation_music=False))
    report = checker.check(
        project={"id": "project"},
        clip_id="clip",
        source={"source_type": "generated", "rights_confirmed": True},
        music_asset=_generated_music(),
        sfx_assets=[_generated_sfx()],
        render_output={
            "output_key": "render/project/clips/clip.mp4",
            "duration": 30.0,
            "width": 1080,
            "height": 1920,
        },
    )

    assert report["overall"]["risk_level"] == "low"
    assert report["overall"]["upload_readiness"] == "ready_with_low_risk"
    assert report["result"]["passed"] is True


def test_platform_readiness_never_claims_content_id_or_legal_approval() -> None:
    report = CopyrightSafetyChecker(_policy()).check(
        project={"id": "project"},
        source={
            "source_type": "link",
            "source_url": "https://www.youtube.com/watch?v=example",
            "rights_confirmed": True,
        },
        assessment_phase="source_only",
    )
    serialized = json.dumps(report).lower()

    assert report["platform_readiness"]["youtube_shorts"]["manual_review_required"] is True
    assert "content id safe" not in serialized
    assert "fair use" not in serialized
    assert "copyright safe" not in serialized


def test_unified_clip_intelligence_preserves_compact_safety_truth() -> None:
    report = CopyrightSafetyChecker(_policy()).check(
        project={"id": "project"},
        clip_id="clip",
        source={"source_type": "upload", "rights_confirmed": False},
        render_output={"output_key": "render/project/clips/clip.mp4"},
    )
    unified = unified_clip_intelligence(
        render_metadata={"copyright_safety_v2": report},
        render_output={"clip_id": "clip", "output_key": "render/project/clips/clip.mp4"},
    )

    safety = unified["copyright_safety"]
    assert safety["risk_level"] == "unknown"
    assert safety["manual_review_required"] is True
    assert safety["source_rights_confirmed"] is False
    assert safety["disclaimer"] == COPYRIGHT_SAFETY_DISCLAIMER


def test_report_json_and_markdown_include_disclaimer_and_checklist(tmp_path: Path) -> None:
    report = CopyrightSafetyChecker(_policy()).check(
        project={"id": "project"},
        source={"source_type": "unknown"},
        assessment_phase="source_only",
    )
    paths = write_copyright_safety_reports(report, tmp_path)
    payload = json.loads(Path(paths["copyright_safety_report.json"]).read_text(encoding="utf-8"))
    markdown = copyright_safety_markdown(payload)

    assert payload["copyright_safety_v2"]["overall"]["disclaimer"] == (
        COPYRIGHT_SAFETY_DISCLAIMER
    )
    assert "technical risk assessment, not legal advice" in markdown
    assert "- [ ] Confirm you own or have permission" in markdown


def test_default_configuration_blocks_only_blocked_risk() -> None:
    settings = _policy()

    assert settings.enabled is True
    assert settings.warn_only is False
    assert settings.block_on_blocked is True
    assert settings.block_on_high_risk is False
    assert settings.require_rights_confirmation_for_links is True
    assert settings.require_music_license_verified is True
    assert settings.require_sfx_license_verified is True
    assert settings.require_visual_asset_license_verified is True


def test_cli_simulation_detects_unconfirmed_third_party_source(tmp_path: Path) -> None:
    report_dir = tmp_path / "reports"
    completed = subprocess.run(
        [
            sys.executable,
            "tools/validate_copyright_safety.py",
            "--simulate",
            "--source",
            "third_party_youtube",
            "--music",
            "generated_safe",
            "--report-dir",
            str(report_dir),
        ],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        check=False,
    )
    payload = json.loads((report_dir / "copyright_safety_report.json").read_text(encoding="utf-8"))

    assert completed.returncode == 0, completed.stderr
    assert payload["copyright_safety_v2"]["overall"]["risk_level"] == "blocked"
    assert payload["simulation"]["real_project_validation"] is False


def test_cli_source_url_and_manifest_modes_write_reports(tmp_path: Path) -> None:
    source_reports = tmp_path / "source_reports"
    source = subprocess.run(
        [
            sys.executable,
            "tools/validate_copyright_safety.py",
            "--source-url",
            "https://www.youtube.com/watch?v=example",
            "--rights-confirmed",
            "--report-dir",
            str(source_reports),
        ],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        check=False,
    )
    rendered = tmp_path / "clip.mp4"
    rendered.write_bytes(b"rendered")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "project_id": "missing_local_project",
                "renders": [
                    {
                        "clip_id": "clip",
                        "storage_key": "render/project/clips/clip.mp4",
                        "duration": 20.0,
                        "width": 1080,
                        "height": 1920,
                        "metadata": {},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    manifest_reports = tmp_path / "manifest_reports"
    manifest_run = subprocess.run(
        [
            sys.executable,
            "tools/validate_copyright_safety.py",
            "--rendered-file",
            str(rendered),
            "--manifest",
            str(manifest),
            "--storage-root",
            str(tmp_path / "storage"),
            "--report-dir",
            str(manifest_reports),
        ],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert source.returncode == 0, source.stderr
    assert manifest_run.returncode == 0, manifest_run.stderr
    assert (source_reports / "copyright_safety_summary.md").is_file()
    assert (manifest_reports / "copyright_safety_report.json").is_file()


def test_cli_music_library_mode_checks_real_local_manifest(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "tools/validate_copyright_safety.py",
            "--music-library",
            "--asset-root",
            str(Path("assets").resolve()),
            "--report-dir",
            str(tmp_path),
        ],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        check=False,
    )
    payload = json.loads((tmp_path / "copyright_safety_report.json").read_text(encoding="utf-8"))

    assert completed.returncode == 0, completed.stderr
    assert payload["music_library"]["safe_assets_checked"] >= 1
    assert payload["music_library"]["blocked_safe_assets"] == 0
    assert payload["music_library"]["generated_assets_are_validation_quality"] is True
