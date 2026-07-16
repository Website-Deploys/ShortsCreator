# Music Intelligence V2

Music Intelligence V2 chooses whether a Short should use background music, builds a
speech-first mix plan, selects only verified local assets, renders that plan with
FFmpeg, and preserves honest validation metadata through the output gallery.

## Scope and Safety

Music Intelligence V2 does not download songs, scrape YouTube, Spotify, TikTok, or
Instagram, bypass licensing, identify commercial songs, or claim generated starter
assets are production-quality music.

Automatic selection requires every asset to have all of the following:

- an existing file below the configured asset root;
- a non-empty `license`;
- `license_verified: true`;
- `safe_default: true`;
- `usage_allowed` not set to false;
- no unsafe vocal-under-speech conflict.

Assets with unknown or unverified licenses remain visible to validation tools but are
never selected automatically.

## Pipeline

1. Editing reads Story, Virality, Trend Research, Planning, transcript timing, and user
   settings.
2. `music_intelligence_v2` decides whether music helps and creates mood, energy, tempo,
   fade, ducking, hook, and payoff guidance.
3. Rendering loads the local registry and scores safe assets for mood, energy, tempo,
   speech safety, duration, license, niche, trend fit, library tier, quality, and reuse.
4. FFmpeg trims or loops the asset, applies fades and a subtle payoff swell, ducks it
   from the speech sidechain, and mixes with `amix=duration=first`.
5. FFprobe confirms output audio, duration, and audio/video stream timing.
6. Render metadata and `unified_clip_intelligence` explain what was planned, selected,
   mixed, skipped, and validated.

