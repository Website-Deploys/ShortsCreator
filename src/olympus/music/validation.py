"""Honest post-render Music Intelligence validation."""

from __future__ import annotations

from typing import Any


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def build_music_validation(
    intelligence: dict[str, Any],
    *,
    output_audio_present: bool,
    sync_validation: dict[str, Any],
    duration_validation: dict[str, Any],
    ffmpeg_completed: bool,
) -> dict[str, Any]:
    decision = _dict(intelligence.get("decision"))
    selected = _dict(intelligence.get("selected_asset"))
    mix = _dict(intelligence.get("mix_plan"))
    planned = bool(decision.get("should_use_music"))
    asset_resolved = bool(selected.get("path"))
    license_safe = bool(
        selected.get("license")
        and selected.get("license_verified") is True
        and selected.get("safe_default") is True
    )
    asset_safe = bool(
        license_safe
        and selected.get("automatic_use_allowed") is True
        and selected.get("quality_status") == "passed"
        and selected.get("speech_safe") is True
        and selected.get("source")
    )
    mixed = bool(planned and asset_resolved and ffmpeg_completed and output_audio_present)
    sync_passed = sync_validation.get("passed") is True
    duration_passed = duration_validation.get("passed") is True
    warnings: list[str] = []
    if planned and not asset_resolved:
        warnings.append("Music was planned but no safe asset was resolved.")
    if asset_resolved and not asset_safe:
        warnings.append(
            "Resolved music did not pass license, quality, source, or speech-safety checks."
        )
    if mixed:
        warnings.append(
            "The music input was mixed by FFmpeg, but its isolated audible contribution "
            "was not waveform-verified."
        )
        warnings.append(
            "Speech clarity was protected by conservative gain and ducking, but "
            "intelligibility was not manually verified."
        )
    passed = bool(
        (not planned or (mixed and asset_safe))
        and output_audio_present
        and sync_passed
        and duration_passed
    )
    return {
        "planned": planned,
        "asset_resolved": asset_resolved,
        "mixed": mixed,
        "audible": "not_verified" if mixed else False,
        "speech_clarity_passed": "not_verified" if mixed else None,
        "license_safe": license_safe if asset_resolved else None,
        "asset_safe": asset_safe if asset_resolved else None,
        "folder_type": selected.get("folder_type"),
        "quality_status": selected.get("quality_status"),
        "validation_asset": selected.get("folder_type") == "generated",
        "output_audio_present": output_audio_present,
        "audio_video_sync_passed": sync_passed,
        "duration_passed": duration_passed,
        "gain_db": mix.get("music_gain_db"),
        "loudness_estimate": _dict(intelligence.get("audio_analysis")).get("music_loudness"),
        "warning": warnings[0] if warnings else None,
        "warnings": warnings,
        "passed": passed,
    }
