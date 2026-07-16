# Curated Music Library Tool V2

The Curated Music Library Tool manages local music that feeds the existing Music
Intelligence V2 selector. It imports user-provided files, records license truth,
inspects audio quality with FFmpeg/FFprobe, quarantines unsafe entries, detects
duplicates, and reports library coverage.

It does not download or scrape music from YouTube, Spotify, TikTok, Instagram,
SoundCloud, or any streaming platform. It does not bypass DRM, login, membership,
commercial restrictions, attribution, or copyright. Olympus never infers that a local
file is legally usable.

## Folder Structure

```text
assets/music/
  music_manifest.json
  generated/   locally generated validation beds
  curated/     verified licensed production assets
  user/        known local assets awaiting full verification
  quarantine/  missing/unknown license or manual-review assets
  rejected/    reserved for explicitly rejected library files
  reports/     JSON and Markdown library reports
```

Files in `generated` are starter assets. They remain usable for testing but are not
presented as curated production music. Existing generated files are preserved during
manifest migration.

## Initialize

```powershell
cd D:\Olympus
.\.venv\Scripts\python.exe tools\manage_music_library.py --init
```

Initialization creates missing folders and safely migrates the previous flat manifest
to the `music_library_v2` contract. Invalid JSON is reported and is not overwritten.

## Import

Import one local file:

```powershell
.\.venv\Scripts\python.exe tools\manage_music_library.py `
  --import-file "D:\Music\track.wav" `
  --title "Track Name" `
  --license "CC0" --license-verified `
  --source "User provided" `
  --mood motivational --use-case motivational_speech `
  --energy medium_high --intensity balanced `
  --instrumental --speech-safe --loopable
```

Import a licensed folder with shared metadata:

```powershell
.\.venv\Scripts\python.exe tools\manage_music_library.py `
  --import-dir "D:\Music\licensed_pack" `
  --license "user_licensed" --license-verified `
  --source "User provided licensed pack" `
  --mood cinematic --use-case cinematic_tension `
  --energy medium --instrumental --speech-safe
```

Supported formats are `.wav`, `.mp3`, `.m4a`, `.aac`, `.flac`, and `.ogg`.
The source file is never modified or deleted. Olympus copies a validated file into the
library with a normalized, collision-safe name. The tool does not inspect legal
documents or infer rights; `--license-verified` must only be supplied when accurate.

## License Rules

Accepted categories:

- `project_generated_safe`
- `user_owned`
- `user_licensed`
- `CC0`
- `public_domain`
- `royalty_free_verified`
- `custom_verified`

Unsafe or nonautomatic categories include `unknown`, `unverified`,
`copyrighted_unknown`, `streaming_platform_rip`, `no_license`, and
`personal_use_only`.

Automatic selection requires an existing file under `assets/music`, an accepted
license, `license_verified=true`, non-empty source metadata,
`safe_default=true`, `quality_status=passed`, `speech_safe=true`, mood and energy
metadata, no missing attribution text, and no duplicate-secondary status.

Missing or unknown licenses go to quarantine. Known but unverified licenses remain in
the user tier. Attribution-required entries without attribution text remain disabled.
Commercial or platform restrictions are surfaced as rejection reasons.

## Audio Analysis

```powershell
.\.venv\Scripts\python.exe tools\manage_music_library.py --analyze
```

FFprobe reads duration, sample rate, channel count, codec, container, and bitrate.
FFmpeg `ebur128`, `astats`, and `silencedetect` provide integrated loudness, peak,
RMS, dynamic range, clipping risk, silence ratio, lightweight energy classification,
and a conservative loopability hint.

The preferred automatic-use duration is 8 seconds to 10 minutes. Extreme loudness,
severe clipping, excessive silence, unreadable media, zero duration, or unavailable
loudness analysis requires review or rejects the asset.

BPM, musical key, and vocals are not guessed. BPM remains null with confidence
`unknown` unless supplied with `--bpm`. Vocal presence remains unknown unless tagged
with `--instrumental` or `--has-vocals`. An unknown vocal state is not speech-safe by
default.

## Tag and Review

```powershell
.\.venv\Scripts\python.exe tools\manage_music_library.py `
  --tag ASSET_ID --mood emotional --use-case podcast_bed `
  --energy low --intensity subtle --bpm 82 --speech-safe --loopable

.\.venv\Scripts\python.exe tools\manage_music_library.py `
  --disable ASSET_ID --reason "too repetitive"

.\.venv\Scripts\python.exe tools\manage_music_library.py `
  --enable ASSET_ID --safe-default --license-verified
```

Enable requires both explicit flags and still fails unless every automatic-use rule
passes. Editing JSON manually is not required.

## Duplicate Detection

```powershell
.\.venv\Scripts\python.exe tools\manage_music_library.py --find-duplicates
```

Exact SHA-256 matches form a duplicate group. The primary preference is curated,
then verified user, then generated, followed by passing quality, sample rate, and
bitrate. Secondary exact duplicates cannot be automatically selected. Matching
normalized title plus duration within one second is reported as a similarity warning,
not silently treated as an exact duplicate.

Music Intelligence combines persistent `usage_count` with per-render/project usage to
penalize repetition.

## Reports

```powershell
.\.venv\Scripts\python.exe tools\manage_music_library.py --summary
.\.venv\Scripts\python.exe tools\manage_music_library.py --validate
```

Generated files:

- `assets/music/reports/music_library_summary.json`
- `assets/music/reports/music_library_summary.md`
- `assets/music/reports/music_import_report.json`
- `assets/music/reports/music_validation_report.json`
- `assets/music/reports/duplicate_report.json`

The summary reports safe automatic assets, curated/generated/user/quarantine counts,
mood coverage, missing moods, license warnings, duplicates, unregistered files, and
recommended next actions.

## Music Intelligence Integration

For an exact requested mood, Music Intelligence prioritizes:

1. verified curated production assets;
2. verified user assets;
3. generated validation assets;
4. no music when no safe asset exists.

`music_library_selection` records the manifest version, pool size, curated/generated
availability, selected tier, rejected count, and honest selection reason. The frontend
shows source tier, quality, license status, and a warning when a generated validation
bed is used because no curated match exists.

## Limitations

- No production curated music is bundled.
- The user must supply legally usable local music and accurate license metadata.
- Generated beds remain validation-quality.
- No streaming-platform import or downloader exists.
- Audio analysis is deterministic and lightweight; it is not source separation,
  vocal ML, beat tracking, or subjective listening review.
- Audibility and speech intelligibility still require manual listening for subjective
  confirmation.
