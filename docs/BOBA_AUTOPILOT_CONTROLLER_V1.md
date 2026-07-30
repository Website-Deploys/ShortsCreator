# BOBA Autopilot Controller V1

## 1. Purpose

BOBA Autopilot Controller V1 coordinates Olympus diagnostic and recovery
modules through a persisted, bounded state machine. Its purpose is to turn
separate BOBA reports into one auditable internal recovery cycle without
granting BOBA unrestricted system control.

## 2. What Autopilot Controller Does

The controller captures a bounded project snapshot, selects the next typed
module operation, advances eligible read-only analysis, waits for exact
target-module approvals, records incidents and decisions, enforces budgets,
coordinates approved calls, routes quality outcomes, and prepares future
handoffs.

It coordinates these existing modules:

- BOBA Observer
- BOBA Error Doctor
- BOBA Root Cause Analyzer
- BOBA Repair Planner
- BOBA Code Surgeon
- BOBA Tool Recovery Brain
- BOBA Output Quality Reviewer

## 3. What It Does Not Do

Autopilot V1 does not directly execute commands, Git, or FFmpeg. It does not
modify code, approve repairs, install software, restore checkpoints, resume
Olympus, upload or publish content, push or merge code, deploy changes, use
external services, or bypass rights and safety gates.

## 4. Why Autopilot Is Not Unrestricted Autonomy

The controller accepts only an explicit registry of module names and
operations. Actions outside that registry are prohibited. Read-only actions
may advance automatically under policy; execution-capable actions require an
exact approval created and revalidated by the target module. Hard budgets,
project snapshots, locks, checkpoints, loop detection, and human stop controls
bound every run.

## 5. Difference From Workflow Controller

Autopilot coordinates an internal diagnostic and recovery cycle. A future
Workflow Controller remains responsible for deciding whether the Olympus
pipeline may resume or move to another workflow stage. An Autopilot `continue`
operation continues controller coordination only; it never resumes Olympus.

## 6. Difference From Safety Gate

Autopilot reads persisted safety state and stops when that state is blocked,
unknown, or unsuitable for the requested action. A future Safety Gate remains
the independent enforcement layer for final safety eligibility. Autopilot can
prepare a Safety Gate handoff but cannot approve it.

## 7. Difference From Final Decision Bus

The Final Decision Bus is a future consumer of bounded evidence and decisions.
Autopilot may prepare a handoff for it but does not make release, publication,
deployment, or production-completion decisions.

## 8. Difference From Tool Recovery Brain

Tool Recovery owns registered tools, recovery strategies, exact recovery
approval, bounded execution, validation, and rollback. Autopilot chooses when a
typed Tool Recovery operation is appropriate and coordinates only the exact
approved operation. It does not construct or run Tool Recovery commands.

## 9. Difference From Code Surgeon

Code Surgeon owns patch proposals, path policy, exact patch approval, isolated
worktrees, validation, rollback, and optional local commit preparation.
Autopilot references the exact proposal and approval but never writes a patch,
modifies `main`, pushes, merges, or deploys.

## 10. Control Modes

- `advisory_only`: inspects and plans without invoking modules or acquiring the
  state-changing project lease.
- `safe_read_only_automatic`: may invoke registered read-only diagnostic
  generation and inspection operations.
- `approved_execution_coordination`: adds coordination of exact approved Code
  Surgeon or Tool Recovery operations.
- `manual_step`: reserved for bounded operator-directed coordination.

No mode grants unrestricted command execution.

## 11. State Machine

The persisted graph has 32 states:

1. `created`
2. `inspecting_project`
3. `rights_review_required`
4. `safety_review_required`
5. `observer_required`
6. `diagnosis_required`
7. `root_cause_analysis_required`
8. `repair_planning_required`
9. `awaiting_repair_decision`
10. `awaiting_execution_approval`
11. `code_repair_ready`
12. `tool_recovery_ready`
13. `checkpoint_recovery_required`
14. `approved_execution_pending`
15. `execution_running`
16. `execution_failed`
17. `rollback_required`
18. `rollback_running`
19. `rollback_failed`
20. `technical_validation_required`
21. `output_quality_review_required`
22. `human_quality_review_required`
23. `repair_replanning_required`
24. `root_cause_reanalysis_required`
25. `awaiting_safety_gate`
26. `ready_for_workflow_controller`
27. `completed_internal_cycle`
28. `paused`
29. `cancelled`
30. `blocked`
31. `failed`
32. `unknown`

Every transition is explicitly allowlisted and persisted. Diagnostic,
approval, technical validation, quality review, and handoff states cannot be
silently skipped.