The duration-safe filter choices follow the official FFmpeg documentation for
[`afade`, `sidechaincompress`, `amix`, and `loudnorm`](https://ffmpeg.org/ffmpeg-filters.html).
Container and stream inspection follows the official
[`ffprobe` documentation](https://ffmpeg.org/ffprobe.html).

## Asset Registry

The canonical manifest is:

```text
assets/music/music_manifest.json
```

Supported folders are:

```text
assets/music/generated
assets/music/curated
assets/music/user
assets/music/quarantine
assets/music/rejected
assets/music/reports
```

The manifest is rooted at `music_library_v2`. The registry derives the absolute path
from `relative_path` and never trusts a manifest path outside `assets/music`.
Required automatic-use fields include:

```json
{
  "asset_id": "licensed_focus_bed",
  "relative_path": "curated/licensed_focus_bed.wav",
  "folder_type": "curated",
  "title": "Licensed Focus Bed",
  "duration_seconds": 90.0,
  "bpm": 100,
  "bpm_confidence": "manual",
  "key": "C",
  "mood_tags": ["focused", "calm"],
  "use_case_tags": ["education_focus", "podcast_bed"],
  "energy_level": "medium_low",
  "energy_score": 0.42,
  "intensity": "subtle",
  "genre_tags": ["ambient", "minimal"],
  "niche_tags": ["education_tutorial", "podcast_interview"],
  "loopable": true,
  "has_vocals": false,
  "speech_safe": true,
  "license": "CC0-1.0",
  "license_url": "https://license.example/record",
  "license_verified": true,
  "safe_default": true,
  "auto_select_allowed": true,
  "manual_review_required": false,
  "quality_status": "passed",
  "source": "User provided licensed pack",
  "created_at": "2026-07-11T00:00:00Z",
  "quality_tier": "production_curated",
  "fingerprint": "sha256:...",
  "usage_count": 0,
  "recommended_gain_db": -23.0,
  "warnings": []
}
```

For a user-provided asset, record the user's permission or license in the manifest and
set `license_verified` only after that record has been checked. Unknown-license files
must stay `safe_default: false`.

## Curated Library Manager

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\manage_music_library.py --init
D:\Olympus\.venv\Scripts\python.exe tools\manage_music_library.py --list
D:\Olympus\.venv\Scripts\python.exe tools\manage_music_library.py --summary
D:\Olympus\.venv\Scripts\python.exe tools\manage_music_library.py --validate
D:\Olympus\.venv\Scripts\python.exe tools\manage_music_library.py --analyze
D:\Olympus\.venv\Scripts\python.exe tools\manage_music_library.py --find-duplicates
```

Import only a local file the user is legally allowed to process:

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\manage_music_library.py `
  --import-file "D:\Music\licensed-track.wav" `
  --title "Licensed Track" --license "CC0" --license-verified `
  --source "User provided" --mood motivational --energy medium_high `
  --instrumental --speech-safe
```

Missing, unknown, or unsafe licenses are quarantined and never automatically selected.
Known but unverified assets remain in the user tier with manual review required.

## Decision Rules

- Motivational, business, and self-improvement clips prefer `motivational_drive`.
- Emotional stories prefer `emotional_bed`.
- Podcast/interview clips prefer `subtle_bed`.
- Education/tutorial clips prefer `educational_focus`.
- Gaming/stream clips prefer `gaming_energy`.
- Comedy/entertainment clips prefer `playful_energy`.
- News/debate/commentary clips use restrained `cinematic_tension`.
- Singing or music-performance clips disable background music by default.
- User-disabled, very short, unlicensed, missing, or otherwise unsafe cases render no
  background music and persist the reason.
- Matching verified curated assets outrank user and generated assets.
- Generated assets are an honest validation-quality fallback when no curated or
  verified user mood match exists.

## Mixing and Validation

Voice remains the primary stream. Music gain is bounded by configuration and content
role. Speech-heavy clips use FFmpeg `sidechaincompress` with conservative attack and
release values. Both speech and music are padded/trimmed to the planned duration before
`amix`, so music cannot shorten the clip. Global `-shortest` is not used.

`music_mixed: true` means FFmpeg received a resolved music input and completed the
render with output audio. The current validator does not isolate the music contribution
from the mixed waveform and does not run speech recognition after mixing. Therefore:

- audibility is reported as `not_verified`;
- speech clarity is reported as `not_verified`;
- sync, duration, output-audio presence, license safety, and graph execution are
  validated separately.

This distinction prevents metadata from claiming subjective listening quality.

## Starter Assets

Generate six local validation-quality instrumental beds:

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\install_music_assets.py
```

These assets are generated locally from simple harmonic FFmpeg sources and are marked
`generated_validation_asset` with `project_generated_safe` license metadata. They are
starter assets only. Production output should use curated music with verified licenses.

## Validation CLI

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_music_intelligence.py --list-assets
D:\Olympus\.venv\Scripts\python.exe tools\validate_music_intelligence.py --analyze-assets
D:\Olympus\.venv\Scripts\python.exe tools\validate_music_intelligence.py --simulate --niche motivational --story-shape pain_transformation
D:\Olympus\.venv\Scripts\python.exe tools\validate_music_intelligence.py --rendered-file path\clip.mp4 --manifest path\manifest.json
D:\Olympus\.venv\Scripts\python.exe tools\validate_music_intelligence.py --project-id PROJECT_ID
```

## Frontend

Each rendered clip card shows whether music was used, mood, role, selected track, gain,
ducking, reason, license status, validation status, and warnings. The “Why this clip
works” section includes the music decision reason.

## Limitations

- No copyrighted catalogue or internet music provider is integrated.
- Generated beds are validation-quality, not production-quality.
- Existing source music detection is not available; conflict risk is reported unknown.
- BPM and musical-key values come from verified manifest metadata, not runtime beat
  detection.
- The manager leaves BPM, key, and vocal confidence unknown unless supplied manually
  or explicitly recorded by a trusted source.
- Simple looping is duration-safe but does not claim beat-level seam analysis.
- Audibility and intelligibility require waveform-isolation analysis or manual listening
  before they can be marked verified.
- Audio energy and loopability are lightweight FFmpeg-derived hints, not ML judgments.
