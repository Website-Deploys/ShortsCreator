# BOBA Workflow Controller V1

## 1. Purpose

BOBA Workflow Controller V1 persists the exact internal production stage that a
project, clip, or output is in. It makes stage dependencies, transition evidence,
pauses, recovery holds, and internal completion inspectable without replacing the
existing Olympus worker system.

## 2. What Workflow Controller owns

The controller owns the immutable workflow definition snapshot, workflow runs,
stage instances, artifact bindings, dependency checks, exact transition requests
and decisions, execution leases, pauses, incidents, recovery holds, human
decisions, handoffs, events, and the current controller summary.

## 3. What it does not own

It does not diagnose root causes, choose repairs, execute arbitrary functions,
run commands, invoke Git or FFmpeg directly, restore checkpoints, install
packages, restart services, kill processes, fetch URLs, download media, upload,
publish, push, merge, or deploy. It does not replace durable Olympus workers.

## 4. Difference from Autopilot Controller

Autopilot owns bounded diagnosis and recovery coordination. Workflow Controller
owns the paused stage ledger and accepts only a typed recovery result bound to the
exact project, run, hold, failed stage, snapshot, validations, and artifacts.
Receiving recovery evidence never resumes normal workflow execution.

## 5. Difference from Integration Layer

Integration Layer is the closed typed router for registered operations. Workflow
Controller decides whether one graph transition is eligible, persists the target
stage as running, and then asks Integration Layer to route that one operation.
The controller never calls a target handler directly.

## 6. Difference from Safety Gate

Safety Gate evaluates a bounded request against policy. Workflow Controller only
records and verifies an exact, current Safety decision when a stage requires one.
It cannot grant, weaken, or bypass Safety authority.

## 7. Difference from Checkpoint Recovery Manager

Checkpoint Recovery Manager owns checkpoint validation and restoration policy.
Workflow Controller can require and reference validated checkpoint evidence, but
V1 cannot restore a checkpoint or treat a path as proof by itself.

## 8. Difference from Final Decision Bus

Final Decision Bus remains a separately gated future authority boundary. Workflow
Controller V1 coordinates registered internal stages and internal output
completion only; it does not make release, upload, publication, or deployment
decisions.

## 9. Built-in workflow definition

The immutable V1 graph contains exactly 19 stages:

1. `workflow_created`
2. `source_registration`
3. `rights_review`
4. `source_ready`
5. `whole_video_analysis`
6. `candidate_discovery`
7. `clip_ranking`
8. `editorial_selection`
9. `creative_direction`
10. `clip_brief_generation`
11. `hook_retention_planning`
12. `caption_motion_planning`
13. `music_mood_planning`
14. `render_preparation`
15. `rendering`
16. `technical_validation`
17. `output_quality_review`
18. `human_review` when required
19. `internal_output_completion`

The graph is code-defined, digest-stable, cycle-checked, and cannot be replaced by
an API payload.

## 10. Project and clip stages

Early understanding and selection stages have project scope. Creative planning
branches per clip. Rendering, technical validation, quality review, optional
human review, and internal completion bind to an exact output identity. Stage
instances preserve project, clip, and output isolation.

## 11. Stage dependencies

Each stage definition declares required predecessors, accepted input artifact
types, produced artifact types, gates, timeout, and attempt limit. A transition
is blocked when a predecessor is absent, incomplete, failed, or when required
evidence is missing, unavailable, stale, malformed, or from another branch.

## 12. Workflow states

Runs distinguish created, active, paused, blocked, recovery, completed,
cancelled, failed, and unknown states. Project state adds precise waiting states
for approval, Safety, human review, recovery, eligibility, and exact transition
execution.

## 13. Stage states

Stage instances distinguish pending, dependency-blocked, ready, waiting,
running, completed, completed-with-limitations, failed, timed-out, cancelled,
recovery-required, superseded, skipped-not-required, blocked, and unknown.
Terminal stage history is immutable.

## 14. Artifact lineage

Bindings include project, run, stage, optional clip/output identity, producer,
schema, digest, sanitized storage reference, availability, staleness, and
quality/Safety relevance. Source media is immutable and read-only. Raw media is
validated locally but is never transported through Integration Layer.

## 15. Transition requests

A request identifies one source stage, one target stage definition, one
registered operation, one revision, one project snapshot, and one input artifact
digest. Optional approval, Safety, checkpoint, quality, and human references are
bound into the persisted request.

## 16. Transition decisions

Evaluation records every required condition separately and selects a typed
result such as allowed-read-only, allowed-exact-internal, awaiting approval,
blocked rights, blocked checkpoint, blocked validation, blocked quality, stale,
or invalid. A blocked decision never invokes a target.

## 17. Exact internal transitions

An allowed execution-capable stage still requires separate coordination. The
controller rechecks revision, decision expiry, stage readiness, exact approval
and Safety bindings, acquires a lease, persists running state, routes only the
registered operation, requires target revalidation, validates result artifacts,
and advances no more than that one stage.