## 12. Action Classes

- `automatic_read_only`: bounded inspection or generation through the typed
  module registry.
- `approval_required_read_only`: a read-only target operation whose module
  policy still requires explicit approval.
- `approval_required_execution`: Code Surgeon or Tool Recovery execution owned
  by the target module.
- `future_gated`: a handoff that V1 may prepare but cannot apply.
- `prohibited`: an unknown, arbitrary, destructive, publication, workflow
  resume, or otherwise disallowed request.

## 13. Safe Automatic Analysis

Observer, Error Doctor, Root Cause Analyzer, and Repair Planner generation may
run automatically only when:

- the run mode permits read-only automation;
- rights and safety preflight are clear;
- the project snapshot still matches;
- the action is in the typed registry;
- the budget remains available;
- no active conflicting run or loop exists.

Malformed output, insufficient evidence, conflicting evidence, stale state, or
module failure stops progression and preserves an incident.

## 14. Approval-Required Execution

Execution-capable actions are never triggered by `advance-safe`. They remain in
an approval state until an exact Code Surgeon or Tool Recovery approval record
is supplied. The run must also permit execution coordination, retain budget,
match the planned snapshot, and satisfy checkpoint and rollback requirements.

## 15. Exact Target-Module Approval

Code Surgeon approvals bind the repair case, patch proposal, approval type,
base commit SHA, diff SHA, path scope, special paths, validation commands,
expiration, and explicit confirmation.

Tool Recovery approvals bind the recovery case, plan, one strategy, registered
tool, settings, retry budget, time budget, quality requirements, checkpoint
reference, expiration, and exact confirmation text.

Autopilot stores a bounded approval binding but cannot create the approval.
The target module independently revalidates it when invoked. Any mismatch,
expiry, snapshot change, plan change, strategy change, patch change, or base
change blocks execution.

## 16. Project Snapshots

Each run captures bounded identities and states for the rights gate, Observer,
Error Doctor, Root Cause Analyzer, Repair Planner, Code Surgeon, Tool Recovery,
and Output Quality Reviewer. It also records workflow stage, accepted output
IDs, sanitized source references, active recovery operations, stale or missing
artifacts, rights state, safety state, and a deterministic SHA-256 digest.

Snapshots do not include raw media or unbounded logs.

## 17. Concurrency and Locking

Only one state-changing Autopilot run may hold the local project lease.
Advisory-only inspection may coexist because it cannot execute or advance
state-changing operations. Lock creation is exclusive, refresh is owner/run
bound, active locks cannot be stolen, and stale locks require explicit
confirmation before replacement. A confirmed stale lock is preserved for
audit.

## 18. Recovery Budgets

Each run has hard limits for:

- total actions and execution actions;
- module invocations and retries;
- identical failed retries;
- total and execution duration;
- risk score;
- Code Surgeon attempts;
- Tool Recovery attempts;
- quality reviews;
- replanning cycles;
- root-cause reanalysis cycles.

Warnings are emitted at 70% and 90%. Exhaustion pauses or blocks further work.
A budget reset is a separate human-approved action, creates a new budget
record, and preserves prior usage and incidents.

## 19. Loop Detection

Every action has a deterministic fingerprint bound to project, run, action
type, target module, operation, target plan, target strategy, and snapshot.
The controller detects completed duplicates, repeated identical failures, and
A-B-A state loops. New evidence changes the fingerprint and can justify a new
bounded attempt; unchanged evidence does not.

## 20. Checkpoint Requirements

Execution planning records whether a checkpoint is required, its bounded
reference and digest, preservation requirements, checkpoint status, and
rollback readiness. Missing, stale, corrupt, invalid, or unverified required
checkpoints block execution. Autopilot does not create or restore checkpoints;
it prepares a Checkpoint Recovery Manager handoff.

## 21. Code Surgeon Coordination

Autopilot may request proposal-only or proposal validation work as registered
read-only operations. Exact approved execution is coordinated only after
snapshot, rights, safety, budget, approval, checkpoint, and rollback checks.
Code Surgeon performs and independently validates the isolated operation.
Technical success still routes to Output Quality Reviewer.

## 22. Tool Recovery Coordination

Autopilot may request Tool Recovery planning or health checks as registered
read-only work. Execution, output validation, fallback, and rollback remain
bound to exact Tool Recovery records and approval. A technical pass is not
final quality acceptance. Failure routes to rollback, replanning, reanalysis,
or a human stop according to persisted evidence.

## 23. Output Quality Reviewer Coordination

