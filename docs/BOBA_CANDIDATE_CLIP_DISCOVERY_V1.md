# BOBA Candidate Clip Discovery V1

## Purpose

BOBA Candidate Clip Discovery V1 finds advisory Short-form source windows from local,
already-produced Olympus and BOBA artifacts. It sits beside the Olympus pipeline and does not
replace Planning, Editing, Rendering, or Optimization.

V1 discovers possible clips. It does not produce final ranking, predict audience performance,
prove copyright safety, or trigger media processing.

## Inputs

The deterministic engine can use:

- compact timed transcript segments;
- BOBA Whole Video Understanding V1 topic segments, emotional beats, context/payoff links,
  section scores, and shortability hints;
- Analysis Signals V2 energy events;
- Story V2 micro-stories and recommended clip stories;
- timed Virality V2 moments and compact virality reasons;
- existing Planning V2 candidates as advisory evidence when they already exist; and
- bounded BOBA project memory as a small confidence advisory.

Every optional input is reported honestly in `signal_usage`. Missing Whole Video Understanding
activates local fallback behavior. Discovery fails clearly only when no timed transcript or
timed upstream signal is available.

## Candidate Contract

Each `BobaCandidateClipV1` includes:

- source start, end, and duration;
- a deterministic candidate ID;
- suggested title, hook idea, story angle, and candidate type;
- discovery reason, confidence, and standalone score;
- setup, context, and payoff flags;
- topic, emotion, and compact virality cues;
- a boundary suggestion;
- bounded evidence IDs and up to three short transcript snippets; and
- explicit warnings.

The discovery artifact is `BobaCandidateClipDiscoveryV1` with schema version
`boba_candidate_clip_discovery_v1`.

## Window Logic

Default timing policy:

- minimum: 12 seconds;
- ideal range: 25-45 seconds;
- maximum: 90 seconds; and
- maximum retained candidates: 20.

Short windows expand around their source signal when source duration allows. Overlong windows
are clamped. Project/source duration is authoritative, so malformed upstream timestamps cannot
extend a candidate beyond the video. Known payoff endpoints are preserved where possible.

These are editorial suggestions, not frame-accurate A/V boundary repair.

## Boundary Suggestions

`BobaBoundarySuggestionV1` records recommended start/end, added pre-roll/post-roll, abrupt-start
and abrupt-end warnings, and an explanation. Pre-roll favors setup when a context/payoff link says
setup is required. A missing confirmed payoff remains visible as an abrupt-end warning rather
than being hidden.

## Standalone and Context Safety

Candidates carry separate `standalone_score`, `setup_required`, `context_needed`, and
`payoff_present` fields. Context/payoff links can move a candidate start earlier and protect a
known payoff end. If setup and payoff cannot both fit safely inside 90 seconds, V1 warns that
earlier context may be missing.

## Deduplication and Diversity

Discovery applies deterministic window comparison:

- exact duplicate windows are rejected;
- overlap above 80% rejects the lower-priority candidate;
- overlap from 50% through 80% adds a review warning unless topic, emotion, type, or payoff makes
  the candidate meaningfully different; and
- confidence, standalone safety, payoff presence, topic, emotion, and candidate type guide the
  final bounded selection.

Every removed window has a compact rejection reason. The diversity summary reports topic,
emotion, and candidate-type coverage plus duplicate/high-overlap removal counts. Candidate quotas
are not filled with fabricated windows.

## Storage

`BobaMemoryStore` writes atomically to:

```text
work/boba/projects/<project_id>/candidate_clip_discovery/index.json
```

The artifact contains no raw media, frames, full transcript field, secrets, or generated clips.
Older projects without this file load as unavailable.

## API

Run discovery from existing local artifacts:

```text
POST /api/v1/boba/projects/{project_id}/candidate-clips/discover
```

Read the saved artifact:

```text
GET /api/v1/boba/projects/{project_id}/candidate-clips
```

POST does not download, render, or call external APIs. GET returns a clear not-found response when
the project has no saved discovery artifact.

The Results UI displays candidate windows, titles, hooks, story angles, confidence, standalone
safety, setup/payoff status, discovery reasons, and warnings without presenting discovery as an
applied edit.

## Downstream Use

`BobaIntegration.collect_project_signals()` exposes the saved artifact and a compact
`discovered_candidate_clips` list. This makes candidates available to a future BOBA ranking pass.
The Creative Director may use discovered candidates only when no Olympus selected plans or
planning candidates are available and creative-brief generation is explicitly requested.

Olympus Planning remains authoritative. Discovery never auto-selects or auto-renders a window.

## Validator

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_candidate_clip_discovery.py --self-check
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_candidate_clip_discovery.py --synthetic-project
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_candidate_clip_discovery.py --project-id PROJECT_ID
```

Reports are generated only under:

```text
work/validation_reports/boba_candidate_clip_discovery/
```

Synthetic validation uses metadata-shaped fixtures, verifies persistence and window safety, and
does not require media, network, downloaders, renderers, external APIs, or secrets.

## Limitations

- Heuristics are local and deterministic, not human semantic judgment.
- Confidence is an editorial signal, not a probability of virality.
- Transcript phrase matching can produce false positives.
- Aggregate Virality V2 reasons are used conservatively because they may not be window-specific.
- Final clip ranking is intentionally deferred to a later BOBA ranking feature.
- Final boundary repair, A/V sync, captions, editing, rendering, and validation remain Olympus
  responsibilities.
- Human review is required before any discovered candidate is used downstream.
