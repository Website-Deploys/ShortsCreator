# Real Rendering End-to-End Validation V2

## Purpose

This validator proves whether a local Olympus project can traverse the real durable workflow from ingestion through optimization and produce downloadable, FFprobe-valid MP4 files. It is a validation utility, not a production engine or release-readiness badge.

## Meaning of “Real Rendering End-to-End”

The local synthetic mode performs these operations through the existing Olympus services:

1. Generates an original local MP4 with FFmpeg.
2. Stores it through `IntakeService`.
3. Creates a normal project through `ProjectService`.
4. Starts the durable `WorkflowService` graph.
5. Runs analysis, story, virality, planning, editing, rendering, and optimization.
6. Validates workflow checkpoints and persisted artifacts.
7. Reads the same rendering and optimization contracts used by the API and frontend.
8. Verifies every referenced MP4 with FFprobe.

The analysis stage uses a deterministic validator-only transcript adapter. The adapter supplies timestamped fixture text after the real audio-extraction stage succeeds. This keeps the run local and repeatable; it does not test speech-recognition accuracy.

## What It Validates

- Every durable workflow stage reaches `completed`.
- The rendering checkpoint resolves to `render/<project_id>/run/index.json`.
- The canonical render manifest parses and references existing MP4 files.
- MP4 files are non-trivial, inside the storage root, and free of incomplete temporary outputs.
- FFprobe sees H.264 video, AAC audio, 1080x1920 output, valid duration, and an A/V stream delta within 0.15 seconds.
- Repaired timeline, boundary-quality, and caption metadata are present.
- Optimization starts after a valid rendering checkpoint.
- `optimization/<project_id>/index.json` and publish packages exist.
- Optimized MP4 package assets resolve to real rendered files.
- API response schemas serialize the final project, render, manifest, and optimization entities.
- Frontend-facing manifest fields and clip download URLs are available.
- BOBA, upload, and safety metadata availability is reported without being fabricated.

## What It Does Not Validate

- Viral or editorial quality judged by a person.
- Manual playback quality.
- Speech-recognition accuracy.
- Music taste or music audibility by human listening.
- Face-tracking or multi-speaker visual quality.
- Real user-video behavior in synthetic mode.
- YouTube or video-link ingestion.
- External APIs or internet services.
- Overall release readiness.

## Why Synthetic Local Media

The generated source is original, deterministic, private-data-free, and independent of network access. It contains a simple moving visual marker, timed color markers, and a modulated voice-like tone. The low-entropy visual design avoids making CPU-only H.264 validation artificially expensive. The fixture lasts 60 seconds, while its deterministic transcript fixture contains one complete short story in the opening 8 seconds. This exercises the normal production render settings while keeping local validation bounded and avoiding copyrighted or user-sensitive media.

## FFmpeg Resource Safety

The first real synthetic run (`proj_aa17947810324dabad7b69eb9e8f6b0b`) exposed a renderer bug rather than a fixture-size problem. A timed `zoompan` filter already emitted 30 FPS, but the graph appended a second `fps=30` filter. On the fixture's 1/15360 video time base, that second conversion expanded an expected 240-frame, 8-second clip to 122,880 frames (512 times too many). Caption rendering over that amplified stream eventually ended with FFmpeg exit `4294967284` (signed `-12`) and Windows `WinError 1450` resource exhaustion.

The renderer now lets `zoompan` own the frame rate and adds a separate FPS filter only when zoom is absent. The validator also uses a bounded local profile by default: `veryfast` x264, two encoder threads, one filter/filter-complex thread, and the existing render timeout. Production renderer defaults remain `medium` with FFmpeg-managed thread counts unless explicitly configured.

FFmpeg runs with status spam disabled and stderr redirected to a temporary file. Olympus retains only the last 40 lines from the last 128 KiB, so worker memory does not grow with subprocess output. Failures preserve the stage name, sanitized command summary, bounded stderr tail, normalized return code, and an explicit resource hint. Temporary clip files remain scoped to `TemporaryDirectory` and are removed on failed renders.

## Commands

Run a fresh local synthetic pipeline:

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_real_rendering_e2e.py --local-synthetic
```

The bounded defaults can be adjusted for diagnostics with `--render-preset`, `--render-threads`, and `--render-filter-threads`. Increasing them may raise local CPU and memory use; the default command is the recommended validation profile.

Inspect an existing project without rerendering:

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_real_rendering_e2e.py --project-id PROJECT_ID
```

Run the pipeline with an explicitly selected safe local file:

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_real_rendering_e2e.py --local-file PATH_TO_VIDEO
```

Local-file mode still uses the deterministic validator transcript and reports that the source may be user media. Only use media you are permitted to process.

## Reports

Reports are written only beneath:

```text
work/validation_reports/real_rendering_e2e/
```

Files:

- `real_rendering_e2e_report.json`
- `real_rendering_e2e_summary.md`

Generated media, storage artifacts, downloads, and reports remain ignored and must not be committed.

## Pass and Fail Meaning

`passed=true` means this specific local run completed every durable stage, produced at least one valid rendered clip, passed canonical checkpoint and optimization handoff checks, and exposed complete API/frontend-facing data. Any missing stage, stale-only manifest, invalid MP4, missing required metadata, blocked optimization, or unavailable download makes the run fail.

A passing synthetic report is evidence of pipeline mechanics only. It is not evidence of human playback quality, creative excellence, or production release readiness.

## Known Limitations

- The transcript is deterministic fixture data rather than recognition of the generated tone.
- FFprobe validates stream structure and timing, not perceived quality.
- Downloadability is validated through the same storage key and route contract; no browser is opened.
- Optional BOBA, upload, and safety metadata may be unavailable and are reported as warnings.
- The durable workflow can complete while the older project lifecycle field remains `analyzed`; the validator reports that status and validates final API data from persisted workflow, render, and optimization artifacts.
- Runtime depends on local FFmpeg performance and can be lengthy on CPU-only hosts.
- FFmpeg nonzero exits or operating-system resource exhaustion remain hard failures. The validator reports bounded diagnostics and never downgrades them to a pass.
