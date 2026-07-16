"""Focused coverage for Captions / Typography V2."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from olympus.editing import captions as CAP  # noqa: N812
from olympus.editing import timeline as T  # noqa: N812
from olympus.integration.clip_intelligence import unified_clip_intelligence
from olympus.rendering import command as C  # noqa: N812
from olympus.rendering.ffmpeg_renderer import _render_metadata


def _event(
    text: str,
    start: float,
    end: float,
    *,
    speaker: str | None = None,
    timing_source: str = "word_level",
) -> dict[str, object]:
    return T.event(
        "caption",
        start,
        end,
        reason="test transcript timing",
        confidence=0.94,
        text=text,
        speaker=speaker,
        word_timings=[],
        timing_source=timing_source,
        timing_quality="word_level" if timing_source == "word_level" else "segment_level",
        estimated=timing_source != "word_level",
        highlighted_words=[],
        style="default_clean",
        animation="phrase_reveal",
        readability=T.caption_readability(text, start, end),
    )


def _build(
    events: list[dict[str, object]],
    *,
    blueprint: dict[str, object] | None = None,
    face_plan: dict[str, object] | None = None,
    captions_enabled: bool = True,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    return CAP.build_caption_intelligence(
        clip={"clip_id": "clip_caption", "duration": 6.0},
        events=events,
        timing_quality={
            "source": "word_level" if events else "unavailable",
            "estimated": False,
            "quality_level": "word_level" if events else "unavailable",
            "warnings": [],
        },
        blueprint=blueprint or {},
        face_plan=face_plan or {"mode": "center_fallback"},
        project_id="project_caption",
        captions_enabled=captions_enabled,
    )


def test_real_word_timestamps_are_preserved() -> None:
    chunks = CAP.caption_chunks_for_segment(
        {
            "start": 0.0,
            "end": 1.5,
            "speaker": "spk_0",
            "text": "This changes everything",
            "words": [
                {"word": "This", "start": 0.05, "end": 0.25, "confidence": 0.97},
                {"word": "changes", "start": 0.28, "end": 0.72, "confidence": 0.96},
                {"word": "everything", "start": 0.76, "end": 1.42, "confidence": 0.95},
            ],
        }
    )
    for chunk in chunks:
        chunk["segment_index"] = 0

    events, quality = CAP.timed_caption_events(chunks, 2.0)

    assert quality["source"] == "word_level"
    assert quality["estimated"] is False
    assert events[0]["start"] == 0.05
    assert events[0]["end"] == 1.42
    assert events[0]["word_timings"]


def test_missing_word_timestamps_are_marked_estimated() -> None:
    chunks = CAP.caption_chunks_for_segment(
        {"start": 0.0, "end": 2.0, "text": "A short clear sentence"}
    )
    for chunk in chunks:
        chunk["segment_index"] = 0

    events, quality = CAP.timed_caption_events(chunks, 2.0)

    assert quality["source"] == "estimated"
    assert quality["estimated"] is True
    assert quality["quality_level"] == "segment_level"
    assert all(event["estimated"] is True for event in events)
    assert any("estimated" in warning.lower() for warning in quality["warnings"])


def test_dense_adjacent_word_bursts_merge_when_readability_improves() -> None:
    chunks = [
        {
            "text": "This is extremely",
            "segment_index": 0,
            "segment_start": 0.0,
            "segment_end": 1.3,
            "speaker": "spk_0",
            "timing_source": "word_level",
            "timing_quality": "word_level",
            "word_timings": [
                {"word": "This", "start": 0.0, "end": 0.12},
                {"word": "is", "start": 0.12, "end": 0.2},
                {"word": "extremely", "start": 0.2, "end": 0.4},
            ],
        },
        {
            "text": "important today",
            "segment_index": 0,
            "segment_start": 0.0,
            "segment_end": 1.3,
            "speaker": "spk_0",
            "timing_source": "word_level",
            "timing_quality": "word_level",
            "word_timings": [
                {"word": "important", "start": 0.4, "end": 0.9},
                {"word": "today", "start": 0.9, "end": 1.3},
            ],
        },
    ]

    events, quality = CAP.timed_caption_events(chunks, 1.3)

    assert quality["source"] == "word_level"
    assert len(events) == 1
    assert events[0]["text"] == "This is extremely important today"
    assert "merged for two-line readability" in events[0]["reason"]


def test_real_dense_three_event_burst_uses_lookahead_merge() -> None:
    chunks = [
        {
            "text": "and it was one of the most",
            "segment_index": 0,
            "segment_start": 19.38,
            "segment_end": 21.86,
            "speaker": "spk_0",
            "timing_source": "word_level",
            "timing_quality": "word_level",
            "word_timings": [
                {"word": "and", "start": 19.38, "end": 19.44},
                {"word": "it", "start": 19.44, "end": 19.52},
                {"word": "was", "start": 19.52, "end": 19.58},
                {"word": "one", "start": 19.58, "end": 19.74},
                {"word": "of", "start": 19.74, "end": 19.76},
                {"word": "the", "start": 19.76, "end": 19.9},
                {"word": "most", "start": 19.9, "end": 20.02},
            ],
        },
        {
            "text": "successful",
            "segment_index": 0,
            "segment_start": 19.38,
            "segment_end": 21.86,
            "speaker": "spk_0",
            "timing_source": "word_level",
            "timing_quality": "word_level",
            "word_timings": [{"word": "successful", "start": 20.02, "end": 20.48}],
        },
        {
            "text": "prank we've ever done.",
            "segment_index": 0,
            "segment_start": 19.38,
            "segment_end": 21.86,
            "speaker": "spk_0",
            "timing_source": "word_level",
            "timing_quality": "word_level",
            "word_timings": [
                {"word": "prank", "start": 20.48, "end": 20.82},
                {"word": "we've", "start": 20.82, "end": 21.14},
                {"word": "ever", "start": 21.14, "end": 21.3},
                {"word": "done.", "start": 21.3, "end": 21.86},
            ],
        },
    ]

    events, _ = CAP.timed_caption_events(chunks, 48.09)

    assert len(events) == 2
    assert " ".join(str(event["text"]) for event in events) == (
        "and it was one of the most successful prank we've ever done."
    )
    assert sum(len(event["word_timings"]) for event in events) == 12
    assert all(len(str(event["text"])) <= 44 for event in events)
    assert all(
        len(str(event["text"])) / (float(event["end"]) - float(event["start"])) <= 30
        for event in events
    )


def test_dense_word_group_uses_two_line_capacity_without_readability_failure() -> None:
    words = [
        ("I", 0.0, 0.04),
        ("don't", 0.04, 0.14),
        ("want", 0.14, 0.26),
        ("to", 0.26, 0.3),
        ("put", 0.3, 0.46),
        ("any", 0.46, 0.7),
        ("dead", 0.7, 0.92),
        ("brother", 0.92, 1.18),
        ("peer", 1.18, 1.5),
        ("pressure", 1.5, 1.82),
        ("on", 1.82, 2.04),
        ("them.", 2.04, 3.36),
    ]
    chunks = CAP.caption_chunks_for_segment(
        {
            "start": 0.0,
            "end": 3.36,
            "speaker": "spk_0",
            "text": "I don't want to put any dead brother peer pressure on them.",
            "words": [
                {"word": word, "start": start, "end": end}
                for word, start, end in words
            ],
        }
    )
    for chunk in chunks:
        chunk["segment_index"] = 0

    events, quality = CAP.timed_caption_events(chunks, 3.36)
    _, intelligence = _build(events)

    assert any(len(str(event["text"]).split()) > 7 for event in events)
    assert all(len(str(event["text"]).split()) <= 14 for event in events)
    assert quality["source"] == "word_level"
    assert intelligence["caption_readability_validation"]["passed"] is True


def test_boundary_clipped_tail_word_is_not_captioned() -> None:
    localized = T.clip_segments(
        [
            {
                "start": 13.2,
                "end": 15.0,
                "text": "them. But",
                "speaker": "spk_0",
                "words": [
                    {"word": "them.", "start": 13.2, "end": 14.52},
                    {"word": "But", "start": 14.52, "end": 15.0},
                ],
            }
        ],
        0.0,
        14.77,
    )
    chunks = CAP.caption_chunks_for_segment(localized[0])
    for chunk in chunks:
        chunk["segment_index"] = 0

    events, quality = CAP.timed_caption_events(chunks, 14.77)

    assert [event["text"] for event in events] == ["them."]
    assert all("But" not in str(event["text"]) for event in events)
    assert any("clipped by the selected clip boundary" in item for item in quality["warnings"])


def test_short_complete_word_caption_extends_when_clip_has_room() -> None:
    chunks = [
        {
            "text": "Yes",
            "segment_index": 0,
            "segment_start": 1.0,
            "segment_end": 1.1,
            "speaker": "spk_0",
            "timing_source": "word_level",
            "timing_quality": "word_level",
            "word_timings": [{"word": "Yes", "start": 1.0, "end": 1.1}],
        }
    ]

    events, _ = CAP.timed_caption_events(chunks, 2.0)

    assert len(events) == 1
    assert float(events[0]["end"]) - float(events[0]["start"]) == pytest.approx(0.35)


def test_empty_and_disabled_caption_paths_are_honest() -> None:
    events, quality = CAP.timed_caption_events([], 4.0)
    disabled_events, intelligence = _build([], captions_enabled=False)

    assert events == []
    assert quality["source"] == "unavailable"
    assert disabled_events == []
    assert intelligence["validation"]["captions_planned"] is False
    assert intelligence["validation"]["passed"] is True


@pytest.mark.parametrize(
    ("niche", "expected"),
    [
        ("motivation", "motivational_impact"),
        ("podcast_interview", "clean_podcast"),
        ("education_tutorial", "educational_clear"),
        ("gaming_reaction", "gaming_energy"),
        ("music_performance", "music_minimal"),
        ("emotional_confession", "emotional_soft"),
        ("comedy", "comedy_pop"),
    ],
)
def test_niche_selects_caption_preset(niche: str, expected: str) -> None:
    _, intelligence = _build(
        [_event("A clear spoken line", 0.0, 1.2)],
        blueprint={"content_niche": {"primary": niche}},
    )

    assert intelligence["style_decision"]["caption_style"] == expected


def test_exact_planning_caption_preset_is_honored() -> None:
    _, intelligence = _build(
        [_event("A faithful hook line", 0.0, 1.2)],
        blueprint={"caption_decision_v2": {"style": "bold_hook"}},
    )

    assert intelligence["style_decision"]["caption_style"] == "bold_hook"
    assert "planning guidance" in intelligence["style_decision"]["reason"]


def test_single_face_safe_zone_uses_opposite_region() -> None:
    _, intelligence = _build(
        [_event("Keep the speaker visible", 0.0, 1.2)],
        face_plan={
            "mode": "single_face_tracking",
            "crop_keyframes": [{"time": 0.0, "y_center": 0.4}],
        },
    )

    safe_zone = intelligence["caption_safe_zone"]
    assert safe_zone["strategy"] == "tracked_face_opposite_zone"
    assert safe_zone["chosen_position"] == "bottom_center"
    assert safe_zone["face_avoidance_used"] is True


def test_two_speaker_stack_uses_reliable_speaker_regions() -> None:
    decorated, intelligence = _build(
        [
            _event("Top speaker line", 0.0, 1.0, speaker="spk_a"),
            _event("Bottom speaker line", 1.0, 2.0, speaker="spk_b"),
        ],
        face_plan={
            "mode": "two_speaker_stack",
            "participants": [
                {
                    "speaker_id": "spk_a",
                    "face_track_id": "face_a",
                    "association_confidence": 0.92,
                },
                {
                    "speaker_id": "spk_b",
                    "face_track_id": "face_b",
                    "association_confidence": 0.9,
                },
            ],
            "layout_regions": [
                {"role": "top", "source_face_track_id": "face_a"},
                {"role": "bottom", "source_face_track_id": "face_b"},
            ],
        },
    )

    assert intelligence["speaker_captioning"]["enabled"] is True
    assert intelligence["caption_safe_zone"]["strategy"] == "speaker_aware_regions"
    assert [event["ass_style"] for event in decorated] == ["SpeakerTop", "SpeakerBottom"]
    assert [event["speaker_label"] for event in decorated] == ["Speaker 1", "Speaker 2"]


def test_unreliable_speaker_association_falls_back_without_identity_claims() -> None:
    decorated, intelligence = _build(
        [_event("A speaker line", 0.0, 1.0, speaker="diarized_7")],
        face_plan={
            "mode": "two_speaker_stack",
            "participants": [
                {
                    "speaker_id": "diarized_7",
                    "face_track_id": "face_7",
                    "association_confidence": 0.3,
                }
            ],
            "layout_regions": [{"role": "top", "source_face_track_id": "face_7"}],
        },
    )

    assert intelligence["speaker_captioning"]["enabled"] is False
    assert intelligence["speaker_captioning"]["speaker_labels_used"] == []
    assert decorated[0]["ass_style"] == "Hook"
    assert decorated[0]["speaker_label"] == "Speaker 1"


def test_hook_and_payoff_emphasis_never_invent_words() -> None:
    decorated, intelligence = _build(
        [
            _event("This truth matters", 0.0, 1.0),
            _event("Constraints create freedom", 3.8, 5.5),
        ],
        blueprint={
            "hook_v2": {
                "category": "curiosity_gap",
                "hook_line": "The impossible secret nobody knows",
            },
            "ending_payoff_v2": {"ending_line": "Constraints create freedom"},
            "story_v2_guidance": {
                "editing_guidance": {
                    "caption_emphasis_words": ["freedom", "inventedword"]
                }
            },
        },
    )

    highlighted = {
        word for event in decorated for word in event.get("highlighted_words", [])
    }
    spoken = {word.lower() for event in decorated for word in str(event["text"]).split()}
    assert intelligence["hook_caption_treatment"]["applied"] is True
    assert "freedom" in highlighted
    assert "impossible" not in highlighted
    assert "inventedword" not in highlighted
    assert highlighted <= spoken


def test_ass_generation_is_valid_and_escapes_transcript_text() -> None:
    decorated, intelligence = _build(
        [_event("Never use {unsafe} \\ captions", 0.0, 1.4)],
        blueprint={
            "content_niche": {"primary": "motivation"},
            "hook_v2": {"category": "direct_claim", "hook_line": "Never use unsafe captions"},
        },
    )
    timeline = {
        "metadata": {"caption_intelligence_v2": intelligence},
        "tracks": [{"kind": "caption", "events": decorated}],
    }

    content = C.build_ass(C.caption_cues(timeline), timeline)
    validation = C.validate_ass(content)

    assert validation["ass_valid"] is True
    assert validation["events_count"] == 1
    assert validation["styles_count"] >= 6
    assert "0:00:00.00" in content
    assert "\uff5bUNSAFE\uff5d" in content
    assert "\uff3c" in content


def test_ass_validation_rejects_non_increasing_timestamps() -> None:
    content = """[Script Info]
