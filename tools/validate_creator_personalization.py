"""Validate local Creator Personalization V2 without rendering or hidden learning."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

from olympus.personalization import (
    CreatorPersonalizationService,
    ProfileStore,
    apply_editing_personalization,
    apply_planning_personalization,
    caption_personalization,
    combine_applications,
    motion_personalization,
    music_personalization,
    personalize_hashtags,
    preset_names,
    profile_directives,
    profile_from_preset,
    rerank_title_candidates,
)
from olympus.personalization.validation import assert_privacy_safe
from olympus.platform.config import get_settings


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--self-check", action="store_true")
    modes.add_argument("--create-profile", metavar="PRESET")
    modes.add_argument("--simulate", action="store_true")
    modes.add_argument("--simulate-feedback", action="store_true")
    modes.add_argument("--export-profile", metavar="PROFILE_ID")
    modes.add_argument("--reset-profile", metavar="PROFILE_ID")
    parser.add_argument("--profile", default="balanced_default")
    parser.add_argument("--niche", default="general")
    parser.add_argument("--rating", choices=("like", "dislike", "neutral"), default="like")
    parser.add_argument("--labels", default="")
    parser.add_argument("--storage-dir", type=Path)
    parser.add_argument("--activate", action="store_true")
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--report", type=Path)
    return parser.parse_args()


def _store(root: Path) -> ProfileStore:
    settings = get_settings().creator_personalization
    return ProfileStore(
        root,
        max_profiles=settings.max_profiles,
        max_note_chars=settings.max_feedback_notes_chars,
        learning_enabled_by_default=settings.learning_enabled_by_default,
    )


def _service(root: Path) -> CreatorPersonalizationService:
    settings = get_settings().creator_personalization
    return CreatorPersonalizationService(
        _store(root),
        conservative_until_feedback_count=settings.conservative_until_feedback_count,
        enabled=settings.enabled,
    )


def _privacy_checks() -> dict[str, bool]:
    secret_rejected = False
    long_text_rejected = False
    try:
        assert_privacy_safe({"api_key": "do-not-store"})
    except Exception:
        secret_rejected = True
    try:
        assert_privacy_safe({"preference": "word " * 300})
    except Exception:
        long_text_rejected = True
    return {
        "local_only": True,
        "explicit_feedback_only": True,
        "no_cloud_sync": True,
        "secret_fields_rejected": secret_rejected,
        "long_text_rejected": long_text_rejected,
    }


def _base_report(mode: str) -> dict[str, Any]:
    return {
        "mode": mode,
        "profile_id": None,
        "profile_name": None,
        "storage_ok": False,
        "learning_enabled": False,
        "feedback_recorded": False,
        "affected_systems": [],
        "adjustments": [],
        "privacy_checks": _privacy_checks(),
        "warnings": [],
        "errors": [],
        "passed": False,
    }


def _simulation(profile_id: str, niche: str) -> dict[str, Any]:
    profile = profile_from_preset(
        profile_id,
        profile_id="simulation_profile",
        profile_name=f"{profile_id.replace('_', ' ').title()} Simulation",
    )
    profile.channel_context.content_niches = [niche]
    directives = profile_directives(profile)
    candidate = {
        "candidate_type": "speaker_moment",
        "safety_status": "low",
        "story_v2_guidance": {
            "context_risk": 0.2,
            "payoff_present": True,
            "story_completeness_score": 0.88,
        },
        "v2_candidate_metadata": {"hook_analysis": {"category": "curiosity_gap"}},
    }
    initial_scores = {
        "emotion": 0.65,
        "payoff": 0.72,
        "hook": 0.74,
        "story_completion": 0.8,
        "story": 0.78,
        "clarity": 0.82,
        "retention": 0.76,
    }
    planning_scores, planning = apply_planning_personalization(
        initial_scores,
        candidate,
        directives,
        max_score_delta=get_settings().creator_personalization.max_score_delta,
    )
    editing_output, editing = apply_editing_personalization(
        {
            "style": "balanced_default",
            "pacing": "balanced",
            "zoom_frequency": "medium",
            "sfx_density": "low",
            "transition_style": "subtle",
        },
        directives,
    )
    captions = caption_personalization(
        directives,
        default_style="default_clean",
        default_max_words=5,
    )
    music = music_personalization(
        directives,
        target_mood="neutral",
        gain_db=-18.0,
        source_is_music=False,
    )
    motion = motion_personalization(
        directives,
        style="default_clean",
        intensity=0.5,
    )
    titles, upload = rerank_title_candidates(
        [
            {
                "text": "A useful lesson",
                "pattern": "context",
                "truth_score": 0.9,
                "clarity_score": 0.9,
                "curiosity_score": 0.2,
            },
            {
                "text": "The mindset shift that changes the outcome",
                "pattern": "emotional",
                "truth_score": 0.86,
                "clarity_score": 0.85,
                "curiosity_score": 0.8,
            },
        ],
        directives,
    )
    hashtags, hashtags_added, hashtags_removed = personalize_hashtags(
        ["#Shorts", "#General"],
        directives,
        relevant_terms=[niche, "shorts", "motivation", "mindset", "podcast"],
        limit=8,
    )
    upload["hashtags_added"] = hashtags_added
    upload["hashtags_removed"] = hashtags_removed
    combined = combine_applications(planning, editing, captions, music, motion, upload)
    report = _base_report("simulate")
    report.update(
        {
            "profile_id": profile.profile_id,
            "profile_name": profile.profile_name,
            "storage_ok": True,
            "learning_enabled": profile.learning.enabled,
            "affected_systems": combined["affected_systems"],
            "adjustments": combined["adjustments"],
            "simulation": {
                "preset": profile_id,
                "niche": niche,
                "planning_scores_before": initial_scores,
                "planning_scores_after": planning_scores,
                "editing": editing_output,
                "captions": {
                    "style": captions["style"],
                    "highlight_density": captions["highlight_density"],
                    "max_words_per_line": captions["max_words_per_line"],
                },
                "music": {
                    "target_mood": music["target_mood"],
                    "gain_db": music["gain_db"],
                    "music_presence": music["music_presence"],
                },
                "motion": {
                    "style": motion["style"],
                    "intensity": motion["intensity"],
                },
                "best_title": titles[0]["text"],
                "hashtags": hashtags,
            },
            "warnings": combined["warnings"],
            "passed": bool(combined["affected_systems"]),
        }
    )
    return report


def _self_check() -> dict[str, Any]:
    report = _base_report("self_check")
    with tempfile.TemporaryDirectory(prefix="olympus-personalization-") as directory:
        service = _service(Path(directory))
        default = service.initialize()
        created = [
            service.create_profile(preset, profile_name=f"{preset} check")
            for preset in preset_names()
            if preset != "balanced_default"
        ]
        service.activate_profile(created[0].profile_id)
        exported = service.export_profile(default.profile_id)
        imported = service.import_profile(exported["profile"])
        profiles = service.list_profiles()
        report.update(
            {
                "profile_id": default.profile_id,
                "profile_name": default.profile_name,
                "storage_ok": len(profiles) == len(preset_names()) + 1,
                "preset_count": len(preset_names()),
                "export_import_ok": imported.profile_id != default.profile_id,
                "atomic_replace_ok": not list(Path(directory).rglob("*.tmp")),
                "passed": (
                    len(profiles) == len(preset_names()) + 1
                    and imported.profile_id != default.profile_id
                    and all(report["privacy_checks"].values())
                ),
            }
        )
    return report


def _feedback_simulation(rating: str, labels: list[str]) -> dict[str, Any]:
    report = _base_report("simulate_feedback")
    with tempfile.TemporaryDirectory(prefix="olympus-feedback-") as directory:
        service = _service(Path(directory))
        profile = service.store.create_profile(
            "balanced_default",
            profile_id="feedback_simulation",
            learning_enabled=True,
            activate=True,
        )
        feedback = service.record_feedback(
            profile_id=profile.profile_id,
            project_id="simulation_project",
            clip_id="simulation_clip",
            rating=rating,
            labels=labels,
            notes="Explicit short validation feedback.",
            clip_traits={
                "hook_category": "curiosity_gap",
                "title_pattern": "emotional",
                "caption_style": "bold_hook",
                "music_mood": "motivational",
                "motion_style": "motivational_dynamic",
                "clip_traits": ["complete_story", "strong_payoff"],
            },
        )
        updated = service.get_profile(profile.profile_id)
        learned = feedback.extracted_safe_learning.model_dump(mode="json")
        report.update(
            {
                "profile_id": profile.profile_id,
                "profile_name": profile.profile_name,
                "storage_ok": len(service.store.list_feedback(profile.profile_id)) == 1,
                "learning_enabled": updated.learning.enabled,
                "feedback_recorded": True,
                "feedback_id": feedback.feedback_id,
                "feedback_applied": feedback.applied_to_profile,
                "safe_learning": learned,
                "affected_systems": [
                    key.replace("liked_", "").replace("disliked_", "")
                    for key, values in learned.items()
                    if values
                ],
                "passed": (
                    feedback.applied_to_profile
                    and updated.learning.total_feedback_count == 1
                    and bool(any(learned.values()))
                ),
            }
        )
    return report


def _persistent_operation(args: argparse.Namespace) -> dict[str, Any]:
    root = args.storage_dir or Path(get_settings().creator_personalization.storage_dir)
    service = _service(root)
    service.initialize()
    if args.create_profile:
        profile = service.create_profile(
            args.create_profile,
            learning_enabled=False,
            activate=args.activate,
        )
        report = _base_report("create_profile")
        report.update(
            {
                "profile_id": profile.profile_id,
                "profile_name": profile.profile_name,
                "storage_ok": True,
                "learning_enabled": profile.learning.enabled,
                "storage_dir": str(root.resolve()),
                "passed": True,
            }
        )
        return report
    if args.export_profile:
        result = service.export_profile(args.export_profile)
        profile = result["profile"]
        report = _base_report("export_profile")
        report.update(
            {
                "profile_id": profile["profile_id"],
                "profile_name": profile["profile_name"],
                "storage_ok": True,
                "exported_file": result["filename"],
                "passed": result["exported"] is True,
            }
        )
        return report
    report = _base_report("reset_profile")
    report["profile_id"] = args.reset_profile
    if not args.confirm:
        report["errors"] = ["Reset requires --confirm."]
        return report
    profile = service.reset_profile(args.reset_profile)
    report.update(
        {
            "profile_name": profile.profile_name,
            "storage_ok": True,
            "learning_enabled": profile.learning.enabled,
            "passed": profile.learning.total_feedback_count == 0,
        }
    )
    return report


def _run(args: argparse.Namespace) -> dict[str, Any]:
    if args.self_check:
        return _self_check()
    if args.simulate:
        return _simulation(str(args.profile), str(args.niche))
    if args.simulate_feedback:
        labels = [item.strip() for item in str(args.labels).split(",") if item.strip()]
        return _feedback_simulation(str(args.rating), labels)
    return _persistent_operation(args)


def main() -> int:
    args = _parse_args()
    try:
        result = _run(args)
    except Exception as exc:
        result = _base_report("failed")
        result["errors"] = [str(exc)]
    payload = {"creator_personalization_validation_v2": result}
    rendered = json.dumps(payload, indent=2, ensure_ascii=False)
    print(rendered)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered + "\n", encoding="utf-8")
    return 0 if result.get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
