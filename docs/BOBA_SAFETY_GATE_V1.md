# BOBA Safety Gate V1

## 1. Purpose

BOBA Safety Gate V1 is the final evaluation boundary before an
execution-capable BOBA module may receive coordination for one approved
internal action. It turns bounded project, approval, rights, checkpoint,
validation, quality, budget, and risk evidence into an evidence-linked decision.

An allowance is not a guarantee that an action will succeed or preserve output
quality. It is temporary, exact, non-transferable, and revocable.

## 2. What Safety Gate Does

Safety Gate:

- validates an exact action request and project snapshot;
- checks the registered target module, operation, and action class;
- verifies exact approval-bound plan, strategy, patch, tool, settings, budget,
  checkpoint, validation, and quality identities;
- evaluates rights, rollback, protection, validation, quality, budget, and risk;
- produces a scoped decision, constraint record, risk assessment, and handoff;
- revalidates or invalidates a prior decision after meaningful state changes;
- persists bounded immutable policy and decision history.

## 3. What Safety Gate Does Not Do

Safety Gate evaluates but does not execute. It does not run commands, Git,
FFmpeg, target modules, validators, repairs, or recovery tools. It does not
modify code, configuration, project artifacts, source media, or accepted
outputs.

V1 does not restore checkpoints, resume Olympus, install software, restart
services, access external services, upload or publish content, or push, merge,
deploy, release, or tag code.

## 4. Difference From Rights + Permission Gate

Rights + Permission Gate determines whether a source may be processed under
the recorded ownership, permission, provenance, and safety state. Safety Gate
consumes that evidence as one mandatory policy layer for media-relevant
actions.

Safety Gate cannot create rights, reinterpret unknown rights as approval, or
bypass a rights block. It also evaluates concerns beyond rights, such as exact
approval binding, rollback, validation, quality, budgets, and technical risk.

## 5. Difference From Autopilot Controller

Autopilot Controller coordinates bounded BOBA state transitions and registered
target-module invocations. Safety Gate only evaluates the exact action that
Autopilot proposes.

An Autopilot request alone is insufficient. For approval-coordinated execution,
Autopilot first verifies the target-module approval and then requires a current
Safety Gate decision for the exact action. A denied, expired, invalidated,
human-review, or more-evidence decision cannot be reinterpreted as allowance.

## 6. Difference From Workflow Controller

A future Workflow Controller may own checkpoint recovery and workflow
continuation. Safety Gate V1 does not own either capability.

Workflow resume and checkpoint restore are future-gated actions. Safety Gate
may explain a safe handoff, but `workflow_resume_authorized` and
`checkpoint_restore_authorized` always remain false.

## 7. Difference From Final Decision Bus

The Final Decision Bus combines editorial or release-facing conclusions.
Safety Gate makes a narrow technical policy decision about one exact internal
action. It does not decide that media is publishable, legally safe, viral, or
production-ready.

## 8. Safety Policy Hierarchy

Policy is applied in this order:

1. absolute prohibitions;
2. rights and permission restrictions;
3. source-media and accepted-output protection;
4. human approval requirements;
5. exact action binding;
6. checkpoint and rollback requirements;
7. validation requirements;
8. quality-preservation requirements;
9. recovery budget limits;
10. project-state consistency;
11. module-specific restrictions;
12. risk threshold;
13. advisory preferences.

A lower layer cannot override a denial from a higher layer.

## 9. Absolute Prohibitions

V1 denies rights or safety bypass, DRM/access-control bypass, source-media
deletion or overwrite, accepted-output overwrite, direct protected-main
modification, force push, automatic merge/deployment/publication/upload,
secret exposure, arbitrary commands, destructive Git, unlimited retries,
hidden quality reduction, required-validation removal, unapproved external or
paid providers, and out-of-scope modification.

Human review cannot override an absolute prohibition.

## 10. Future-Gated Actions

V1 returns `unsupported_future_action` for workflow resume, checkpoint restore,
remote PR creation, push, merge, deployment, publication, upload, package
installation, service restart, production configuration changes, database
migration, and destructive cleanup.

These actions may produce an advisory handoff. They are never allowed by V1.

## 11. Potentially Allowlisted Internal Actions

Registered read-only generation and inspection may be considered for Observer,
Error Doctor, Root Cause Analyzer, Repair Planner, Code Surgeon proposal and
validation, Tool Recovery planning and health checks, and artifact-only Output
Quality review.

Exact approval-coordinated allowance may be considered for Code Surgeon
isolated execution or local review commit, Tool Recovery execution or rollback,
bounded Autopilot budget reset, and approved read-only technical inspection.
Every required control must pass.

## 12. Exact Action Requests

`BobaSafetyActionRequestV1` binds:

