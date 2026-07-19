# Long-Video Full Render Proof V2

## Purpose

`tools/validate_long_video_full_render.py` is a production-hardening validator for the
complete local Olympus durable workflow. It proves that a genuinely long source can travel
through ingestion, analysis, story, virality, planning, editing, rendering, optimization,
and final payload inspection without bypassing the renderer.

The validator extends the existing long-video validation contract and reuses the same local
durable runtime used by Real Rendering E2E Validation V2. It does not create a parallel
production pipeline.

## What It Proves

A passing synthetic or local-file run proves all of the following for that exact run:

- FFprobe measured the source at or above the configured minimum duration.
- Every durable workflow stage completed and persisted its expected artifact.
- `analysis_signals_v2` exists in the completed analysis artifact.
- Planning produced the requested minimum number of distinct clip plans.
- Editing produced matching timelines.
- The production FFmpeg renderer produced real MP4 files with audio and video.
- The canonical manifest exists at `render/<project_id>/run/index.json`.
- Every accepted MP4 passes FFprobe, duration, and A/V-delta checks.
- Optimization packages every accepted rendered clip.
- Final API/frontend-compatible payload inspection exposes downloadable clips.
- Exact and near-duplicate source intervals are rejected.
- No FFmpeg resource-exhaustion signature was observed.

## What It Does Not Prove

- A synthetic pass is not proof against real creator footage, variable frame rates, camera
  codecs, real speech, or noisy audio.
- The deterministic transcript fixture does not test transcription accuracy or alignment to
  the generated tone track.
- It does not prove music quality, face detection, OCR, object detection, or multi-speaker
  editorial quality.
- It does not claim release readiness, virality, or peak-memory safety for every machine.
- It does not use YouTube, external downloads, cloud APIs, copyrighted media, or private
  user media.

## Synthetic-Long Mode

Synthetic mode generates a genuine local MP4 whose default duration is 30 minutes. The
source uses a 640x360, bounded 30-fps, low-entropy H.264 picture with simple section markers and a
locally generated AAC tone. FFprobe, not metadata supplied by the validator, decides the
source duration.

The deterministic transcript fixture contains timestamped segments over the full source
duration and several spaced setup/tension/turn/payoff patterns. The real Story, Virality,
Planning, Editing, Rendering, and Optimization services consume those persisted artifacts.

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_long_video_full_render.py --synthetic-long
D:\Olympus\.venv\Scripts\python.exe tools\validate_long_video_full_render.py --synthetic-long --minutes 30 --min-clips 3
```

An optional stricter run requests at least five clips:

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_long_video_full_render.py --synthetic-long --minutes 30 --min-clips 5
```

Generated media and reports stay under `work/validation_reports/long_video_full_render/`.
They are validation artifacts and must not be committed.

## Local-File Mode

Local-file mode accepts only a path already present on the machine. The caller must own or
have permission to process the file. The validator never downloads media and never copies
the original into the repository; normal project ingestion stores the source in configured
Olympus storage for the validation project.

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_long_video_full_render.py --local-file D:\path\rights-cleared.mp4 --min-clips 3
```

The default minimum is 30 minutes. A shorter development fixture is rejected unless the
caller explicitly lowers `--minimum-minutes`. A lowered threshold is development evidence,
not a real long-video proof.

## Project Inspection Mode

Project mode reads existing project, workflow, engine, manifest, package, and MP4 artifacts.
It never starts, repairs, retries, or rerenders the project.

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_long_video_full_render.py --project-id PROJECT_ID
```

Missing source media, stage artifacts, manifests, MP4s, or packages are reported as failures
with their expected storage paths.

