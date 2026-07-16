"""Generate original validation-quality Music Intelligence V2 starter beds.

No network request is made. The generated harmonic beds are deliberately simple,
instrumental, and marked as validation assets rather than production music.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from olympus.music.library import (  # noqa: E402
    MusicLibraryManager,
    energy_category,
    file_fingerprint,
    intensity_category,
)

PROFILES: tuple[dict[str, Any], ...] = (
    {
        "asset_id": "music_v2_motivational_drive",
        "title": "Validation Motivational Drive",
        "filename": "motivational_drive.wav",
        "frequencies": (110, 220, 330),
        "bpm": 120,
        "key": "A",
        "moods": ["motivational", "inspirational", "intense"],
        "genres": ["cinematic", "electronic", "inspirational"],
        "niches": ["motivational", "business_money", "self_improvement"],
        "energy": 0.76,
        "intensity": 0.70,
        "gain": -18.0,
    },
    {
        "asset_id": "music_v2_emotional_bed",
        "title": "Validation Emotional Bed",
        "filename": "emotional_bed.wav",
        "frequencies": (82, 164, 246),
        "bpm": 82,
        "key": "E",
        "moods": ["emotional", "cinematic", "hopeful"],
        "genres": ["ambient", "cinematic", "piano"],
        "niches": ["emotional_story", "relationship_life_advice"],
        "energy": 0.34,
        "intensity": 0.32,
        "gain": -23.0,
    },
    {
        "asset_id": "music_v2_educational_focus",
        "title": "Validation Educational Focus",
        "filename": "educational_focus.wav",
        "frequencies": (98, 196, 294),
        "bpm": 98,
        "key": "G",
        "moods": ["focused", "calm", "neutral"],
        "genres": ["ambient", "minimal", "lofi"],
        "niches": ["education_tutorial", "podcast_interview", "tech_ai"],
        "energy": 0.42,
        "intensity": 0.34,
        "gain": -23.0,
    },
    {
        "asset_id": "music_v2_playful_energy",
        "title": "Validation Playful Energy",
        "filename": "playful_energy.wav",
        "frequencies": (130, 260, 390),
        "bpm": 120,
        "key": "C",
        "moods": ["playful", "light", "energetic"],
        "genres": ["playful", "light_electronic"],
        "niches": ["entertainment_comedy", "reaction"],
        "energy": 0.64,
        "intensity": 0.55,
        "gain": -20.0,
    },
    {
        "asset_id": "music_v2_cinematic_tension",
        "title": "Validation Cinematic Tension",
        "filename": "cinematic_tension.wav",
        "frequencies": (73, 146, 219),
        "bpm": 90,
        "key": "D",
        "moods": ["cinematic", "mysterious", "intense"],
        "genres": ["ambient", "cinematic", "minimal"],
        "niches": ["news_commentary", "debate_argument", "serious_story"],
        "energy": 0.48,
        "intensity": 0.46,
        "gain": -23.0,
    },
    {
        "asset_id": "music_v2_gaming_energy",
        "title": "Validation Gaming Energy",
        "filename": "gaming_energy.wav",
        "frequencies": (140, 280, 420),
        "bpm": 140,
        "key": "F#",
        "moods": ["intense", "energetic", "playful"],
        "genres": ["electronic", "pulse"],
        "niches": ["gaming_stream", "reaction"],
        "energy": 0.86,
        "intensity": 0.80,
        "gain": -18.0,
    },
)


def _run(args: list[str]) -> None:
    subprocess.run(args, check=True, capture_output=True)


def _generate(path: Path, frequencies: tuple[int, int, int], *, force: bool) -> None:
    if path.exists() and not force:
        return
    inputs: list[str] = []
    for frequency in frequencies:
        inputs.extend(
            [
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency={frequency}:duration=36:sample_rate=48000",
            ]
        )
    _run(
        [
            "ffmpeg",
            "-y",
            *inputs,
            "-filter_complex",
            (
                "[0:a]volume=0.080[a0];[1:a]volume=0.040[a1];[2:a]volume=0.022[a2];"
                "[a0][a1][a2]amix=inputs=3:normalize=0,lowpass=f=3600,"
                "highpass=f=45,loudnorm=I=-18:TP=-2:LRA=7,aresample=48000,"
                "alimiter=limit=0.85"
            ),
            "-c:a",
            "pcm_s16le",
            str(path),
        ]
    )


def _measure_loudness(path: Path) -> tuple[float | None, float | None]:
    completed = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-i",
            str(path),
            "-af",
            "loudnorm=I=-18:TP=-2:LRA=7:print_format=json",
            "-f",
            "null",
            "NUL",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    output = completed.stderr or ""
    start, end = output.rfind("{"), output.rfind("}")
    if completed.returncode != 0 or start < 0 or end <= start:
        return None, None
    try:
        measured = json.loads(output[start : end + 1])
        return float(measured["input_i"]), float(measured["input_tp"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None, None


def install(root: Path, *, force: bool = False) -> dict[str, Any]:
    root = root.resolve()
    music_root = root / "music"
    generated = music_root / "generated"
    manager = MusicLibraryManager(music_root)
    library = manager.initialize()
    existing = {
        str(item.get("asset_id") or ""): item
        for item in library.get("assets", [])
        if isinstance(item, dict)
    }
    now = datetime.now(UTC).isoformat()
    for profile in PROFILES:
        path = generated / str(profile["filename"])
        _generate(path, profile["frequencies"], force=force)
        loudness, peak = _measure_loudness(path)
        existing[str(profile["asset_id"])] = {
            "asset_id": profile["asset_id"],
            "title": profile["title"],
            "filename": profile["filename"],
            "relative_path": f"generated/{profile['filename']}",
            "absolute_path": str(path.resolve()),
            "folder_type": "generated",
            "duration_seconds": 36.0,
            "sample_rate": 48000,
            "channels": 1,
            "codec": "pcm_s16le",
            "container": "wav",
            "bitrate": 768000,
            "bpm": None,
            "bpm_confidence": "unknown",
            "key": profile["key"],
            "key_confidence": "generated_profile",
            "mood_tags": profile["moods"],
            "energy_level": energy_category(profile["energy"]),
            "energy_score": profile["energy"],
            "intensity": intensity_category(profile["intensity"]),
            "intensity_score": profile["intensity"],
            "tempo_category": "unknown",
            "genre_tags": profile["genres"],
            "use_case_tags": profile["niches"],
            "niche_tags": profile["niches"],
            "loopable": True,
            "loop_points": [],
            "has_vocals": False,
            "vocal_confidence": "generated_profile",
            "instrumental": True,
            "speech_safe": True,
            "license": "project_generated_safe",
            "license_url": None,
            "license_summary": (
                "Original harmonic validation bed generated locally by Project Olympus."
            ),
            "license_verified": True,
            "source_url": None,
            "rights_holder": "Project Olympus",
            "attribution_required": False,
            "attribution_text": None,
            "safe_default": True,
            "auto_select_allowed": True,
            "manual_review_required": False,
            "source": "generated_validation_asset",
            "created_at": now,
            "imported_at": None,
            "analyzed_at": now,
            "last_validated_at": now,
            "quality_status": "passed",
            "quality_tier": "validation_quality",
            "recommended_gain_db": profile["gain"],
            "loudness_lufs": loudness,
            "loudness_method": "ffmpeg_loudnorm_measurement",
            "peak_db": peak,
            "rms_db": None,
            "dynamic_range": None,
            "clipping_detected": bool(peak is not None and peak >= -0.1),
            "silence_ratio": None,
            "fingerprint": file_fingerprint(path),
            "duplicate_group_id": None,
            "duplicate_primary": None,
            "usage_count": 0,
            "last_used_at": None,
            "rejection_reasons": [],
            "warnings": [
                "Generated starter asset for validation, not curated production music.",
                "BPM is intentionally unknown because no beat analysis was performed.",
            ],
        }
    library["assets"] = sorted(
        existing.values(),
        key=lambda item: str(item.get("asset_id") or ""),
    )
    library["warnings"] = sorted(
        set(library.get("warnings") or [])
        | {
            "Generated assets are validation quality; import verified curated music "
            "for production output."
        }
    )
    manager.save(library)
    return library


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("assets"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    manifest = install(args.root, force=args.force)
    print(
        json.dumps(
            {
                "manifest": str((args.root / "music" / "music_manifest.json").resolve()),
                "asset_count": len(manifest["assets"]),
                "quality": "validation_quality",
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
