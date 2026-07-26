# BOBA Root Cause Analyzer V1

## 1. Purpose

BOBA Root Cause Analyzer V1 converts a persisted BOBA Error Doctor report into
a bounded, deterministic causal analysis. It helps a human identify what failed
first, which explanations are best supported, what remains uncertain, and what
safe evidence should be inspected next.

The analyzer is advisory only. Its highest-ranked candidate is not necessarily
a proven root cause.

## 2. What Root Cause Analyzer Does

The analyzer:

- reads the saved Error Doctor artifact for one project;
- normalizes compatible diagnostic cases without changing the source report;
- reconstructs failure timelines from available timestamps;
- builds bounded causal graphs from explicit evidence and known dependencies;
- separates candidates, triggers, contributing factors, and symptoms;
- ranks competing candidates using evidence quality and explanatory coverage;
- preserves counter-evidence, contradictions, and unexplained symptoms;
- identifies evidence gaps and creates ordered verification plans;
- records workflow impact and prepares human-reviewed escalation handoffs; and
- persists a JSON-safe report for the API and frontend.

## 3. What Root Cause Analyzer Does Not Do

V1 does not repair files, edit code, execute commands, run validators, install
tools or dependencies, restart services, retry rendering, modify source
artifacts, activate fallback tools, fetch URLs, call external APIs, scrape,
download media, ingest media, delete files, bypass rights or safety gates, or
resume workflows.

Human approval is required before any verification or repair action.

## 4. Difference From Observer

BOBA Observer records bounded facts about known modules and artifacts. Root
Cause Analyzer does not rescan the project or regenerate Observer output. It can
use Observer evidence references only when the persisted Error Doctor report
already names them.

## 5. Difference From Error Doctor

Error Doctor organizes symptoms, evidence, hypotheses, cascades, and diagnostic
recommendations. Root Cause Analyzer consumes that persisted report and adds
causal ordering, competing-candidate ranking, graph relationships, evidence
gaps, verification plans, workflow impact, and advisory handoffs. It never
regenerates Error Doctor automatically.

## 6. Difference From Repair Planner

Root Cause Analyzer explains supported and competing causes. A future Repair
Planner may consume approved candidates and propose recovery options. V1 does
not create or apply repairs and does not invoke Repair Planner.

## 7. Difference From Tool Recovery Brain

For tool failures, V1 may prepare a handoff containing the required capability,
failed tool or stage, failure class, output constraints, safety constraints,
prohibited methods, and missing proof. Tool Recovery Brain may use that handoff
later. V1 does not select, install, activate, or execute a fallback tool.

## 8. Input Error Doctor Report

The primary input is the persisted Error Doctor artifact loaded through the
existing BOBA store. Optional manual context must be bounded and diagnostic.
Malformed or unavailable source data degrades to an insufficient-evidence
analysis with warnings; it does not trigger a scan, command, validator, or
automatic source-report regeneration.

## 9. Failure Timelines

Each normalized case receives a timeline of available evidence, failure, and
dependency events. Timestamps are used only when supplied by source evidence.
Missing timestamps remain missing, conflicting timestamps reduce ordering
confidence, and the earliest known event is not automatically labeled the root
cause.

## 10. Causal Graphs

Causal graphs contain bounded nodes and edges for candidates, triggers,
contributing factors, symptoms, artifacts, modules, validations, and safety
blocks. Relationships distinguish direct causation, probable causation, weak
causation, correlation, dependency, and blocking. `caused` is used only when
direct evidence supports it. Cycles and graph truncation are reported.

## 11. Root-Cause Candidates

Candidates include a category, evidence quality, confidence, score components,
supporting and conflicting evidence, explained and unexplained symptoms,
alternative candidates, confirmation checks, rejection checks, and warnings.
Generation is bounded and deterministic.

## 12. Root Cause Versus Trigger

A trigger is the event that exposed or initiated a failure. A root cause is an
underlying condition that sufficiently explains the failure chain. The analyzer
keeps these roles separate and does not promote the first event to root cause
without supporting evidence.

## 13. Root Cause Versus Contributing Factor

A contributing factor may increase likelihood, severity, or impact without
being independently necessary or sufficient. V1 records those properties
explicitly and does not automatically rank a contributing factor as the cause.

## 14. Root Cause Versus Downstream Symptom

