# A/V Sync and Random Cut Boundary Fix V2

## Problem

Rendered Shorts could report matching stream durations while speech still sounded late, and some
clips ended inside a word or immediately after the payoff. Container duration alone does not prove
that audio content and visual content begin together.

## Root Causes

- Planning selected segment-level boundaries, but Editing had no final word-level repair step.
- Editing copied planned `start`, `end`, and `duration` independently, allowing stale duration data.
- Captions used clip-relative timing correctly, but inherited the unrepaired source origin.
- FFmpeg used matching source trims, but the output-level `-t` remained a second hard cutoff.
- The voice enhancement chain introduced deterministic processing latency. A synthetic flash/beep
  fixture measured about 27 ms before compensation, primarily around denoising and dynamics.
- Existing ffprobe checks compared stream durations, not aligned content markers.

## Canonical Timeline Contract

`ClipSourceWindowV1` in `src/olympus/editing/timeline_contracts.py` records:

- requested Planning boundaries;
- repaired render boundaries;
- final duration derived from the repaired range;
- preroll and postroll;
- repair reasons and warnings.

Timeline Initialization creates this contract once. Video, audio, captions, music, SFX, and motion
then share the repaired clip-relative origin. Rendering prefers `source_window_v1` and retains a
legacy fallback for old projects.

## Boundary Repair Rules

`src/olympus/editing/boundary_repair.py` applies conservative repair before downstream edits:

- move a mid-word start before the word with a small preroll;
- use a nearby segment start when word timing is unavailable;
- extend a mid-word or continuous-speech end through the final word;
- preserve nearby Story/Planning payoff-end guidance;
- add a short breathing tail after active speech;
- use conservative postroll when transcript timing is absent;
- clamp every repaired end to the known source duration;
- report an abrupt-end warning when safe tail space is impossible.

The repair does not invent transcript content or silently exceed the source.

## FFmpeg Trim Rules

The renderer uses one repaired source range in the filtergraph:

```text
trim=start=START:end=END,setpts=PTS-STARTPTS
atrim=start=START:end=END,asetpts=PTS-STARTPTS
```

There is no input-level `-ss`, no global `-shortest`, and no output-level `-t`. Speech/video define
the clip while music and SFX are padded or trimmed inside the graph. Stream timestamps are reset at
the same origin. ffprobe now also records stream `start_time`.

The measured voice-chain latency is compensated by 25 ms before final audio padding/trimming. This
value is covered by synthetic marker validation and is exposed in render metadata; it is not a claim
that every codec and source has zero latency.

## Caption Alignment

Transcript segments and words are localized using:

```text
caption_time = source_time - repaired_start_seconds
```

Negative cues are shifted or removed, cues beyond the final duration are removed, and cue/word ends
are clipped to the repaired duration. Caption timing warnings persist in Caption Intelligence V2.

## Render Metadata

Rendered metadata now includes a `timeline` object with requested/repaired boundaries, preroll,
postroll, repair status, boundary warnings, duration validation, and sync validation. Sync metadata
states whether content markers were checked; ordinary project ffprobe validation remains a stream
timing check rather than pretending to inspect spoken content.

## Validation

Run:

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_av_sync_boundaries.py --self-check
D:\Olympus\.venv\Scripts\python.exe tools\validate_av_sync_boundaries.py --simulate
D:\Olympus\.venv\Scripts\python.exe tools\validate_av_sync_boundaries.py --project-id PROJECT_ID
```

Reports are written under `work/validation_reports/av_sync_boundaries/` and stay ignored. Simulate
mode generates local synthetic media with aligned flash/beep markers, repairs a mid-word start/end,
renders through the production FFmpeg command builder, validates ASS timing, detects marker offset,
checks final-word tail, and confirms no early-cutoff flags. It uses no user media or network service.

## What This Fixes

- one canonical repaired source window;
- word/segment-aware start and end repair;
- final-word and payoff-tail protection where source duration permits;
- shared audio/video/caption timing origin;
- measured compensation for current voice-filter latency;
- content-marker validation in the synthetic validator;
- honest warnings when repair or marker proof is unavailable.

## What This Does Not Fix

This pass does not change render checkpoint handoff, BOBA intelligence, face tracking, music quality,
scouting/link ingestion, or overall release readiness. Synthetic success does not prove that every
real user video is fixed; representative user-approved media still requires separate validation.
