"""Safe local curated-music library management and audio inspection."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

MUSIC_LIBRARY_VERSION = "2.0"
MANIFEST_FILENAME = "music_manifest.json"
LIBRARY_FOLDERS = (
    "generated",
    "curated",
    "user",
    "rejected",
    "quarantine",
    "reports",
)
SUPPORTED_AUDIO_EXTENSIONS = frozenset({".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg"})
PREFERRED_AUDIO_EXTENSIONS = frozenset({".wav", ".m4a", ".mp3"})
ACCEPTED_LICENSES = frozenset(
    {
        "project_generated_safe",
        "user_owned",
        "user_licensed",
        "cc0",
        "public_domain",
        "royalty_free_verified",
        "custom_verified",
    }
)
UNSAFE_LICENSES = frozenset(
    {
        "unknown",
        "unverified",
        "copyrighted_unknown",
        "streaming_platform_rip",
        "no_license",
        "personal_use_only",
    }
)
MOOD_TAGS = frozenset(
    {
        "motivational",
        "emotional",
        "cinematic",
        "calm",
        "focused",
        "playful",
        "intense",
        "mysterious",
        "inspirational",
        "neutral",
        "gaming_energy",
        "comedy",
        "serious",
        "ambient",
    }
)
USE_CASE_TAGS = frozenset(
    {
        "motivational_speech",
        "emotional_story",
        "podcast_bed",
        "education_focus",
        "gaming_stream",
        "comedy_short",
        "cinematic_tension",
        "business_money",
        "self_improvement",
        "background_bed",
        "payoff_swell",
        "intro_only",
        "outro_only",
    }
)
ENERGY_SCORES = {
    "very_low": 0.12,
    "low": 0.28,
    "medium_low": 0.42,
    "medium": 0.56,
    "medium_high": 0.74,
    "high": 0.9,
}
INTENSITY_SCORES = {"subtle": 0.3, "balanced": 0.58, "strong": 0.84}


class MusicLibraryError(RuntimeError):
    """Expected library-management failure with a stable code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def normalize_tag(value: object) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return re.sub(r"[^a-z0-9_]+", "", text)


def normalize_license(value: object) -> str:
    normalized = normalize_tag(value)
    aliases = {
        "cc0_10": "cc0",
        "cc0_1_0": "cc0",
        "cc0_1": "cc0",
        "publicdomain": "public_domain",
        "royalty_free": "royalty_free_verified",
    }
    return aliases.get(normalized, normalized)


def streaming_source_requires_review(source: object, source_url: object) -> bool:
    source_record = f"{source or ''} {source_url or ''}".lower()
    return any(
        token in source_record
        for token in (
            "youtube",
            "youtu.be",
            "spotify",
            "tiktok",
            "instagram",
            "soundcloud",
            "streaming platform rip",
        )
    )


