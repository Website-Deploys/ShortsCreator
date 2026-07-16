# Olympus Long-Video Validation V2

`tools/validate_long_video.py` validates real long-form sources and existing
Olympus projects without changing the production pipeline. It reuses Olympus's
existing API, stage artifacts, render manifests, FFmpeg, and FFprobe contracts.

The tool never claims a 30+ minute, planning, render, sync, metadata, or frontend
success unless that specific work was observed. Synthetic smoke checks are
marked as synthetic and never count as real-video validation.

## What It Validates

- supported local media discovery and duration classification
- source metadata with FFprobe
- manual-upload projects and existing projects
- link-project provenance with `--from-link`
- Story, Virality, Planning, Editing, Rendering, and Optimization stage status
- total timeout, per-stage timeout, and no-progress conditions
- expected clip count and structured `low_output_reason`
- candidate and selected-clip coverage across the full source timeline
- duplicate ranges, excessive overlap, hook/story repetition, and bucket diversity
- downloaded MP4 resolution, codecs, audio, sample rate, sync, and duration
- stale engine-stage versions that can explain pre-V2 artifacts
- Story/Trend/Music/Captions/Motion/Layout metadata survival
- `unified_clip_intelligence` and output-card data
- JSON and Markdown reports with an actionable next command

## What It Does Not Validate

- It does not prove that a clip is viral.
- It does not replace manual playback, listening, or editorial review.
- Metadata-only and smoke modes do not run Story, Planning, Editing, or Rendering.
- Planning-only mode does not claim render success.
- Filename content labels are hints only and are reported as `filename_only`.
- Existing-project mode does not download and probe the original source unless a
  local `--file` is supplied; it uses persisted project metadata honestly.
- It does not require Docker, WSL, paid APIs, or internet access.

## Sample Folders

Discovery searches these folders by default:

```text
D:\Olympus\validation_samples
D:\Olympus\samples
D:\Olympus\test_media
D:\Olympus\media
D:\Olympus\work\validation_samples
```

Supported extensions are `.mp4`, `.mov`, `.mkv`, `.webm`, and `.m4v`.

Recommended filenames can include `podcast`, `interview`, `stream`, `gaming`,
`motivational`, `speech`, `music`, `two_speaker`, or `multi_speaker`. These labels
help organize reports; they are not content-analysis claims.

## Duration Classes

| Source duration | Report classification | Expected clips |
| --- | --- | --- |
| under 3 minutes | `short_under_3min` | 1-5 |
| 3-10 minutes | `medium_3_to_10min` | 2-8 |
| 10-30 minutes | `long_10_to_30min` | 3-12 |
| 30-60 minutes | `long_30_to_60min` | 5-20 |
| 60-120 minutes | `very_long_60_to_120min` | 8-30 |
| over 120 minutes | `stream_over_120min` | 10-40 |

The ranges are sanity checks, not forced output counts. A lower count can pass
when Planning persists a detailed `low_output_reason` with evidence. One clip
from a long video without that explanation is a failure.

CLI tier filters are `smoke`, `10min`, `30min`, `60min`, `90min`, `120min`, and
`stream`. The 60- and 90-minute filters split the 60-120 minute report class for
sample selection; 120-minute and stream filters select 120+ minute sources.

## Backend

Planning, full-pipeline, existing-project, and link-project validation use the
local API. Run it without `--reload`; long artifact writes can otherwise trigger
reload loops.

```powershell
cd D:\Olympus
.\.venv\Scripts\python.exe -m uvicorn olympus.api.app:app --app-dir src --host 127.0.0.1 --port 8000
```

An unreachable local process is reported as `LOCAL_BACKEND_UNAVAILABLE`, not as
an internet or package-network failure.

## Commands

Discover and classify samples:

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_long_video.py --discover
```

Probe one file without running the backend pipeline:

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_long_video.py --file D:\Olympus\validation_samples\long_video.mp4 --metadata-only
```

Run a fast source/environment smoke check:

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_long_video.py --file D:\Olympus\validation_samples\long_video.mp4 --smoke
```

Validate intelligence through Planning while avoiding render work:

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_long_video.py --file D:\Olympus\validation_samples\long_video.mp4 --planning-only --timeout-seconds 7200
```

Olympus engines auto-chain. Planning-only polls Planning at a one-second maximum
interval, then cancels any auto-started Editing, Rendering, or Optimization work.
If downstream state already appeared, the report says so. It never reports that
rendering was skipped when a downstream engine actually started.

Run the complete pipeline and probe every downloaded MP4:

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_long_video.py --file D:\Olympus\validation_samples\long_video.mp4 --full-pipeline --timeout-seconds 7200
```

Validate an existing project without starting missing work:

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_long_video.py --project-id PROJECT_ID
```

Continue an existing project through Planning or Rendering:

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_long_video.py --project-id PROJECT_ID --planning-only
D:\Olympus\.venv\Scripts\python.exe tools\validate_long_video.py --project-id PROJECT_ID --full-pipeline
```

Require link-ingestion provenance:

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_long_video.py --project-id PROJECT_ID --from-link
```

Validate a folder or a 30-60 minute tier:

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_long_video.py --samples-dir D:\Olympus\validation_samples --metadata-only
D:\Olympus\.venv\Scripts\python.exe tools\validate_long_video.py --samples-dir D:\Olympus\validation_samples --tier 30min --planning-only
```

Tune policy and watchdogs:

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_long_video.py `
  --file D:\Olympus\validation_samples\long_video.mp4 `
  --full-pipeline `
  --timeout-seconds 7200 `
  --stage-timeout-seconds 1800 `
  --poll-interval-seconds 10 `
  --min-clips 5 `
  --max-clips 20 `
  --require-rendered-clips
```

