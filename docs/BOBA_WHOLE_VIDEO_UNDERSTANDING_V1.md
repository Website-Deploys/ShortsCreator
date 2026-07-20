# BOBA Whole Video Understanding V1

## Purpose

BOBA Whole Video Understanding V1 builds a compact, explainable map of an existing Olympus
project. It helps BOBA reason about the source as a whole before Scout or Creative Director
advice is produced.

This is an additive BOBA intelligence layer. It does not replace Olympus analysis, Story,
Virality, Planning, Editing, or Rendering.

## Operating Model

V1 is deterministic and local. It:

- reads existing project artifacts;
- uses bounded transcript evidence snippets;
- reuses Story V2 topic and micro-story data when available;
- reuses Analysis V2 audio-energy and emotion timelines when available;
- reuses Virality heat and Planning selections when available;
- falls back to transparent keyword, cue, punctuation, and timing heuristics;
- records unavailable signals and fallback use explicitly.

It does not call external APIs, cloud AI services, YouTube, download services, or rendering.

## Inputs

The integration reads the same canonical artifacts already used by BOBA:

- transcript: `analysis/<project_id>/stages/speech_transcription.json`;
- compact analysis signals: `analysis/<project_id>/stages/signal_health.json`;
- story: `story/<project_id>/stages/story_analysis_v2.json`;
- virality: `virality/<project_id>/stages/virality_summary.json`;
- planning: existing Planning V2 ranking, candidate, and summary stage artifacts;
- project memory: compact local BOBA project memory when available.

Missing optional artifacts do not stop transcript-backed understanding. A missing transcript is a
clear validation error because V1 will not invent source content.

## Outputs

`BobaWholeVideoUnderstandingV1` includes:

- overall summary, video type, primary/secondary topics, creator intent, audience value, and tone;
- topic timeline with bounded evidence snippets and source-signal attribution;
- story arc map for setup, context, build-up, key moments, payoff, conclusion, and unresolved threads;
- emotional beat map with intensity, confidence, reason, and source signals;
- context/payoff links with setup requirements and standalone-clip guidance;
- section importance, clarity, energy, novelty, shortability, filler, and repetition scores;
- shortability hints for candidates, hooks, payoff clips, context-dependent ranges, and unsafe standalone ranges;
- exact signal usage, unavailable signals, warnings, and limitations.

No raw frames, biometric identity, media, or full transcript are stored in the artifact.

## Topic Timeline

Story V2 topic sections are preferred. If they are unavailable, V1 groups adjacent transcript
segments using local keyword overlap, timing gaps, and explicit topic-shift phrases. The fallback
is labeled in `signal_usage`.

## Story Arc

Story V2 micro-stories supply the strongest setup/payoff evidence. When they are missing, V1 uses
bounded transcript positions and explicit payoff cues. Unresolved or missing payoffs remain
warnings instead of being fabricated.

## Emotional Beats

Story or Analysis V2 emotion timelines are preferred. Otherwise V1 uses a transparent transcript
keyword and punctuation heuristic. These labels are editorial cues, not psychological or facial
emotion recognition.

## Context And Payoff

The engine links Story V2 setup/context ranges to later payoff ranges. A transcript-only fallback
uses explicit phrases such as "the reason", "because", "finally", and "that's why". If no
defensible link exists, the map stays empty and the artifact records a warning.

## Section Scoring

Scores are normalized from available evidence:

- importance combines story completeness, selected-plan overlap, virality heat, payoff, and energy;
- clarity penalizes context dependency and filler;
- energy uses Analysis V2 events, emotional beats, and punctuation fallback;
- novelty penalizes repeated sections;
- shortability combines clarity, importance, energy, novelty, payoff, and Planning overlap;
- filler and repetition remain separately visible.

These are editorial heuristics. They do not predict real audience behavior.

## Shortability Hints

Each topic section may be labeled as:

- `candidate_for_short`;
- `needs_more_context`;
- `avoid_as_standalone`;
- `possible_hook`;
- `payoff_clip`.

Every hint includes a reason, setup requirement, hook potential, payoff strength, and recommended
review action.

## Storage And Memory

The full compact artifact uses the existing atomic BOBA project storage pattern:

`work/boba/projects/<project_id>/whole_video_understanding/index.json`

Only a smaller `BobaWholeVideoMemorySummaryV1` is added to project memory. It contains video type,
primary topic, strongest/weakest section labels, and shortability patterns. It excludes the full
transcript, raw media, private URLs, and source frames.

## Downstream Integration

- Creative Director optionally uses the overlapping topic, emotion, and setup requirement.
- Scout can use saved shortability hints when a manually supplied candidate explicitly links an
  existing local `project_id` in its metadata.
- Both integrations remain advisory. They do not trigger downloads, processing, or rendering.

## API

Build or refresh from existing project artifacts:

```text
POST /api/v1/boba/projects/{project_id}/whole-video-understanding
```

Read the saved artifact:

```text
GET /api/v1/boba/projects/{project_id}/whole-video-understanding
```

GET returns a clear not-found response when no artifact exists. POST does not render, download,
or make an external request.

## Frontend

The Results page adds a compact BOBA Whole Video Understanding panel with:

- overall summary;
- topic timeline;
- setup/payoff and unresolved-thread summary;
- emotional beats;
- best and weak/filler sections;
- shortability hints;
- unavailable-signal and limitation warnings;
- an explicit build/refresh action.

## Validator

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_whole_video_understanding.py --self-check
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_whole_video_understanding.py --synthetic-project
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_whole_video_understanding.py --project-id PROJECT_ID
```

Reports are written under ignored workspace storage:

`work/validation_reports/boba_whole_video_understanding/`

The synthetic modes require no media, secrets, internet, or external service.

## Limitations

- V1 is not human-level semantic understanding.
- It does not prove virality, retention, or audience performance.
- It does not establish copyright or processing rights.
- Emotion labels are heuristic unless supported by stronger upstream providers.
- Topic similarity uses local lexical rules rather than embeddings.
- The output remains advisory and requires human review for ambiguous context or payoffs.
