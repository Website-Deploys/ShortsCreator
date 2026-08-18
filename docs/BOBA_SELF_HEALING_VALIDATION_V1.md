# BOBA Self-Healing Validation V1

## 1. What this document is

An audit of BOBA's self-healing safety boundary, and the record of the coverage
gaps that audit closed.

The headline finding: **the self-healing pipeline and its validation layer
already existed.** No new engine was written, and no production logic was
changed. What did not exist was proof that the most safety-critical guards were
actually load-bearing — and six of them were not. Section 7 is the substance of
this work.

## 2. Where self-healing actually lives

`autopilot_controller.py` is the self-healing orchestrator. Its own docstring
states the boundary:

> Persisted, bounded coordination for BOBA's self-healing modules. Autopilot
> Controller V1 coordinates typed BOBA operations. It never runs a command, Git,
> FFmpeg, a network request, or a repair directly.

It coordinates; it never executes. Execution belongs to Code Surgeon and Tool
Recovery, and only under an approval that binds exactly.

## 3. Ownership map

| Lifecycle stage | Owner | Executes? | Authoritative for |
|---|---|---|---|
| Observation | `observer.py` | no | module health, artifact freshness, dependency status |
| Symptom triage | `error_doctor.py` | no | failure cases, evidence collection |
| Diagnosis | `root_cause_analyzer.py` | no | root cause vs symptom, uncertainty |
| Repair proposal | `repair_planner.py` | no | plan, scope, risk, rollback intent |
| Rights | `rights_permission_gate.py` | no | rights clearance |
| Safety | `safety_gate.py` | no | safety authorisation |
| Code execution | `code_surgeon.py` | **yes**, isolated worktree only | patch application under bound approval |
| Tool execution | `tool_recovery.py` | **yes**, approved tools only | provider fallback under bound approval |
| Technical verification | `validator_runner.py` | no | check verdicts |
| Quality verification | `output_quality_reviewer.py` | no | quality acceptance |
| Coordination | `autopilot_controller.py` | **no** | state machine, budgets, loop detection |
| Workflow | `workflow_controller.py` | no | workflow state |
| Final action | `final_decision_bus.py` | no | final authorisation |
| Routing | `integration_layer.py` | no | typed cross-module routing |
| Projection | `validation_reports.py` (#42) | no | read-only validation/report projection |

## 4. Lifecycle

`BobaAutopilotStateV1` has 33 states. The healing path:

```
created → inspecting_project → rights_review_required → safety_review_required
→ observer_required → diagnosis_required → root_cause_analysis_required
→ repair_planning_required → awaiting_repair_decision
→ awaiting_execution_approval
→ {code_repair_ready | tool_recovery_ready | checkpoint_recovery_required}
→ approved_execution_pending → execution_running
→ technical_validation_required → output_quality_review_required
→ awaiting_safety_gate → ready_for_workflow_controller
→ completed_internal_cycle
```

Failure paths: `execution_failed`, `rollback_required`, `rollback_running`,
`rollback_failed`, `repair_replanning_required`, `root_cause_reanalysis_required`,
`human_quality_review_required`, `paused`, `blocked`, `failed`, `cancelled`.

Transitions are guarded by `validate_autopilot_state_transition`, which consults
a fixed `VALID_AUTOPILOT_TRANSITIONS` graph. Safety, rights, approval, validation
and quality stages cannot be skipped.

## 5. The safety boundary

Execution is gated by two pure verification functions, not by convention.

`code_surgeon.verify_approval` returns every binding mismatch. An approval
authorises exactly one patch, for one repair case, at one base commit, with one
diff, over one path set, for a bounded time:

| Guard | Prevents |
|---|---|
| `approved` and `explicit_confirmation` | implicit or assumed approval |
| `approval_type` | an approval of the wrong class authorising execution |
| `patch_proposal_id` | **an approval authorising a different patch** |
| `code_repair_case_id` | **an approval authorising a different repair case** |
| `approved_base_commit_sha` | applying to a moved base |
| `approved_diff_sha256` | applying a tampered diff |
| `approved_scope` exact set equality | silent scope expansion |
| special-path subset | sensitive paths riding along |
| `approval_expires_at` | stale authorisation |
| expiry parse failure | a malformed expiry reading as "no expiry" |

`tool_recovery.verify_recovery_approval` binds 14 dimensions: grant, exact
confirmation text, case, plan, exactly one strategy, exact tool ids, exact
configuration overrides, exact retry budget, exact time budget, exact quality
requirements, checkpoint reference, bounded expiry, timestamp, approver identity.

Both return a list of errors. An empty list is the only authorisation.

## 6. Fail-closed and uncertainty

Uncertainty is a first-class state, not a gap to be filled:

- `root_cause_analyzer`: `insufficient_evidence`, `conflicting_evidence`,
  `multiple_competing_causes`, `unknown` are terminal for automatic repair.
- `repair_planner`: `needs_more_evidence`, `human_decision_required`,
  `conflicting_causes`, `blocked`; approval status is `planning_only` or
  `awaiting_human_review` — planning holds no execution authority.
- `safety_gate`: constraints can be `unavailable`, `stale`, `conflicting`.
- `code_surgeon`: `proposal_only` is the default execution status.

**Execution success is not repair success.** After execution the controller
routes to `technical_validation_required` and `output_quality_review_required`;
`validator_runner` and `output_quality_reviewer` own those verdicts. A successful
patch application with a failing validation lands in
`repair_replanning_required` or `rollback_required`, not in success.

## 7. Coverage gaps found and closed

Guard-by-guard empirical sweep: disable one guard in the production function,
run the full engine test file and the Autopilot validator, record whether
anything fails. Grep-based coverage estimates were discarded as unreliable —
they produced a false positive for `tool_recovery`, whose parametrised mutation
test covers 12 of 14 branches without naming the messages.

**`code_surgeon.verify_approval` — 4 of 10 guards were removable with the entire
suite and the 120-scenario Autopilot validator still green:**

| Guard | Before | After |
|---|---|---|
| `patch_proposal_id` | **undetected** | detected |
| `code_repair_case_id` | **undetected** | detected |
| special-path subset | **undetected** | detected |
| expiry parse failure | **undetected** | detected |

**`tool_recovery.verify_recovery_approval` — 2 of 14 removable:**

| Guard | Before | After |
|---|---|---|
| approval timestamp present | **undetected** | detected |
| approver identity present | **undetected** | detected |

The two `code_surgeon` cases at the top of that table are the invariant
"approval for one repair must never authorise another". It was correctly
implemented and entirely unproven.

Six behavioural tests now cover these. All 10 and all 14 guards are detected
when removed. No production logic changed: the guards were right, nothing was
holding them in place.

## 8. Existing validation, verified by running it

| Validator | Result |
|---|---|
| `validate_boba_autopilot_controller --self-check` | pass, `errors: []` |
| `validate_boba_autopilot_controller --synthetic-project` | **120/120 scenarios**, `passed: true`, no warnings |
| `validate_boba_observer --self-check` | pass |
| `validate_boba_error_doctor --self-check` | pass |
| `validate_boba_root_cause_analyzer --self-check` | pass |
| `validate_boba_repair_planner --self-check` | pass |
| `validate_boba_code_surgeon --self-check` | pass |
| `validate_boba_tool_recovery --self-check` | pass |
| `validate_boba_safety_gate --self-check` | pass |

The 120 scenarios cover observation staleness (14–16), diagnosis uncertainty
(18, 20), repair routing (21–26), approval binding (29–37, 48), execution
coordination (38, 44), verification outcomes (39–41, 45–46, 49–55), rollback
(42–43, 47), budget exhaustion (58–70), loop and idempotency (71–77), invalid
transitions (79), malformed module output (81), truthfulness (91–92), and
prohibited capabilities (102–120, including `118_no_rights_bypass` and
`119_no_safety_bypass`).

No scenario is hardcoded true.

## 9. Determinism

`--synthetic-project` output is byte-identical across runs except `created_at`.
All 120 scenario results and every capability signal are stable.

Unlike #42's projection, this validator exposes no content digest, so nothing
*asserts* that stability. Recorded as a limitation in §11 rather than fixed,
because adding a digest to a passing validator is a change to another roadmap
item's tool.

## 10. Negative controls

| Guarantee broken | Detected by |
|---|---|
| State machine allows any transition | validator `79`; 4 unit tests, incl. skipping `awaiting_safety_gate` |
| Approval expiry ignored | validator `30_expired_approval`; `test_011` |
| Loop detection disabled | validator `71`–`76` (6 scenarios); 4 unit tests |
| Cross-proposal approval accepted | nothing, before this work; now `test_051` |
| Scope expansion accepted | `test_010` |
| Special-path approval skipped | nothing, before this work; now `test_053` |
| Recovery approval unattributable | nothing, before this work; now the two provenance tests |

Every break was reverted; the working tree contains no production modification.

## 11. Known limitations

- The Autopilot validator has no deterministic content digest (§9).
- Prohibited-capability scenarios (102–120) assert a self-reported signal
  profile, not kernel-level interception. They prove the coordinator did not
  *record* a prohibited action; they are not a sandbox.
- Loop detection bounds identical actions by fingerprint. Semantically
  equivalent repairs with different fingerprints are bounded by the action and
  time budgets instead, not by loop detection.
- Restart-mid-operation recovery is covered for stale actions (`78`) and stale
  locks (`05`), not for every stage independently.
- `verify_recovery_approval` coverage largely asserts a non-empty error list
  rather than a specific message, so a mutation could in principle be caught by
  the wrong guard.

## 12. Pre-existing failures, not caused by this work

Verified identical before and after.

| Item | Where |
|---|---|
| 1 test failure | `test_boba_output_quality_reviewer.py::test_target_resolution_rejects_external_symlink` — an earlier root-escape guard fires before the expected `external symlink` message |
| 3 mypy `no-any-return` | `api/v1/routes/boba.py:2982,3226,3414` |
| 3 ruff `I001` | `tools/validate_durable_restart_resume.py`, `validate_long_video_full_render.py`, `validate_multi_speaker_layout.py` |
| 4 skips | `test_boba_tool_recovery.py` — FFmpeg/FFprobe absent |

## 13. Out of scope

- **No new self-healing engine.** The pipeline exists; duplicating it would
  create a second authority over repairs.
- **No new validation module.** `validate_boba_autopilot_controller.py` already
  validates the cross-engine loop at 120/120.
- No read-only projection, API surface or frontend panel for self-healing. #42
  built those for validation/reports; nothing here requires them.
- No changes to the state graph, budgets, or safety vocabularies.
- No numeric health score. The engines are categorical throughout.
