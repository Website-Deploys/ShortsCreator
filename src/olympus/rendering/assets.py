"""Local Editing V2 asset library.

The renderer may only mix assets that are present on disk and described by the
local manifest. Missing or unlicensed assets are reported as unavailable; no
music/SFX success is fabricated from planner metadata.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from olympus.music import load_music_assets, resolve_music_intelligence
from olympus.platform.config import get_settings

ASSET_MANIFEST = "manifest.json"
_NOISE_LIKE_TERMS = {
    "static",
    "noise",
    "white_noise",
    "hiss",
    "crackle",
    "glitch",
    "distorted",
    "broadband",
}


def asset_root(root: str | Path | None = None) -> Path:
    configured = root if root is not None else get_settings().rendering.asset_root
    return Path(configured).expanduser().resolve()


def load_manifest(root: str | Path | None = None) -> dict[str, Any]:
    path = asset_root(root) / ASSET_MANIFEST
    if not path.exists():
        return {
            "version": "1",
            "assets": [],
            "reason": f"No asset manifest found at {path}",
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError) as exc:
        return {
            "version": "1",
            "assets": [],
            "reason": f"Asset manifest could not be read: {exc}",
        }
    return data if isinstance(data, dict) else {"version": "1", "assets": []}


def _assets(root: Path, kind: str) -> list[dict[str, Any]]:
    manifest = load_manifest(root)
    out: list[dict[str, Any]] = []
    for raw in manifest.get("assets", []):
        if not isinstance(raw, dict):
            continue
        if str(raw.get("type", "")).lower() != kind:
            continue
        if raw.get("usage_allowed") is not True:
            continue
        filename = str(raw.get("filename", ""))
        if not filename:
            continue
        path = (root / filename).resolve()
        if not path.exists() or not path.is_file():
            continue
        item = dict(raw)
        item["path"] = str(path)
        out.append(item)
    return out


def _dict_value(container: dict[str, Any], key: str) -> dict[str, Any]:
    value = container.get(key)
    return value if isinstance(value, dict) else {}


def _score_asset(asset: dict[str, Any], desired: set[str]) -> tuple[int, str]:
    categories = {str(c).lower() for c in asset.get("categories", []) if c}
    tags = {str(c).lower() for c in asset.get("tags", []) if c}
    score = len(desired & categories) * 3 + len(desired & tags)
    return score, str(asset.get("id") or asset.get("filename") or "")


def _asset_terms(asset: dict[str, Any]) -> set[str]:
    values = [
        asset.get("id"),
        asset.get("filename"),
        asset.get("sfx_type"),
        asset.get("quality"),
        asset.get("notes"),
        *list(asset.get("categories", []) or []),
        *list(asset.get("tags", []) or []),
    ]
    return {str(value).lower().replace(" ", "_") for value in values if value}


def _is_noise_like_sfx(asset: dict[str, Any]) -> bool:
    if asset.get("noise_like") is True:
        return True
    terms = _asset_terms(asset)
    return any(noise in term for term in terms for noise in _NOISE_LIKE_TERMS)


def _music_terms(timeline: dict[str, Any]) -> set[str]:
    meta = _dict_value(timeline, "metadata")
    v2 = _dict_value(meta, "v2_metadata")
    decision = _dict_value(meta, "music_decision_v2")
    terms = {
        str(v2.get("music_mood_chosen", "")).lower(),
        str(v2.get("content_category", "")).lower(),
        str(v2.get("editing_intensity", "")).lower(),
        str(decision.get("mood", "")).lower(),
        str(decision.get("category", "")).lower(),
    }
    hook = _dict_value(meta, "hook_v2")
    terms.add(str(hook.get("category", "")).lower())
    return {t.replace(" ", "_") for t in terms if t and t != "none"}


def _sfx_terms(effect_type: str) -> set[str]:
    low = effect_type.lower()
    terms = {low}
    if "impact" in low or "hook" in low or "hit" in low:
        terms.update({"impact", "bass_hit", "low_boom", "subtle_hit"})
    if "whoosh" in low or "swoosh" in low or "zoom" in low:
        terms.update({"whoosh", "swoosh", "transition_sweep"})
    if "pop" in low or "caption" in low:
        terms.update({"pop", "click", "subtle_tick"})
    if "riser" in low or "reveal" in low:
        terms.update({"riser", "reverse_riser"})
    if "glitch" in low:
        terms.add("glitch")
    return terms


def _license(asset: dict[str, Any]) -> dict[str, Any]:
    return {
        "license": asset.get("license"),
        "attribution": asset.get("attribution"),
        "source_url": asset.get("source_url"),
        "usage_allowed": asset.get("usage_allowed") is True,
        "notes": asset.get("notes"),
    }


def _planned_music_intelligence(timeline: dict[str, Any]) -> dict[str, Any]:
    meta = _dict_value(timeline, "metadata")
    editing = _dict_value(meta, "editing_v2")
    planned = _dict_value(meta, "music_intelligence_v2") or _dict_value(
        editing, "music_intelligence_v2"
    )
    if planned:
        return planned
    legacy = _dict_value(meta, "music_decision_v2")
    terms = sorted(_music_terms(timeline) or {"neutral"})
    disabled = str(legacy.get("status") or "").lower() == "disabled"
    duration = _timeline_duration(timeline)
    return {
        "version": "2",
        "music_decision_id": f"legacy_{timeline.get('clip_id') or 'clip'}",
        "clip_id": timeline.get("clip_id"),
        "project_id": timeline.get("project_id"),
        "input_signals": {
            "content_niche": terms[0],
            "speech_density": None,
            "source_audio_type": "unknown",
            "trend_patterns": [],
            "user_preferences": {"music_enabled": not disabled},
        },
        "decision": {
            "should_use_music": not disabled,
            "reason": legacy.get("reason") or "Legacy timeline requested a local music bed.",
            "disabled_reason": "user_disabled" if disabled else None,
            "music_role": "subtle_bed",
            "target_mood": terms[0],
            "target_energy": 0.4,
            "target_intensity": 0.35,
            "target_tempo_range": [70, 120],
            "target_genres": terms,
            "avoid_genres": ["vocal"],
            "vocal_music_allowed": False,
            "instrumental_required": True,
            "confidence": 0.4,
        },
        "selected_asset": None,
        "asset_scores": [],
        "mix_plan": {
            "voice_priority": True,
            "music_gain_db": -22.0,
            "ducking_enabled": True,
            "ducking_threshold": -24.0,
            "ducking_ratio": 6.0,
            "fade_in_seconds": 0.35,
            "fade_out_seconds": 0.8,
            "loop_strategy": "pending_asset_resolution",
            "trim_strategy": "safe_default",
            "hook_swell": False,
            "payoff_swell": False,
            "warnings": ["Legacy timeline used compatibility music guidance."],
        },
        "ducking_plan": {
            "enabled": True,
            "method": "ffmpeg_sidechaincompress",
            "speech_segments_used": 0,
            "reduction_db": 6.0,
            "attack_ms": 120.0,
            "release_ms": 450.0,
            "warnings": [],
        },
        "music_preparation": {
            "source_duration": None,
            "target_duration": duration,
            "loop_strategy": "pending_asset_resolution",
            "trim_strategy": "safe_default",
            "fade_in": 0.35,
            "fade_out": 0.8,
            "crossfade_used": False,
            "hook_alignment": "gentle_entry",
            "payoff_alignment": None,
            "warnings": [],
        },
        "music_story_events": {},
        "audio_analysis": {},
        "validation": {"music_mixed": False, "music_audible": "not_rendered"},
    }


def select_music(
    timeline: dict[str, Any],
    root: str | Path | None = None,
    *,
    usage_counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    base = asset_root(root)
    registry = load_music_assets(base)
    intelligence = resolve_music_intelligence(
        _planned_music_intelligence(timeline),
        list(registry.get("safe_assets") or []),
        rejected_assets=list(registry.get("unsafe_assets") or []),
        usage_counts=usage_counts,
        library_metadata=registry,
    )
    decision = _dict_value(intelligence, "decision")
    selected = _dict_value(intelligence, "selected_asset")
    mix = _dict_value(intelligence, "mix_plan")
    preparation = _dict_value(intelligence, "music_preparation")
    if not decision.get("should_use_music") or not selected.get("path"):
        disabled_reason = str(decision.get("disabled_reason") or "")
        return {
            "status": "disabled"
            if disabled_reason
            in {"source_is_music_performance", "user_disabled", "speech_clarity_risk"}
            else "unavailable",
            "mixed": False,
            "reason": decision.get("reason")
            or registry.get("reason")
            or "No verified safe local music asset was available.",
            "disabled_reason": disabled_reason or None,
            "music_intelligence_v2": intelligence,
            "registry_manifest": registry.get("manifest_path"),
        }
    duration = _timeline_duration(timeline)
    return {
        "status": "selected",
        "mixed": True,
        "asset_id": selected.get("asset_id"),
        "path": selected["path"],
        "filename": selected.get("filename"),
        "title": selected.get("title"),
        "mood": selected.get("mood_tags") or [decision.get("target_mood")],
        "role": decision.get("music_role"),
        "gain_db": mix.get("music_gain_db"),
        "looped": preparation.get("loop_strategy") != "no_loop_needed",
        "loop_strategy": preparation.get("loop_strategy"),
        "trim_strategy": preparation.get("trim_strategy"),
        "duration_used": duration,
        "fade_in_s": mix.get("fade_in_seconds"),
        "fade_out_s": mix.get("fade_out_seconds"),
        "ducking_plan": intelligence.get("ducking_plan"),
        "music_story_events": intelligence.get("music_story_events"),
        "mix_plan": mix,
        "reason": selected.get("selection_reason"),
        "license": {
            "license": selected.get("license"),
            "license_url": selected.get("license_url"),
            "license_verified": selected.get("license_verified") is True,
            "safe_default": selected.get("safe_default") is True,
            "source": selected.get("source"),
        },
        "music_intelligence_v2": intelligence,
        "registry_manifest": registry.get("manifest_path"),
    }


def _timeline_duration(timeline: dict[str, Any]) -> float:
    try:
        return max(0.0, float(timeline.get("duration") or 0.0))
    except (TypeError, ValueError):
        return 0.0


def _music_gain_db(asset: dict[str, Any], terms: set[str]) -> float:
    try:
        recommended = float(asset.get("recommended_gain_db", -20.0))
    except (TypeError, ValueError):
        recommended = -20.0
    joined = " ".join(terms)
    if any(token in joined for token in ("emotional", "story", "calm")):
        low, high = -24.0, -20.0
    elif any(token in joined for token in ("energetic", "stream", "entertainment", "high-energy")):
        low, high = -18.0, -14.0
    elif any(token in joined for token in ("motivational", "cinematic", "dramatic", "high_aura")):
        low, high = -18.0, -15.0
    else:
        low, high = -20.0, -18.0
    return round(min(high, max(low, recommended)), 1)


def _planned_sfx_events(timeline: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for track in timeline.get("tracks", []):
        if not isinstance(track, dict):
            continue
        for event in track.get("events", []):
            if not isinstance(event, dict):
                continue
            etype = str(event.get("type", "")).lower()
            if etype.startswith("sfx_") or etype in {"hook_enhancement", "transition"}:
                events.append(event)
    # Add a conservative hook hit even when planning only gave motion events.
    if not any(float(e.get("start") or 0.0) <= 0.4 for e in events):
        events.insert(
            0,
            {
                "type": "sfx_impact",
                "start": 0.12,
                "reason": "first-word hook emphasis",
                "volume_db": -13,
            },
        )
    return events


def _sfx_event_limit(timeline: dict[str, Any]) -> int:
    meta = _dict_value(timeline, "metadata")
    editing = _dict_value(meta, "editing_v2")
    sfx_plan = _dict_value(editing, "sfx_plan")
    density = str(sfx_plan.get("density") or "").lower()
    intensity = str(editing.get("edit_intensity") or "").lower()
    if "high" in density or "high" in intensity or "energetic" in intensity:
        return 6
    return 4


def _sfx_gain_db(event_type: str, requested: Any, selected: dict[str, Any]) -> float:
    try:
        gain = float(requested)
    except (TypeError, ValueError):
        try:
            gain = float(selected.get("recommended_gain_db", -16.0))
        except (TypeError, ValueError):
            gain = -16.0
    low = event_type.lower()
    if "impact" in low or "hit" in low or "hook" in low:
        return round(min(-8.0, max(-12.0, gain)), 1)
    if "pop" in low or "caption" in low:
        return round(min(-12.0, max(-18.0, gain)), 1)
    if "whoosh" in low or "swoosh" in low or "zoom" in low:
        return round(min(-14.0, max(-20.0, gain)), 1)
    if "riser" in low or "reveal" in low:
        return round(min(-18.0, max(-24.0, gain)), 1)
    return round(min(-12.0, max(-20.0, gain)), 1)


def select_sfx(timeline: dict[str, Any], root: str | Path | None = None) -> dict[str, Any]:
    base = asset_root(root)
    all_choices = _assets(base, "sfx")
    choices = [
        asset
        for asset in all_choices
        if asset.get("safe_default") is not False and not _is_noise_like_sfx(asset)
    ]
    planned = _planned_sfx_events(timeline)
    skipped: list[dict[str, Any]] = []
    rejected_assets = [
        {
            "asset_id": asset.get("id"),
            "filename": asset.get("filename"),
            "reason": "rejected_noise_like_sfx",
        }
        for asset in all_choices
        if asset not in choices
    ]
    if not choices:
        return {
            "status": "unavailable",
            "mixed_count": 0,
            "planned_count": len(planned),
            "skipped_count": len(planned) + len(rejected_assets),
            "skipped_reasons": ["rejected_noise_like_sfx"] if rejected_assets else [],
            "safety_applied": True,
            "events": [
                {
                    "time": float(e.get("start") or e.get("at") or 0.0),
                    "type": str(e.get("type") or "sfx"),
                    "mixed": False,
                    "reason": "planned but no safe local SFX asset exists",
                }
                for e in planned
            ],
            "rejected_assets": rejected_assets,
            "reason": (
                f"No usable royalty-free SFX assets found under {base}. "
                "Run tools/install_editing_assets.py or add licensed effects to assets/sfx."
            ),
        }

    resolved: list[dict[str, Any]] = []
    max_events = _sfx_event_limit(timeline)
    for event in planned:
        etype = str(event.get("type") or "sfx")
        if len(resolved) >= max_events:
            skipped.append({"type": etype, "reason": "sfx_density_limit"})
            continue
        if _sfx_terms(etype) & _NOISE_LIKE_TERMS:
            skipped.append({"type": etype, "reason": "rejected_noise_like_sfx"})
            continue
        terms = _sfx_terms(etype)
        selected = max(choices, key=lambda asset: _score_asset(asset, terms))
        resolved.append(
            {
                "time": max(0.0, float(event.get("start") or event.get("at") or 0.0)),
                "type": etype,
                "asset_id": selected.get("id"),
                "path": selected["path"],
                "filename": selected.get("filename"),
                "gain_db": _sfx_gain_db(
                    etype, event.get("volume_db") or event.get("gain_db"), selected
                ),
                "mixed": True,
                "reason": str(event.get("reason") or "timed to edit beat"),
                "sfx_type": selected.get("sfx_type") or etype.replace("sfx_", ""),
                "quality": selected.get("quality"),
                "noise_like": bool(selected.get("noise_like")),
                "safe_default": selected.get("safe_default") is not False,
                "license": _license(selected),
            }
        )
    return {
        "status": "mixed" if resolved else "unavailable",
        "mixed_count": len(resolved),
        "planned_count": len(planned),
        "skipped_count": len(skipped) + len(rejected_assets),
        "skipped_reasons": sorted(
            {str(item.get("reason")) for item in [*skipped, *rejected_assets] if item.get("reason")}
        ),
        "safety_applied": True,
        "events": resolved,
        "skipped": skipped,
        "rejected_assets": rejected_assets,
        "reason": f"resolved {len(resolved)} safe SFX event(s) from local asset manifest",
    }


def resolve_assets(
    timeline: dict[str, Any],
    root: str | Path | None = None,
    *,
    music_usage_counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Resolve all optional render assets for one timeline."""

    return {
        "asset_root": str(asset_root(root)),
        "music": select_music(timeline, root, usage_counts=music_usage_counts),
        "sfx": select_sfx(timeline, root),
    }
