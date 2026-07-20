# BOBA Editorial Decision Engine V1

## Purpose

BOBA Editorial Decision Engine V1 converts a saved BOBA Clip Ranking artifact into
deterministic, explainable editorial recommendations. It answers two bounded questions:

1. Which ranked candidates should move toward production review?
2. What source-faithful editorial direction should a future Olympus edit use?

The engine is an advisory intelligence layer. It does not alter an Olympus plan or timeline,
render media, download content, call an external service, or prove likely audience performance.

## What An Editorial Decision Means

An editorial decision is compact metadata for one ranked candidate. It records:

- selected or not selected;
- production priority;
- `ready_for_render`, `needs_revision`, or `blocked` preflight status;
- final story angle and opening-line direction;
- hook, pacing, caption, motion, music-mood, and SFX-intensity guidance;
- visual emphasis and retention tactics;
- explicit risks, blockers, reasons, and improvement notes;
- a future-consumable editing instruction packet.

`ready_for_render` means only that the available metadata passed BOBA's editorial preflight.
It does not mean an MP4 exists or that an effect was applied.

## Inputs

The only required input is a saved BOBA Clip Ranking Brain V1 artifact. The engine also uses
these local artifacts when available:

- BOBA Candidate Clip Discovery;
- BOBA Whole Video Understanding;
- BOBA Creative Director briefs;
- Olympus analysis, story, virality, planning, and editing metadata;
- bounded BOBA project memory;
- local source type, rights state, transcript availability, and face/speaker signal state.

Unavailable optional signals produce explicit fallback metadata. The engine does not fabricate
missing analysis and does not store raw media or a full transcript.

## Selection Rules

Selection is deterministic:

1. Consider saved ranking order and recommendations.
2. Select non-blocked `must_make` and `strong_candidate` clips first.
3. Add non-blocked `backup_candidate` clips only when needed to reach the default target.
4. Keep at most ten selected clips.
5. Keep weak, rejected, duplicate-only, invalid-window, and rights-blocked candidates out of the
   production order.

When enough viable candidates exist, the target is three to ten selected clips. Fewer selections
are allowed when the saved ranking does not contain enough safe candidates; BOBA does not promote
a blocked clip merely to satisfy a count.

## Render Readiness

### `ready_for_render`

Requires a sufficiently strong ranking plus no blocking or revision-level hook, payoff, context,
duplicate, filler, or rights risk.

### `needs_revision`

Used for a promising candidate that needs a stronger source-supported opening, boundary repair,
additional context, a complete payoff, filler removal, or rights confirmation.

### `blocked`

Used for explicit rights denial, severe rights penalty, invalid source window, severe standalone
context failure, ranking rejection, or a duplicate-only rejected candidate.

Rights warnings are conservative review signals. They do not establish ownership, permission, or
copyright safety.

## Hook Strategy

The engine chooses one bounded strategy from source metadata:

- `curiosity_gap`
- `emotional_reveal`
- `problem_solution`
- `contradiction`
- `shocking_truth`
- `motivational_payoff`
- `story_turn`
- `educational_open_loop`
- `direct_value`

Opening instructions preserve the ranked source hook. A weak hook receives a revision instruction
instead of invented wording or a stronger unsupported claim.

## Caption Strategy

Caption direction is one of:

- `clean_subtitles`
- `bold_hook_captions`
- `emotional_emphasis`
- `keyword_highlight`
- `minimal`
- `none`

Curiosity, contradiction, and shock favor bold hook captions. Emotional and motivational moments
favor emotional emphasis. Educational material favors keyword highlighting. Missing transcript or
audio evidence can reduce the instruction to `none` and adds a risk warning.

## Motion Strategy

Motion direction is one of:

- `stable`
- `subtle_zoom`
- `dynamic_zoom`
- `punch_in`
- `high_motion`
- `layout_safe`

Strong hooks and high-energy clips may receive punch-in or dynamic guidance. Missing face/layout
evidence forces a stable or layout-safe recommendation. V1 does not create crop keyframes and does
not claim that a renderer applied this guidance.

## Music And SFX Strategy

Music is mood metadata only:

- `none`
- `motivational`
- `emotional`
- `suspense`
- `energetic`
- `calm`
- `funny`
- `cinematic`
- `educational`

The artifact never selects a song, copyrighted track, asset key, or file path. SFX guidance is only
`none`, `light`, `moderate`, or `heavy`. Existing Olympus asset safety and rendering truth remain
authoritative.

## Risk Review

Every candidate receives flags for:

- weak hook;
- missing context;
- weak payoff;
- filler or repetition;
- duplicate or overlap risk;
- rights risk;
- unavailable transcript/audio evidence;
- unavailable face/layout evidence;
- unavailable optional upstream signals.

The decision set aggregates ready, revision, and blocked counts plus top risks, blockers, and
warnings. Risks remain visible in persisted JSON, API responses, and the frontend panel.

## Editing Instruction Packet

Each decision contains compact instructions for:

- hook treatment;
- source-window cutting;
- captions;
- motion;
- audio mood and SFX intensity;
- pacing;
- retention;
- required risk correction.

The packet is available to future Olympus integration, but V1 does not automatically override the
planner or editing engine. BOBA Creative Director may use selected, non-blocked decisions as a
fallback input when no authoritative Olympus plan candidates are present.

## Artifact Storage

The canonical artifact path is:

```text
work/boba/projects/<project_id>/editorial_decision/index.json
```

Writes are atomic, credential-like fields remain rejected, strings are contract-bounded, and the
payload is JSON-safe. Old projects without this artifact continue to load; GET returns a clear 404
until decisions are generated.

## API

```text
POST /api/v1/boba/projects/{project_id}/editorial-decisions
GET  /api/v1/boba/projects/{project_id}/editorial-decisions
```

POST reads saved local artifacts, runs the deterministic engine, and persists the result. It does
not render, download, or make network calls. GET returns only the saved artifact.

## Validator

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_editorial_decision.py --self-check
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_editorial_decision.py --synthetic-project
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_editorial_decision.py --project-id PROJECT_ID
```

Reports are written under ignored local storage:

```text
work/validation_reports/boba_editorial_decision/
```

Synthetic validation uses metadata-only candidates covering must-make, strong, backup, revision,
reject, rights-risk, and weak-payoff behavior. It requires no media, secrets, renderer, downloader,
or external API.

## Limitations

- V1 is advisory and does not replace human editorial or rights review.
- Render readiness is a heuristic preflight, not production-readiness proof.
- The engine does not modify Olympus plans, timelines, filters, or render commands.
- The engine does not select music assets or establish copyright safety.
- Missing analysis signals use explicit deterministic fallbacks.
- Memory can adjust bounded style preferences but cannot override blockers or rights safeguards.
- No score or recommendation predicts actual reach, retention, or virality.