- project, Autopilot run, and Autopilot action;
- requesting module, target module, operation, and action class;
- bounded action description and parameter digest;
- project snapshot ID and digest;
- plan, strategy, approval, patch, base SHA, tool, and capability;
- configuration, checkpoint, rollback, validation, quality, retry, and time
  references.

Requests contain references and digests, not raw patches, media, secrets,
commands, private absolute paths, external URLs, or full configuration values.

## 13. Project Snapshots

Every request requires an exact project snapshot ID and SHA-256 digest.
Autopilot-backed requests resolve their snapshot from the persisted controller.

Missing, stale, conflicting, or changed snapshots block or invalidate the
decision. Relevant changes to source protection, accepted outputs, approval-
bound artifacts, rights, or active-run state also invalidate reuse.

## 14. Target-Module Approvals

Safety Gate verifies the approval record owned by the target module. Code
Surgeon and Tool Recovery retain their existing approval contracts and
independent verification.

Approval must exist, be explicit, unexpired, and match the exact project,
snapshot, plan, strategy, patch, base SHA, tool, capability, settings, retry
budget, time budget, checkpoint, and quality requirements that apply.

Safety Gate cannot create target approval, and a Safety Gate decision cannot
replace target approval. Target modules must independently revalidate both.

## 15. Rights and Permission Checks

Media-relevant actions require current rights and permission evidence that
allows the requested local processing scope. Unknown, blocked, permission-
required, or stale evidence blocks the action.

Code-only advisory actions do not fabricate irrelevant media rights. Upload and
publication remain unauthorized for every decision. Safety Gate does not claim
legal or copyright certainty.

## 16. Checkpoint and Rollback Checks

Read-only actions may record that no checkpoint is required. Execution actions
must provide the required current, validated checkpoint and a ready,
non-destructive rollback plan.

Missing, stale, corrupt, unverified, or mismatched checkpoints block execution.
Missing or unsafe rollback, source-media risk, and accepted-output risk also
block. Safety Gate records readiness but never restores a checkpoint or runs a
rollback.

## 17. Validation Readiness

Execution requires a bounded validation plan with required validators,
availability, pre-action checks, post-action checks, rollback checks,
acceptance criteria, and rejection criteria.

Unavailable or skipped required validators, missing criteria, missing rollback
checks, and weakened validation block the action. Optional unavailable checks
remain visible. Safety Gate never invokes validators.

## 18. Quality Preservation

Quality review binds non-negotiable requirements, approved degradations,
baseline requirements, and the exact quality-plan identity.

Silent resolution or frame-rate reduction, audio or caption removal, source-
window changes, sync regression, and meaning/payoff regression block. A
disclosed minor limitation may require scoped human review; technical success
alone does not prove quality. Safety Gate never modifies an output.

## 19. Budget Enforcement

Safety Gate consumes bounded project-wide action, execution, retry, time, and
module-attempt budget evidence. Exhaustion blocks further execution.

A budget reset requires separate exact approval, remains inside hard policy,
preserves history, and creates a new reference. It cannot erase a loop block or
permit unlimited retries.

## 20. Risk Assessment

Risk factors record category, severity, likelihood, evidence, mitigations,
residual risk, blocking state, and human-review need. Overall score is bounded
from 0 to 100 and maps deterministically to minimal, low, medium, high,
critical, or blocked risk.

Mitigations can reduce risk but cannot erase contradictory evidence or a hard
prohibition. Scores are policy guidance, not certainty.

## 21. Decision Types

V1 can return:

- `allowed_for_internal_read_only`;
- `allowed_for_exact_internal_execution`;
- `denied`;
- `human_review_required`;
- `more_evidence_required`;
- `blocked_rights`;
- `blocked_safety_policy`;
- `blocked_stale_state`;
- `blocked_budget`;
- `blocked_checkpoint`;
- `blocked_validation`;
- `blocked_quality`;
- `unsupported_future_action`;
- `invalid_request`;
- `expired`;
- `invalidated`.

Each decision includes conditions, unmet conditions, denial reasons, expiry,
confidence, and a plain-language summary.

## 22. Decision Digests

Canonical JSON and SHA-256 bind the request and decision to stable bounded
content. The decision records request, project snapshot, policy, and approval
identity.

The same bounded input produces the same digest. A changed parameter, plan,
strategy, patch, tool, configuration, checkpoint, validation, quality, budget,
rights state, or policy produces a mismatch or invalidation.

## 23. Expiry and Invalidation

Default maximum TTLs are 900 seconds for read-only allowance, 300 seconds for
execution allowance, and 1,800 seconds for human-review decisions. A stricter
project policy may shorten these limits.

Expired decisions cannot be used. Revalidation checks the current request,
snapshot, policy, approval, and supplied bindings. Invalidation appends a
separate record and preserves the original immutable decision.

## 24. Human Review

Human review is bound to the exact safety case, request digest, and snapshot
digest. Reviewer identity is bounded and hashed in persisted review evidence;
credentials and tokens are rejected.

