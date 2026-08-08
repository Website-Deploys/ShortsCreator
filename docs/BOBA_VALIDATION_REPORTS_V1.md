# BOBA Validation + Reports V1

## 1. Architecture

A **projection and presentation boundary** over the existing canonical Validator
Runner and Report Reader records. It coordinates and presents validation and
report evidence so a human can read it, and it does nothing else.

It is not a validator, not a report store and not a decision authority. It runs
no validator, reads no report file from disk, writes no owner record, creates no
Safety decision, advances no workflow and approves nothing.

## 2. Ownership

```
Frontend panel (presentation only)
      ↓
Validation + Reports projection (this layer, read-only)
      ↓
Validator Runner       → owns validation execution, check verdicts, evidence
                         records, suite decisions and validator identity
Report Reader          → owns safe report reading, parsing, findings,
                         contradictions and report bodies
Artifact Inspector     → owns artifact identity, digests and lineage
Workflow Controller    → owns workflow state, stage identity and revision
Safety Gate            → owns safety authorisation
Final Decision Bus     → owns final action authorisation
Integration Layer      → owns typed cross-module routing
```

Existing owners remain authoritative. This layer may read them, never override
them, and never execute on their behalf.

## 3. Audit finding that shaped the design

The Validator Runner's own check vocabulary (`BobaValidationCheckStatusV1`) has
**fourteen** values. The required matrix vocabulary has **seven**. A naive
mapping would therefore destroy owner facts.

| Owner status | Matrix state | Carries a verdict |
|---|---|---|
| `passed` | `PASS` | yes |
| `failed` | `FAIL` | yes |
| `blocked` | `BLOCKED` | no |
| `dependency_blocked` | `BLOCKED` | no |
| `errored` | `BLOCKED` | no |
| `timed_out` | `BLOCKED` | no |
| `cancelled` | `BLOCKED` | no |
| `skipped_not_required` | `SKIPPED` | no |
| `pending` | `NOT_RUN` | no |
| `ready` | `NOT_RUN` | no |
| `running` | `NOT_RUN` | no |
| `superseded` | `STALE` | no |
| `unavailable` | `MISSING` | no |
| `unknown` | `MISSING` | no |

Because that mapping is lossy on its own, **every matrix cell also carries the
verbatim `owner_status`**, the un-overridden `owner_reported_state`, a
`derived_state_reason` naming the exact owner status, and `verdict_available`.
No owner fact is discarded; only the presentation is condensed.

An owner status this layer does not recognise becomes `MISSING`, never a pass.

## 4. Truthfulness rules enforced in code

These are Pydantic validators and typed floors, not documentation:

- A cell with `derived_state == "PASS"` **requires** owner evidence. An owner
  pass with no evidence record is presented as `MISSING`.
- `verdict_available` may only be true for `PASS` or `FAIL`.
- A stale cell must present as `STALE`.
- A summary cannot report `technical_validation_passed` without evidence, or
  `required_checks_passed` while evidence is missing.
- `production_ready`, `output_quality_authorized`, `workflow_transition_authorized`,
  `safety_authorized`, `upload_authorized`, `publication_authorized` and
  `approval_granted` are typed `Literal[False]`. They cannot be set true.
- A report card cannot claim `integrity_verified` without a matching digest, and
  cannot claim `body_stored`.
- An evidence reference cannot support both a pass and a failure, and
  unavailable evidence cannot support a pass.
- A conflict cannot claim to be resolved, won, merged, averaged, or to have a
  root cause, repair or workflow completion inferred.

## 5. Validation matrix

Seven states, never collapsed: `PASS`, `FAIL`, `BLOCKED`, `SKIPPED`, `NOT_RUN`,
`STALE`, `MISSING`. Only `PASS` counts as success.

Each cell preserves the owner fact, the derived presentation, an evidence
reference, digests (input, environment, result), timestamps and the workflow
revision. Ordering is `(validator_id, plan_check_id, attempt_number, cell_id)`,
so output is deterministic. Output is bounded at 200 cells.

## 6. Staleness binding

A verdict is bound to eight dimensions. Any change invalidates reuse:

| Dimension | How it is checked |
|---|---|
| `project_id` | run's project against the requested project |
| `workflow_run_id` | run's workflow against the current workflow run |
| `stage_instance_id` | run's stage against the current stage |
| `target_id` | presence of an exact bound target |
| `workflow_revision` | owner's `project_snapshot_current` |
| `artifact_digest` | owner's `target_digest_unchanged` |
| `validator_version` | cell version against the registered descriptor version |
| `validation_request_id` | presence of the owner's request identity |

When a dimension changes, presentation becomes `STALE`, `reuse_valid` becomes
false, and the owner's original status and state are still shown.

## 7. Reports

Report bodies remain owned by the Report Reader. This layer stores references,
digests and bounded summaries only; `body_stored` is a typed `False`.

Each card carries identity, source module, report type, read status, generated
timestamp, content digest, digest-match, schema support, historical/stale/
malformed/truncated flags, validation and artifact linkage, evidence references,
severity counts, lineage (producer module, read run, read request) and ownership.

