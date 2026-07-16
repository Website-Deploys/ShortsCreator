# Multi-Speaker Layout V2

Multi-Speaker Layout V2 converts timestamped face detections and optional diarized
speaker labels into stable, anonymous vertical layouts that FFmpeg actually renders.

## Privacy and Identity

Olympus does not recognize people, infer names, compare faces against external data, or
persist biometric identities. `face_track_1`, `face_track_2`, and similar IDs are local
temporal tracks for one clip only.

Speaker labels originate only from diarized transcript segments. A speaker is associated
with a face track only when the diarized interval has one uniquely visible stable track.
This is temporal visibility evidence, not lip-sync analysis or biometric identity.

## Layout Modes

- `single_face_tracking`: one stable face drives a smoothed dynamic crop.
- `two_speaker_stack`: two independently cropped 1080x960 regions are combined into a
  1080x1920 top/bottom layout.
- `active_speaker_focus`: diarized turns with unique face associations drive stable crop
  switches with minimum holds and hysteresis.
- `multi_face_safe_frame`: three or more stable participants use a group-safe crop rather
  than a tiny grid.
- `natural_frame_preserved`: both faces already fit safely in a vertical composition.
- `center_fallback`: detections or layout geometry are insufficient.

## Track Consolidation

Detections are matched across nearby timestamps using overlap, normalized center
distance, size consistency, motion prediction, confidence, and optional upstream
temporal-ID hints. Low-confidence jumps are rejected. Short gaps are held and bounded;
incoming IDs are never treated as real-world identity.

## Two-Speaker Stack

Each participant receives independent normalized crop keyframes. The renderer trims the
source once, splits that video stream, crops and scales each branch to 1080x960, and uses
`vstack` to produce 1080x1920. The existing source audio is not split: one speech stream
continues through the existing voice, music, SFX, ducking, loudness, sync, and duration
graph.

## Active-Speaker Policy

Active-speaker focus requires:

- diarized speaker segments;
- unique temporal speaker-to-face associations;
- association confidence above configuration;
- meaningful speaker-segment duration;
- switch hysteresis and a maximum switch rate.

Face size alone never produces an active-speaker claim.

## Rendering and Timing

The layout branch preserves the existing safeguards:

- video `trim` and `setpts=PTS-STARTPTS`;
- audio `atrim` and `asetpts=PTS-STARTPTS`;
- explicit padding and duration trims;
- one mapped master audio stream;
- no global `-shortest`;
- existing captions, motion, enhancement, music, and SFX processing.

`multi_speaker_validation.applied=true` is written only after FFmpeg successfully uses a
renderable non-fallback layout. Stack mode reports two rendered regions. Active-speaker
mode reports only switches present in the rendered crop plan.

## Configuration

Settings use the `OLYMPUS_MULTI_SPEAKER_LAYOUT__...` environment prefix. Important
controls include confidence and coverage thresholds, minimum speaker hold, switch
hysteresis, missing-detection hold, interpolation gap, crop movement limits, and maximum
switches per minute.

## Frontend

The existing rendered clip card displays layout mode, applied/fallback status,
participants, speaker association availability, active-speaker use, rendered region and
switch counts, confidence, validation, fallback reason, and warnings. The unified “Why
this clip works” section carries the layout reason.

## Validation CLI

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_multi_speaker_layout.py --simulate --faces 2 --speakers 0
D:\Olympus\.venv\Scripts\python.exe tools\validate_multi_speaker_layout.py --face-artifact face.json
D:\Olympus\.venv\Scripts\python.exe tools\validate_multi_speaker_layout.py --rendered-file clip.mp4 --manifest manifest.json
D:\Olympus\.venv\Scripts\python.exe tools\validate_multi_speaker_layout.py --project-id PROJECT_ID --validate-renders
```

## Limitations

- The default face-detection analysis stage remains unavailable without a configured CV
  model, so real projects honestly use center fallback unless detections are supplied.
- Default transcription does not guarantee diarization.
- No lip-motion active-speaker model is implemented.
- Crop stability can be measured geometrically, but visual quality still requires
  playback inspection.
- Active-speaker focus and stacked layouts are deterministic editing tools, not claims
  about participant identity.
