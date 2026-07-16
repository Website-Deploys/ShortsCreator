"""Install a safe local Editing V2 starter asset pack.

This tool does not download copyrighted sounds. It generates a small original
set of quiet background beds and simple SFX with FFmpeg lavfi sources, then
writes a manifest with license/attribution metadata so Olympus can mix them
honestly during local validation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _run(args: list[str]) -> None:
    subprocess.run(args, check=True, capture_output=True)


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _asset(
    *,
    asset_id: str,
    filename: str,
    kind: str,
    categories: list[str],
    recommended_gain_db: float,
    notes: str,
    sfx_type: str | None = None,
    quality: str = "starter_generated",
    noise_like: bool = False,
    safe_default: bool = True,
) -> dict[str, Any]:
    item = {
        "id": asset_id,
        "filename": filename,
        "type": kind,
        "categories": categories,
        "tags": categories,
        "source_url": "generated://olympus/editing-assets/v1",
        "license": "CC0-1.0",
        "attribution": "Generated locally by Project Olympus using FFmpeg lavfi sources.",
        "downloaded_at": datetime.now(UTC).isoformat(),
        "usage_allowed": True,
        "recommended_gain_db": recommended_gain_db,
        "quality": quality,
        "notes": notes,
    }
    if kind == "sfx":
        item.update(
            {
                "sfx_type": sfx_type or categories[0],
                "noise_like": noise_like,
                "safe_default": safe_default,
            }
        )
    return item


def _music(root: Path, filename: str, frequencies: tuple[int, int, int]) -> None:
    path = root / filename
    if path.exists():
        return
    a, b, c = frequencies
    _run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={a}:duration=90:sample_rate=44100",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={b}:duration=90:sample_rate=44100",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={c}:duration=90:sample_rate=44100",
            "-filter_complex",
            (
                "[0:a]volume=0.10[a0];[1:a]volume=0.055[a1];[2:a]volume=0.032[a2];"
                "[a0][a1][a2]amix=inputs=3:normalize=0,"
                "lowpass=f=4200,afade=t=in:st=0:d=1.5,afade=t=out:st=88:d=2"
            ),
            "-c:a",
            "pcm_s16le",
            str(path),
        ]
    )


def _sfx(root: Path, filename: str, expression: str) -> None:
    path = root / filename
    if path.exists():
        return
    _run(["ffmpeg", "-y", "-f", "lavfi", "-i", expression, "-c:a", "pcm_s16le", str(path)])


def install(root: Path) -> dict[str, Any]:
    music_dir = root / "music"
    sfx_dir = root / "sfx"
    for folder in (music_dir, sfx_dir, root / "fonts", root / "overlays", root / "licenses"):
        folder.mkdir(parents=True, exist_ok=True)

    _music(music_dir, "motivational_cinematic_bed.wav", (110, 220, 440))
    _music(music_dir, "educational_focus_bed.wav", (98, 196, 392))
    _music(music_dir, "energetic_pulse_bed.wav", (130, 260, 520))

    _sfx(
        sfx_dir,
        "impact_01.wav",
        "sine=frequency=72:duration=0.32:sample_rate=44100,afade=t=out:st=0.18:d=0.14",
    )
    _sfx(
        sfx_dir,
        "whoosh_01.wav",
        (
            "sine=frequency=420:duration=0.42:sample_rate=44100,"
            "afade=t=in:st=0:d=0.05,afade=t=out:st=0.20:d=0.22,lowpass=f=1200"
        ),
    )
    _sfx(
        sfx_dir,
        "pop_01.wav",
        "sine=frequency=880:duration=0.12:sample_rate=44100,afade=t=out:st=0.05:d=0.07",
    )
    _sfx(
        sfx_dir,
        "riser_01.wav",
        (
            "sine=frequency=330:duration=0.8:sample_rate=44100,"
            "afade=t=in:st=0:d=0.12,afade=t=out:st=0.56:d=0.24"
        ),
    )

    assets = [
        _asset(
            asset_id="music_motivational_cinematic_bed",
            filename="music/motivational_cinematic_bed.wav",
            kind="music",
            categories=["motivational", "cinematic", "dramatic", "high_aura"],
            recommended_gain_db=-17,
            notes=(
                "Generated quiet harmonic bed for local validation; replace with a "
                "human music library for production."
            ),
        ),
        _asset(
            asset_id="music_educational_focus_bed",
            filename="music/educational_focus_bed.wav",
            kind="music",
            categories=["educational", "calm", "podcast", "talking_head"],
            recommended_gain_db=-20,
            notes="Generated subtle bed intended to sit behind speech.",
        ),
        _asset(
            asset_id="music_energetic_pulse_bed",
            filename="music/energetic_pulse_bed.wav",
            kind="music",
            categories=["energetic", "stream", "entertainment", "high-energy"],
            recommended_gain_db=-16,
            notes="Generated brighter bed for high-energy validation.",
        ),
        _asset(
            asset_id="sfx_impact_01",
            filename="sfx/impact_01.wav",
            kind="sfx",
            categories=["impact", "bass_hit", "low_boom", "subtle_hit"],
            recommended_gain_db=-10,
            sfx_type="soft_impact",
            notes="Generated low hit for hook/payoff accents.",
        ),
        _asset(
            asset_id="sfx_whoosh_01",
            filename="sfx/whoosh_01.wav",
            kind="sfx",
            categories=["whoosh", "swoosh", "transition_sweep", "zoom"],
            recommended_gain_db=-18,
            sfx_type="clean_whoosh",
            notes="Generated sine-envelope whoosh for movement accents.",
        ),
        _asset(
            asset_id="sfx_pop_01",
            filename="sfx/pop_01.wav",
            kind="sfx",
            categories=["pop", "click", "subtle_tick", "caption"],
            recommended_gain_db=-15,
            sfx_type="subtle_pop",
            notes="Generated short pop for caption/text accents.",
        ),
        _asset(
            asset_id="sfx_riser_01",
            filename="sfx/riser_01.wav",
            kind="sfx",
            categories=["riser", "reverse_riser", "reveal"],
            recommended_gain_db=-20,
            sfx_type="gentle_riser",
            notes="Generated simple riser for reveal moments.",
        ),
    ]
    for item in assets:
        path = root / str(item["filename"])
        item["sha256"] = _sha256(path)
        item["size_bytes"] = path.stat().st_size

    manifest = {
        "version": "1",
        "generated_at": datetime.now(UTC).isoformat(),
        "notes": (
            "Starter assets are generated locally, CC0, and safe for local demos. "
            "They are intentionally simple; replace with curated licensed music/SFX for production."
        ),
        "assets": assets,
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("assets"))
    args = parser.parse_args()
    manifest = install(args.root)
    print(
        f"Installed {len(manifest['assets'])} generated Editing V2 assets "
        f"at {args.root.resolve()}"
    )


if __name__ == "__main__":
    main()
