# BOBA Repair Plan Panel V1

## 1. Purpose

The Repair Plan Panel is a specialized read-only mode of the BOBA Review UI and
the BOBA Error Doctor Panel. It projects the repair plans that Repair Planner
already persisted, links every statement to the canonical record that owns it,
shows the proposed steps without exposing command text, shows the approvals and
verification the owner requires, shows linked recovery history, lets a reviewer
compare plans field by field, and routes one non-authoritative action to its
real owning module.

## 2. Authority boundary

The panel does not generate a repair plan, revise one, approve or reject one,
execute a plan or a step, start a recovery attempt, retry a tool, restore a
checkpoint, restart a process, transition a workflow, modify code, artifacts or
media, run a command, shell, PowerShell, Git or FFmpeg, install or download a
tool, create Rights, Safety or Final Decision approvals, upload or publish.

It is not a second Repair Planner. Repair Planner proposed every plan shown, and
the panel never states that a plan is the correct repair.

## 3. Repair plan identity

A repair plan is one Repair Planner **repair strategy**. Its identity is the
`repair_strategy_id`, carried alongside its `repair_case_id`. A planning case
holds many strategies, so the case id alone could not identify a reviewed plan.

## 4. Ownership chain

```
Error Doctor case        -> diagnostic_case_id
Root Cause Analyzer case -> analysis_case_id     (source_diagnostic_case_id)
Repair Planner case      -> repair_case_id       (source_analysis_case_id)
Repair Planner strategy  -> repair_strategy_id   (the reviewed repair plan)
Repair Planner step      -> repair_step_id with order
Tool Recovery case       -> recovery_case_id     (source_repair_case_id)
Code Surgeon case        -> code_repair_case_id  (source_repair_case_id)
```

## 5. Review UI and Error Doctor integration

`BobaRepairPlanReviewPanel` is mounted at all four project results render sites,
immediately after the Error Doctor Panel. The global Review UI workspace, the
Candidate Review Panel, the Clip Brief Panel and the Error Doctor Panel are all
left in place. The mount variable is `repairPlanReviewPanel`, deliberately
distinct from the pre-existing local `errorDoctorPanel` and `clipBriefPanel`
variables in `ResultsSection.tsx`.

The panel reuses Review UI's digest, id, text-sanitisation, payload-sanitisation,
private-path and workflow-run helpers, and the Error Doctor Panel's
bounded-excerpt and secret-redaction helpers, so semantics stay byte-identical
across both reliability panels. It opens no second event stream.

## 6. Source modules

Fourteen fixed sources are read through fixed `BobaMemoryStore` loaders: Repair
Planner, Root Cause Analyzer, Error Doctor, Observer, Code Surgeon, Tool
Recovery, Validator Runner, Report Reader, Artifact Inspector, Output Quality
Reviewer, Workflow Controller, Safety Gate, Final Decision Bus and Autopilot
Controller. Only Repair Planner is required, because it owns the plan identity.
Autopilot Controller is advisory only and never authorises a repair.

A browser request cannot add a source, an action, a module, an operation, a URL,
a path or a command. The registry is fixed source code.

## 7. Command withholding

`BobaRepairStepV1.target` and `BobaRepairRollbackPlanV1.rollback_steps` may hold
literal command text, so **neither is ever projected into a browser payload**.
When a step description is itself command-like, the panel emits the fixed notice
instead of the text rather than redacting inline, because a partially redacted
command can still leak a fragment.

Detection combines the shell-metacharacter set transcribed from Tool Recovery,
an executable-name allowlist and a flagged-argument pattern. The matched text is
never returned. Contracts pin `raw_command_exposed`, `private_path_exposed` and
`executable_by_panel` to `False`.

## 8. Required notices

Four notices are fixed strings, asserted in the backend, the validator, the unit
tests and the frontend tests:

- `Command details withheld from the review panel.`
- `Private path details redacted.`
- `This step cannot be executed from this panel.`
- `Full source record retained by Repair Planner.`

## 9. Truthfulness rules

- Repair Planner proposed this strategy; it is not "the correct repair".
- A source status is never strengthened.
- Reversible does not mean risk-free.
- An available rollback plan does not mean a rollback is guaranteed.
- Owner-reported success is not independent verification.
- Recovered is not resolved.
- A completed plan is not a verified plan.

## 10. Contracts

Twenty-two contracts are defined, all `extra="forbid"`: registry snapshot, plan
reference, review session, queue item, plan snapshot, step projection, risk
projection, approval requirement, verification requirement, evidence card,
recovery link, conflict record, comparison, action descriptor, action request,
action receipt, event, timeline entry, notification, summary, signal usage and
the aggregate set.