Malformed reports, unsupported schemas, digest mismatches and stale reports are
each named rather than smoothed over. Output is bounded at 64 cards.

## 8. Report aggregation and conflicts

Multiple validators and reports are preserved separately. Contradictory results
are kept side by side and named as conflicts. Nothing is averaged or merged, no
result is selected as best, and no root cause, repair or workflow completion is
inferred.

Detected conflict kinds: `check_status_conflict`, `result_status_conflict`,
`validator_version_conflict`, `input_digest_conflict`, `suite_decision_conflict`,
`report_status_conflict`, `report_digest_conflict`, `reported_contradiction`,
`unknown`.

## 9. Persistence

Uses existing BOBA storage under `validation_reports/`. This module persists only
what it owns:

| Record | Mutability |
|---|---|
| `index.json` (active projection) | replaceable |
| `registries/{id}.json` | immutable |
| `requests/{id}.json` | immutable (idempotency) |
| `events/log.json` | append-only, bounded to 500 |

No authoritative validator or report record is duplicated. Reset removes only the
active index; registry history, request history, the event log, all owner
history, report bodies, media and outputs are preserved.

Export is sanitised with the Report Reader's own export sanitiser and excludes
report bodies, raw paths, commands, secrets and media.

## 10. Security

Refused rather than silently rewritten: absolute paths, Windows drive paths, UNC
paths, traversal, external URLs, raw media references, credential-like text and
malformed digests. Owner records belonging to another project are refused, not
merged. Unsafe owner prose is replaced with an explicit redaction placeholder.

Raw input is validated *before* sanitisation, because the shared `_safe_text`
helper rewrites `https://` into `http[private-path]/` and a post-sanitisation
check would therefore accept the very material this refuses.

## 11. API

Twelve fixed, project-scoped routes. Only two mutate, and both touch this
module's own metadata alone.

| Method | Route |
|---|---|
| GET | `/boba/projects/{project_id}/validation-reports` |
| GET | `/boba/projects/{project_id}/validation-reports/registry` |
| GET | `/boba/projects/{project_id}/validation-reports/summary` |
| GET | `/boba/projects/{project_id}/validation-reports/matrix` |
| GET | `/boba/projects/{project_id}/validation-reports/reports` |
| GET | `/boba/projects/{project_id}/validation-reports/reports/{report_document_id}` |
| GET | `/boba/projects/{project_id}/validation-reports/evidence` |
| GET | `/boba/projects/{project_id}/validation-reports/conflicts` |
| GET | `/boba/projects/{project_id}/validation-reports/events` |
| POST | `/boba/projects/{project_id}/validation-reports/requests` |
| GET | `/boba/projects/{project_id}/validation-reports/export` |
| DELETE | `/boba/projects/{project_id}/validation-reports` |

## 12. Integration

Registered as module `validation_reports` in the Integration Layer with 13
operations. Every operation is `read_only`, apart from the framework's standard
`export` and `metadata_reset` classes. No operation requires or grants approval
or Safety authorisation, and none is prohibited or future-gated.

The Safety Gate classifies all 13 operations as `automatic_read_only`, which is
the honest classification: this module reaches no owner and executes nothing.

## 13. Frontend

`BobaValidationReportsPanel` renders validation summary, the seven-state matrix
strip, per-check rows with owner status beside derived state, report cards,
report details, findings, evidence, conflicts, stale-state indicators, lineage,
validator identity, timestamps and digest indicators.

It has loading, empty and error states for every asynchronous section, labelled
live and alert regions, accessible toggle semantics and a responsive layout. It
performs no optimistic mutation, exposes no approve/reject/execute control and
hard-codes every authorisation flag to false.

It sits **alongside** the owner-specific `BobaValidatorRunnerPanel` and
`BobaReportReaderPanel` rather than replacing them, because those remain the
owners' own surfaces.

## 14. Tests

- Backend: **212** tests in `tests/unit/test_boba_validation_reports.py`.
- Task validator: **103** synthetic scenarios across 12 condition groups plus
  **20** declared-boundary self-checks in
  `tools/validate_boba_validation_reports.py`.
- Frontend: **72** tests across `validationReports.test.ts` and
  `BobaValidationReportsPanel.test.ts`.

Validator condition groups: validation-evidence, stale-state, matrix, summary,
reports, aggregation, security, persistence, idempotency, api,
frontend-contract, ownership.

## 15. Limitations

- This layer reports what the owners recorded. It cannot detect a validator that
  is itself wrong, only that evidence is absent, stale or contradictory.
- `workflow_revision` and `artifact_digest` staleness rely on the Validator
  Runner's own `project_snapshot_current` and `target_digest_unchanged` fields.
  If the owner does not populate them, those dimensions cannot be evaluated and
  are simply not reported as invalidated.
- Conflict detection is structural. It finds disagreements between records; it
  does not judge which record is correct.
- Passing technical validation is never production readiness, quality
  acceptance, rights clearance, or approval for upload or publication.
