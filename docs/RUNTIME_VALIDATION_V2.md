# Olympus Runtime Validation V2

Use this pass to validate Olympus with real local videos on Windows. Do not run
the backend with `--reload` during full validation because artifact writes can
trigger reload loops.

## Put Videos Here

Recommended folder:

```powershell
D:\Olympus\validation_samples
```

Recommended samples:

- single-face talking video, 1-3 min
- podcast/two-speaker video, 5-10 min
- medium video, 10-20 min
- long video, 30+ min
- stream/video, 60+ min if available

Supported extensions: `.mp4`, `.mov`, `.mkv`, `.webm`, `.m4v`.

## Run Backend

```powershell
D:\Olympus\.venv\Scripts\python.exe -m uvicorn olympus.api.app:app --app-dir src
```

## Run Frontend

```powershell
cd D:\Olympus\frontend
npm run dev
```

## Discover Samples

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_real_video_flow.py --discover --samples-dir D:\Olympus\validation_samples
```

If no videos are found, the tool writes an honest report with
`real_video_validation=false` and instructions for where to place files.

## Validate All Samples

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_real_video_flow.py --samples-dir D:\Olympus\validation_samples --report-dir D:\Olympus\work\validation_reports
```

## Validate One File

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_real_video_flow.py --file D:\Olympus\validation_samples\my_video.mp4
```

## Useful Modes

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_real_video_flow.py --smoke
D:\Olympus\.venv\Scripts\python.exe tools\validate_real_video_flow.py --tier short
D:\Olympus\.venv\Scripts\python.exe tools\validate_real_video_flow.py --long
```

## Reports

Default output folder:

```powershell
D:\Olympus\work\validation_reports
```

Files written:

- `validation_report.json`: top-level run summary
- `validation_summary.md`: readable summary
- `per_video_report.json`: one report per source video
- `per_clip_report.json`: one report per rendered clip
- `ffprobe_outputs.json`: raw/media validation facts
- `timings.json`: stage timing summary
- `warnings.json`: warnings collected across the run

## Pass/Fail Signals

The validator checks:

- sample discovery and duration tier
- upload/intake/project creation
- stage status and timings
- stale stage-version warnings
- planned vs rendered clip counts
- long-video timeline coverage
- render manifest presence
- rendered file download
- `ffprobe` duration, resolution, codecs, audio stream, sample rate
- sync and duration deltas
- `unified_clip_intelligence`
- payload fields that power “Why this clip works”

## Common Failures

- **No videos found**: place files in `D:\Olympus\validation_samples`.
- **Backend unavailable**: start the backend command above without `--reload`.
- **FFmpeg/ffprobe missing**: install FFmpeg and ensure it is on PATH.
- **Transcription timeout**: check model/runtime setup and stage timings.
- **No clips planned**: inspect `low_output_reason`.
- **Render failed**: inspect rendering stage details and FFmpeg logs.
- **Frontend empty output**: verify render manifest and planning payload exist.
- **Sync validation failed**: inspect per-clip `ffprobe_validation`.

## Honesty Rules

- Do not claim real-video validation passed unless a real file was processed.
- Do not claim long-video validation passed unless a real 30+ minute file was processed.
- Do not claim audio/video sync passed unless `ffprobe` validation passed.
- Manual playback is separate from automated validation; report it explicitly.
