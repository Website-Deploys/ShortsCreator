# Analysis Signal Activation V2

## Purpose

Analysis Signal Activation V2 turns previously hardcoded missing analysis stages into a
versioned, honest signal layer. It activates deterministic local signals where Olympus already
has enough evidence and records explicit unavailable states where a dependency, model, or input
is missing.

This pass does not install models, call external APIs, identify people, or infer semantic objects
without a configured provider.

## Audit Findings

Before this pass:

- video inspection and audio extraction were real when FFmpeg was available;
- transcription was real only when a configured provider returned timestamped segments;
- speaker segmentation worked only when transcription already supplied speaker labels;
- scene detection and shot detection were hardcoded unavailable stages;
- OCR, face detection, and object detection were hardcoded unavailable stages;
- emotion timeline was hardcoded unavailable even when a transcript existed;
- no normalized audio-energy, silence, visual-region, visual-pacing, or signal-health artifact
  existed;
- Story, Planning, Editing, Virality, BOBA integration, and the frontend already referenced some
  stage artifacts, but many references received no usable data;
- the analysis pipeline and all affected stages were version `1`.

No competing signal framework or duplicate provider implementation was found.

## Signal Contract

`src/olympus/analysis/signals.py` defines:

- `AnalysisSignalStatusV1`
- `AnalysisSignalHealthV1`
- `AnalysisTimelineEventV1`
- `AnalysisTimelineSignalV1`

Allowed signal states are:

- `available`
- `partial`
- `fallback`
- `unavailable`
- `failed`
- `skipped`

Unavailable signals use a zero confidence and a reason such as `dependency_missing`,
`model_missing`, or `insufficient_input`.

## Persisted Artifact

The new `signal_health` analysis stage persists:

```text
analysis/<project_id>/stages/signal_health.json
```

Its `data.analysis_signals_v2` object contains:

- signal health counts and per-signal status;
- compact timeline events for audio energy, silence, scenes, shots, speaker turns, visual regions,
  emotion, and visual pacing;
- explicit status entries for transcript, OCR, face detection, face tracking, and object detection;
- stage references instead of duplicated transcript blobs;
- no raw frames, media bytes, identity data, or object classes invented by heuristics.

The API also exposes optional top-level `signal_health` and `analysis_signals_v2` fields. Old
projects without the new stage continue to load with those fields absent.

## Locally Activated Signals

### Audio Energy and Silence

FFmpeg continues to extract 16 kHz mono PCM audio. Olympus now computes bounded RMS windows from
that real WAV data and groups them into loud, normal, quiet, and silence-like regions.

This is an amplitude signal, not speech recognition or loudness mastering analysis.

### Scene Detection

FFmpeg performs deterministic downscaled scene-change analysis with a fixed threshold. The stage
stores only timestamps, scene scores, and scene segments.

### Shot Detection

Shot segments are derived directly from completed scene boundaries. No semantic shot classifier is
claimed.

### Visual Regions and Pacing

Low-rate FFmpeg `signalstats` brightness samples are attached to full-frame scene regions. Visual
pacing is derived from shot/cut frequency.

These signals are marked `partial` because they do not detect semantic objects and do not represent
real audience retention.

### Speaker Segmentation

The provider order is:

1. use real speaker labels supplied by transcription;
2. otherwise group transcript segments into anonymous turn regions using speech gaps;
3. otherwise derive anonymous speech regions from measured silence gaps;
4. report unavailable if none of those inputs exists.

Fallback turns are not true diarization and do not identify distinct people.

### Emotion Timeline

When transcript segments exist, Olympus combines a small explicit keyword/punctuation heuristic
with local audio energy. The result is always marked `fallback` and identifies its method as
`transcript_audio_heuristic`.

It is not facial emotion recognition, psychological inference, or model-based sentiment analysis.

## Signals Still Unavailable

In the validated local environment:

- OpenCV/face provider is absent, so face detection is unavailable;
- face tracking is unavailable because timestamped real face detections are absent;
- OCR dependencies/provider are absent, so OCR is unavailable;
- a diarization provider is absent, so only anonymous turn fallback is available;
- object-model dependencies and weights are absent, so semantic object detection is unavailable.

Olympus does not download these dependencies or model weights automatically.

## Downstream Consumers

Story, Virality, Planning, and Editing stage contexts now expose `cognitive_signal(name)`. This
returns the normalized entry even when its status is unavailable or fallback, allowing consumers to
distinguish missing evidence from empty results.

Existing consumers benefit without becoming blockers:

- Story reads the heuristic emotion timeline with its fallback method preserved;
- Planning reads real scene boundaries and anonymous speaker-turn boundaries;
- Editing reads speaker data while retaining honest diarization metadata;
- Virality momentum can blend deterministic visual pacing and audio energy at a conservative
  weight;
- the persisted artifact remains accessible through the same analysis-stage storage convention
  used by BOBA integration, without modifying BOBA Core or Memory.

Missing signals continue to produce safe `None`/unavailable behavior.

## Frontend Display

The existing Analysis Viewer now shows:

- available, partial, fallback, unavailable, and failed counts;
- each normalized signal and its status;
- the first honest warning or unavailable reason;
- stage progress using the wording “analysis stages completed” rather than “signals understood.”

The UI does not claim that the video was fully understood.

## Versioning

- analysis pipeline version: `2`
- audio extraction: `2`
- speaker segmentation: `2`
- scene detection: `2`
- shot detection: `2`
- OCR availability: `2`
- face detection availability: `2`
- object detection availability: `2`
- emotion timeline: `2`
- knowledge graph: `2`
- signal health: `1`

Loading an old project adds the missing stage slot and updates the pipeline version. Completed
affected stages rerun because their analyzer versions changed.

## Validator

Environment/dependency check:

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_analysis_signals.py --self-check
```

Temporary synthetic FFmpeg pipeline:

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_analysis_signals.py --synthetic
```

Inspection-only existing project check:

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_analysis_signals.py `
  --project-id PROJECT_ID
```

Reports are written under:

```text
work/validation_reports/analysis_signals/
  analysis_signals_report.json
  analysis_signals_summary.md
```

Reports and temporary synthetic media are not source artifacts and must not be committed.

## Limitations

- Scene detection uses a fixed local threshold and may need tuning for unusual footage.
- Shot boundaries are scene-derived rather than model-classified.
- Brightness is sampled at low rate and represents the full frame.
- Speaker fallback does not prove who spoke.
- Emotion fallback is a transparent heuristic, not ground truth.
- Face tracking remains unproven without a configured provider and rights-cleared sample.
- OCR remains unproven without a configured OCR provider.
- Object detection remains unavailable without a configured model and weights.
- This pass does not claim release readiness.
