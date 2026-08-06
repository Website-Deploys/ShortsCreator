# BOBA Error Doctor Panel V1

## 1. Purpose

The Error Doctor Panel is a specialized read-only mode of the BOBA Review UI. It
projects the incidents, diagnoses, root-cause findings, repair plans and recovery
attempts that the existing reliability modules persisted, links each statement to
the canonical record that owns it, lets a reviewer compare incidents, and routes
one advisory action to its real owning module.

## 2. Authority boundary

The panel does not detect errors, create incidents, diagnose, determine root
causes, create repair plans, execute repairs or recovery, restore checkpoints,
transition workflows, modify code, artifacts or media, run a command, shell,
PowerShell, Git or FFmpeg, install or download tools, create Rights, Safety or
approval decisions, upload or publish.

## 3. Review UI integration

`BobaErrorDoctorReviewPanel` is mounted at all four project results render sites,
after the Clip Brief Panel. The global Review UI workspace, the Candidate Review
Panel, the Clip Brief Panel and the pre-existing error displays are all left in
place. The panel reuses Review UI's digest, sanitisation, private-path and error
classification helpers and opens no second event stream.

## 4. Source reliability modules

Fourteen fixed sources are read through fixed `BobaMemoryStore` loaders: Error
Doctor, Observer, Root Cause Analyzer, Repair Planner, Code Surgeon, Tool
Recovery, Output Quality Reviewer, Validator Runner, Report Reader, Artifact
Inspector, Workflow Controller, Safety Gate, Final Decision Bus and Autopilot
Controller. Only the Error Doctor record is required; Autopilot evidence is
advisory.

## 5. Incident identity

The incident is Error Doctor's `BobaDiagnosticCaseV1.diagnostic_case_id`. The
ownership chain is preserved exactly as the repository defines it:

    Observer finding          -> finding_id
    Error Doctor case         -> diagnostic_case_id       (the incident)
    Root Cause Analyzer case  -> analysis_case_id         (source_diagnostic_case_id)
    Repair Planner case       -> repair_case_id           (source_analysis_case_id)
    Tool Recovery case        -> recovery_case_id         (source_repair_case_id)
    Code Surgeon case         -> code_repair_case_id      (source_repair_case_id)

## 6. Workflow and stage identity

Workflow run identity, stage instance identity and workflow revision come from
the Workflow Controller's own active run. The incident's `workflow_stage` string
comes from Error Doctor. No identity is accepted from the browser.

## 7. Current, stale and historical records

Error Doctor stores one current diagnostic set and records no supersession
marker, so `stale`, `historical` and `superseded` stay explicitly false and are
never inferred from timestamps, filenames or ordering. `incident_revision_id`
and `superseding_incident_id` stay absent for the same reason. Error Doctor
records no error code, so `error_code` stays absent.

## 8. Facts, assessments and hypotheses

Every displayed diagnostic statement is classified as a confirmed fact, a
source-owned assessment, a source-owned hypothesis, an unresolved claim or
unavailable. The classifications are never merged into one narrative, and a
hypothesis is never promoted to a fact.

## 9. Diagnosis presentation

The diagnosis projection carries Error Doctor's own `diagnosis_status`,
`error_category`, symptom summary and probable-cause summary. The original
wording is shown in a bounded technical excerpt and the plain-language sentence
is kept in a separate field.

## 10. Root-cause presentation

Every Root Cause Analyzer candidate is projected separately with its own
evidence, contradictory evidence, evidence quality and repairability. No
candidate is selected, ranked or averaged.

## 11. Confidence preservation

`confidence` and `likelihood_score` are separate owner-defined values, projected
with the owner's scale and a definition stating that the owner does not define
them as probabilities. `confidence_comparable_across_sources` is always false and
no value is ever averaged or compared.

## 12. No confirmed root cause in V1

Root Cause Analyzer pins `human_review_required = True` on every analysis case
and `verification_required` on every candidate, so the panel never displays a
confirmed root cause. Candidates are headed "Root-cause hypothesis".

## 13. Incident queue