A downstream symptom is an observed consequence, such as a blocked stage or
missing output. The analyzer groups cascaded symptoms and ranks supported
upstream failures above repeated downstream effects when the evidence warrants
it.

## 15. Intentional Safety Blocking

Unknown rights, denied rights, missing approval, or an active safety gate are
classified as intentional safety or human-decision blocks rather than software
defects. V1 never recommends bypassing those controls.

## 16. Evidence Quality

Evidence is classified by source, reliability, directness, and causal role.
Candidate confidence is reduced for weak support, stale or missing validation,
timestamp conflicts, contradictory evidence, healthy counterexamples, and
unexplained symptoms. Missing proof is a validation gap, not proof of a defect.

## 17. Competing Explanations

High-priority candidates retain alternatives and counter-evidence. Simpler,
better-supported explanations rank above speculative ones, but all meaningful
competing explanations remain visible for human review.

## 18. Confirmation and Rejection Checks

Each candidate can include checks that would strengthen or weaken the
explanation. These are descriptions for future approved modules or operators;
the analyzer does not perform them.

## 19. Evidence Gaps

Evidence gaps identify missing timestamps, validation reports, schema or
version fields, tool status, resource history, checkpoint state, configuration
values, rights state, or other bounded proof. Each gap explains why the
information matters and how it could change confidence.

## 20. Verification Plans

Verification plans order candidate checks and start with safe, read-only
inspection where possible. They state prerequisites, expected evidence,
stop conditions, safety requirements, and human-approval requirements. Plans
are advisory and never execute.

## 21. Workflow Impact

Workflow-impact records list affected, blocked, degraded, healthy, and unknown
stages, plus unsafe next actions. They do not authorize workflow resume or
change durable-job state.

## 22. Escalation Handoffs

V1 can prepare bounded, non-applying handoffs for Repair Planner, Tool Recovery
Brain, Validator Runner, Artifact Inspector, Report Reader, Safety Gate, Rights
Gate, Workflow Controller, Code Surgeon, and human operators. Every handoff has
`apply_automatically=false` and `human_approval_required=true`. Code Surgeon is
recommended only for sufficiently supported probable code defects after simpler
causes have been excluded.

## 23. API Routes

The existing BOBA API exposes:

- `POST /api/v1/boba/projects/{project_id}/root-cause-analyzer`
- `GET /api/v1/boba/projects/{project_id}/root-cause-analyzer`
- `GET /api/v1/boba/projects/{project_id}/root-cause-analyzer/export`
- `DELETE /api/v1/boba/projects/{project_id}/root-cause-analyzer`

POST consumes the saved Error Doctor artifact, accepts optional bounded
diagnostic context, and supports `dry_run=true`. GET returns the saved artifact
or a clear unavailable response. DELETE removes only Root Cause Analyzer data.

## 24. Artifact Path

The canonical local artifact is:

`work/boba/projects/<project_id>/root_cause_analyzer/index.json`

It uses the established BOBA atomic-write pattern and the
`boba_root_cause_analyzer_v1` schema. Reports are bounded and contain no raw
media, complete logs, complete Error Doctor or Observer dumps, credentials,
tokens, or secrets.

## 25. Export and Reset

Export returns the compact
`boba_root_cause_analyzer_export_v1` schema. It removes private filesystem paths,
full evidence values, evidence timestamps, complete source reports, logs,
transcripts, media, and credentials. Reset removes only the analyzer artifact;
Error Doctor, Observer, and other BOBA artifacts remain unchanged.

## 26. Validator Commands

Run the local validator with the existing virtual environment:

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_root_cause_analyzer.py --self-check
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_root_cause_analyzer.py --synthetic-project
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_root_cause_analyzer.py --project-id PROJECT_ID
```

Reports are written under
`work/validation_reports/boba_root_cause_analyzer/` and must not be committed.
The validator uses local persisted or synthetic JSON only. It does not execute
commands, validators, media processing, repairs, or fallback tools on behalf of
the analyzer.

## 27. Limitations

- Results are limited by the quality and completeness of saved Error Doctor
  evidence.
- Sparse or conflicting timestamps can prevent a definitive event order.
- Correlation and dependency do not prove causation.
- Candidate scores are deterministic prioritization aids, not guarantees.
- V1 does not independently inspect arbitrary logs, files, machines, services,
  networks, or external systems.
- V1 does not prove production readiness or successful repair.
- Verification and repair remain future, separately approved human actions.
