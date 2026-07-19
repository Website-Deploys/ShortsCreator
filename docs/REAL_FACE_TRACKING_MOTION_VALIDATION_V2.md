# Real Face Tracking and Motion Validation V2

## Purpose

This validator measures whether Olympus face crop plans are stable, safe, honestly reported, and
compatible with rendered motion. It is a validation and hardening tool; it does not add a creative
motion style or replace the editing/rendering pipeline.

The validator uses the existing Olympus flow:

1. Anonymous normalized detections are consolidated by
   `olympus.editing.multi_speaker.build_multi_speaker_layout`.
2. The resulting face/layout plan gates `build_motion_intelligence`.
3. The existing FFmpeg command builder consumes crop keyframes and motion events.
4. FFprobe validates the temporary rendered MP4.

Reports contain numeric metrics and truth flags only. Raw frames, face images, identity data, and
biometric embeddings are not persisted.

## Current Audit Findings

- `CropPlannerAnalyzer` produces `face_tracking_plan` / `multi_speaker_layout_v2` metadata.
- Face tracks use anonymous IDs, confidence filtering, bounded interpolation, a dead zone, and a
  confidence-weighted exponential moving average.
- The renderer consumes stable keyframes through a dynamic FFmpeg crop expression. Two-speaker
  stack plans use independent crops and `vstack`.
- Motion is disabled when face or layout safety cannot be established. Two-speaker stack currently
  disables additional motion rather than risking unsafe framing.
- Render manifests distinguish planned face tracking from `face_tracking_applied` truth.
- The production `FaceDetectionAnalyzer` is currently an unavailable model stage. No OpenCV or
  other local detector dependency is declared by the base package.
- Therefore synthetic fallback proves fallback/render safety only. Real face tracking is not proven
  without an explicit rights-cleared local face file and an available local OpenCV runtime.

## Validation Modes

Run commands from `D:\Olympus` with the existing virtual environment.

### Self-check

```powershell
.\.venv\Scripts\python.exe tools\validate_face_tracking_motion.py --self-check
```

Checks module imports, motion/layout configuration, FFmpeg, FFprobe, report safety, and whether the
optional local OpenCV detector is available. OpenCV absence is a limitation warning, not a failure
of self-check.

### Synthetic fallback

```powershell
.\.venv\Scripts\python.exe tools\validate_face_tracking_motion.py --synthetic-fallback
```

Generates a moving face-like geometric shape and audio entirely with FFmpeg. It deliberately passes
no face detections, requires `center_fallback`, applies a bounded motion event, renders a temporary
MP4, and validates codec/stream/duration truth. Temporary media is deleted.

This mode always reports:

- `real_face_sample_used=false`
- `face_tracking_available=false`
- `real_face_proof=false`

It must never be cited as real face tracking proof.

### Local face file

```powershell
.\.venv\Scripts\python.exe tools\validate_face_tracking_motion.py `
  --local-face-file D:\rights-cleared\sample.mp4 `
  --confirm-rights
```

The path must be an explicit absolute local video path. URLs, file URIs, network paths, generated
dependency folders, and unsupported extensions are rejected. `--confirm-rights` is mandatory. The
tool does not discover nearby media, copy the source into the repo, upload it, or identify anyone.

When the optional local OpenCV runtime is available, the tool samples one frame at a time, emits
only anonymous normalized boxes to the existing Olympus tracker, discards each frame immediately,
builds crop/motion plans, renders a short temporary clip, and records metrics. OpenCV Haar confidence
is a validation-only planning heuristic and is not identity recognition.

If OpenCV and the production face detector are unavailable, this mode fails honestly and reports
that real face tracking was not proven.

### Existing project inspection

```powershell
.\.venv\Scripts\python.exe tools\validate_face_tracking_motion.py `
  --project-id PROJECT_ID
```

Inspects canonical and legacy editing/render artifacts without rerendering or repairing the project.
It verifies plan/applied/fallback consistency, motion metadata, referenced MP4 existence, and FFprobe
codec/stream truth. Because source frames are not reprocessed, project inspection does not assume
that a real face sample was used and cannot independently recompute face cutoff metrics.

## Metrics

The `FaceMotionValidationResultV1` contract includes:

- `tracking_coverage_ratio`: sampled frames containing one or more detections divided by successful
  sampled frames. The real-file pass threshold is `0.60`.
- `face_inside_safe_zone_ratio`: evaluated boxes fully inside the effective crop after safe margins
  and bounded motion zoom. The default pass threshold is `0.90`.
- `jitter_score`: mean normalized crop-center displacement between adjacent keyframes. The default
  maximum is `0.08`.
- `max_crop_shift_per_second`: largest normalized crop-center shift divided by elapsed keyframe time.
  The default maximum is `0.22`.
- `face_cutoff_detected`: true when a box crosses the effective crop boundary beyond tolerance.
- `center_fallback_used`: required when no usable face track exists.
- `render_completed` and `output_mp4_valid`: require a real temporary MP4 with H.264 video, AAC
  audio, expected dimensions, and duration within `0.15` seconds.

Thresholds live in `FaceMotionValidationThresholdsV1`. They are deterministic validation limits,
not new production editing policy.

## Pass and Fail Meaning

- **Self-check pass** means the local validator can run. It does not prove face tracking.
- **Synthetic fallback pass** means fallback plus bounded motion rendered safely. It does not prove
  face detection or tracking.
- **Local face pass** requires detection coverage, renderable keyframes, safe crop metrics, bounded
  jitter/shift, a real motion filter, and a valid temporary MP4.
- **Project inspection pass** means persisted metadata and the referenced MP4 are internally
  consistent. It does not establish real media provenance or redo visual analysis.

Failures remain visible in `errors` and never become successful metadata-only claims.

## Reports

Reports are written only under:

```text
work/validation_reports/face_tracking_motion/
```

Each mode writes `face_motion_validation_<mode>.json`. Reports are ignored generated artifacts and
must not be committed. The writer rejects report destinations outside `work/validation_reports` and
rejects raw image, frame, identity, embedding, or biometric payloads.

## Limitations

This validator does not prove:

- music quality or audibility;
- multi-speaker editorial quality;
- identity recognition (Olympus does not perform it here);
- human editorial taste;
- release readiness;
- real face tracking when only self-check or synthetic fallback ran.

The local Haar detector is optional and validation-only. Production face detection remains
unavailable until a separately reviewed, privacy-safe detector is configured in the analysis stage.