The queue is built from the trusted incident references, one item per diagnostic
case, bounded to 500 loaded incidents and 50 per page.

## 14. Queue priority

Fourteen fixed presentation tiers order the queue: critical Safety or Rights
implication (10), workflow blocking (20), failed or partial recovery (30),
conflicting records (40), missing diagnosis (50), missing root cause (60), repair
plan awaiting approval (70), stale verification (80), recurring (90), other
unresolved (100), recovered but unverified (110), resolved (120), superseded
(130), historical (140). A tier is a display order, never a score, a danger
ranking or a repair-success estimate.

## 15. Filters and sorts

Seventeen filters and seven sorts are supported and anything else is refused.
There is no most-dangerous, easiest-fix, best-repair or success-probability sort.
The severity sort uses Error Doctor's own severity vocabulary.

## 16. Evidence sources

One evidence card is produced per fixed source, plus one per Error Doctor
evidence row and one per referenced Observer finding. Cards are bounded to 100
per incident.

## 17. Logs and stack traces

Excerpts are bounded: technical message 8,192 characters, easy explanation 4,096,
log or stack-trace excerpt 16,384, individual line 2,048. Line structure is kept
so a trace stays readable. No complete log, stack trace, patch or source file is
persisted in review metadata.

## 18. Sensitive-value redaction

Secret shapes transcribed from Tool Recovery and Code Surgeon are removed from
every excerpt: bearer tokens, assigned secrets, private keys, GitHub and AWS
tokens, JWTs, credential URLs and secret-bearing environment assignments. The
card reports `sensitive_values_redacted` and the UI shows "Sensitive values
redacted".

## 19. Private-path redaction

Whole private paths are removed using the owner-side pattern before Review UI's
prefix pattern, so the local user directory name never survives. The card reports
`private_paths_redacted` and the UI shows "Private path details redacted".

## 20. Repair-plan presentation

Repair Planner strategies are projected with their status, strategy type, step
count, bounded step descriptions, required approvals, and every `requires_*`
flag. `executable_by_panel` and `raw_command_exposed` are pinned false by the
contract. Step `target` values, which may contain command text, are never
projected. Code Surgeon affected paths are counted, never listed.

## 21. Recovery-attempt history

Every Tool Recovery attempt is projected separately with its owner status,
timestamps, tool, exit code, rollback record and bounded failure summary. Failed
attempts are never hidden or collapsed.

## 22. Attempted versus completed

`attempted`, `completed` and `succeeded_by_owner` are separate fields. The
contract refuses a projection that claims completion without an attempt.

## 23. Owner success versus independent verification

`succeeded_by_owner` comes from Tool Recovery's `completed` or
`succeeded_pending_validation` status. `verified` is true only when an output
validation record reports `required_checks_passed` and
`accepted_for_quality_review`. The two are counted separately everywhere.

## 24. Recovered versus resolved

`recovered` means an owner reported a completed recovery attempt. No module
records an incident resolution flag, so `resolved` stays false. The UI labels the
state "Recovered, not resolved".

## 25. Validator evidence

Validator Runner runs are projected with their own status and check counts.
Missing validation evidence stays missing and never becomes a pass, and a passing
focused check is never presented as full recovery or production readiness.

## 26. Artifact evidence

Affected artifacts are matched to Artifact Inspector references by persisted
identity and digest. Artifact integrity is never inferred from a file existing.

## 27. Conflict handling

Conflicts are raised only between records naming the same incident identity:
stage identity, diagnosis, root cause, repair plan, recovery status, validation
and severity. Every conflict is recorded unresolved with
`explicit_supersession_found = false`, and conflict detection reads no confidence
value.

## 28. Comparison

Two to four incidents may be compared across identity, severity, diagnosis, root
cause, evidence coverage, repair plans, recovery history, validation, artifacts,
warnings and limitations. `no_automatic_winner`,
`no_automatic_root_cause_selection` and `no_automatic_repair_selection` are all
pinned true by the contract.

## 29. Human actions

One action is available: acknowledge incident, owned by Review UI's
`acknowledge_notification` operation, which already declares `incident` in its
supported target types and `incident_review` in its supported review modes. It
writes only the Review UI session's acknowledged list and sets
`authoritative_state_changed = false`.

