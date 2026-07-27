# BOBA Repair Planner V1

## 1. Purpose

BOBA Repair Planner V1 converts a persisted BOBA Root Cause Analyzer V1
report into bounded, evidence-linked, reversible repair options. It is a
planning layer for future human-reviewed recovery systems.

V1 plans only. A plan is not proof that a repair will succeed.

## 2. What Repair Planner Does

Repair Planner:

- reads one saved Root Cause Analyzer report;
- decides whether repair is appropriate;
- generates and ranks advisory strategies;
- identifies risk, scope, checkpoints, rollback, and validation;
- preserves technical and creative output requirements;
- rejects unsafe strategies explicitly;
- creates human-reviewed handoffs to future recovery modules;
- persists a compact JSON-safe report.

## 3. What Repair Planner Does Not Do

Repair Planner does not:

- repair, delete, rename, move, regenerate, or overwrite files;
- edit code or generate/apply code patches;
- execute shell commands, Git, tests, or validators;
- modify configuration or generated artifacts;
- install or uninstall dependencies;
- restart services or kill processes;
- activate fallback tools;
- retry rendering or ingest media;
- resume workflows;
- fetch URLs, call external APIs, scrape, upload, or download;
- bypass rights, safety, approval, validation, or quality gates;
- expose credentials, tokens, cookies, secrets, or private paths;
- guarantee repair success or production readiness.

## 4. Difference From Root Cause Analyzer

Root Cause Analyzer explains why a saved failure may have occurred. It
produces causal candidates, evidence, timelines, graphs, gaps, verification
plans, workflow impact, and escalation advice.

Repair Planner consumes that persisted analysis read-only and answers what
future recovery approaches could address the supported cause. It never
regenerates Root Cause Analyzer, Error Doctor, or Observer.

## 5. Difference From Tool Recovery Brain

Repair Planner can describe bounded retry, lower-resource, capability, and
fallback requirements. It does not select or execute a fallback tool.

A future Tool Recovery Brain may execute an explicitly approved strategy,
within its retry budget, and must return the result to validation and quality
review.

## 6. Difference From Code Surgeon

Repair Planner can create a Code Surgeon handoff only when code-defect evidence
is strong or moderate and sufficiently confident. It does not create a patch.

A future Code Surgeon must work on a separate branch, never patch `main`
directly, run required tests, preserve rollback, and obtain review.

## 7. Input Root Cause Analyzer Report

Primary input:

`work/boba/projects/<project_id>/root_cause_analyzer/index.json`

Repair Planner uses:

- analysis cases and ranked candidates;
- evidence quality, confidence, and repairability;
- failure timelines and causal graphs;
- verification plans and workflow impact;
- safety, rights, and human-review state.

Optional manual planning context is bounded, sanitized, JSON-safe, and cannot
authorize execution. Missing or malformed analysis returns an honest
unavailable result and recommends manual Root Cause Analyzer generation.

## 8. Repair Eligibility

Planning statuses include:

- `plan_ready`;
- `conditional_plan`;
- `needs_more_evidence`;
- `conflicting_causes`;
- `intentional_safety_block`;
- `human_decision_required`;
- `repair_not_required`;
- `blocked`;
- `unknown`.

Healthy states, optional artifacts with no required impact, validation gaps,
rights blocks, and missing human decisions are not mislabeled as software
repairs.

## 9. Repair Strategies

Strategy types include no action, evidence collection, checkpoint restore,
scoped artifact regeneration, bounded retry, lower-resource recovery,
registered-tool fallback requests, configuration/environment recovery,
validation rerun, failure isolation, Code Surgeon handoff, permission review,
human action, and stop processing.

Every strategy includes:

- supported candidate references;
- rationale and an easy-language explanation;
- future steps and responsible modules;
- prerequisites and expected effects;
- risk, complexity, reversibility, and confidence;
- checkpoint, backup, approval, and validation requirements;
- prohibited actions and stop conditions.

## 10. Strategy Ranking

Ranking is deterministic. It favors:

- direct causal relevance;
- reversible, small-scope recovery;
- validated checkpoints;
- source and quality preservation;
- bounded resource use;
- known rollback and validation;
- no code, external, paid, or destructive action.

It penalizes weak evidence, missing or corrupt checkpoints, repeated identical
failures, code/environment changes, external or paid services, and uncertain
validation. Scores are clamped and are not certainty.

## 11. Repair Scopes

Supported scopes are:

`no_repair`, `artifact`, `checkpoint`, `workflow`, `configuration`,
`environment`, `tool`, `dependency`, `data_input`, `validation`, `rendering`,
`code`, `rights_permission`, `human_decision`, and `unknown`.

Recovery must stay inside the selected scope and must not regenerate unrelated
modules.

## 12. Retry Limits

Retry-related strategies use a finite default budget:

- maximum attempts: `2`;
- maximum recovery duration: `900` seconds;
- stop on repeated identical failure;
- stop on quality regression, scope expansion, or safety/rights concern;
- escalate when the finite budget is exhausted.

