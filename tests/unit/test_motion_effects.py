"""Tests for bounded Motion Graphics / Effects V2 planning and render truth."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from olympus.editing.motion import (
    build_motion_intelligence,
    select_motion_style,
    validate_motion_effects,
)
from olympus.integration.clip_intelligence import unified_clip_intelligence
from olympus.rendering import command as C  # noqa: N812 (module alias is intentional)
from olympus.rendering.ffmpeg_renderer import _render_metadata


def _face_plan(
    *, mode: str = "single_face_tracking", fallback: str | None = None
) -> dict[str, Any]:
    return {
        "mode": mode,
        "fallback_reason": fallback,
        "input_analysis": {"detected_face_count": 1},
        "crop_keyframes": [
            {"time": 0.0, "x_center": 0.48, "y_center": 0.43, "confidence": 0.9},
            {"time": 12.0, "x_center": 0.52, "y_center": 0.43, "confidence": 0.9},
        ],
        "layout_regions": [
            {"crop_keyframes": [{"time": 0.0}, {"time": 12.0}]},
            {"crop_keyframes": [{"time": 0.0}, {"time": 12.0}]},
        ]
        if mode == "two_speaker_stack"
        else [],
        "warnings": [],
    }


def _contract(
    *,
    niche: str = "motivational",
    hook_category: str = "curiosity_gap",
    face_plan: dict[str, Any] | None = None,
    source_motion: str = "low",
) -> dict[str, Any]:
    duration = 12.0
    return build_motion_intelligence(
        clip={
            "clip_id": "clip_motion",
            "source_start": 30.0,
            "source_end": 42.0,
            "duration": duration,
        },
        blueprint={
            "content_niche": {"primary": niche},
            "hook_v2": {"category": hook_category, "score": 0.86},
            "story_v2_guidance": {
                "story_guidance_used": True,
                "story_shape": "setup_tension_payoff",
                "turning_point": {"time": 35.0},
                "payoff": "The answer changes the outcome.",
                "payoff_present": True,
            },
            "ending_payoff_v2": {
                "ending_type": "lesson",
                "ending_line": "The answer changes the outcome.",
                "payoff_present": True,
            },
            "closing_payoff": {"timestamp": 40.0},
            "viral_score_v2": {"overall": 0.84},
            "editing_trend_guidance": {"pacing_style": "restrained_dynamic"},
            "source_motion": {"level": source_motion},
        },
        caption_intelligence={
            "input_signals": {"speech_density": 2.5},
            "style_decision": {"caption_style": "bold_hook_word_highlight"},
            "caption_safe_zone": {
                "strategy": "tracked_face_opposite_zone",
                "collision_risk": "low",
            },
        },
        music_intelligence={"decision": {"music_role": "motivational_drive"}},
        face_plan=face_plan or _face_plan(),
        sfx_plan={"enabled": True, "effects": []},
        project_id="project_motion",
    )


def _timeline(contract: dict[str, Any]) -> dict[str, Any]:
    face_plan = _face_plan()
    effects = contract["effect_plan"]["effects"]
    return {
        "clip_id": "clip_motion",
        "source_start": 0.0,
        "source_end": 12.0,
        "duration": 12.0,
        "tracks": [
            {"kind": "video", "events": effects},
            {"kind": "audio", "events": []},
            {"kind": "caption", "events": []},
            {"kind": "markers", "events": []},
        ],
        "metadata": {
            "face_tracking_plan": face_plan,
            "multi_speaker_layout_v2": face_plan,
            "motion_intelligence_v2": contract,
            "editing_v2": {
                "motion_intelligence_v2": contract,
                "motion_plan": {"events": effects},
                "face_tracking_plan": face_plan,
                "video_enhancement_plan": {"profile": "clean_high_retention"},
                "voice_enhancement_plan": {"filters": ["highpass"]},
            },
            "render_assets_v2": {"music": {}, "sfx": {}},
        },
    }


@pytest.mark.parametrize(
    ("niche", "expected"),
    [
        ("motivational", "motivational_dynamic"),
        ("podcast_interview", "clean_podcast"),
        ("education_tutorial", "educational_clarity"),
        ("gaming_stream", "gaming_reactive"),
        ("entertainment_comedy", "comedy_pop"),
        ("music_singing", "music_performance_minimal"),
    ],
)
def test_motion_style_changes_by_content(niche: str, expected: str) -> None:
    assert select_motion_style(niche=niche)[0] == expected


def test_story_driven_grammar_places_hook_turn_and_payoff() -> None:
    contract = _contract()
    effects = contract["effect_plan"]["effects"]

    assert contract["decision"]["should_apply_motion"] is True
    assert effects[0]["type"] == "hook_punch_in"
    assert effects[0]["start_time"] <= 3.0
    assert any(effect["type"] == "pattern_interrupt_zoom" for effect in effects)
    assert effects[-1]["type"] == "quote_hold"
    assert effects[-1]["end_time"] <= 12.0
    assert all(effect["safety_checked"] for effect in effects)


def test_high_source_motion_disables_added_effects() -> None:
    contract = _contract(source_motion="high")

    assert contract["decision"]["should_apply_motion"] is False
    assert contract["decision"]["disabled_reason"] == "source_motion_high"
    assert contract["effect_plan"]["effects"] == []


def test_singing_uses_minimal_motion_without_pattern_interrupt() -> None:
    contract = _contract(niche="music_singing")

    assert contract["decision"]["motion_style"] == "music_performance_minimal"
    assert contract["decision"]["intensity"] == "minimal"
    assert contract["effect_plan"]["hook_effect"]["scale"] <= 1.04
    assert contract["effect_plan"]["pattern_interrupts"] == []


def test_emotional_tone_avoids_harsh_pattern_interrupt() -> None:
    contract = _contract(niche="emotional_story", hook_category="emotional_confession")

    assert contract["decision"]["motion_style"] == "emotional_cinematic"
    assert contract["effect_plan"]["hook_effect"]["type"] == "subtle_push_in"
    assert contract["effect_plan"]["pattern_interrupts"] == []


def test_two_speaker_stack_skips_whole_frame_motion() -> None:
    contract = _contract(face_plan=_face_plan(mode="two_speaker_stack"))

    assert contract["decision"]["should_apply_motion"] is False
    assert contract["decision"]["disabled_reason"] == "layout_complexity"
    assert contract["effect_plan"]["effects"] == []
    assert contract["motion_safety_validation"]["layout_safe"] is False


def test_unstable_face_tracking_disables_motion() -> None:
    contract = _contract(
        face_plan=_face_plan(mode="center_fallback", fallback="sparse_or_low_confidence_faces")
    )

    assert contract["decision"]["disabled_reason"] == "face_tracking_unstable"
    assert contract["motion_safety_validation"]["face_safe"] is False


def test_unavailable_face_detection_cannot_claim_face_safety() -> None:
    plan = _face_plan(mode="center_fallback", fallback="face_detection_unavailable")
    plan["input_analysis"] = {
        "detected_face_count": 0,
        "face_tracking_available": False,
    }
    contract = _contract(face_plan=plan)

    assert contract["decision"]["should_apply_motion"] is False
    assert contract["decision"]["disabled_reason"] == "face_tracking_unstable"
    assert contract["motion_safety_validation"]["face_safe"] is False
    assert any(
        "unavailable" in warning.lower()
        for warning in contract["motion_safety_validation"]["warnings"]
    )


def test_safety_rejects_flash_speed_ramp_density_and_out_of_bounds() -> None:
    effects = [
        {
            "type": "impact_flash_safe",
            "start_time": 0.0,
            "end_time": 0.2,
            "scale": 1.0,
        },
        {"type": "hook_punch_in", "start_time": 0.0, "end_time": 0.8, "scale": 1.4},
        {"type": "reaction_zoom", "start_time": 1.0, "end_time": 1.4, "scale": 1.1},
        {"type": "speed_ramp", "start_time": 3.0, "end_time": 4.0, "scale": 1.0},
        {"type": "payoff_hold", "start_time": 8.0, "end_time": 12.5, "scale": 1.1},
    ]

    accepted, validation = validate_motion_effects(
        effects,
        duration=12.0,
        caption_safe=True,
        face_safe=True,
        layout_safe=True,
    )

    assert [effect["type"] for effect in accepted] == ["hook_punch_in"]
    assert accepted[0]["scale"] == 1.18
    assert validation["flash_safe"] is True
    assert validation["speed_ramps_enabled"] is False
    assert len(validation["warnings"]) >= 4


def test_ffmpeg_graph_consumes_motion_and_preserves_audio_timing() -> None:
    timeline = _timeline(_contract())
    graph = C.filter_complex(timeline, 1080, 1920, 30, None)

    assert "zoompan=z=" in graph
    assert "sin(PI" in graph
    assert "cos(PI" in graph
    assert "x='iw/2-(iw/zoom/2)'" in graph
    assert "trim=start=0.000:end=12.000,setpts=PTS-STARTPTS" in graph
    assert "atrim=start=0.000:end=12.000,asetpts=PTS-STARTPTS" in graph
    assert "-shortest" not in graph


def test_render_metadata_requires_filter_output_probe_sync_and_duration() -> None:
    timeline = _timeline(_contract())
    graph = C.filter_complex(timeline, 1080, 1920, 30, None)
    probe = {
        "format": {"duration": "12.000"},
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1080,
                "height": 1920,
                "duration": "12.000",
            },
            {
                "codec_type": "audio",
                "codec_name": "aac",
                "sample_rate": "48000",
                "duration": "12.000",
            },
        ],
    }
    metadata = _render_metadata(
        timeline,
        [],
        probe,
        {"output_exists": True},
        {"ffmpeg_filtergraph": graph, "output_exists": True},
    )

    validation = metadata["motion_render_validation"]
    assert validation["effects_rendered"] == validation["effects_planned"]
    assert validation["ffmpeg_filter_present"] is True
    assert validation["sync_passed"] is True
    assert validation["duration_passed"] is True
    assert validation["passed"] is True
    assert metadata["render_effects_v2"]["motion"]["applied"] is True


def test_false_motion_metadata_fails_without_expected_filter() -> None:
    timeline = _timeline(_contract())
    probe = {
        "format": {"duration": "12.000"},
        "streams": [
            {"codec_type": "video", "width": 1080, "height": 1920, "duration": "12.000"},
            {"codec_type": "audio", "duration": "12.000"},
        ],
    }

    metadata = _render_metadata(
        timeline,
        [],
        probe,
        {"output_exists": True},
        {"ffmpeg_filtergraph": "scale=1080:1920", "output_exists": True},
    )

    assert metadata["motion_render_validation"]["passed"] is False
    assert metadata["motion_render_validation"]["effects_rendered"] == 0
    assert metadata["render_effects_v2"]["motion"]["applied"] is False


def test_unified_clip_intelligence_includes_motion_truth() -> None:
    contract = _contract()
    unified = unified_clip_intelligence(
        editing_v2={"motion_intelligence_v2": contract},
        render_metadata={
            "motion_intelligence_v2": contract,
            "motion_safety_validation": contract["motion_safety_validation"],
            "motion_render_validation": {
                "effects_planned": 3,
                "effects_rendered": 3,
                "passed": True,
                "warnings": [],
            },
        },
    )

    motion = unified["motion_graphics"]
    assert motion["applied"] is True
    assert motion["motion_style"] == "motivational_dynamic"
    assert motion["effect_count"] == 3
    assert motion["hook_effect"] == "hook_punch_in"
    assert motion["render_validation_passed"] is True


def test_old_timeline_without_motion_contract_remains_safe() -> None:
    graph = C.video_filter({"tracks": []}, 1080, 1920, fps=30)

    assert "zoompan=" not in graph
    assert C.motion_effects({}) == []
    assert C.motion_expected_filters({}) == []


def test_validation_cli_simulate_and_manifest(tmp_path: Path) -> None:
    command = [
        sys.executable,
        "tools/validate_motion_effects.py",
        "--simulate",
        "--niche",
        "motivational",
        "--hook-category",
        "curiosity_gap",
    ]
    simulated = subprocess.run(command, check=False, capture_output=True, text=True, timeout=60)
    assert simulated.returncode == 0, simulated.stderr
    report = json.loads(simulated.stdout)["motion_effects_validation_report"]
    assert report["motion_style"] == "motivational_dynamic"
    assert report["effects_planned"] >= 2

    contract = _contract()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "renders": [
                    {
                        "metadata": {
                            "motion_intelligence_v2": contract,
                            "motion_render_validation": {
                                "effects_planned": 3,
                                "effects_rendered": 3,
                                "passed": True,
                                "warnings": [],
                            },
                        }
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    validated = subprocess.run(
        [sys.executable, "tools/validate_motion_effects.py", "--manifest", str(manifest_path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert validated.returncode == 0, validated.stderr
    assert json.loads(validated.stdout)["motion_effects_validation_report"]["pass_fail"] is True
