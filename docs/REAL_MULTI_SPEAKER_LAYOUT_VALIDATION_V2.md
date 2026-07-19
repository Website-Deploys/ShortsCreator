# Real Multi-Speaker Layout Validation V2

## Purpose

This validator measures whether Olympus can plan and render multi-speaker layouts without unstable
framing, subject cutoff, unsupported active-speaker claims, or dishonest metadata. It hardens the
existing Multi-Speaker Layout V2 path; it does not add a new layout engine or creative style.

Reports contain numeric metrics and truth flags only. Raw frames, face images, names, identity data,
and biometric embeddings are never persisted.

## Current Pipeline Audit

- `SpeakerSegmentationAnalyzer` only converts speaker labels already supplied by transcription into
  timeline segments. It does not perform diarization itself.
- `CropPlannerAnalyzer` normalizes anonymous face boxes and calls
  `build_multi_speaker_layout` with face tracks and any available speaker timeline.
- Two stable faces with no reliable speaker association use `two_speaker_stack` when the natural
  source frame cannot preserve both subjects safely.
- Active-speaker focus is allowed only when diarized segments map uniquely to anonymous visible
  tracks. Minimum holds and switch hysteresis prevent rapid switching.
- Missing or low-confidence face signals produce an explicit `center_fallback` reason.
- The renderer uses two independent crop expressions followed by FFmpeg `vstack` for stack mode.
- Render metadata records planned/applied modes, expected/rendered regions, expected/rendered
  switches, dimensions, sync, duration, warnings, and pass/fail truth.
- Existing production logic did not calculate region coverage, subject cutoff, or layout jitter
  metrics. This validator adds those metrics without changing production behavior.
- Production face detection remains unavailable. Speaker signals are also unavailable unless the
  configured transcription provider supplies diarized speaker labels.

## Validation Modes

Run commands from `D:\Olympus` with the existing virtual environment.

### Self-check

```powershell
.\.venv\Scripts\python.exe tools\validate_multi_speaker_layout.py --self-check
```

Checks module/config imports, FFmpeg, FFprobe, report safety, and optional local OpenCV availability.
No media or external access is required.

### Synthetic two-speaker

```powershell
.\.venv\Scripts\python.exe tools\validate_multi_speaker_layout.py `
  --synthetic-two-speaker
```

The compatibility alias `--synthetic` is also accepted. The tool generates two moving speaker-like
geometric shapes with alternating visual activity and local audio, creates anonymous track boxes,
plans a two-region stack, renders through the existing FFmpeg command builder, validates the MP4,
and deletes temporary media.

It also runs a planning-only active-speaker probe with alternating anonymous visibility and speaker
segments. This verifies switch planning separately from the primary stack render.

Synthetic mode always reports:

- `real_multi_speaker_sample_used=false`
- `synthetic_sample_used=true`
- `real_multi_speaker_proof=false`

Synthetic success cannot be cited as real multi-speaker proof.

### Local multi-speaker file

```powershell
.\.venv\Scripts\python.exe tools\validate_multi_speaker_layout.py `
  --local-multi-speaker-file D:\rights-cleared\two-speaker.mp4 `
  --confirm-rights
```

The path must be an explicitly supplied absolute local video. URLs, file URIs, network paths,
generated dependency folders, and unsupported extensions are rejected. Rights confirmation is
mandatory. The source is not copied into the repo, uploaded, or committed.

When optional local OpenCV is available, the tool samples one frame at a time, discards each frame
immediately, sends only anonymous normalized boxes into the existing tracker/layout planner, renders
a short temporary stack when two stable subjects are available, and writes numeric metrics.

Direct local-file mode has no standalone diarizer. It therefore does not claim active-speaker truth.
If face detection is unavailable or two stable subjects are not found, it fails honestly and records
the selected fallback or non-multi-speaker strategy.

### Existing project inspection

```powershell
.\.venv\Scripts\python.exe tools\validate_multi_speaker_layout.py `
  --project-id PROJECT_ID
```

Inspects canonical and legacy editing/render artifacts without rerendering or repairing them. It
checks signal availability, planned/applied strategy, region and switch counts, fallback honesty,
referenced MP4 existence, and H.264/AAC stream validity. Raw detections are not reprocessed, so
subject cutoff cannot be independently recomputed in this mode.

Legacy `--simulate`, `--face-artifact`, and `--rendered-file` modes remain available for existing QA
and tests.

## Metrics

`MultiSpeakerLayoutValidationResultV1` includes:

- `speaker_region_coverage_ratio`: average fraction of expected regions present across sampled
  frames. Default minimum: `0.95`.
- `face_inside_region_ratio`: fraction of anonymous subject boxes inside their assigned effective
  crop safe zone. Default minimum: `0.90`.
- `subject_cutoff_detected`: true when a subject box crosses its effective crop boundary.
- `layout_jitter_score`: average normalized crop-center displacement across layout regions. Default
  maximum: `0.08`.
- `max_region_shift_per_second`: largest time-normalized crop-center movement. Default maximum:
  `0.22`.
- `active_speaker_switches`: genuine focus changes only; repeated labels are not counted.
- `wrong_speaker_focus_warnings`: active-focus or render-truth contradictions.
- `fallback_used` and `fallback_reason`: explicit fallback truth when signals are insufficient.
- `render_completed` and `output_mp4_valid`: require a real temporary MP4 with H.264 video, AAC
  audio, expected dimensions, and duration within `0.15` seconds.

Thresholds are deterministic validator limits, not new production editing policy.

## Pass and Fail Meaning

- **Self-check pass** means the validator can run. It proves no media behavior.
- **Synthetic pass** means two independent crops and the stack renderer produced a valid MP4 with
  bounded numeric safety metrics. It does not prove real people or real diarization.
- **Local-file pass** means two anonymous subject tracks produced a safe stack and valid temporary
  MP4. Active-speaker quality remains unproven without diarization.
- **Project inspection pass** means persisted plan/render truth and referenced media are internally
  consistent. It does not redo visual analysis.

Failures stay visible in `errors`; unavailable signals never become successful metadata-only claims.

## Reports

Reports are written only under:

```text
work/validation_reports/multi_speaker_layout/
```

Each mode writes `multi_speaker_layout_validation_<mode>.json`. The writer rejects destinations
outside `work/validation_reports` and rejects raw image, frame, identity, or biometric payloads.
Generated reports and temporary media must not be committed.

## Limitations

This validation does not prove:

- real multi-speaker quality when only synthetic mode ran;
- music quality or audibility;
- face identity recognition;
- human creative taste;
- release readiness.

Without a rights-cleared real two-speaker sample, real multi-speaker proof is not yet available.