A reviewer may deny, request more evidence, acknowledge a disclosed limitation,
select a safer alternative, or approve an otherwise policy-permitted scoped
action. Review cannot authorize publication, rights bypass, source
modification, accepted-output overwrite, or another hard prohibition.

## 25. Code Surgeon Evaluation

Proposal and validation operations are read-only candidates. Isolated patch
execution requires the exact Code Surgeon approval, proposal ID, diff SHA-256,
base commit SHA, scope, checkpoint, rollback, validation, quality, and budget
evidence.

Creating a local review commit requires separate approval. A local commit never
authorizes push, merge, deployment, or direct protected-main modification.

## 26. Tool Recovery Evaluation

Planning and health checks are read-only candidates. Execution requires the
exact approved recovery plan, selected strategy, tool, capability, temporary
settings, retry budget, time budget, quality requirements, checkpoint, and
rollback.

A changed fallback or tool invalidates the decision. Recovery output protection
and rollback ownership remain with Tool Recovery; Safety Gate invokes neither.

## 27. Output Quality Evaluation

Artifact-only review can receive read-only allowance. Local technical
inspection requires exact approval and remains read-only. Safety Gate consumes
the review plan and quality evidence but does not inspect media directly,
execute validators, accept an output, or change the output.

## 28. Autopilot Integration

Approval-coordinated Autopilot actions require `safety_decision_id`. Autopilot
first verifies the target-module approval, then calls Safety Gate
revalidation for the exact current action before target invocation.

Autopilot checks decision identity, value, validity, expiry, run, action,
target, operation, and parameter digest. Safety denial, expiry, invalidation,
human review, or missing evidence emits a truthful event and blocks target
invocation.

## 29. Handoffs

Allowed decisions route back to Autopilot with target revalidation required.
Denials and missing evidence may route to Repair Planner, Root Cause Analyzer,
Validator Runner, Checkpoint Manager, Rights Gate, Output Quality Reviewer, or
a human operator.

Workflow future actions route only as advisory handoffs to a future Workflow
Controller. Execution handoffs keep `apply_automatically=false`.

## 30. API Routes

The BOBA API exposes:

- `POST /projects/{project_id}/safety-gate/policies`;
- `POST /projects/{project_id}/safety-gate/requests`;
- `POST /projects/{project_id}/safety-gate/evaluate`;
- `POST /projects/{project_id}/safety-gate/decisions/{id}/revalidate`;
- `POST /projects/{project_id}/safety-gate/decisions/{id}/invalidate`;
- `POST /projects/{project_id}/safety-gate/evaluations/{id}/human-review`;
- `GET /projects/{project_id}/safety-gate`;
- `GET /projects/{project_id}/safety-gate/evaluations/{id}`;
- `GET /projects/{project_id}/safety-gate/decisions/{id}`;
- `GET /projects/{project_id}/safety-gate/export`;
- `DELETE /projects/{project_id}/safety-gate`.

These routes create, evaluate, inspect, revalidate, record, export, or reset
metadata. They do not execute the proposed action.

## 31. Artifact Paths

Active metadata:

`work/boba/projects/{project_id}/safety_gate/index.json`

Immutable or append-preserved records:

- `safety_gate/policies/{policy_snapshot_id}.json`;
- `safety_gate/evaluations/{safety_case_id}/index.json`;
- `safety_gate/decisions/{safety_decision_id}/index.json`.

The exact prefix is relative to the configured `BobaMemoryStore` root.

## 32. Export and Reset

Export is JSON-safe and removes secrets, credentials, tokens, private absolute
paths, raw patches, raw media, commands, stdout/stderr, and full command logs.
It explicitly reports that execution, workflow resume, and publication were
not used.

Reset removes only the active Safety Gate `index.json`. It preserves immutable
policy, evaluation, decision, and invalidation history, upstream BOBA
artifacts, approvals, Autopilot history, source media, and accepted outputs.

## 33. Validator Commands

Run the offline self-check:

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_safety_gate.py --self-check
```

Run all 179 synthetic scenarios:

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_safety_gate.py --synthetic-project
```

Inspect one persisted project without executing anything:

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_safety_gate.py --project-id PROJECT_ID
```

Reports are written under `work/validation_reports/boba_safety_gate/` and must
not be committed.

## 34. Limitations

Safety Gate V1 is deterministic, local, and evaluation-only. It depends on the
truth and freshness of persisted upstream evidence. It does not independently
prove legal rights, copyright safety, repair success, output quality,
production readiness, or publication readiness.

V1 does not execute actions, access networks or external services, install
software, restore checkpoints, resume workflows, upload or publish content, or
push, merge, deploy, release, or tag code. Future owners must add their own
policy and approval boundaries rather than treating a V1 handoff as authority.