## 11. Contract-level refusals

- An approval requirement cannot be `satisfied_by_owner` without a canonical
  owner record **and** digest.
- A verification requirement cannot be `independently_verified` unless it is
  `satisfied`.
- A recovery link cannot be `completed` without `attempted`, and cannot be
  `independently_verified` without `succeeded_by_owner`.
- A step projection cannot set any exposure flag to true.
- A risk projection cannot unset `reversible_does_not_mean_risk_free`.
- Every signal-usage write flag is `Literal[False]`.

## 12. Absent owner fields

Repair Planner records no strategy revision identity, no supersession marker and
no historical archive. `repair_plan_revision_id` and
`superseding_repair_plan_id` therefore stay `None`, and `stale`, `historical` and
`superseded` stay explicitly `False`. None of them is inferred from ordering or
timestamps. It records no per-step lifecycle status and no per-step rationale, so
`original_status` is always `proposed` and `bounded_reason` is always empty.

## 13. List-typed owner prose

Several plan documents record prose as `list[str]` (`rollback_validation`,
`comparison_baseline`). `joined_owner_text` flattens them into sentences so no
Python list repr ever reaches a browser payload.

## 14. Step projections

Steps are projected in the owner's own `order` (bounded 1–64). Derived flags for
tool execution, process restart, checkpoint restore, workflow transition and
artifact change come from the owner's declared step type and flags, never from
guesswork. Every step carries `requires_human_approval` and the
not-executable notice.

## 15. Risk projections

All twelve named owner risk dimensions are projected verbatim, plus the
strategy-specific risk row when the owner names this exact strategy. The owner's
confidence float is shown unchanged and labelled as the owner's own number. The
panel computes **no** composite risk score and **no** repair-success estimate.

## 16. Approval requirements

Requirements are derived only from the owner's approval gate and the strategy's
own declared flags. Rollback-plan and validation-plan requirements can be
satisfied by the owner's own plan documents, which supply a real canonical record
and digest. Human review, Safety Gate, Rights Gate and Output Quality can never
be satisfied here, because no canonical record binds those decisions to a repair
strategy identity.

Repair Planner's approval-status vocabulary is `planning_only`,
`awaiting_human_review`, `blocked`, `not_required_for_no_action` and `unknown`.
It has **no approved value**, so an approved repair plan can never be displayed.

## 17. Verification requirements

Pre-repair checks, post-repair checks, required validators, checkpoint
validation, rollback validation, artifact inspection and output-quality checks
are projected. A required-validator requirement is satisfied only when Validator
Runner's own results report every named validator as passed.
`independently_verified` is always false: the panel verifies nothing itself.

## 18. Evidence cards

Cards are built from the strategy, planning case, risk assessment, approval gate,
rollback plan, checkpoint plan, validation plan, quality preservation plan,
execution handoffs, rejected strategies, root-cause case and candidates,
diagnostic case, Tool Recovery cases, Code Surgeon cases, validator results and
the workflow run. Safety Gate, Final Decision Bus and Output Quality Reviewer
cards are always marked `missing` with an explicit reason: their records carry no
repair-strategy identity. Rollback card excerpts are always empty.

## 19. Linked recovery history

Tool Recovery attempts are reached through the plan's repair case.
`linked_by_strategy_id` records whether the owner named this exact strategy, and
a case-only link carries an explicit warning. A sibling strategy's recovery
success is never inherited: `completed` requires both `succeeded_by_owner` and
`linked_by_strategy_id`.

## 20. Conflict detection

Seventeen conflict conditions are detected across duplicate plan identity,
disagreeing analysis and incident parents, approval-status contradictions,
destructive-flag contradictions, rollback contradictions, verification
contradictions, recovery-status contradictions, strategy-recommendation
disagreement, lifecycle contradictions and workflow-stage disagreement.

A conflict is reported only between records naming the **same exact identity**,
and is never resolved by comparing confidence, risk or recency.

## 21. Queue and display tiers

Fourteen deterministic display tiers order plans for review. A tier is a display
order, never a score, a plan ranking or a repair-success estimate. Eighteen
filters and six sorts are supported; an unsupported filter or sort is refused
rather than silently ignored. Paging is bounded to 50 per page.

## 22. Plan comparison

Up to four plans are compared field by field across strategy, steps, approvals,
risk, destructiveness, rollback, verification, recovery, evidence coverage,
warnings and limitations. Duplicate ids are collapsed. Missing owner fields are
listed rather than filled in. The comparison pins `no_automatic_winner`,
`no_automatic_plan_selection` and `no_automatic_execution_selection`.

## 23. Action registry

Eleven action descriptors are defined. **Exactly one is available.**