Artifact-only review may run automatically when a concrete output reference is
available. Other review modes remain policy and approval bound. Decisions route
as follows:

- technical rejection to root-cause reanalysis;
- creative or regression rejection to repair replanning;
- missing evidence to Validator Runner and human review;
- subjective uncertainty to human quality review;
- rights or safety blocks to their respective gates;
- internal acceptance to bounded Safety Gate and Workflow Controller handoffs.

## 24. Failure and Rollback Handling

Failures create bounded incidents and events with target module, action,
evidence IDs, severity, and protected-state risk. Autopilot never performs a
rollback directly. It invokes only the target module's registered approved
rollback operation. Rollback failure blocks the run and requires human review.

## 25. Human Decisions

The API accepts only bounded decision names such as reject, select an
alternative, request more evidence, pause, cancel, approve a disclosed quality
limitation, approve a budget reset, or acknowledge uncertain state. Reviewer
identity is stored as a digest. Credentials and arbitrary commands are not
stored. Human quality approval cannot publish, and budget approval cannot
bypass rights or safety.

## 26. Internal-Cycle Completion

`completed_internal_cycle` means only that Autopilot's bounded diagnostic,
recovery, validation, quality, and future-handoff preparation is complete.
It does not mean Olympus resumed, production completed, content uploaded, or
content published.

## 27. Live Event Stream

Events use monotonic per-run sequence numbers and bounded technical and
easy-language messages. Progress is derived only from persisted action counts;
it remains null when no real action basis exists. Facts and assessments are
separate fields. Events never include raw logs, credentials, secrets, or
private absolute paths.

## 28. API Routes

Base path: `/api/v1/boba/projects/{project_id}/autopilot`

- `POST /runs`
- `POST /runs/{run_id}/plan-next`
- `POST /runs/{run_id}/advance-safe`
- `POST /runs/{run_id}/coordinate-approved`
- `POST /runs/{run_id}/pause`
- `POST /runs/{run_id}/continue`
- `POST /runs/{run_id}/cancel`
- `POST /runs/{run_id}/human-decision`
- `POST /runs/{run_id}/budget-reset-request`
- `GET /`
- `GET /runs/{run_id}`
- `GET /runs/{run_id}/events`
- `GET /export`
- `DELETE /`

The routes reject unknown projects or runs, conflicts, stale actions, invalid
transitions, approval mismatches, exhausted budgets, loops, invalid
checkpoints, uncertain protected state, arbitrary modules or operations,
workflow resume, and publication requests.

## 29. Artifact Paths

Under the configured BOBA project storage root:

- controller set: `<project_id>/autopilot_controller/index.json`
- run record: `<project_id>/autopilot_controller/runs/<run_id>/index.json`
- append-only events:
  `<project_id>/autopilot_controller/runs/<run_id>/events.jsonl`
- active lease: `<project_id>/autopilot_controller/active.lock.json`
- confirmed stale leases:
  `<project_id>/autopilot_controller/active.lock.stale.<id>.json`

Validation reports are written to
`work/validation_reports/boba_autopilot_controller/` and are ignored.

## 30. Export and Reset

Exports are JSON-safe, bounded, path-sanitized, and secret-sanitized. They
exclude raw media and full command output. Reset removes Autopilot metadata
only and refuses unsafe removal while a run is active. It does not delete
upstream BOBA reports, source media, accepted outputs, patches, Code Surgeon
worktrees, Tool Recovery workspaces, or checkpoints.

## 31. Validator Commands

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_autopilot_controller.py --self-check
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_autopilot_controller.py --synthetic-project
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_autopilot_controller.py --project-id PROJECT_ID
```

Self-check validates imports, contracts, registry construction, local event and
lock persistence, and prohibited capabilities. Synthetic mode runs exactly 120
named offline scenarios with temporary storage and mocked typed module
integrations. Project mode inspects persisted metadata without advancing it.

## 32. Limitations

- V1 coordinates existing modules; it is not unrestricted autonomy.
- Safety Gate, Workflow Controller, Final Decision Bus, Checkpoint Recovery
  Manager, and Live Companion remain future enforcement or presentation
  layers.
- Autopilot cannot approve a target-module repair.
- It cannot directly execute commands, Git, or FFmpeg.
- It cannot modify code, install software, restart services, or kill processes.
- It cannot restore checkpoints or resume Olympus.
- It cannot access external services, download media, upload, or publish.
- It cannot push, merge, tag, or deploy.
- It cannot bypass rights or safety.
- Human approval remains required for execution.
- Internal-cycle completion is not production completion.