An identical failed strategy is down-ranked when prior-attempt context exists.
Unlimited retry is explicitly rejected.

## 13. Checkpoint Requirements

Each planning case has a checkpoint plan. Depending on scope, it may require an
artifact snapshot, generated-state snapshot, workflow checkpoint,
configuration snapshot, repository branch, database backup, or media reference.

Source media must remain untouched. Missing, corrupt, stale, or unvalidated
checkpoints cannot be recovery proof.

## 14. Rollback Planning

Every non-trivial strategy has:

- rollback triggers;
- preserved-state requirements;
- ordered rollback steps;
- rollback validation;
- an owner module;
- destructive rollback blocking;
- human approval.

Strategies without sufficient rollback are rejected or blocked.

## 15. Validation Planning

Repair Planner describes but does not run pre-repair, post-repair, rollback,
and resume checks. These may cover:

- artifact readability, schema, checksums, and dependencies;
- checkpoint integrity;
- ffprobe, duration, codecs, frame rate, and audio;
- A/V synchronization;
- caption timing and framing;
- technical and creative output quality;
- unit, integration, regression, API, and frontend checks;
- rights, safety, and workflow readiness.

Missing validation never becomes a pass. Any failed required check blocks
acceptance.

## 16. Output-Quality Preservation

Quality plans preserve:

- the correct source section and complete story meaning;
- duration, resolution, frame rate, audio, and codecs;
- A/V sync, captions, and intentional vertical framing;
- complete frames/audio without duplication or truncation;
- truthful metadata and visible failures.

Silent quality reduction is forbidden. Fallback completion alone is never
acceptance. Unacceptable degradation rejects the output and triggers rollback.

## 17. Safety and Rights Constraints

Unknown rights, blocked rights, and required permission remain blocked. The
planner never proposes DRM, access-control, platform, rights, or safety bypass.

External uploads, paid providers, destructive actions, and legal decisions
require explicit human approval. Warnings cannot be hidden or removed.

## 18. Approval Gates

Every case has an approval gate. V1 grants no execution approval.

Read-only report access, comparison, safe export, and keeping processing
stopped may occur without execution approval. Future modification, retry,
fallback, installation, restart, patch, validation, and resume actions require
the applicable checkpoint, rollback, validator, quality, rights, safety, code
review, and final human approval.

## 19. Rejected Unsafe Strategies

Rejected records are created for:

- source-media modification or deletion;
- unlimited retries;
- silent quality reduction;
- execution without checkpoint or rollback;
- direct patching of `main`;
- rights or safety bypass;
- missing required validation;
- credential or private-path exposure;
- unapproved external/paid providers;
- unsupported destructive data actions.

Rejected strategies are never presented as recommended.

## 20. Execution Handoffs

Advisory handoffs may target:

- Tool Recovery Brain;
- Code Surgeon;
- Validator Runner;
- Artifact Inspector;
- Report Reader;
- Safety Gate;
- Rights + Permission Gate;
- Workflow Controller;
- Checkpoint Recovery Manager;
- Output Quality Reviewer;
- human operator.

Every handoff has `apply_automatically=false` and
`human_approval_required=true`. Workflow Controller independently decides
whether resume is safe after every required gate passes.

## 21. API Routes

- `POST /api/v1/boba/projects/{project_id}/repair-planner`
- `GET /api/v1/boba/projects/{project_id}/repair-planner`
- `GET /api/v1/boba/projects/{project_id}/repair-planner/export`
- `DELETE /api/v1/boba/projects/{project_id}/repair-planner`

POST reads saved Root Cause Analyzer data and accepts optional bounded
`planning_context` and `dry_run`. GET returns saved data or a clear 404.

## 22. Artifact Path

Repair Planner persists atomically at:

`work/boba/projects/<project_id>/repair_planner/index.json`

The report is compact, bounded, schema-versioned, and contains no raw media,
full logs, complete upstream report, secrets, credentials, or tokens.

## 23. Export and Reset

Safe export removes private paths, sensitive evidence, prior-attempt details,
manual context, complete diagnostic reports, logs, transcripts, media, and
credentials.

Reset removes only the Repair Planner artifact. Root Cause Analyzer, Error
Doctor, Observer, and all other BOBA artifacts remain unchanged.

## 24. Validator Commands

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_repair_planner.py --self-check
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_repair_planner.py --synthetic-project
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_repair_planner.py --project-id PROJECT_ID
```

Generated reports are written under:

`work/validation_reports/boba_repair_planner/`

They are local ignored artifacts and must not be committed.

## 25. Limitations

- V1 plans only and does not verify that a future repair will succeed.
- Ranking quality depends on persisted Root Cause Analyzer evidence.
- Registries are bounded local capability descriptions, not live tool checks.
- Checkpoints and validators are not inspected or executed dynamically.
- No repair executor, Tool Recovery Brain, Code Surgeon, Validator Runner,
  Checkpoint Recovery Manager, Quality Reviewer, or Workflow Controller is
  invoked.
- Manual approval remains required before any future executable action.
- Production readiness is not claimed.