## Self-Check

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_long_video_full_render.py --self-check
```

Self-check verifies FFmpeg, FFprobe, writable storage/report roots, workflow imports, render
manifest resolution, optimization repository availability, and the fact that no external
access is required. It does not claim a pipeline or render success.

## Pass and Fail Criteria

The default proof requires:

1. Source duration of at least 1,800 seconds by FFprobe.
2. Completed ingestion, analysis, story, virality, planning, editing, rendering, and
   optimization durable jobs.
3. All stage artifacts present.
4. At least three planned, rendered, accepted, and optimized clips.
5. A canonical render manifest and optimization index.
6. Valid audio/video streams, positive duration, and A/V delta at or below 0.15 seconds for
   every accepted MP4.
7. Matching edited, rendered, and optimized clip identities.
8. A JSON-safe final payload with one download URL per rendered clip.
9. No exact duplicate or at-least-95-percent overlapping source interval.
10. No resource-exhaustion marker or stale render work files.

If only one clip is produced, the report contains:

`long-video multi-clip proof not satisfied`

Overlaps above 80 percent are reported. Overlaps at or above 95 percent fail as
near-duplicates.

## Multi-Clip Behavior

The planner already builds transcript-backed windows across the full duration and applies
candidate de-duplication and timeline diversity. Editing creates one repaired timeline per
approved plan. Rendering processes timelines sequentially. Each clip is rendered once for
preview and once at full 1080x1920 output, and the temporary previews are removed by the
normal cleanup stage.

The validator compares:

- planned IDs to edited timeline IDs,
- edited IDs to rendered IDs,
- accepted rendered IDs to optimized package IDs,
- source intervals for exact and high overlap,
- repeated hook lines for warnings.

## Resource and Time Reporting

The JSON report records:

- wall-clock pipeline runtime,
- durable per-stage start, finish, and duration,
- preview/full render runtime per clip,
- observed renderer FFmpeg invocation count,
- inferred analysis FFmpeg invocation count,
- maximum simultaneous render calls and sequential/parallel status,
- output size per clip and total output bytes,
- render work-key cleanup,
- bounded FFmpeg stderr tails on failure,
- resource-exhaustion signatures.

The validator does not install a process-memory sampler. Reports state exactly:

`peak RAM not measured`

## Reports

The validator writes:

- `work/validation_reports/long_video_full_render/long_video_full_render_report.json`
- `work/validation_reports/long_video_full_render/long_video_full_render_summary.md`
- `work/validation_reports/long_video_full_render/long_video_full_render_project_inspection_report.json`
- `work/validation_reports/long_video_full_render/long_video_full_render_project_inspection_summary.md`
- `work/validation_reports/long_video_full_render/long_video_full_render_self_check.json`

The report contract is `LongVideoFullRenderResultV1` in
`src/olympus/validation/long_video.py`.

## Validated Synthetic Run

On 2026-07-19, the default proof command completed for project
`proj_68dfe2bbb080475c9afc7941326d6879`:

- FFprobe source duration: 1,800.0 seconds.
- Planned, edited, rendered, accepted, and optimized clips: 6 each.
- Output: 1080x1920 H.264 video with AAC 48 kHz audio for all six clips.
- Maximum absolute A/V delta: 0.017 seconds.
- Canonical render manifest, optimization manifest, and final payload: valid.
- Exact/severe duplicate source intervals: none.
- Pipeline runtime excluding source generation: 279.487 seconds.
- Synthetic source generation runtime: 79.709 seconds.
- Durable rendering stage runtime: 254.834 seconds.
- Renderer FFmpeg invocations: 12 (six preview and six full-resolution), maximum one
  concurrent invocation.
- Render temporary storage cleanup: passed.
- Resource exhaustion: not detected.
- Peak RAM: not measured.
- Manual playback: not performed; validation used persisted manifests and FFprobe evidence.

The run used deterministic synthetic transcript guidance and low-entropy generated media.
It is synthetic long-video proof only, not real creator-footage or release-readiness proof.

## Known Limitations

- Synthetic video is deliberately low entropy and does not represent difficult real footage.
- The generated tone is not speech, so the full-duration transcript is deterministic fixture
  guidance rather than an STT result.
- FFmpeg process counting is exact for source generation and renderer invocations; analysis
  FFmpeg count is inferred from completed analysis stages because those subprocesses do not
  expose a shared observer.
- Peak RAM is not measured.
- Local-file proof depends on the machine, source codec, storage capacity, and rights-cleared
  media supplied by the operator.
