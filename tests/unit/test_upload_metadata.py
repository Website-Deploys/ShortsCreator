from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from olympus.integration.clip_intelligence import unified_clip_intelligence
from olympus.metadata import generate_upload_metadata, validate_upload_metadata
from olympus.metadata.hashtags import build_hashtag_plan
from olympus.metadata.platforms import platform_rules

REPO_ROOT = Path(__file__).resolve().parents[2]


def _unified(
    *,
    niche: str = "motivational",
    hook_category: str = "curiosity_gap",
    hook_line: str = "This is why discipline matters when nobody is watching.",
    risk: str = "low",
    readiness: str = "ready_with_low_risk",
    live: bool = False,
) -> dict[str, Any]:
    return {
        "story": {
            "story_shape": "problem_solution",
            "setup": "Discipline is easy to discuss.",
            "payoff": "The real test happens without an audience.",
            "ending_reason": "key_takeaway",
        },
        "virality": {
            "hook_line": hook_line,
            "hook_category": hook_category,
            "overall_score": 0.81,
        },
        "trend_research": {
            "niche": niche,
            "research_status": "live" if live else "fallback",
            "provider_status": "available" if live else "fallback",
            "provider_used": "official_sources" if live else "evergreen",
            "cache_status": "fresh" if live else "fallback",
            "live_research_succeeded": live,
            "source_count": 3 if live else 0,
            "matched_patterns": [{"label": "clear_takeaway"}],
            "confidence": 0.78 if live else 0.55,
        },
        "caption_intelligence": {"highlighted_words": ["discipline", "focus"]},
        "music_intelligence": {"role": "supportive_background"},
        "motion_graphics": {"motion_style": "subtle_punch_in"},
        "copyright_safety": {
            "risk_level": risk,
            "upload_readiness": readiness,
            "manual_review_required": risk != "low",
        },
    }


def _generate(**overrides: Any) -> dict[str, Any]:
    unified = _unified(**overrides)
    return dict(
        generate_upload_metadata(
            project_id="project_test",
            clip_id="clip_test",
            render_id="render_test",
            unified_clip_intelligence=unified,
        )
    )


@pytest.mark.parametrize(
    ("niche", "hook_category", "expected_pattern"),
    [
        ("motivational", "curiosity_gap", "curiosity_gap"),
        ("podcast", "podcast", "podcast"),
        ("education", "education", "education"),
        ("gaming", "gaming", "gaming"),
        ("music", "music", "performance"),
    ],
)
def test_niche_title_variants_are_grounded_and_ranked(
    niche: str, hook_category: str, expected_pattern: str
) -> None:
    metadata = _generate(niche=niche, hook_category=hook_category)
    youtube = metadata["youtube_shorts"]

    assert youtube["title"]
    assert len(youtube["title"]) <= 70
    assert 3 <= len(youtube["title_variants"]) <= 5
    assert expected_pattern in {candidate["pattern"] for candidate in youtube["title_variants"]}
    assert not youtube["title"].isupper()
    assert all(candidate["truth_score"] >= 0.8 for candidate in youtube["title_variants"])


def test_title_length_and_claim_language_are_bounded() -> None:
    metadata = dict(
        generate_upload_metadata(
            project_id="p",
            clip_id="c",
            unified_clip_intelligence=_unified(
                hook_line=("A careful and specific lesson about patient deliberate practice " * 8),
            ),
            settings={"max_title_length": 42, "title_variant_count": 5},
        )
    )
    titles = [candidate["text"] for candidate in metadata["youtube_shorts"]["title_variants"]]

    assert titles
    assert all(len(title) <= 42 for title in titles)
    assert all("guaranteed viral" not in title.casefold() for title in titles)
    assert all("copyright safe" not in title.casefold() for title in titles)
    assert all("until this happened" not in title.casefold() for title in titles)


def test_platform_copy_is_distinct_human_and_non_baiting() -> None:
    metadata = _generate()
    youtube = metadata["youtube_shorts"]
    instagram = metadata["instagram_reels"]
    tiktok = metadata["tiktok"]

    assert 1 <= len(youtube["description"].splitlines()) <= 3
    assert instagram["caption"] != tiktok["caption"]
    assert youtube["pinned_comment"]
    all_copy = " ".join(
        [youtube["description"], instagram["caption"], tiktok["caption"], youtube["pinned_comment"]]
    ).casefold()
    assert "like if" not in all_copy
    assert "comment yes" not in all_copy


def test_disabled_platform_is_not_treated_as_invalid() -> None:
    metadata = dict(
        generate_upload_metadata(
            project_id="p",
            clip_id="c",
            unified_clip_intelligence=_unified(),
            settings={"generate_youtube": False},
        )
    )

    assert metadata["youtube_shorts"]["title"] == ""
    assert metadata["instagram_reels"]["caption"]
    assert metadata["tiktok"]["caption"]
    assert metadata["validation"]["passed"] is True