ScriptType: v4.00+
[V4+ Styles]
Format: Name, Fontname
Style: Normal,Arial
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:01.00,Normal,,0,0,0,,Invalid interval
"""

    validation = C.validate_ass(content)

    assert validation["ass_valid"] is False
    assert any(
        "does not end after it starts" in warning for warning in validation["warnings"]
    )


def test_readability_validation_detects_fast_long_empty_and_overlap() -> None:
    events = [
        {**_event("", 0.0, 0.2), "ass_style": "Normal"},
        {
            **_event(
                "one two three four five six seven eight nine ten eleven twelve "
                "thirteen fourteen fifteen",
                0.1,
                0.5,
            ),
            "ass_style": "Normal",
        },
    ]
    report = CAP.validate_readability(
        events,
        {"strategy": "platform_safe_fallback", "warnings": []},
        {"Normal"},
    )

    assert report["passed"] is False
    assert report["reading_speed_warnings"]
    assert report["line_length_warnings"]
    assert report["overlap_warnings"]
    assert report["timing_warnings"]
    assert report["version"] == "2"
    assert report["event_count"] == 2
    assert report["failed_event_count"] == 2
    assert report["dense_event_count"] == 1
    assert report["overlap_count"] == 1
    assert report["max_words_per_caption"] == 14
    assert report["max_characters_per_caption"] == 44
    assert report["caption_event_readability"]
    assert report["safe_zone_passed"] is True


def test_render_metadata_and_unified_contract_preserve_caption_truth() -> None:
    decorated, intelligence = _build(
        [_event("Rendered caption proof", 0.0, 1.2)],
        blueprint={"content_niche": {"primary": "education"}},
    )
    timeline = {
        "clip_id": "clip_caption",
        "plan_id": "plan_caption",
        "duration": 2.0,
        "source_start": 0.0,
        "source_end": 2.0,
        "tracks": [{"kind": "caption", "events": decorated}],
        "metadata": {
            "editing_v2": {"caption_intelligence_v2": intelligence},
            "caption_intelligence_v2": intelligence,
        },
    }
    metadata = _render_metadata(
        timeline,
        logs=[],
        probe={
            "format": {"duration": "2.000"},
            "streams": [
                {"codec_type": "video", "duration": "2.000"},
                {"codec_type": "audio", "duration": "2.000"},
            ],
        },
        caption_context={
            "ass_file_created": True,
            "ass_file_exists": True,
            "ass_non_empty": True,
            "ass_valid": True,
            "ass_event_count": 1,
            "ass_styles_count": 6,
            "ffmpeg_filter_present": True,
            "output_exists": True,
            "warnings": [],
        },
    )
    unified = unified_clip_intelligence(
        clip=timeline,
        editing_v2=metadata["editing_v2"],
        render_metadata=metadata,
        render_output={"subtitles_included": True, "duration": 2.0},
    )

    assert metadata["caption_render_validation"]["passed"] is True
    assert metadata["caption_render_validation"]["render_manifest_confirmed"] is False
    assert metadata["render_effects_v2"]["captions"]["included"] is True
    assert unified["caption_intelligence"]["style"] == "educational_clear"
    assert unified["caption_intelligence"]["render_validation_passed"] is True


def test_caption_validator_cli_simulation_passes() -> None:
    root = Path(__file__).resolve().parents[2]
    completed = subprocess.run(
        [
            sys.executable,
            str(root / "tools" / "validate_caption_typography.py"),
            "--simulate",
            "--niche",
            "education_tutorial",
        ],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)["caption_validation_report"]
    assert report["pass_fail"] is True
    assert report["ass_validation"]["ass_valid"] is True
    assert report["captions_planned"] is True
    assert report["ass_valid"] is True
    assert report["events_count"] == 2
    assert report["style"] == "educational_clear"
    assert report["timing_source"] == "word_level"


def test_caption_validator_project_mode_requires_every_clip_to_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "validate_caption_typography", root / "tools" / "validate_caption_typography.py"
    )
    assert spec is not None and spec.loader is not None
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)
    passing = {
        "clip_id": "clip_pass",
        "caption_intelligence_v2": {"version": "2"},
        "caption_readability_validation": {"passed": True, "warnings": []},
        "caption_render_validation": {
            "passed": True,
            "render_manifest_confirmed": True,
            "warnings": [],
        },
    }
    failing = {
        **passing,
        "clip_id": "clip_fail",
        "caption_readability_validation": {
            "passed": False,
            "warnings": ["dense caption"],
        },
    }
    monkeypatch.setattr(
        validator,
        "_project_caption_data",
        lambda _project_id: ([passing, failing], []),
    )

    result = validator._report(
        SimpleNamespace(
            ass_file=None,
            simulate=False,
            rendered_file=None,
            manifest=None,
            project_id="project_test",
            niche="education_tutorial",
            hook_category="curiosity_gap",
        )
    )["caption_validation_report"]

    assert len(result["clips"]) == 2
    assert result["failed_clip_count"] == 1
    assert result["failed_clips"] == ["clip_fail"]
    assert result["pass_fail"] is False
