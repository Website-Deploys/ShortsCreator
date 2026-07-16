"""License-strict local music asset registry."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from olympus.music.library import (
    automatic_rejection_reasons,
    energy_score,
    intensity_score,
    load_library_manifest,
    normalize_license,
    safe_asset_path,
)

MUSIC_MANIFEST = Path("music") / "music_manifest.json"
LEGACY_MANIFEST = Path("manifest.json")


def _root(root: str | Path) -> Path:
    return Path(root).expanduser().resolve()


def load_music_manifest(root: str | Path) -> dict[str, Any]:
    """Load Music Library V2 while tolerating the previous flat manifest."""

    base = _root(root)
    canonical = base / MUSIC_MANIFEST
    legacy = base / LEGACY_MANIFEST
    if canonical.exists():
        library = load_library_manifest(base / "music")
        warnings = [str(item) for item in _list(library.get("warnings"))]
        reason = "; ".join(warnings) if library.get("invalid_manifest") else None
        return {
            **library,
            "assets": [
                item
                for item in _list(library.get("assets"))
                if isinstance(item, dict)
            ],
            "manifest_path": str(canonical),
            "schema": "music_library_v2",
            "reason": reason,
        }
    if not legacy.exists():
        return {
            "version": "2.0",
            "assets": [],
            "manifest_path": str(canonical),
            "schema": "missing",
            "reason": f"No music manifest found at {canonical}",
        }
    try:
        value = json.loads(legacy.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "version": "2.0",
            "assets": [],
            "manifest_path": str(legacy),
            "schema": "legacy",
            "reason": f"Music manifest could not be read: {exc}",
        }
    data = value if isinstance(value, dict) else {}
    assets = [
        item
        for item in _list(data.get("assets"))
        if isinstance(item, dict) and str(item.get("type", "")).lower() == "music"
    ]
    return {
        **data,
        "assets": assets,
        "manifest_path": str(legacy),
        "schema": "legacy",
    }


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _tags(value: Any) -> list[str]:
    if isinstance(value, str):
        values: list[Any] = [value]
    elif isinstance(value, list):
        values = value
    else:
        values = []
    return sorted(
        {
            str(item).strip().lower().replace("-", "_").replace(" ", "_")
            for item in values
            if str(item).strip()
        }
    )


def _asset_relative_path(raw: dict[str, Any]) -> str:
    relative = str(raw.get("relative_path") or "").strip().replace("\\", "/")
    if relative:
        return relative.removeprefix("music/")
    legacy = str(raw.get("path") or raw.get("filename") or "").strip().replace("\\", "/")
    return legacy.removeprefix("music/")


def _normalize_asset(base: Path, raw: dict[str, Any]) -> dict[str, Any]:
    relative_path = _asset_relative_path(raw)
    path = safe_asset_path(base / "music", relative_path)
    path_valid = path is not None
    file_exists = bool(path and path.is_file())
    license_name = normalize_license(raw.get("license"))
    license_verified = raw.get("license_verified") is True
    safe_default = raw.get("safe_default") is True
    explicit_auto = raw.get("auto_select_allowed")
    auto_select_allowed = (
        explicit_auto is True
        if isinstance(explicit_auto, bool)
        else bool(
            license_verified
            and safe_default
            and raw.get("usage_allowed") is not False
        )
    )
    quality_status = str(raw.get("quality_status") or "").lower()
    if not quality_status and raw.get("quality") in {
        "validation_quality",
        "production_curated",
        "passed",
    }:
        quality_status = "passed"
    folder_type = str(raw.get("folder_type") or "").lower()
    if not folder_type:
        folder_type = relative_path.split("/", 1)[0] if "/" in relative_path else "generated"
    normalized: dict[str, Any] = {
        "asset_id": str(
            raw.get("asset_id") or raw.get("id") or Path(relative_path).stem
        ),
        "path": str(path) if path is not None else None,
        "filename": (
            f"music/{relative_path}" if relative_path else str(raw.get("filename") or "")
        ),
        "relative_path": relative_path or None,
        "title": str(
            raw.get("title")
            or raw.get("asset_id")
            or raw.get("id")
            or Path(relative_path).stem
        ),
        "folder_type": folder_type,
        "duration": _float(raw.get("duration_seconds") or raw.get("duration")),
        "duration_seconds": _float(
            raw.get("duration_seconds") or raw.get("duration")
        ),
        "sample_rate": _int(raw.get("sample_rate")),
        "channels": _int(raw.get("channels")),
        "codec": raw.get("codec"),
        "container": raw.get("container"),
        "bitrate": _int(raw.get("bitrate")),
        "bpm": _float(raw.get("bpm")),
        "bpm_confidence": raw.get("bpm_confidence") or "unknown",
        "key": raw.get("key"),
        "key_confidence": raw.get("key_confidence") or "unknown",
        "mood_tags": _tags(
            raw.get("mood_tags") or raw.get("categories") or raw.get("tags")
        ),
        "energy_level": energy_score(
            raw.get("energy_score") or raw.get("energy_level") or raw.get("energy")
        ),
        "energy_category": raw.get("energy_level"),
        "intensity": intensity_score(
            raw.get("intensity_score") or raw.get("intensity")
        ),
        "intensity_category": raw.get("intensity"),
        "genre_tags": _tags(raw.get("genre_tags")),
        "use_case_tags": _tags(raw.get("use_case_tags")),
        "niche_tags": _tags(
            raw.get("niche_tags")
            or raw.get("use_case_tags")
            or raw.get("categories")
        ),
        "loopable": raw.get("loopable") is True,
        "loop_points": _list(raw.get("loop_points")),
        "has_vocals": raw.get("has_vocals"),
        "instrumental": raw.get("instrumental"),
        "speech_safe": raw.get("speech_safe") is True,
        "license": license_name or None,
        "license_url": raw.get("license_url"),
        "license_summary": raw.get("license_summary"),
        "license_verified": license_verified,
        "source": raw.get("source"),
        "source_url": raw.get("source_url"),
        "rights_holder": raw.get("rights_holder"),
        "attribution_required": raw.get("attribution_required") is True,
        "attribution_text": raw.get("attribution_text"),
        "safe_default": safe_default,
        "auto_select_allowed": auto_select_allowed,
        "manual_review_required": raw.get("manual_review_required") is True,
        "quality_status": quality_status or "unknown",
        "quality_tier": raw.get("quality_tier") or raw.get("quality"),
        "quality": raw.get("quality_tier") or raw.get("quality"),
        "recommended_gain_db": _float(raw.get("recommended_gain_db")),
        "integrated_loudness_lufs": _float(
            raw.get("loudness_lufs") or raw.get("integrated_loudness_lufs")
        ),
        "peak_dbfs": _float(raw.get("peak_db") or raw.get("peak_dbfs")),
        "rms_db": _float(raw.get("rms_db")),
        "dynamic_range": _float(raw.get("dynamic_range")),
        "clipping_detected": raw.get("clipping_detected") is True,
        "silence_ratio": _float(raw.get("silence_ratio")),
        "fingerprint": raw.get("fingerprint") or raw.get("sha256"),
        "duplicate_group_id": raw.get("duplicate_group_id"),
        "duplicate_primary": raw.get("duplicate_primary"),
        "usage_count": _int(raw.get("usage_count")) or 0,
        "last_used_at": raw.get("last_used_at"),
        "created_at": raw.get("created_at") or raw.get("downloaded_at"),
        "imported_at": raw.get("imported_at"),
        "analyzed_at": raw.get("analyzed_at"),
        "last_validated_at": raw.get("last_validated_at"),
        "warnings": [str(item) for item in _list(raw.get("warnings"))],
    }
    reasons = automatic_rejection_reasons(
        normalized,
        path_valid=path_valid,
        file_exists=file_exists,
    )
    normalized["rejection_reasons"] = reasons
    normalized["automatic_use_allowed"] = not reasons
    return normalized


def load_music_assets(root: str | Path) -> dict[str, Any]:
    """Return normalized safe and rejected pools for Music Intelligence V2."""

    base = _root(root)
    manifest = load_music_manifest(base)
    assets = [
        _normalize_asset(base, item)
        for item in manifest.get("assets", [])
        if isinstance(item, dict)
    ]
    _reject_duplicate_hashes(assets)
    safe = [item for item in assets if item["automatic_use_allowed"]]
    unsafe = [item for item in assets if not item["automatic_use_allowed"]]
    folder_counts = {
        folder: sum(1 for item in assets if item.get("folder_type") == folder)
        for folder in ("curated", "generated", "user", "quarantine", "rejected")
    }
    return {
        "manifest_path": manifest.get("manifest_path"),
        "version": str(manifest.get("version") or "2.0"),
        "schema": manifest.get("schema"),
        "assets": assets,
        "safe_assets": safe,
        "unsafe_assets": unsafe,
        "rejected_assets": manifest.get("rejected_assets") or [],
        "curated_assets": [
            item for item in safe if item.get("folder_type") == "curated"
        ],
        "generated_assets": [
            item for item in safe if item.get("folder_type") == "generated"
        ],
        "user_assets": [
            item for item in safe if item.get("folder_type") == "user"
        ],
        "folder_counts": folder_counts,
        "stats": manifest.get("stats") or {},
        "reason": manifest.get("reason"),
        "warnings": manifest.get("warnings") or [],
    }


def _reject_duplicate_hashes(assets: list[dict[str, Any]]) -> None:
    groups: dict[str, list[dict[str, Any]]] = {}
    for asset in assets:
        fingerprint = str(asset.get("fingerprint") or "")
        if fingerprint:
            groups.setdefault(fingerprint, []).append(asset)
    for fingerprint, members in groups.items():
        if len(members) < 2:
            continue
        primary = max(members, key=_duplicate_priority)
        group_id = "dup_" + fingerprint.removeprefix("sha256:")[:12]
        for member in members:
            member["duplicate_group_id"] = group_id
            member["duplicate_primary"] = member is primary
            if member is primary:
                continue
            reasons = set(_list(member.get("rejection_reasons")))
            reasons.add("duplicate_secondary")
            member["rejection_reasons"] = sorted(str(item) for item in reasons)
            member["automatic_use_allowed"] = False


def _duplicate_priority(asset: dict[str, Any]) -> tuple[int, int, int, int]:
    folder = {"curated": 4, "user": 3, "generated": 2}.get(
        str(asset.get("folder_type") or ""),
        1,
    )
    quality = 2 if asset.get("quality_status") == "passed" else 1
    return (
        folder,
        quality,
        _int(asset.get("sample_rate")) or 0,
        _int(asset.get("bitrate")) or 0,
    )


def _int(value: Any) -> int | None:
    try:
        return int(float(value)) if value is not None else None
    except (TypeError, ValueError):
        return None


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