def test_hashtag_plans_respect_limits_remove_duplicates_and_block_spam() -> None:
    rules = platform_rules("tiktok", max_tiktok_hashtags=5)
    plan = build_hashtag_plan(
        rules=rules,
        niche="gaming",
        keywords=["strategy", "strategy", "reaction"],
        requested_tags=["#FYP", "#NSFW", "#strategy"],
    )

    assert len(plan["hashtags"]) <= 5
    assert len({tag.casefold() for tag in plan["hashtags"]}) == len(plan["hashtags"])
    assert "#Gaming" in plan["hashtags"]
    assert "#TikTok" in plan["hashtags"]
    assert all(tag.casefold() not in {"#fyp", "#nsfw"} for tag in plan["hashtags"])
    assert any(item["reason"] == "blocked_or_invalid" for item in plan["removed_tags"])


def test_platform_hashtag_limits_and_niche_relevance() -> None:
    metadata = _generate(niche="education", hook_category="education")

    assert 3 <= len(metadata["youtube_shorts"]["hashtags"]) <= 8
    assert 5 <= len(metadata["instagram_reels"]["hashtags"]) <= 12
    assert 3 <= len(metadata["tiktok"]["hashtags"]) <= 8
    assert "#Education" in metadata["youtube_shorts"]["hashtags"]
    assert "#FYP" not in metadata["tiktok"]["hashtags"]


def test_unknown_source_requires_manual_review_without_prohibited_wording() -> None:
    metadata = _generate(risk="unknown", readiness="needs_manual_review")
    serialized = json.dumps(metadata).casefold()

    assert metadata["status"] == "generated_needs_review"
    assert metadata["universal"]["manual_review_required"] is True
    assert metadata["universal"]["ready_for_upload"] is False
    assert metadata["youtube_shorts"]["safety_warnings"]
    assert "copyright safe" not in serialized
    assert "guaranteed viral" not in serialized


def test_blocked_safety_marks_metadata_not_ready_and_validation_fails() -> None:
    metadata = _generate(risk="blocked", readiness="not_ready")

    assert metadata["status"] == "not_ready"
    assert metadata["validation"]["passed"] is False
    assert metadata["validation"]["safety_validation"]["passed"] is False
    assert metadata["universal"]["manual_review_required"] is True


def test_trend_truth_is_preserved_without_fake_trend_tags() -> None:
    fallback = _generate(live=False)
    live = _generate(live=True)

    assert fallback["input_signals"]["live_research_succeeded"] is False
    assert fallback["input_signals"]["trend_provider_used"] == "evergreen"
    assert live["input_signals"]["live_research_succeeded"] is True
    assert live["input_signals"]["trend_source_count"] == 3
    all_tags = [
        *fallback["youtube_shorts"]["hashtags"],
        *fallback["instagram_reels"]["hashtags"],
        *fallback["tiktok"]["hashtags"],
    ]
    assert all(tag.casefold() not in {"#trending", "#trendingnow", "#fyp"} for tag in all_tags)


def test_validation_rejects_empty_title_duplicate_spam_and_long_copy() -> None:
    metadata = _generate()
    bad = copy.deepcopy(metadata)
    source = " ".join(f"sourceword{index}" for index in range(30))
    bad["youtube_shorts"]["title"] = ""
    bad["youtube_shorts"]["description"] = source
    bad["tiktok"]["hashtags"] = ["#FYP", "#FYP"]

    validation = validate_upload_metadata(bad, source_text=source)

    assert validation["passed"] is False
    assert validation["title_validation"]["passed"] is False
    assert validation["no_copied_content"] is False
    assert validation["hashtag_validation"]["passed"] is False


def test_unified_clip_intelligence_includes_compact_upload_metadata() -> None:
    metadata = _generate()
    unified = unified_clip_intelligence(render_metadata={"upload_metadata_v2": metadata})
    compact = unified["upload_metadata"]

    assert compact["youtube_title"] == metadata["youtube_shorts"]["title"]
    assert compact["instagram_caption"] == metadata["instagram_reels"]["caption"]
    assert compact["tiktok_caption"] == metadata["tiktok"]["caption"]
    assert compact["validation_passed"] is True


def _run_cli(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "tools/validate_upload_metadata.py", *args],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )


def test_cli_simulate_and_sample_transcript() -> None:
    simulated = _run_cli(
        REPO_ROOT,
        "--simulate",
        "--niche",
        "motivational",
        "--hook-category",
        "curiosity_gap",
    )
    sampled = _run_cli(
        REPO_ROOT,
        "--sample-transcript",
        "This is why discipline matters when nobody is watching.",
        "--niche",
        "motivational",
    )

    assert simulated.returncode == 0, simulated.stderr
    assert sampled.returncode == 0, sampled.stderr
    assert json.loads(simulated.stdout)["upload_metadata_validation_report"]["pass_fail"] == "pass"
    assert json.loads(sampled.stdout)["upload_metadata_validation_report"]["generated"] is True


def test_cli_validates_metadata_file(tmp_path: Path) -> None:
    path = tmp_path / "upload_metadata_v2.json"
    path.write_text(json.dumps(_generate()), encoding="utf-8")

    result = _run_cli(REPO_ROOT, "--metadata-file", str(path))
    payload = json.loads(result.stdout)

    assert result.returncode == 0, result.stderr
    assert payload["upload_metadata_validation_report"]["mode"] == "metadata_file"
    assert payload["upload_metadata_validation_report"]["pass_fail"] == "pass"