def energy_score(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return round(min(1.0, max(0.0, float(value))), 3)
    return ENERGY_SCORES.get(normalize_tag(value))


def energy_category(value: object) -> str:
    normalized = normalize_tag(value)
    if normalized in ENERGY_SCORES:
        return normalized
    score = energy_score(value)
    if score is None:
        return "unknown"
    if score < 0.2:
        return "very_low"
    if score < 0.35:
        return "low"
    if score < 0.5:
        return "medium_low"
    if score < 0.66:
        return "medium"
    if score < 0.82:
        return "medium_high"
    return "high"


def intensity_score(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return round(min(1.0, max(0.0, float(value))), 3)
    return INTENSITY_SCORES.get(normalize_tag(value))


def intensity_category(value: object) -> str:
    normalized = normalize_tag(value)
    if normalized in INTENSITY_SCORES:
        return normalized
    score = intensity_score(value)
    if score is None:
        return "balanced"
    if score < 0.44:
        return "subtle"
    if score < 0.72:
        return "balanced"
    return "strong"


def tempo_category(bpm: object) -> str:
    value = _float(bpm)
    if value is None:
        return "unknown"
    if value < 90:
        return "slow"
    if value <= 125:
        return "medium"
    return "fast"


def file_fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def safe_asset_path(library_root: Path, relative_path: object) -> Path | None:
    text = str(relative_path or "").strip().replace("\\", "/")
    if not text:
        return None
    try:
        path = (library_root / text).resolve()
        path.relative_to(library_root.resolve())
    except (OSError, ValueError):
        return None
    return path


def automatic_rejection_reasons(
    asset: dict[str, Any],
    *,
    path_valid: bool,
    file_exists: bool,
) -> list[str]:
    """Return every reason an asset cannot be selected automatically."""

    reasons: list[str] = []
    if not str(asset.get("asset_id") or "").strip():
        reasons.append("asset_id_missing")
    if not path_valid:
        reasons.append("invalid_asset_path")
    elif not file_exists:
        reasons.append("missing_asset_file")
    duration = _float(asset.get("duration_seconds") or asset.get("duration"))
    if duration is None or duration <= 0:
        reasons.append("duration_missing_or_invalid")
    if not _tags(asset.get("mood_tags")):
        reasons.append("mood_tags_missing")
    if energy_score(asset.get("energy_score") or asset.get("energy_level")) is None:
        reasons.append("energy_level_missing")
    license_name = normalize_license(asset.get("license"))
    if not license_name:
        reasons.append("license_missing")
    elif license_name in UNSAFE_LICENSES or license_name not in ACCEPTED_LICENSES:
        reasons.append("license_unsafe_or_unknown")
    if asset.get("license_verified") is not True:
        reasons.append("license_not_verified")
    if not str(asset.get("source") or "").strip():
        reasons.append("source_missing")
    if streaming_source_requires_review(
        asset.get("source"),
        asset.get("source_url"),
    ):
        reasons.append("streaming_platform_source_requires_review")
    if asset.get("attribution_required") is True and not str(
        asset.get("attribution_text") or ""
    ).strip():
        reasons.append("attribution_text_missing")
    restrictions = " ".join(
        str(asset.get(key) or "")
        for key in ("license_summary", "license", "warnings")
    ).lower()
    if any(
        token in restrictions
        for token in ("personal use only", "non-commercial", "noncommercial")
    ):
        reasons.append("commercial_use_restricted")
    if any(token in restrictions for token in ("platform only", "youtube only", "tiktok only")):
        reasons.append("platform_use_restricted")
    if asset.get("safe_default") is not True:
        reasons.append("not_safe_default")
    if asset.get("speech_safe") is not True:
        reasons.append("not_speech_safe")
    if str(asset.get("quality_status") or "").lower() != "passed":
        reasons.append("quality_not_passed")
    if asset.get("manual_review_required") is True:
        reasons.append("manual_review_required")
    if asset.get("duplicate_primary") is False:
        reasons.append("duplicate_secondary")
    return sorted(set(reasons))


def _empty_library(library_root: Path) -> dict[str, Any]:
    return {
        "version": MUSIC_LIBRARY_VERSION,
        "updated_at": utc_now_iso(),
        "library_root": str(library_root.resolve()),
        "assets": [],
        "rejected_assets": [],
        "warnings": [],
        "stats": {},
    }


def _unwrap_manifest(raw: object, library_root: Path) -> tuple[dict[str, Any], bool]:
    if not isinstance(raw, dict):
        return _empty_library(library_root), False
    nested = raw.get("music_library_v2")
    if isinstance(nested, dict):
        library = {
            **_empty_library(library_root),
            **nested,
            "library_root": str(library_root.resolve()),
            "assets": [
                item for item in _list(nested.get("assets")) if isinstance(item, dict)
            ],
            "rejected_assets": [
                item
                for item in _list(nested.get("rejected_assets"))
                if isinstance(item, dict)
            ],
            "warnings": [str(item) for item in _list(nested.get("warnings"))],
        }
        return library, False
    assets = [item for item in _list(raw.get("assets")) if isinstance(item, dict)]
    library = _empty_library(library_root)
    library["assets"] = [
        _migrate_legacy_asset(item, library_root) for item in assets
    ]
    library["warnings"] = [
        "Migrated the previous flat music manifest to music_library_v2."
    ]
    return library, bool(assets or raw)


def load_library_manifest(library_root: str | Path) -> dict[str, Any]:
    root = Path(library_root).expanduser().resolve()
    path = root / MANIFEST_FILENAME
    if not path.exists():
        return _empty_library(root)
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        library = _empty_library(root)
        library["warnings"] = [f"Music manifest could not be read: {exc}"]
        library["invalid_manifest"] = True
        return library
    library, migrated = _unwrap_manifest(raw, root)
    library["migration_required"] = migrated
    return library


def save_library_manifest(library_root: str | Path, library: dict[str, Any]) -> Path:
    root = Path(library_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    library["version"] = MUSIC_LIBRARY_VERSION
    library["updated_at"] = utc_now_iso()
    library["library_root"] = str(root)
    library["stats"] = library_stats(library)
    path = root / MANIFEST_FILENAME
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps({"music_library_v2": library}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return path


def initialize_library(library_root: str | Path) -> dict[str, Any]:
    root = Path(library_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    for folder in LIBRARY_FOLDERS:
        (root / folder).mkdir(parents=True, exist_ok=True)
    library = load_library_manifest(root)
    if library.get("invalid_manifest"):
        return library
    library.pop("migration_required", None)
    save_library_manifest(root, library)
    return library


def _migrate_legacy_asset(raw: dict[str, Any], library_root: Path) -> dict[str, Any]:
    now = utc_now_iso()
    path_text = str(raw.get("path") or raw.get("filename") or "").replace("\\", "/")
    if path_text.startswith("music/"):
        path_text = path_text[len("music/") :]
    folder = path_text.split("/", 1)[0] if "/" in path_text else "generated"
    if folder not in {"generated", "curated", "user", "rejected", "quarantine"}:
        folder = "generated"
        path_text = f"generated/{Path(path_text).name}"
    path = safe_asset_path(library_root, path_text)
    existing = bool(path and path.is_file())
    old_energy = raw.get("energy_level") or raw.get("energy")
    old_intensity = raw.get("intensity")
    license_name = normalize_license(raw.get("license"))
    source = str(raw.get("source") or raw.get("source_url") or "")
    quality = str(raw.get("quality") or "")
    quality_status = (
        "passed"
        if existing
        and (_float(raw.get("duration")) or 0) > 0
        and quality in {"validation_quality", "production_curated", "passed"}
        else "review"
    )
    safe_default = raw.get("safe_default") is True
    asset = {
        "asset_id": str(raw.get("asset_id") or raw.get("id") or Path(path_text).stem),
        "title": str(raw.get("title") or raw.get("asset_id") or Path(path_text).stem),
        "filename": Path(path_text).name,
        "relative_path": path_text,
        "absolute_path": str(path) if path else None,
        "folder_type": folder,
        "duration_seconds": _float(raw.get("duration")),
        "sample_rate": _int(raw.get("sample_rate")),
        "channels": _int(raw.get("channels")),
        "codec": raw.get("codec"),
        "container": raw.get("container") or Path(path_text).suffix.lstrip("."),
        "bitrate": _int(raw.get("bitrate")),
        "bpm": _float(raw.get("bpm")),
        "bpm_confidence": "manifest" if raw.get("bpm") is not None else "unknown",
        "key": raw.get("key"),
        "key_confidence": "manifest" if raw.get("key") else "unknown",
        "loudness_lufs": _float(
            raw.get("loudness_lufs") or raw.get("integrated_loudness_lufs")
        ),
        "loudness_method": "legacy_manifest",
        "peak_db": _float(raw.get("peak_db") or raw.get("peak_dbfs")),
        "rms_db": _float(raw.get("rms_db")),
        "dynamic_range": _float(raw.get("dynamic_range")),
        "clipping_detected": bool(raw.get("clipping_detected", False)),
        "silence_ratio": _float(raw.get("silence_ratio")),
        "mood_tags": _tags(
            raw.get("mood_tags") or raw.get("categories") or raw.get("tags")
        ),
        "genre_tags": _tags(raw.get("genre_tags")),
        "use_case_tags": _tags(
            raw.get("use_case_tags") or raw.get("niche_tags") or raw.get("categories")
        ),
        "niche_tags": _tags(raw.get("niche_tags") or raw.get("categories")),
        "energy_level": energy_category(old_energy),
        "energy_score": energy_score(old_energy),
        "intensity": intensity_category(old_intensity),
        "intensity_score": intensity_score(old_intensity),
        "tempo_category": tempo_category(raw.get("bpm")),
        "has_vocals": raw.get("has_vocals") if isinstance(raw.get("has_vocals"), bool) else None,
        "vocal_confidence": "manifest" if isinstance(raw.get("has_vocals"), bool) else "unknown",
        "instrumental": (
            not bool(raw.get("has_vocals"))
            if isinstance(raw.get("has_vocals"), bool)
            else None
        ),
        "speech_safe": raw.get("speech_safe") is True,
        "loopable": raw.get("loopable") is True,
        "loop_points": raw.get("loop_points") or [],
        "intro_seconds": _float(raw.get("intro_seconds")),
        "outro_seconds": _float(raw.get("outro_seconds")),
        "license": license_name or None,
        "license_url": raw.get("license_url"),
        "license_summary": raw.get("license_summary") or raw.get("notes"),
        "license_verified": raw.get("license_verified") is True,
        "source": source or None,
        "source_url": raw.get("source_url"),
        "rights_holder": raw.get("rights_holder"),
        "attribution_required": bool(raw.get("attribution_required", False)),
        "attribution_text": raw.get("attribution_text") or raw.get("attribution"),
        "safe_default": safe_default,
        "auto_select_allowed": bool(
            safe_default
            and raw.get("license_verified") is True
            and raw.get("speech_safe") is True
            and quality_status == "passed"
        ),
        "manual_review_required": False,
        "quality_status": quality_status,
        "quality_tier": quality or (
            "validation_quality" if folder == "generated" else "unknown"
        ),
        "rejection_reasons": [],
        "warnings": [str(item) for item in _list(raw.get("warnings"))],
        "created_at": raw.get("created_at") or raw.get("downloaded_at") or now,
        "imported_at": raw.get("imported_at"),
        "analyzed_at": raw.get("analyzed_at"),
        "last_validated_at": now,
        "fingerprint": raw.get("fingerprint") or raw.get("sha256"),
        "duplicate_group_id": raw.get("duplicate_group_id"),
        "duplicate_primary": raw.get("duplicate_primary"),
        "usage_count": _int(raw.get("usage_count")) or 0,
        "last_used_at": raw.get("last_used_at"),
        "recommended_gain_db": _float(raw.get("recommended_gain_db")),
    }
    reasons = automatic_rejection_reasons(
        asset,
        path_valid=path is not None,
        file_exists=existing,
    )
    asset["rejection_reasons"] = reasons
    asset["auto_select_allowed"] = not reasons
    return asset


def analyze_audio(
    path: Path,
    *,
    ffprobe_binary: str = "ffprobe",
    ffmpeg_binary: str = "ffmpeg",
) -> dict[str, Any]:
    """Inspect an audio file without claiming BPM, key, or vocal ML inference."""

    result: dict[str, Any] = {
        "passed": False,
        "duration_seconds": None,
        "sample_rate": None,
        "channels": None,
        "codec": None,
        "container": path.suffix.lower().lstrip(".") or None,
        "bitrate": None,
        "bpm": None,
        "bpm_confidence": "unknown",
        "key": None,
        "key_confidence": "unknown",
        "loudness_lufs": None,
        "loudness_method": None,
        "peak_db": None,
        "rms_db": None,
        "dynamic_range": None,
        "clipping_detected": False,
        "silence_ratio": None,
        "energy_level": "unknown",
        "energy_score": None,
        "tempo_category": "unknown",
        "loopable_hint": False,
        "intro_seconds": None,
        "outro_seconds": None,
        "quality_status": "failed",
        "warnings": [],
        "errors": [],
    }
    probe = _resolve_binary(ffprobe_binary)
    if probe is None:
        result["errors"].append("ffprobe is not available")
        return result
    try:
        completed = subprocess.run(
            [
                probe,
                "-v",
                "error",
                "-show_entries",
                (
                    "format=duration,bit_rate,format_name:"
                    "stream=codec_type,codec_name,sample_rate,channels,bit_rate"
                ),
                "-of",
                "json",
                str(path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        result["errors"].append(str(exc))
        return result
    if completed.returncode != 0:
        result["errors"].append(
            completed.stderr.strip() or f"ffprobe exited {completed.returncode}"
        )
        return result
    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        result["errors"].append(f"ffprobe returned invalid JSON: {exc}")
        return result
    streams = [item for item in _list(payload.get("streams")) if isinstance(item, dict)]
    audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
    format_data = _dict(payload.get("format"))
    if audio is None:
        result["errors"].append("file contains no audio stream")
        return result
    duration = _float(format_data.get("duration"))
    result.update(
        {
            "duration_seconds": duration,
            "sample_rate": _int(audio.get("sample_rate")),
            "channels": _int(audio.get("channels")),
            "codec": _text(audio.get("codec_name")),
            "container": _text(format_data.get("format_name")) or result["container"],
            "bitrate": _int(audio.get("bit_rate")) or _int(format_data.get("bit_rate")),
        }
    )
    if duration is None or duration <= 0:
        result["errors"].append("audio duration is zero or unavailable")
        return result
    if not result["sample_rate"] or int(result["sample_rate"]) <= 0:
        result["errors"].append("audio sample rate is unavailable")
        return result

    ffmpeg = _resolve_binary(ffmpeg_binary)
    if ffmpeg is None:
        result["warnings"].append("ffmpeg unavailable; loudness analysis was not run")
    else:
        _apply_loudness_analysis(result, path, ffmpeg)
        _apply_signal_analysis(result, path, ffmpeg, duration)
    result["clipping_detected"] = bool(
        result["peak_db"] is not None and float(result["peak_db"]) >= -0.1
    )
    category, score = _energy_from_levels(
        _float(result.get("rms_db")),
        _float(result.get("loudness_lufs")),
    )
    result["energy_level"] = category
    result["energy_score"] = score
    result["loopable_hint"] = bool(
        duration >= 8.0
        and (_float(result.get("silence_ratio")) or 0.0) < 0.2
        and not result["clipping_detected"]
    )
    review_reasons: list[str] = []
    if duration < 8.0 or duration > 600.0:
        review_reasons.append("duration_outside_preferred_8_to_600_seconds")
    loudness = _float(result.get("loudness_lufs"))
    if loudness is None:
        review_reasons.append("loudness_not_measured")
    elif loudness > -5.0 or loudness < -45.0:
        review_reasons.append("extreme_loudness")
    if result["clipping_detected"]:
        review_reasons.append("clipping_detected")
    silence = _float(result.get("silence_ratio"))
    if silence is not None and silence > 0.8:
        review_reasons.append("excessive_silence")
    result["warnings"].extend(review_reasons)
    result["quality_status"] = "review" if review_reasons else "passed"
    result["passed"] = result["quality_status"] in {"passed", "review"}
    return result


def _apply_loudness_analysis(result: dict[str, Any], path: Path, ffmpeg: str) -> None:
    null_output = "NUL" if os.name == "nt" else "/dev/null"
    try:
        completed = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-nostats",
                "-i",
                str(path),
                "-filter_complex",
                "ebur128=peak=true",
                "-f",
                "null",
                null_output,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        result["warnings"].append(f"loudness analysis failed: {exc}")
        return
    output = completed.stderr or ""
    loudness = _last_float(r"\bI:\s*(-?\d+(?:\.\d+)?)\s*LUFS", output)
    peak = _last_float(r"\bPeak:\s*(-?\d+(?:\.\d+)?)\s*dBFS", output)
    if completed.returncode == 0 and loudness is not None:
        result["loudness_lufs"] = loudness
        result["loudness_method"] = "ffmpeg_ebur128"
    else:
        result["warnings"].append("ffmpeg ebur128 did not return integrated loudness")
    if peak is not None:
        result["peak_db"] = peak


def _apply_signal_analysis(
    result: dict[str, Any],
    path: Path,
    ffmpeg: str,
    duration: float,
) -> None:
    null_output = "NUL" if os.name == "nt" else "/dev/null"
    try:
        completed = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-nostats",
                "-i",
                str(path),
                "-af",
                "astats=metadata=1:reset=0,silencedetect=noise=-50dB:d=0.2",
                "-f",
                "null",
                null_output,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        result["warnings"].append(f"signal analysis failed: {exc}")
        return
    output = completed.stderr or ""
    rms = _last_float(r"RMS level dB:\s*(-?\d+(?:\.\d+)?)", output)
    astats_peak = _last_float(r"Peak level dB:\s*(-?\d+(?:\.\d+)?)", output)
    dynamic_range = _last_float(r"Dynamic range:\s*(-?\d+(?:\.\d+)?)", output)
    silence_durations = [
        float(value)
        for value in re.findall(r"silence_duration:\s*(\d+(?:\.\d+)?)", output)
    ]
    if rms is not None:
        result["rms_db"] = rms
    if result.get("peak_db") is None and astats_peak is not None:
        result["peak_db"] = astats_peak
    if dynamic_range is not None:
        result["dynamic_range"] = dynamic_range
    result["silence_ratio"] = round(
        min(1.0, max(0.0, sum(silence_durations) / duration)),
        4,
    )
    if completed.returncode != 0:
        result["warnings"].append("ffmpeg astats/silencedetect exited nonzero")


def _energy_from_levels(
    rms_db: float | None,
    loudness_lufs: float | None,
) -> tuple[str, float | None]:
    level = rms_db if rms_db is not None else loudness_lufs
    if level is None:
        return "unknown", None
    if level <= -35:
        return "very_low", ENERGY_SCORES["very_low"]
    if level <= -29:
        return "low", ENERGY_SCORES["low"]
    if level <= -23:
        return "medium_low", ENERGY_SCORES["medium_low"]
    if level <= -17:
        return "medium", ENERGY_SCORES["medium"]
    if level <= -11:
        return "medium_high", ENERGY_SCORES["medium_high"]
    return "high", ENERGY_SCORES["high"]


def library_stats(library: dict[str, Any]) -> dict[str, Any]:
    assets = [item for item in _list(library.get("assets")) if isinstance(item, dict)]
    counts = {
        folder: sum(1 for item in assets if item.get("folder_type") == folder)
        for folder in ("curated", "generated", "user", "quarantine", "rejected")
    }
    safe = [item for item in assets if item.get("auto_select_allowed") is True]
    moods = sorted(
        {
            mood
            for item in safe
            for mood in _tags(item.get("mood_tags"))
        }
    )
    missing = sorted(MOOD_TAGS - set(moods))
    duplicate_groups = {
        str(item.get("duplicate_group_id"))
        for item in assets
        if item.get("duplicate_group_id")
    }
    return {
        "total_assets": len(assets),
        "curated_assets": counts["curated"],
        "generated_assets": counts["generated"],
        "user_assets": counts["user"],
        "quarantined_assets": counts["quarantine"],
        "rejected_assets": len(_list(library.get("rejected_assets"))) + counts["rejected"],
        "safe_automatic_assets": len(safe),
        "moods_covered": moods,
        "missing_moods": missing,
        "duplicate_groups": len(duplicate_groups),
    }


class MusicLibraryManager:
    """Manage one local music directory without downloading external media."""

    def __init__(
        self,
        library_root: str | Path,
        *,
        ffmpeg_binary: str = "ffmpeg",
        ffprobe_binary: str = "ffprobe",
        report_root: str | Path | None = None,
    ) -> None:
        self.root = Path(library_root).expanduser().resolve()
        self.ffmpeg_binary = ffmpeg_binary
        self.ffprobe_binary = ffprobe_binary
        self._report_root = (
            Path(report_root).expanduser().resolve()
            if report_root is not None
            else self.root / "reports"
        )

    @property
    def manifest_path(self) -> Path:
        return self.root / MANIFEST_FILENAME

    @property
    def report_root(self) -> Path:
        return self._report_root

    def initialize(self) -> dict[str, Any]:
        library = initialize_library(self.root)
        if library.get("invalid_manifest"):
            raise MusicLibraryError(
                "INVALID_MANIFEST",
                "; ".join(str(item) for item in _list(library.get("warnings")))
                or "Music manifest is invalid.",
            )
        import_report = self.report_root / "music_import_report.json"
        if not import_report.exists():
            self.write_json_report(
                "music_import_report.json",
                {
                    "status": "not_run",
                    "message": "No local music import has been attempted.",
                    "created_at": utc_now_iso(),
                },
            )
        return library

    def load(self) -> dict[str, Any]:
        if not self.manifest_path.exists():
            return self.initialize()
        library = load_library_manifest(self.root)
        if library.get("invalid_manifest"):
            raise MusicLibraryError(
                "INVALID_MANIFEST",
                "; ".join(str(item) for item in _list(library.get("warnings")))
                or "Music manifest is invalid.",
            )
        return library

    def save(self, library: dict[str, Any]) -> Path:
        return save_library_manifest(self.root, library)

    def import_file(
        self,
        source_path: str | Path,
        *,
        title: str | None = None,
        license_name: str | None = None,
        license_url: str | None = None,
        license_summary: str | None = None,
        license_verified: bool = False,
        source: str | None = None,
        source_url: str | None = None,
        rights_holder: str | None = None,
        attribution_required: bool = False,
        attribution_text: str | None = None,
        moods: list[str] | None = None,
        genres: list[str] | None = None,
        use_cases: list[str] | None = None,
        energy: str | None = None,
        intensity: str | None = None,
        bpm: float | None = None,
        instrumental: bool | None = None,
        has_vocals: bool | None = None,
        speech_safe: bool = False,
        loopable: bool = False,
        safe_default: bool = False,
    ) -> dict[str, Any]:
        library = self.load()
        path = Path(source_path).expanduser().resolve()
        if not path.is_file():
            raise MusicLibraryError("SOURCE_NOT_FOUND", f"Music source does not exist: {path}")
        if path.suffix.lower() not in SUPPORTED_AUDIO_EXTENSIONS:
            rejected = self._rejected_import(
                path,
                "unsupported_audio_extension",
            )
            library["rejected_assets"].append(rejected)
            self.save(library)
            return {"status": "rejected", "asset": rejected}

        fingerprint = file_fingerprint(path)
        duplicate = next(
            (
                item
                for item in _list(library.get("assets"))
                if isinstance(item, dict) and item.get("fingerprint") == fingerprint
            ),
            None,
        )
        if isinstance(duplicate, dict):
            return {
                "status": "duplicate",
                "asset": duplicate,
                "reason": "exact_file_hash_match",
            }

        analysis = analyze_audio(
            path,
            ffprobe_binary=self.ffprobe_binary,
            ffmpeg_binary=self.ffmpeg_binary,
        )
        if not analysis.get("passed") or analysis.get("quality_status") == "failed":
            rejected = self._rejected_import(
                path,
                "audio_analysis_failed",
                warnings=[
                    *[str(item) for item in _list(analysis.get("warnings"))],
                    *[str(item) for item in _list(analysis.get("errors"))],
                ],
                fingerprint=fingerprint,
            )
            library["rejected_assets"].append(rejected)
            self.save(library)
            return {"status": "rejected", "asset": rejected, "analysis": analysis}

        normalized_license = normalize_license(license_name)
        known_safe_license = normalized_license in ACCEPTED_LICENSES
        unknown_license = (
            not normalized_license
            or normalized_license in UNSAFE_LICENSES
            or not known_safe_license
        )
        manual_energy = energy_category(energy) if energy else None
        selected_energy = manual_energy or str(analysis.get("energy_level") or "unknown")
        selected_energy_score = (
            energy_score(manual_energy)
            if manual_energy
            else _float(analysis.get("energy_score"))
        )
        selected_intensity = intensity_category(intensity or "balanced")
        selected_bpm = bpm if bpm is not None else analysis.get("bpm")
        selected_instrumental = (
            instrumental
            if instrumental is not None
            else not has_vocals
            if has_vocals is not None
            else None
        )
        selected_has_vocals = (
            has_vocals
            if has_vocals is not None
            else not instrumental
            if instrumental is not None
            else None
        )
        selected_moods = _validated_tags(moods, MOOD_TAGS)
        selected_genres = _tags(genres)
        selected_use_cases = _validated_tags(use_cases, USE_CASE_TAGS)
        source_needs_review = streaming_source_requires_review(source, source_url)
        production_ready = bool(
            license_verified
            and source
            and analysis.get("quality_status") == "passed"
            and speech_safe
            and selected_moods
            and selected_energy_score is not None
            and selected_has_vocals is not None
            and not source_needs_review
            and (not attribution_required or attribution_text)
        )
        if unknown_license or analysis.get("quality_status") != "passed":
            folder_type = "quarantine"
        elif known_safe_license and production_ready:
            folder_type = "curated"
        else:
            folder_type = "user"

        normalized_title = (title or path.stem).strip() or path.stem
        asset_id = self._asset_id(normalized_title, fingerprint)
        filename = self._unique_filename(
            folder_type,
            normalized_title,
            path.suffix.lower(),
            fingerprint,
        )
        destination = self.root / folder_type / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        relative_path = destination.relative_to(self.root).as_posix()

        warnings = [str(item) for item in _list(analysis.get("warnings"))]
        if bpm is None:
            warnings.append("BPM was not supplied and was not inferred.")
        if selected_has_vocals is None:
            warnings.append("Vocal presence is unknown; speech safety requires manual tagging.")
        if unknown_license:
            warnings.append("Missing or unknown license; asset quarantined.")
        elif not license_verified:
            warnings.append("License is recorded but not verified; automatic use is disabled.")
        if not source:
            warnings.append("Source metadata is missing; manual review is required.")
        if attribution_required and not attribution_text:
            warnings.append("Attribution is required but attribution text is missing.")

        requested_safe = bool(safe_default or license_verified)
        manual_review = bool(
            unknown_license
            or not production_ready
        )
        asset: dict[str, Any] = {
            "asset_id": asset_id,
            "title": normalized_title,
            "filename": filename,
            "relative_path": relative_path,
            "absolute_path": str(destination),
            "folder_type": folder_type,
            "duration_seconds": analysis.get("duration_seconds"),
            "sample_rate": analysis.get("sample_rate"),
            "channels": analysis.get("channels"),
            "codec": analysis.get("codec"),
            "container": analysis.get("container"),
            "bitrate": analysis.get("bitrate"),
            "bpm": selected_bpm,
            "bpm_confidence": "manual" if bpm is not None else "unknown",
            "key": analysis.get("key"),
            "key_confidence": analysis.get("key_confidence") or "unknown",
            "loudness_lufs": analysis.get("loudness_lufs"),
            "loudness_method": analysis.get("loudness_method"),
            "peak_db": analysis.get("peak_db"),
            "rms_db": analysis.get("rms_db"),
            "dynamic_range": analysis.get("dynamic_range"),
            "clipping_detected": analysis.get("clipping_detected") is True,
            "silence_ratio": analysis.get("silence_ratio"),
            "mood_tags": selected_moods,
            "genre_tags": selected_genres,
            "use_case_tags": selected_use_cases,
            "niche_tags": selected_use_cases,
            "energy_level": selected_energy,
            "energy_score": selected_energy_score,
            "intensity": selected_intensity,
            "intensity_score": intensity_score(selected_intensity),
            "tempo_category": tempo_category(selected_bpm),
            "has_vocals": selected_has_vocals,
            "vocal_confidence": "manual" if selected_has_vocals is not None else "unknown",
            "instrumental": selected_instrumental,
            "speech_safe": speech_safe,
            "loopable": bool(loopable or analysis.get("loopable_hint")),
            "loop_points": [],
            "intro_seconds": analysis.get("intro_seconds"),
            "outro_seconds": analysis.get("outro_seconds"),
            "license": normalized_license or None,
            "license_url": license_url,
            "license_summary": license_summary,
            "license_verified": bool(license_verified and known_safe_license),
            "source": source,
            "source_url": source_url,
            "rights_holder": rights_holder,
            "attribution_required": attribution_required,
            "attribution_text": attribution_text,
            "safe_default": bool(requested_safe and not manual_review),
            "auto_select_allowed": False,
            "manual_review_required": manual_review,
            "quality_status": analysis.get("quality_status"),
            "quality_tier": (
                "production_curated" if folder_type == "curated" else "user_provided"
            ),
            "rejection_reasons": [],
            "warnings": sorted(set(warnings)),
            "created_at": utc_now_iso(),
            "imported_at": utc_now_iso(),
            "analyzed_at": utc_now_iso(),
            "last_validated_at": utc_now_iso(),
            "fingerprint": fingerprint,
            "duplicate_group_id": None,
            "duplicate_primary": None,
            "usage_count": 0,
            "last_used_at": None,
            "recommended_gain_db": None,
        }
        reasons = automatic_rejection_reasons(
            asset,
            path_valid=True,
            file_exists=True,
        )
        asset["rejection_reasons"] = reasons
        asset["auto_select_allowed"] = not reasons
        library["assets"].append(asset)
        self.save(library)
        return {
            "status": "imported"
            if asset["auto_select_allowed"]
            else folder_type,
            "asset": asset,
            "analysis": analysis,
        }

    def import_directory(
        self,
        source_directory: str | Path,
        **metadata: Any,
    ) -> dict[str, Any]:
        directory = Path(source_directory).expanduser().resolve()
        if not directory.is_dir():
            raise MusicLibraryError(
                "SOURCE_DIRECTORY_NOT_FOUND",
                f"Music directory does not exist: {directory}",
            )
        files = sorted(
            path
            for path in directory.rglob("*")
            if path.is_file() and path.suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS
        )
        results = [self.import_file(path, **metadata) for path in files]
        return {
            "source_directory": str(directory),
            "files_considered": len(files),
            "results": results,
        }

    def analyze_all(self) -> dict[str, Any]:
        library = self.load()
        analyses: list[dict[str, Any]] = []
        for asset in _asset_dicts(library):
            path = safe_asset_path(self.root, asset.get("relative_path"))
            if path is None or not path.is_file():
                asset["quality_status"] = "failed"
                asset["auto_select_allowed"] = False
                asset["rejection_reasons"] = sorted(
                    set(_list(asset.get("rejection_reasons"))) | {"missing_asset_file"}
                )
                analyses.append(
                    {
                        "asset_id": asset.get("asset_id"),
                        "passed": False,
                        "errors": ["missing_asset_file"],
                    }
                )
                continue
            analysis = analyze_audio(
                path,
                ffprobe_binary=self.ffprobe_binary,
                ffmpeg_binary=self.ffmpeg_binary,
            )
            self._apply_analysis(asset, analysis)
            analyses.append({"asset_id": asset.get("asset_id"), **analysis})
        self._validate_assets_in_place(library)
        self.save(library)
        return {
            "assets_analyzed": len(analyses),
            "analyses": analyses,
            "passed": all(item.get("passed") for item in analyses) if analyses else True,
        }

    def validate(self) -> dict[str, Any]:
        library = self.load()
        issues = self._validate_assets_in_place(library)
        invalid_manifest = bool(library.get("invalid_manifest"))
        if invalid_manifest:
            issues.append(
                {
                    "asset_id": None,
                    "reasons": ["invalid_manifest_json"],
                }
            )
        self.save(library)
        report = {
            "version": MUSIC_LIBRARY_VERSION,
            "validated_at": utc_now_iso(),
            "manifest_path": str(self.manifest_path),
            "assets_checked": len(_asset_dicts(library)),
            "safe_automatic_assets": sum(
                1
                for item in _asset_dicts(library)
                if item.get("auto_select_allowed") is True
            ),
            "issues": issues,
            "passed": not issues,
        }
        self.write_json_report("music_validation_report.json", report)
        return report

    def find_duplicates(self) -> dict[str, Any]:
        library = self.load()
        assets = _asset_dicts(library)
        by_hash: dict[str, list[dict[str, Any]]] = {}
        for asset in assets:
            fingerprint = str(asset.get("fingerprint") or "")
            if fingerprint:
                by_hash.setdefault(fingerprint, []).append(asset)
        groups: list[dict[str, Any]] = []
        for fingerprint, members in sorted(by_hash.items()):
            if len(members) < 2:
                continue
            primary = max(members, key=_duplicate_priority)
            group_id = "dup_" + hashlib.sha256(fingerprint.encode()).hexdigest()[:12]
            for member in members:
                member["duplicate_group_id"] = group_id
                member["duplicate_primary"] = member is primary
                if member is not primary:
                    member["auto_select_allowed"] = False
                    member["rejection_reasons"] = sorted(
                        set(_list(member.get("rejection_reasons")))
                        | {"duplicate_secondary"}
                    )
            groups.append(
                {
                    "duplicate_group_id": group_id,
                    "asset_ids": [str(item.get("asset_id")) for item in members],
                    "reason": "exact_file_hash_match",
                    "recommended_primary": primary.get("asset_id"),
                }
            )
        similarity_warnings = _similarity_warnings(assets)
        self.save(library)
        report = {
            "created_at": utc_now_iso(),
            "duplicate_groups": groups,
            "similarity_warnings": similarity_warnings,
            "exact_duplicate_count": sum(len(item["asset_ids"]) - 1 for item in groups),
        }
        self.write_json_report("duplicate_report.json", report)
        return report

    def tag(
        self,
        asset_id: str,
        *,
        moods: list[str] | None = None,
        genres: list[str] | None = None,
        use_cases: list[str] | None = None,
        energy: str | None = None,
        intensity: str | None = None,
        bpm: float | None = None,
        speech_safe: bool | None = None,
        loopable: bool | None = None,
    ) -> dict[str, Any]:
        library = self.load()
        asset = _find_asset(library, asset_id)
        if moods:
            asset["mood_tags"] = sorted(
                set(_tags(asset.get("mood_tags"))) | set(_validated_tags(moods, MOOD_TAGS))
            )
        if genres:
            asset["genre_tags"] = sorted(
                set(_tags(asset.get("genre_tags"))) | set(_tags(genres))
            )
        if use_cases:
            tagged = _validated_tags(use_cases, USE_CASE_TAGS)
            asset["use_case_tags"] = sorted(
                set(_tags(asset.get("use_case_tags"))) | set(tagged)
            )
            asset["niche_tags"] = sorted(
                set(_tags(asset.get("niche_tags"))) | set(tagged)
            )
        if energy:
            asset["energy_level"] = energy_category(energy)
            asset["energy_score"] = energy_score(energy)
        if intensity:
            asset["intensity"] = intensity_category(intensity)
            asset["intensity_score"] = intensity_score(intensity)
        if bpm is not None:
            asset["bpm"] = bpm
            asset["bpm_confidence"] = "manual"
            asset["tempo_category"] = tempo_category(bpm)
        if speech_safe is not None:
            asset["speech_safe"] = speech_safe
        if loopable is not None:
            asset["loopable"] = loopable
        self._validate_assets_in_place(library)
        self.save(library)
        return asset

    def disable(self, asset_id: str, reason: str) -> dict[str, Any]:
        library = self.load()
        asset = _find_asset(library, asset_id)
        asset["safe_default"] = False
        asset["auto_select_allowed"] = False
        asset["manual_review_required"] = True
        asset["rejection_reasons"] = sorted(
            set(_list(asset.get("rejection_reasons"))) | {"manually_disabled"}
        )
        asset["warnings"] = sorted(set(_list(asset.get("warnings"))) | {reason})
        self.save(library)
        return asset

    def enable(
        self,
        asset_id: str,
        *,
        safe_default: bool,
        license_verified: bool,
    ) -> dict[str, Any]:
        if not safe_default or not license_verified:
            raise MusicLibraryError(
                "EXPLICIT_REVIEW_REQUIRED",
                "Enabling automatic use requires --safe-default and --license-verified.",
            )
        library = self.load()
        asset = _find_asset(library, asset_id)
        if normalize_license(asset.get("license")) not in ACCEPTED_LICENSES:
            raise MusicLibraryError(
                "UNSAFE_LICENSE",
                "The recorded license is not an accepted verified category.",
            )
        asset["license_verified"] = True
        asset["safe_default"] = True
        asset["manual_review_required"] = False
        asset["rejection_reasons"] = [
            item
            for item in _list(asset.get("rejection_reasons"))
            if item not in {"manually_disabled", "manual_review_required"}
        ]
        self._validate_assets_in_place(library)
        if asset.get("auto_select_allowed") is not True:
            asset["manual_review_required"] = True
            self.save(library)
            raise MusicLibraryError(
                "ASSET_NOT_SAFE",
                "The asset still fails automatic-use requirements: "
                + ", ".join(str(item) for item in _list(asset.get("rejection_reasons"))),
            )
        self.save(library)
        return asset

    def summary(self) -> dict[str, Any]:
        library = self.load()
        stats = library_stats(library)
        unregistered = self._unregistered_files(library)
        license_warnings = [
            {
                "asset_id": item.get("asset_id"),
                "reasons": [
                    reason
                    for reason in _list(item.get("rejection_reasons"))
                    if "license" in str(reason) or "attribution" in str(reason)
                ],
            }
            for item in _asset_dicts(library)
            if any(
                "license" in str(reason) or "attribution" in str(reason)
                for reason in _list(item.get("rejection_reasons"))
            )
        ]
        next_actions: list[str] = []
        if not stats["curated_assets"]:
            next_actions.append("Import verified licensed production tracks into curated.")
        if stats["missing_moods"]:
            next_actions.append(
                "Add licensed coverage for: " + ", ".join(stats["missing_moods"])
            )
        if unregistered:
            next_actions.append("Review unregistered audio files before using them.")
        report = {
            "music_library_result": (
                "PASSED"
                if stats["curated_assets"] and not license_warnings
                else "WARNING"
            ),
            **stats,
            "license_warnings": license_warnings,
            "unregistered_audio_files": unregistered,
            "recommended_next_actions": next_actions,
            "generated_assets_are_validation_quality": bool(stats["generated_assets"]),
            "created_at": utc_now_iso(),
        }
        self.write_json_report("music_library_summary.json", report)
        self.write_summary_markdown(report)
        return report

    def rejected(self) -> dict[str, Any]:
        library = self.load()
        quarantined = [
            item
            for item in _asset_dicts(library)
            if item.get("folder_type") in {"quarantine", "rejected"}
            or item.get("auto_select_allowed") is not True
        ]
        return {
            "rejected_assets": _list(library.get("rejected_assets")),
            "quarantined_or_disabled_assets": quarantined,
        }

    def write_json_report(self, filename: str, payload: dict[str, Any]) -> Path:
        self.report_root.mkdir(parents=True, exist_ok=True)
        path = self.report_root / Path(filename).name
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n",
            encoding="utf-8",
        )
        return path

    def write_import_report(self, payload: dict[str, Any]) -> Path:
        return self.write_json_report("music_import_report.json", payload)

    def write_summary_markdown(self, report: dict[str, Any]) -> Path:
        self.report_root.mkdir(parents=True, exist_ok=True)
        path = self.report_root / "music_library_summary.md"
        lines = [
            "# Music Library Summary",
            "",
            f"Result: **{report['music_library_result']}**",
            "",
            f"- Total assets: {report['total_assets']}",
            f"- Safe automatic assets: {report['safe_automatic_assets']}",
            f"- Curated production assets: {report['curated_assets']}",
            f"- Generated validation assets: {report['generated_assets']}",
            f"- User assets: {report['user_assets']}",
            f"- Quarantined assets: {report['quarantined_assets']}",
            f"- Rejected assets: {report['rejected_assets']}",
            f"- Duplicate groups: {report['duplicate_groups']}",
            "",
            "## Missing Moods",
            "",
            *[f"- {item}" for item in report["missing_moods"]],
            "",
            "## Next Actions",
            "",
            *[f"- {item}" for item in report["recommended_next_actions"]],
            "",
        ]
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def _asset_id(self, title: str, fingerprint: str) -> str:
        slug = _slug(title)[:48] or "music"
        digest = fingerprint.removeprefix("sha256:")[:10]
        return f"music_{slug}_{digest}"

    def _unique_filename(
        self,
        folder_type: str,
        title: str,
        extension: str,
        fingerprint: str,
    ) -> str:
        stem = _slug(title)[:80] or "music"
        candidate = f"{stem}{extension}"
        path = self.root / folder_type / candidate
        if not path.exists():
            return candidate
        return f"{stem}_{fingerprint.removeprefix('sha256:')[:8]}{extension}"

    def _rejected_import(
        self,
        path: Path,
        reason: str,
        *,
        warnings: list[str] | None = None,
        fingerprint: str | None = None,
    ) -> dict[str, Any]:
        return {
            "asset_id": None,
            "filename": path.name,
            "source": "local_import",
            "fingerprint": fingerprint,
            "rejection_reasons": [reason],
            "warnings": warnings or [],
            "rejected_at": utc_now_iso(),
        }

    def _apply_analysis(
        self,
        asset: dict[str, Any],
        analysis: dict[str, Any],
    ) -> None:
        for key in (
            "duration_seconds",
            "sample_rate",
            "channels",
            "codec",
            "container",
            "bitrate",
            "loudness_lufs",
            "loudness_method",
            "peak_db",
            "rms_db",
            "dynamic_range",
            "clipping_detected",
            "silence_ratio",
            "quality_status",
            "intro_seconds",
            "outro_seconds",
        ):
            asset[key] = analysis.get(key)
        if asset.get("energy_level") in {None, "unknown"}:
            asset["energy_level"] = analysis.get("energy_level")
            asset["energy_score"] = analysis.get("energy_score")
        generated_validation = (
            asset.get("folder_type") == "generated"
            and asset.get("quality_tier") == "validation_quality"
        )
        if generated_validation and asset.get("bpm_confidence") != "manual":
            asset["bpm"] = None
            asset["bpm_confidence"] = "unknown"
            asset["tempo_category"] = "unknown"
            asset["warnings"] = sorted(
                set(_list(asset.get("warnings")))
                | {
                    "Generated validation BPM is unknown because no beat analysis "
                    "was performed."
                }
            )
        elif asset.get("bpm") is None:
            asset["bpm_confidence"] = "unknown"
            asset["tempo_category"] = "unknown"
        asset["analyzed_at"] = utc_now_iso()
        asset["warnings"] = sorted(
            set(_list(asset.get("warnings")))
            | set(_list(analysis.get("warnings")))
            | set(_list(analysis.get("errors")))
        )

    def _validate_assets_in_place(
        self,
        library: dict[str, Any],
    ) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        seen_hashes: dict[str, dict[str, Any]] = {}
        for asset in _asset_dicts(library):
            path = safe_asset_path(self.root, asset.get("relative_path"))
            path_valid = path is not None
            exists = bool(path and path.is_file())
            if path is not None:
                asset["absolute_path"] = str(path)
            fingerprint = str(asset.get("fingerprint") or "")
            if fingerprint and fingerprint in seen_hashes:
                asset["duplicate_primary"] = False
                primary = seen_hashes[fingerprint]
                group_id = str(primary.get("duplicate_group_id") or "")
                if not group_id:
                    group_id = "dup_" + hashlib.sha256(
                        fingerprint.encode()
                    ).hexdigest()[:12]
                    primary["duplicate_group_id"] = group_id
                    primary["duplicate_primary"] = True
                asset["duplicate_group_id"] = group_id
            elif fingerprint:
                seen_hashes[fingerprint] = asset
            reasons = automatic_rejection_reasons(
                asset,
                path_valid=path_valid,
                file_exists=exists,
            )
            asset["rejection_reasons"] = reasons
            asset["auto_select_allowed"] = not reasons
            asset["last_validated_at"] = utc_now_iso()
            if reasons:
                issues.append(
                    {
                        "asset_id": asset.get("asset_id"),
                        "reasons": reasons,
                    }
                )
        library["stats"] = library_stats(library)
        return issues

    def _unregistered_files(self, library: dict[str, Any]) -> list[str]:
        registered = {
            str(item.get("relative_path") or "").replace("\\", "/")
            for item in _asset_dicts(library)
        }
        return sorted(
            path.relative_to(self.root).as_posix()
            for path in self.root.rglob("*")
            if path.is_file()
            and path.suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS
            and path.relative_to(self.root).as_posix() not in registered
        )


def _find_asset(library: dict[str, Any], asset_id: str) -> dict[str, Any]:
    asset = next(
        (
            item
            for item in _asset_dicts(library)
            if str(item.get("asset_id") or "") == asset_id
        ),
        None,
    )
    if asset is None:
        raise MusicLibraryError("ASSET_NOT_FOUND", f"Music asset not found: {asset_id}")
    return asset


def _asset_dicts(library: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in _list(library.get("assets")) if isinstance(item, dict)]


def _duplicate_priority(asset: dict[str, Any]) -> tuple[int, int, int, int]:
    folder_score = {"curated": 4, "user": 3, "generated": 2}.get(
        str(asset.get("folder_type") or ""),
        1,
    )
    quality_score = 2 if asset.get("quality_status") == "passed" else 1
    return (
        folder_score,
        quality_score,
        _int(asset.get("sample_rate")) or 0,
        _int(asset.get("bitrate")) or 0,
    )


def _similarity_warnings(assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for index, first in enumerate(assets):
        first_title = _slug(str(first.get("title") or first.get("filename") or ""))
        first_duration = _float(first.get("duration_seconds"))
        if not first_title or first_duration is None:
            continue
        for second in assets[index + 1 :]:
            second_title = _slug(str(second.get("title") or second.get("filename") or ""))
            second_duration = _float(second.get("duration_seconds"))
            if (
                first_title == second_title
                and second_duration is not None
                and abs(first_duration - second_duration) <= 1.0
                and first.get("fingerprint") != second.get("fingerprint")
            ):
                warnings.append(
                    {
                        "asset_ids": [first.get("asset_id"), second.get("asset_id")],
                        "reason": "same_normalized_title_and_similar_duration",
                    }
                )
    return warnings


def _validated_tags(values: list[str] | None, allowed: frozenset[str]) -> list[str]:
    return sorted({item for item in _tags(values) if item in allowed})


def _tags(value: object) -> list[str]:
    if isinstance(value, str):
        values: list[object] = [value]
    else:
        values = _list(value)
    return sorted({normalize_tag(item) for item in values if normalize_tag(item)})


def _slug(value: str) -> str:
    normalized = normalize_tag(value)
    return re.sub(r"_+", "_", normalized).strip("_")


def _last_float(pattern: str, text: str) -> float | None:
    matches = re.findall(pattern, text, flags=re.IGNORECASE)
    if not matches:
        return None
    try:
        return float(matches[-1])
    except (TypeError, ValueError):
        return None


def _resolve_binary(binary: str) -> str | None:
    resolved = shutil.which(binary)
    if resolved:
        return resolved
    path = Path(binary)
    return str(path.resolve()) if path.is_file() else None


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    try:
        return int(float(value)) if value is not None else None
    except (TypeError, ValueError):
        return None