## 30. Unavailable execution actions

Eleven actions are declared unavailable with the exact reason found in the audit:

- diagnosis refresh and root-cause review: only whole-set `generate` operations exist
- repair approval, rejection and revision: no canonical operation records them
- recovery attempt and tool retry: `tool_recovery_brain.execute_approved` is an approved-execution operation
- checkpoint recovery: `workflow_controller.resume` is registered `future_gated`
- escalation: no module exposes an escalation operation
- incident feedback and review note: Creator Learning defines no incident target type

No substitute owner was invented for any of them.

## 31. Confirmation flow

Before submission the panel refreshes the snapshot, verifies the project
snapshot digest, workflow revision, incident digest and every source-record
digest, verifies Safety and Final Decision Bus digests when the descriptor
requires them, re-checks availability, shows the exact consequences and
non-consequences, and requires explicit confirmation. Reasons are bounded and
refused if they carry credentials or private path material.

## 32. Stale-state protection

Validation returns a refusal code for expiry, incident removal, workflow or stage
identity mismatch, project digest drift, workflow revision drift, incident digest
drift, source-record digest drift, Safety digest drift and Final Decision Bus
digest drift. Nothing reaches the owner in those cases.

## 33. Canonical receipts

Receipts are immutable. `authoritative_state_changed`, `repair_executed`,
`recovery_attempt_started`, `workflow_changed`, `code_changed` and
`artifact_changed` cannot be true without a canonical owner record id and digest;
the store refuses such a receipt. A duplicate submission reuses the existing
receipt and the owner is called once.

## 34. Integration Layer

Twenty-five operations are registered under `error_doctor_review`, all read-only,
metadata-reset or export. Only `submit_action` requires target approval.

## 35. Safety Gate

The Safety Gate classifies all 25 operations: 24 `automatic_read_only` and
`submit_action` as `approval_required_read_only`. No target action's
classification is weakened.

## 36. Final Decision Bus and Workflow Controller

Both remain owners. The panel reads their records as evidence and captures their
digests when a descriptor requires them, but no available action asks either for
authorisation because no execution action exists in V1.

## 37. API

Twenty-five project-scoped routes under
`/api/v1/boba/projects/{project_id}/error-doctor-review` cover the review set,
registry, sessions, queue, incident, snapshot, refresh, diagnosis, root cause,
repair plan, recovery history, validation, artifacts, conflicts, comparison,
actions, validate, submit, receipt, timeline, events and export.

## 38. Persistence

Only UI-owned metadata is written, under
`error_doctor_review/{index,registries,sessions,snapshots,actions,receipts,event_cursors}`.
Registries, submitted requests and receipts are immutable. Reset removes only the
panel's own index, sessions, snapshots and event cursors and preserves incidents,
diagnoses, root causes, repair plans, recovery history, validator, artifact,
report, workflow, Safety, Review UI, Candidate Review and Clip Brief history,
source media and accepted outputs.

## 39. Accessibility

The incident list is semantic, incidents are keyboard-selectable with labelled
buttons and checkboxes, the confirmation dialog is a labelled modal, stale-state
messages use a polite status role, bounded excerpt regions are labelled, and
state is never communicated by colour alone.

## 40. Performance

The queue is paginated at 50 with a 500-incident ceiling, comparison is capped at
four incidents, evidence cards at 100, expanded source cards at 20, expanded log
cards at 10, and the timeline at 100 entries per page. No full log, report or
source record is duplicated in the browser.

## 41. Validation

`tools/validate_boba_error_doctor_review.py` runs 265 catalogued correctness
conditions across thirteen groups plus 45 declared-boundary self-checks, using
synthetic canonical records. It never touches real state, the network, Git or
FFmpeg.

## 42. Limitations

Completeness of evidence is not correctness. A hypothesis is not a fact.
Owner-reported recovery success is not independent verification. Recovered is not
resolved. Missing evidence is never a pass. Execution actions remain unavailable
without canonical authorisation. V1 does not claim production readiness.