## 18. Why generic resume is unavailable

Generic `workflow_controller.resume` remains future-gated because “resume” is
too broad to preserve exact stage, evidence, approval, Safety, and idempotency
boundaries. V1 can release a controller pause or prepare a new exact transition,
but it cannot resume all workers or all branches.

## 19. Workflow revisions

Every mutating request requires the caller’s expected revision. Transition
creation and evaluation increment revision independently. Stale requests,
decisions, recovery results, and human actions fail closed.

## 20. Execution leases

Only one execution lease can own an exact project transition at a time. Leases
record run, transition, stage, owner, mode, revision, snapshot, and expiry.
Stale leases require explicit replacement and are never silently stolen.

## 21. Idempotency

The idempotency key binds project, run, stage, transition type, operation,
snapshot, revision, input artifacts, approval, and Safety evidence. An identical
completed request can reuse its saved result. Reusing a key with changed content
is an explicit conflict.

## 22. Pause behavior

Manual and automatic pauses stop future scheduling while preserving source media,
accepted outputs, completed stages, transitions, and evidence. Categories expose
whether the cause was failure, validation, quality, rights, Safety, approval,
checkpoint, stale state, concurrency, recovery, or uncertainty.

## 23. Recovery Holds

A Recovery Hold references an honestly failed, timed-out, blocked, or
recovery-required stage. It preserves the failed terminal record, blocks normal
continuation, and stores recovery lineage separately.

## 24. Autopilot recovery handoffs

Creating a hold emits a typed handoff to Autopilot with exact identifiers,
bounded evidence, allowed recovery actions, and explicit prohibited actions.
Workflow Controller does not diagnose or choose the repair strategy.

## 25. Resume eligibility

Eligibility is a review, not execution. It requires resolved recovery, matching
snapshot/revision, passing technical validation, accepted output quality, current
rights/Safety/approval/checkpoint evidence, no active recovery or conflicting
transition, current artifacts, ready dependencies, human review when required,
and remaining retry budget.

## 26. Technical validation

Stages that require technical validation do not advance on missing, malformed, or
failed evidence. A target process exit code alone is not sufficient proof.
Validation failures are visible pause reasons.

## 27. Output Quality enforcement

Output Quality decisions bind to the exact project, clip, and output. Accepted or
accepted-with-disclosed-limitations decisions can satisfy the gate. Rejected,
missing, stale, or needs-human-review decisions remain blocked.

## 28. Internal output completion

Completion requires every required clip/output branch, required validation,
quality acceptance, and no active recovery hold. It marks an internal artifact
journey complete only. `upload_authorized` and `publication_authorized` remain
structurally false.

## 29. Human decisions

Human decisions are bounded records with reviewer reference, explicit
confirmation, project snapshot, workflow revision, optional stage/transition,
conditions, and expiry. They cannot skip graph stages, override rights or hard
Safety blocks, or authorize upload/publication.

## 30. Workflow events

Events are append-safe and monotonically sequenced. They separate confirmed fact
from assessment, include bounded technical and easy messages, and expose progress
only when derived from real required stage counts.

## 31. API routes

The BOBA API supports definition creation, run creation and inspection, next-stage
planning, transition creation/evaluation, safe read-only advance, exact approved
coordination, pause/continue/cancel, recovery holds/results, eligibility review,
human decisions, events, export, and reset. Routes accept optional fields safely
for older projects and never expose a generic resume-everything endpoint.

## 32. Artifact paths

Active metadata is rooted at:

- `projects/<project_id>/workflow_controller/index.json`
- `projects/<project_id>/workflow_controller/definitions/<definition_id>.json`
- `projects/<project_id>/workflow_controller/runs/<run_id>/index.json`
- stage and transition records below the run directory
- `events.jsonl` below the run directory
- `projects/<project_id>/workflow_controller/active.lock.json`

References reject URLs, traversal, absolute paths, and UNC paths.

## 33. Export/reset

Export is JSON-safe and redacts secrets, private paths, raw media, and complete
logs. Reset removes only the active controller index and lease after every run is
terminal. Immutable workflow history, source media, outputs, Autopilot history,
Safety decisions, Integration transactions, and approvals remain preserved.

## 34. Validator commands

Run:

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_workflow_controller.py --self-check
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_workflow_controller.py --synthetic-project
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_workflow_controller.py --project-id PROJECT_ID
```

Reports are written under
`work/validation_reports/boba_workflow_controller/` and are not source artifacts.
Synthetic mode runs exactly 201 named bounded scenarios.

## 35. Limitations

V1 does not replace durable Olympus workers. Production editing, rendering, and
optimization adapters are registered but fail closed when their trusted
composition-root handlers are unavailable. Synthetic validation uses fixed local
handlers only. There is no generic resume, checkpoint restore, network access,
external API use, media download, upload, publication, push, merge, deployment,
or production-readiness claim.