The validator is deliberately non-destructive: it never deletes a source,
project, or protected artifact. Reports and downloaded render evidence remain in
the report directory. `--keep-artifacts` is accepted to make that retention
intent explicit; no automatic project cleanup occurs with or without it.

## Planning-Only vs Full Pipeline

Planning-only checks:

- source/project metadata
- Analysis, Story, Virality, Trend, and Planning artifacts
- planned clip count and `low_output_reason`
- candidate and selected timeline coverage
- clip range, hook, story, and bucket diversity
- planning-stage unified intelligence

It does not claim an MP4, frontend gallery, caption render, music mix, motion
effect, or layout was produced.

Full-pipeline mode additionally waits for Rendering and Optimization to reach a
terminal state, downloads each manifest MP4, probes the real bytes, and validates
render metadata and the frontend payload contract.

## Timeline Coverage

The report counts candidates and selected clip starts in five buckets:

- `0-10%`
- `10-25%`
- `25-50%`
- `50-75%`
- `75-100%`

It flags all selections in the first 10%, no selection in the second half,
candidate concentration, analyzed duration under 90%, and transcript duration
under 90%. A planning explanation is preserved beside the warning but does not
silently erase the measured coverage condition.

## Diversity

The validator reports:

- any overlapping ranges
- near-identical ranges within one second
- ranges with at least 80% overlap
- hook-pattern diversity
- story-pattern diversity
- timeline-bucket diversity
- repeated music-asset warnings
- an aggregate diversity score

Repeated caption or motion styles are not automatically failures. They become
warnings only when the available metadata indicates inappropriate repetition.

## Timeouts and Stalls

Defaults:

- total timeout: 7200 seconds
- stage timeout: 1800 seconds
- poll interval: 10 seconds
- planning-only maximum poll interval: 1 second

Possible error codes include:

- `STAGE_TIMEOUT_ANALYSIS`
- `STAGE_TIMEOUT_TRANSCRIPTION`
- `STAGE_TIMEOUT_STORY`
- `STAGE_TIMEOUT_VIRALITY`
- `STAGE_TIMEOUT_PLANNING`
- `STAGE_TIMEOUT_RENDERING`
- `PIPELINE_STALLED`
- `NO_PROGRESS`
- `LOCAL_BACKEND_UNAVAILABLE`
- `PROJECT_NOT_FOUND`

The report includes the last observed stage, real stage timestamps, validator
wall-clock time, and the backend monitoring `/system` payload when available.

## Render Validation

Each manifest clip is downloaded from the real render endpoint and checked for:

- existing, non-empty bytes
- 1080x1920 output
- H.264 video
- AAC audio when audio exists
- 48 kHz preferred sample rate
- positive video duration/frame estimate
- audio/video delta at or below 0.15 seconds
- planned/container duration delta at or below 0.15 seconds
- caption, layout, and existing render-truth validation failures

If download or FFprobe fails, metadata alone cannot pass the clip.

## Metadata and Frontend Payload

For the furthest available clip contract, the tool checks:

- Story V2
- Virality V2
- Trend Research V2 or honest fallback
- Music Intelligence V2
- Curated Music Library selection metadata
- Captions/Typography V2
- Motion Graphics V2
- Multi-Speaker Layout V2
- `unified_clip_intelligence`
- fields used by “Why this clip works”

For rendered clips it also verifies that each clip ID can form the real download
route and that the output-card payload contains unified Story/Virality/Planning
reasoning. This is payload validation, not a browser screenshot test.

## Reports

The default directory is:

```text
D:\Olympus\work\validation_reports\long_video
```

Files:

- `long_video_validation_report.json`: complete machine-readable evidence
- `long_video_validation_summary.md`: concise operator summary and next command

Important JSON sections are `source_video`, `stage_timings`, `planning`,
`clip_count_validation`, `timeline_coverage`, `clip_diversity`, `rendered_clips`,
`intelligence_metadata`, `frontend_payload`, `runtime_metrics`, and `result`.

## Common Failures

- `NO_SAMPLES`: put a supported file in `D:\Olympus\validation_samples`.
- `SOURCE_PROBE_FAILED`: verify that the file is real media and FFprobe can read it.
- `LOCAL_BACKEND_UNAVAILABLE`: start Uvicorn with the command in the report.
- `PROJECT_NOT_FOUND`: verify the project ID and storage root.
- low clip count: inspect `planning.clip_count_validation.low_output_reason`.
- early bias: inspect candidate and selected bucket maps.
- duplicate ranges: inspect `planning.clip_diversity.duplicate_ranges`.
- render failure: inspect each clip's `validation_details`, warnings, and errors.
- metadata drop: inspect `intelligence_metadata.per_clip` to locate the missing layer.
- stale artifacts: inspect `artifact_version_warnings`, then rerun the affected project stages.
- empty frontend payload: verify manifest renders and planning plans share IDs.

## Practical Limits

- Full 60-120+ minute runs can take hours and need substantial disk space.
- Runtime depends on transcription hardware, source codec, candidate count, and render count.
- The validator measures behavior; it does not increase production resource limits.
- A real 30+ minute success must come from a real 30+ minute run. A shorter file,
  synthetic smoke, or metadata-only probe is not evidence of long-video support.
- Manual playback and listening remain required before claiming editorial quality.
