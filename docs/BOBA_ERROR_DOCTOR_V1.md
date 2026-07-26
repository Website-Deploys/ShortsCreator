# BOBA Error Doctor V1

## 1. Purpose

BOBA Error Doctor V1 turns a saved BOBA Observer V1 report into a bounded,
structured diagnostic view. It helps a human understand symptoms, probable
explanations, possible hypotheses, missing information, likely cascades, and
safe investigation handoffs.

V1 is advisory only. A probable cause is not a proven root cause.

## 2. What Error Doctor Does

- Reads a supplied or saved `BobaObserverSetV1`.
- Normalizes artifact, module, workflow, dependency, validation, safety, and
  next-action observations.
- Classifies findings by category, severity, urgency, processing impact, and
  safety impact.
- Groups repeated symptoms conservatively.
- Identifies possible dependency cascades from the known BOBA registry.
- Separates confirmed facts from hypotheses.
- Creates read-only or explicitly future-manual investigation recommendations.
- Creates non-applying handoffs for future specialist modules and humans.
- Persists a JSON-safe report when requested by the integration layer.

## 3. What Error Doctor Does Not Do

Error Doctor V1 does not fix files, edit code or configuration, execute
commands, run validators or tests, install tools, restart services, retry
workflows, delete or move files, fetch URLs, call external APIs, download or
ingest media, render clips, bypass rights or safety gates, or claim production
readiness. It does not automatically invoke any handoff target.

## 4. Difference From Observer

Observer V1 records bounded facts about saved BOBA artifacts and workflow
state. Error Doctor consumes those saved observations and interprets their
diagnostic relationship. Error Doctor does not regenerate Observer
automatically and does not mutate the Observer report.

## 5. Difference From Root Cause Analyzer

Error Doctor classifies evidence and offers conservative hypotheses. A future
Root Cause Analyzer may investigate deeper causal chains and reconcile
competing explanations. Error Doctor does not prove root cause merely because
a hypothesis is probable.

## 6. Difference From Repair Planner

Error Doctor states what may warrant investigation. A future Repair Planner may
design an explicitly approved repair after a diagnosis is sufficiently
supported. Error Doctor V1 creates no executable repair plan and applies no
repair.

## 7. Input Observer Report

The primary input is a `BobaObserverSetV1`. Optional callers may add a bounded
diagnostic-context object and up to 32 compact local error summaries. Those
summaries are marked unverified and are not treated as raw logs.

When Observer is missing, empty, or malformed, Error Doctor returns one
`insufficient_evidence` case, recommends manual Observer generation, and
fabricates no project findings.

## 8. Finding Classification

`BobaClassifiedFindingV1` preserves the source finding ID when available and
otherwise creates a stable synthetic source ID. Categories include artifact,
dependency, validation, configuration, environment, rendering, safety,
storage, external-tool, timeout, resource, data-quality, frontend, API, and
unknown conditions.

Unsupported or incomplete evidence becomes `unknown` or
`insufficient_evidence` with warnings rather than a false pass/fail claim.

## 9. Diagnostic Cases

`BobaDiagnosticCaseV1` groups related findings by module, artifact, dependency
root, workflow stage, and known cascade group. Each case includes:

- symptom and probable-cause summaries;
- confirmed facts and bounded evidence;
- hypotheses and missing information;
- affected modules and artifacts;
- processing and safety impacts;
- investigation guidance and escalation target;
- confidence, warnings, and limitations.

Unrelated failures retain separate case and duplicate-group identities.

## 10. Symptoms Versus Probable Causes

Missing required upstream data may be a probable primary cause. Modules blocked
by that same upstream input are secondary symptoms. A missing downstream output
with no missing required input is treated as an incomplete step. Missing
validation is a gap, not proof of a software failure. A failed validation is a
confirmed validation failure, but not necessarily its software root cause.

Rights blocks are intentional safety states, not coding defects.

## 11. Cascading Impacts

`BobaCascadingImpactV1` uses only known BOBA dependency direction:

- content scout → research → trend → candidate scorer → rights;
- whole video → discovery → ranking → editorial → explanation → creative
  direction → briefs;
