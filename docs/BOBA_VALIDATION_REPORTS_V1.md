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

## 9. Determinism

Rebuilding a projection from unchanged canonical evidence produces an identical
`projection_digest`. Ordering is fixed everywhere it could otherwise vary:
matrix cells by `(validator_id, plan_check_id, attempt_number, cell_id)`,
report cards, evidence, conflicts and events all sort on explicit keys, and no
output depends on dictionary or set iteration order.

Generation timestamps are metadata, not content. `created_at` appears on the
projection, the summary and the matrix, and is deliberately **excluded** from
the digested content by `projection_content_for_digest`. Owner timestamps that
genuinely describe the evidence — `started_at`, `completed_at`, `generated_at` —
are content and are digested.

This distinction was a real defect, not a hypothetical one: the digest
originally hashed the whole payload including its own `created_at` fields, so an
unchanged projection produced a different digest on every rebuild and the digest
could not distinguish "nothing changed" from "something changed". The digest
remains sensitive to real change: differing owner evidence, malformed reports,
a stale binding and an empty project each produce a distinct digest.

## 10. Health score — deliberately absent

There is no numeric weighted health score in V1, and none was added.

The Validator Runner does not expose one. Its vocabulary is categorical
(`BobaValidationCheckStatusV1`) plus per-record confidence values. Inventing a
weighted score here would mean this layer manufacturing a judgement no owner
made, which is exactly what the ownership model forbids — and any weighting
chosen would be this module's opinion presented as an owner fact.

The authoritative V1 signals are therefore categorical: the seven-state matrix,
`verdict_available`, `evidence_present`, `evidence_missing`, `stale`, the
per-state `state_counts`, and the owner's own `suite_decision`. Counts are
reported; they are never collapsed into a single score.

## 11. Persistence

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

## 12. Security

Refused rather than silently rewritten: absolute paths, Windows drive paths, UNC
paths, traversal, external URLs, raw media references, credential-like text and
malformed digests. Owner records belonging to another project are refused, not
merged. Unsafe owner prose is replaced with an explicit redaction placeholder.

Raw input is validated *before* sanitisation, because the shared `_safe_text`
helper rewrites `https://` into `http[private-path]/` and a post-sanitisation
check would therefore accept the very material this refuses.

## 13. API

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

## 14. Integration

Registered as module `validation_reports` in the Integration Layer with 13
operations. Every operation is `read_only`, apart from the framework's standard
`export` and `metadata_reset` classes. No operation requires or grants approval
or Safety authorisation, and none is prohibited or future-gated.

The Safety Gate classifies all 13 operations as `automatic_read_only`, which is
the honest classification: this module reaches no owner and executes nothing.

## 15. Frontend

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

## 16. Tests

- Backend: **221** tests in `tests/unit/test_boba_validation_reports.py`.
- Task validator: **105** synthetic scenarios across 12 condition groups plus
  **20** declared-boundary self-checks in
  `tools/validate_boba_validation_reports.py`. Run it with
  `python -m tools.validate_boba_validation_reports --self-check`.
- Frontend: **84** tests in three files with deliberately separate jobs:
  - `validationReports.test.ts` (**38**) exercises the projection logic.
  - `BobaValidationReportsPanel.render.test.tsx` (**31**) renders the panel in
    jsdom and asserts what a reader actually sees, including a click interaction
    and the error-boundary path.
  - `BobaValidationReportsPanel.test.ts` (**15**) covers wiring only — which
    module is mounted where, which endpoints and hooks exist, which controls are
    absent.

The render tests replaced a set of source-text assertions that read the `.tsx`
file and matched prose with `toContain`. Those passed whenever the wording was
present and the behaviour was broken, and broke whenever a comment was reworded,
so they were removed rather than kept for their count. Every behavioural claim
they made has a rendering equivalent, including report lineage, `aria-hidden`
decorative glyphs, and the guarantee that a display failure never reads as a
pass. One assertion was dropped without replacement on purpose: a grep for
Tailwind breakpoint classes, which asserted a stylesheet rather than a
behaviour. The `jsdom` environment is set per test file, so the rest of the
frontend suite still runs under `node`.

Validator condition groups: validation-evidence, stale-state, matrix, summary,
reports, aggregation, security, persistence, idempotency, api,
frontend-contract, ownership.

## 17. Limitations

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
- There is no single number summarising project health, by design. A reader has
  to look at the state counts and the conflicts, because collapsing them would
  hide exactly the cases this layer exists to surface.

## 18. Verification status

Measured on the delivery branch, Python 3.11.15 / Node 22:

| Check | Result |
|---|---|
| `pytest tests/unit/test_boba_validation_reports.py` | 221 passed |
| `python -m tools.validate_boba_validation_reports --self-check` | 105/105 scenarios, 20/20 self-checks, exit 0 |
| `python -m tools.validate_boba_validation_reports --synthetic-project` | 105/105, exit 0 |
| `python -m tools.validate_boba_validation_reports --report` | byte-identical across runs |
| `pytest tests/ -k boba` | 7,735 passed, 4 skipped, 1 pre-existing failure |
| `vitest run` (whole frontend) | 1,450 passed |
| `tsc --noEmit`, `next lint`, `next build` | clean |
| `ruff check` on this module's files | clean |

Both determinism and truthfulness claims are negative-controlled. Reverting the
digest fix fails 5 backend tests and the `persistence:projection-digest-deterministic`
scenario. Relabelling `MISSING` as `Passed` fails 3 rendering tests and 2 logic
tests — and passes every wiring test, which is precisely why the wiring tests
cannot be the only frontend coverage.

## 19. Known pre-existing failures, not caused by this work

These were verified identical before and after, by stashing this branch's
changes and re-running. None is in the Validation + Reports surface and none is
fixed here, because each belongs to another owner's roadmap item.

| Item | Where | Note |
|---|---|---|
| 1 test failure | `test_boba_output_quality_reviewer.py::test_target_resolution_rejects_external_symlink` | Expects a `ValidationError` matching `external symlink`, but an earlier and also-correct root-escape guard fires first. Output Quality Reviewer's own test, not this module's. |
| 3 mypy errors | `api/v1/routes/boba.py:2982,3226,3414` | `no-any-return` in the Validator Runner, Report Reader and Artifact Inspector routes. That file is untouched by this work. |
| 3 ruff `I001` | `tools/validate_durable_restart_resume.py`, `validate_long_video_full_render.py`, `validate_multi_speaker_layout.py` | Unsorted imports in unrelated validators. |
| 4 skips | `test_boba_tool_recovery.py` | FFmpeg/FFprobe absent from the environment. Environmental, not a defect. |

## 20. Explicitly out of scope for V1

Named here so their absence is a decision on record rather than an oversight:

- **Historical report comparison and regression detection.** V1 persists an
  active `index.json`, immutable registry and request snapshots, and an
  append-only event log. It does not diff two projections over time. The
  deterministic `projection_digest` is the primitive such a feature would build
  on, which is why determinism was fixed here.
- **Authentication and authorisation middleware.** Routes follow the existing
  BOBA contract (`_require_enabled`, `_require_project`). Platform-wide auth is
  not this module's concern.
- **A numeric health score.** See §10.
- Other BOBA roadmap items — Self-Healing Validation, Creative Director
  Validation, Scout Validation, Learning Loop Validation, Safety Gate
  Validation, Live Companion, Final System Audit — are untouched.