## 24. The one available action

`repair_plan_action_acknowledge_linked_incident_v1` routes to
`review_ui.acknowledge_notification` with target type `incident` and target id
`source_diagnostic_case_id`. It is non-authoritative and is labelled as doing
nothing to the plan. Review UI defines no repair-plan target type, so
acknowledging the plan itself would misattribute the canonical target.

## 25. The ten unavailable actions

Each is declared unavailable with its exact reason, enforced by a registry
guard: acknowledge plan, approve plan, reject plan, request plan revision,
request plan regeneration, request recovery attempt, request tool retry, request
checkpoint restore, escalate plan, record plan review note.

The decisive audit facts are: Repair Planner exposes only `load`, `generate`,
`export` and `reset`; Tool Recovery and Code Surgeon execution paths are
`approved_execution` operations; `workflow_controller.resume` is registered
`future_gated`; and Creator Learning's feedback target vocabulary is
creative-artifact scoped with no repair, case or incident target.

## 26. Confirmation contract

Every action requires an explicit confirmation digest bound to the snapshot, the
plan digest and the action id. The confirmation text always includes:

> This request does not directly execute commands, modify code, change
> artifacts, restore a checkpoint, restart a process, transition the workflow,
> grant Rights or Safety approval, upload content or publish content.

## 27. Staleness protection

Before submission the engine re-reads canonical state and refuses on repair-case,
analysis, incident or workflow identity mismatch, project snapshot drift,
workflow revision drift, plan digest drift, source record digest drift, Safety
record drift, Final Decision record drift, expiry, or the action no longer being
available. An ambiguous identity chain withholds every action.

## 28. Receipts

Receipts are immutable. A receipt cannot claim an authoritative change, plan
approval, rejection, revision, repair execution, recovery start, checkpoint
restore, process restart, workflow change, code change or artifact change without
a canonical owner record and digest. A repeated submission reuses the existing
receipt rather than contacting the owner twice.

## 29. Persistence

Records live under `repair_plan_review/` as `index.json`, `registries/`,
`sessions/`, `snapshots/`, `actions/`, `receipts/` and `event_cursors/`.
Registries, action requests and receipts are immutable once written. The panel
stores projections, never a copy of an owner's records.

## 30. Reset

A session reset removes only that session. A full reset removes the panel index,
sessions, snapshots and event cursors, and preserves every owner history: repair
plans, repair cases, risk assessments, approval gates, rollback plans,
checkpoint plans, validation plans, root-cause records, incidents, recovery
history, code-repair history, validator history, artifact history, workflow
history, Review UI history and action receipts.

## 31. Integration layer and Safety Gate

The module is registered read-only and not execution capable, with 27 fixed
operations. Safety Gate classifies all 27: 26 `automatic_read_only` and
`submit_action` as `approval_required_read_only`. No operation is classified as
execution capable.

## 32. API surface

Twenty-four project-scoped routes under
`/boba/projects/{project_id}/repair-plan-review` cover the review set, registry,
sessions, queue, plan detail, snapshot and refresh, the seven plan leaves,
comparison, confirmation description, action create/validate/submit/receipt,
timeline, events and export. An unknown plan id returns a client error, never a
server error.

## 33. Frontend

`frontend/src/lib/repairPlanReview.ts` holds pure projection logic and the
withholding contract. `BobaRepairPlanReviewPanel.tsx` renders eight sections with
its own error boundary. The panel spawns no child process, evaluates no string,
sets no `innerHTML`, opens no URL and calls `fetch` only through the typed api
client hooks. Review-session annotations are rejected if they contain
credentials, command text or a private path, and are always labelled
`Review-session annotation — not part of the canonical repair plan.`

## 34. Validation and tests

The offline validator catalogues **327 scenarios** across 15 groups plus **61
declared-boundary self-checks**, all passing. The backend suite runs **723
tests**, and the frontend adds **366 tests** (209 logic, 157 source contract).
Forbidden-token checks assert on precise invocation tokens and behavioural flags,
because the panel's own disclaimers legitimately contain words such as "correct
repair" and "target".

## 35. Known limitations

- No Safety, Rights, Final Decision or Output Quality record can be bound to a
  repair strategy identity, so those requirements can never show as satisfied.
- Repair Planner records no revision or supersession identity, so plan lineage
  cannot be shown.
- The panel cannot acknowledge, approve, reject, revise or escalate a plan, and
  exposes no execution, recovery, checkpoint or workflow action.
- Recovery attempts reached only through the shared repair case are shown with a
  warning rather than hidden, because withholding them would hide real history.
- Owner event streams without timestamps or sequence numbers yield an unconfirmed
  timeline order, reported as such.
