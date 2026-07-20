# BOBA Clip Brief Generator V1

## Purpose

BOBA Clip Brief Generator V1 creates the final compact, editor-readable handoff between
saved BOBA intelligence and a future Olympus editing integration. It distills decisions and
creative direction; it does not execute them.

The generator is deterministic, local, JSON-safe, and advisory. It does not render, download,
call external APIs, select media assets, or change an Olympus timeline.

## Inputs

The generator requires:

- BOBA Creative Director V2 direction;
- BOBA Editorial Decision V1 decisions.

It also consumes these saved artifacts when available:

- BOBA Clip Ranking V1;
- BOBA Candidate Clip Discovery V1;
- BOBA Explanation Engine V1;
- BOBA Whole Video Understanding V1;
- bounded BOBA project memory.

Editorial Decision remains the authority for selection, production priority, source window,
render readiness, and blocking risk. Creative Director V2 remains the authority for detailed
hook, opening, pacing, caption, motion, audio-mood, retention, and emotional direction. Clip
Brief Generator does not duplicate or override either engine; it converts their output into a
practical one-page packet.

Missing required artifacts fail clearly. Missing optional artifacts are recorded in
`signal_usage`, and fallback language is explicit rather than fabricated.

## Brief Set

`BobaClipBriefSetV1` contains:

- project and source identity;
- creation time and `boba_clip_brief_generator_v1` version;
- selected, backup, and blocked briefs;
- selected-clip production order;
- compact project summary;
- exact signal usage;
- warnings and limitations.

### Selected briefs

Selected briefs follow saved Editorial Decision selections that are not blocked. Matching
Creative Director V2 clip direction is used when present. A missing per-clip direction is an
honest Editorial Decision fallback and is reported.

### Backup briefs

Backup briefs retain non-blocked alternatives such as `backup_candidate`, `needs_revision`,
medium-priority, and other unselected editorial options. They are not silently promoted to
selected status.

### Blocked briefs

Blocked briefs preserve editorial blocks, rights blocks, rejected or duplicate-only options,
and invalid source windows. They use `do_not_produce` priority and never imply render readiness.

## Per-Clip Packet

Each `BobaClipBriefV1` includes stable brief, project, candidate, and ranking identities plus:

- advisory source start, end, and duration;
- production priority and render readiness;
- brief title, final angle, and intended viewer feeling;
- hook and opening-three-second instructions;
- story and cut instructions;
- caption and motion instructions;
- audio mood and SFX instructions;
- retention instruction;
- risk fixes;
- editor checklist;
- human-review notes, confidence, warnings, and limitations.

Every `BobaBriefInstructionV1` has a compact summary, a concrete action, an explicit avoidance,
the evidence-based reason, and a `must_follow`, `should_follow`, or `optional` priority.

## Instruction Behavior

### Hook

The hook packet combines the Creative Director V2 hook treatment, Editorial Decision hook
strategy, bounded Explanation reasoning, and ranking hook score when available. It warns
against dead air, generic greetings, unsupported claims, and misleading treatment.

### Opening three seconds

The opening packet states the first visual, caption implication, curiosity trigger, motion
choice, and pacing instruction. It explicitly prevents removable setup from consuming the
opening.

### Story and cut

Story guidance preserves the selected angle, minimum required context, setup-to-payoff
relationship, and final lesson. Cut guidance keeps the advisory source window visible, permits
only verified filler/dead-air removal, and warns against abrupt starts, mid-thought cuts, and
early payoff loss.

### Captions and motion

Caption guidance carries style, emphasis, rhythm, and readability constraints without changing
spoken meaning. Motion guidance carries style and moments while preserving stable framing,
caption clearance, and face/layout safety. Missing or risky visual evidence remains a warning;
the brief does not claim face tracking is available.

### Audio and SFX

Audio guidance contains mood metadata, ducking, silence, and speech-clarity instructions only.
It never chooses a song or stores a music path. Path-like upstream music values are replaced
with an unspecified mood and a warning.

SFX guidance is sparse and speech-first. It explicitly rejects static, hiss, harsh noise,
repetitive hits, and effects that compete with important words.

### Retention

Retention guidance carries the opening loop, mid-clip hold, payoff delivery, and replay trigger.
It prohibits artificial payoff delay and misleading open loops.

## Risk Fixes

Every brief retains explicit checks for:

- missing context;
- weak or incomplete payoff;
- weak hook;
- filler removal;
- source and external-asset rights;
- speech, synchronization, silence, music, and SFX review;
- face, layout, crop, caption, and motion safety.

These are review instructions, not proof that the risk has been resolved.

## Editor Checklist

Every brief includes required checklist items for hook, context, payoff, pacing, captions,
motion, audio, rights, render safety, and final human review. Initial statuses remain `pending`,
`warning`, or `blocked`; the generator does not mark production work as passed.

## Storage

The canonical artifact is written atomically at:

`work/boba/projects/<project_id>/clip_briefs/index.json`

The artifact stores no raw media and no full transcript. Existing projects without the artifact
continue to load; GET returns a clear unavailable response until generation succeeds.

## API

- `POST /api/v1/boba/projects/{project_id}/clip-briefs`
- `GET /api/v1/boba/projects/{project_id}/clip-briefs`

POST reads saved local BOBA artifacts and persists the packet. It does not render, download, or
call an external service. The Results UI exposes selected, backup, and blocked packets with
collapsible instruction and checklist details.

## Validator

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_clip_brief_generator.py --self-check
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_clip_brief_generator.py --synthetic-project
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_clip_brief_generator.py --project-id PROJECT_ID
```

Reports are generated under:

`work/validation_reports/boba_clip_brief_generator/`

The synthetic validator checks category coverage, all selected instruction sections, editor
checklists, risk preservation, mood-only music text, absence of copyrighted track paths,
atomic persistence, JSON safety, and the absence of rendering or external calls.

## Limitations

- V1 is advisory and does not edit or render clips.
- It does not choose music, SFX, visual assets, or copyrighted tracks.
- It does not bypass or prove source or asset rights.
- It does not call external APIs or use live trend research.
- It does not predict real audience performance.
- Confidence is bounded evidence confidence, not production or virality proof.
- Human review remains mandatory before editing, rendering, or publishing.