- briefs → hook → caption → music;
- creator learning → approval/rejection → experimentation → performance;
- Observer → Error Doctor.

Cascade records list impacted modules, artifacts, workflow stages, confidence,
and warnings. They do not claim exact causality.

## 12. Severity and Urgency

Severity values are `informational`, `low`, `medium`, `high`, `critical`,
`blocker`, and `unknown`. Urgency values are `later`, `normal`, `soon`,
`immediate`, `blocked`, and `unknown`.

Optional missing dependencies remain informational or low. Missing required
dependencies and failed required validation are high. Corrupt required state
can be critical or blocking. Rights, safety, required-input, and
destructive-risk conditions can block safe continuation.

## 13. Confirmed Facts Versus Hypotheses

Confirmed facts are bounded statements from Observer evidence. Hypotheses are
stored separately in `BobaDiagnosticHypothesisV1` and always include:

- supporting and conflicting evidence IDs;
- confidence;
- `verification_needed=true`;
- a safe suggested check;
- a warning that the hypothesis is not a proven root cause.

Conflicting evidence lowers confidence and requires human reconciliation.

## 14. Investigation Recommendations

`BobaInvestigationRecommendationV1` may suggest inspecting saved artifacts,
dependencies, schemas, timestamps, configuration, environment evidence, or
validation reports. It may state that a human could run a validator later; in
that case `requires_command_execution` is truthful, but Error Doctor does not
execute it.

Recommendations require human review and never apply code changes, deletion,
rights bypasses, retries, installation, restarts, ingestion, downloads, or
renders.

## 15. Escalation Handoffs

Structured handoffs may target Root Cause Analyzer, Repair Planner, Tool
Recovery Brain, Output Quality Reviewer, Validator Runner, Safety Gate, Rights
and Permission Gate, or a human operator.

Every `BobaErrorDoctorEscalationHandoffV1` has:

- `apply_automatically=false`;
- `human_approval_required=true`;
- bounded evidence IDs and unresolved questions;
- blocked automatic actions;
- a warning that the target was not invoked.

## 16. API Routes

- `POST /api/v1/boba/projects/{project_id}/error-doctor`
- `GET /api/v1/boba/projects/{project_id}/error-doctor`
- `GET /api/v1/boba/projects/{project_id}/error-doctor/export`
- `DELETE /api/v1/boba/projects/{project_id}/error-doctor`

POST accepts optional `diagnostic_context`, `error_summaries`, and `dry_run`.
It consumes the saved Observer artifact and does not generate Observer or run a
workflow. GET returns 404 when unavailable. DELETE removes only Error Doctor.

## 17. Artifact Path

The local artifact is:

```text
work/boba/projects/<project_id>/error_doctor/index.json
```

The existing BOBA store performs an atomic temporary-file write and replace.
The report contains compact JSON only—no raw media, full logs, full Observer
copy, secrets, credentials, or tokens.

## 18. Export and Reset

Safe export uses schema `boba_error_doctor_export_v1`. It excludes private
absolute paths, full evidence observed/expected values, evidence timestamps,
raw logs, full Observer dumps, media, and credentials. It states all non-action
flags explicitly.

Reset removes only `error_doctor/index.json`. Observer, project memory, other
BOBA artifacts, source files, and media remain untouched.

## 19. Validator Commands

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_error_doctor.py --self-check
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_error_doctor.py --synthetic-project
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_error_doctor.py --project-id PROJECT_ID
```

Generated validator reports go under
`work/validation_reports/boba_error_doctor/` and must not be committed.
Synthetic validation uses local JSON only and requires no media, internet,
external API, FFmpeg, command execution, or validator execution inside Error
Doctor.

## 20. Limitations

- V1 depends on the quality and freshness of saved Observer evidence.
- It reads no source code, full logs, raw artifacts, secrets, or media.
- It may classify a symptom without identifying its exact cause.
- Known dependency chains are bounded and may not describe every future module.
- Manual context remains unverified.
- It does not run validators, reproduce failures, or confirm a repair.
- It does not invoke downstream specialist modules.
- Human approval is required before repair or destructive action.
- Passing Error Doctor validation is not a production-readiness claim.
