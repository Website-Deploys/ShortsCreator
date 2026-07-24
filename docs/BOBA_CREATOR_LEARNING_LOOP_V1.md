# BOBA Creator Learning Loop V1

## Purpose

BOBA Creator Learning Loop V1 converts deliberate creator feedback into compact,
local, reusable preferences. It is an advisory extension of BOBA Memory System V1,
not an autonomous optimization system.

## Accepted Feedback

V1 accepts explicit approval, rejection, rating, chosen-alternative, correction,
preference-note, manual-tag, reset, and export events. Targets can be clips,
candidates, rankings, editorial decisions, explanations, creative direction,
clip briefs, hook alternatives, caption/motion recommendations, music-mood
recommendations, or the project.

BOBA does not infer feedback from views, clicks, playback duration, downloads, or
other passive behavior.

## Preference Extraction

The local deterministic engine combines an explicit action with bounded fields
from the selected BOBA artifact. It can extract clip type, hook style, caption
style, motion style, music mood, pacing, story angle, risk sensitivity, and
production priority.

Free-form notes use a small conservative phrase map. For example, “too much zoom”
maps to avoiding high motion intensity, while “captions were too busy” maps to
avoiding high caption density. Unrecognized prose is retained only as the bounded
event note and does not become a preference.

## Confidence and Contradictions

A single event remains low confidence. Repeated consistent events increase
confidence and create a repeated-feedback summary. Approval and rejection of the
same preference are retained as a contradiction, reduce confidence, and create a
human-review warning instead of silently choosing a side.

## Recommendation Guidance

The result exposes advisory guidance for ranking, editorial decisions, Creative
Director, clip briefs, hook/retention, caption/motion, and music mood. Guidance is
emitted only after repeated evidence is strong enough.

`apply_automatically` is always `false` in V1. Existing BOBA modules are not
overridden by this artifact.

## Memory Integration

Creator Learning uses `BobaMemoryStore` atomic writes and can read existing
explicit BOBA memory for consistency context. It does not change the BOBA Memory
V1 project, creator, global, record, import, export, or reset schemas.

The saved learning artifact is:

```text
work/boba/projects/<project_id>/creator_learning/index.json
```

Explicit events use an atomic append-safe JSONL log:

```text
work/boba/projects/<project_id>/creator_learning/events.jsonl
```

Dry-run generation performs no learning or memory write.

## User Control

The frontend panel states that BOBA learns only from submitted feedback. Recording
an event, generating a profile, running a dry run, exporting, and resetting are
separate deliberate actions. Reset removes only the project’s creator-learning
artifact and event log; unrelated BOBA memory remains.

Exports contain compact preferences and event summaries. Raw event notes and
source-artifact references are omitted from export.

## API

```text
POST   /api/v1/boba/projects/{project_id}/creator-learning/events
POST   /api/v1/boba/projects/{project_id}/creator-learning
GET    /api/v1/boba/projects/{project_id}/creator-learning
GET    /api/v1/boba/projects/{project_id}/creator-learning/export
DELETE /api/v1/boba/projects/{project_id}/creator-learning
```

Generation accepts `creator_id` and `dry_run`; `dry_run=true` returns an advisory
result without persistence.

## Validation

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_creator_learning.py --self-check
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_creator_learning.py --synthetic-project
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_creator_learning.py --project-id PROJECT_ID
```

Reports are written to the ignored local path:

```text
work/validation_reports/boba_creator_learning/
```

## Limitations

- V1 learns only from explicit user feedback.
- V1 does not collect hidden behavior.
- V1 does not use external APIs or viewer analytics.
- V1 does not guarantee performance or virality.
- V1 does not automatically override BOBA decisions.
- V1 does not store raw media, full transcripts, or credentials.
- V1 does not replace human editorial review.
