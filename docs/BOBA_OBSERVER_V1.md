# BOBA Observer V1

## 1. Purpose

BOBA Observer V1 is a deterministic, local observation layer for saved BOBA
project state. It reports what artifacts and validation reports are present,
missing, stale, unreadable, or blocked by dependency and safety gaps.

Observer output is advisory. It does not establish production readiness,
semantic correctness, copyright safety, or permission to process media.

## 2. What Observer Does

Observer V1:

- reads known local BOBA JSON artifacts independently;
- reports artifact presence, readability, schema, timestamp freshness, and size;
- evaluates required and optional artifact dependencies;
- summarizes module and workflow health;
- reads the newest local JSON validation report when available;
- reports rights and operational safety state;
- recommends safe inspections and identifies unsafe next actions;
- persists a compact JSON-safe report;
- supports safe export and Observer-only reset.

## 3. What Observer Does Not Do

Observer V1 does not:

- fix or rewrite files;
- diagnose source code;
- plan or apply repairs;
- execute commands or validators;
- delete artifacts;
- fetch URLs, scrape platforms, or call external APIs;
- download or ingest media;
- trigger editing or rendering;
- store raw media, full transcripts, credentials, or auth tokens;
- bypass rights review or replace human approval.

## 4. Difference From a Validator Runner

A Validator Runner starts validation commands and interprets their execution.
Observer does not start validators. It only checks whether a recognized local
JSON report exists, reads a bounded newest report, and records a recognized
simple status when that status is explicit.

Missing, stale, corrupt, or unfamiliar reports remain visible as gaps. Observer
never converts an unknown report into a pass.

## 5. Difference From Error Doctor

A future Error Doctor may diagnose why a module or artifact failed. Observer V1
only records evidence such as a missing upstream artifact, unreadable JSON, or a
failed validation report. It does not infer a code-level root cause.

## 6. Difference From Repair Planner

A future Repair Planner may propose an approved repair sequence. Observer V1
does not create executable repair plans. Its next-action records are bounded
advice for inspection, manual validation, normal artifact generation, or human
rights review.

## 7. Artifact Observation

The registry covers:

- whole-video understanding;
- candidate clip discovery;
- clip ranking;
- editorial decision;
- explanation;
- Creative Director V2;
- clip briefs;
- hook and retention;
- caption and motion;
- music mood;
- creator learning;
- approval/rejection learning;
- experimentation;
- performance feedback;
- Content Scout V2;
- Research Brain;
- Trend/Topic Watcher;
- Candidate Video Scorer;
- Rights + Permission Gate.

Each artifact observation records expected relative path, existence,
readability, schema version, creation timestamp when available, bounded file
size, freshness, dependency status, findings, and warnings.

Freshness is based only on explicit timestamps, file modification time, a
30-day review window, and dependency ordering. A stale result means review is
recommended; it does not prove semantic invalidity.

Bad JSON is isolated to its own observation and does not crash the complete
report. Observer reads at most 10 MB from an individual artifact.

## 8. Module Health Observation

Each registered module is classified as `healthy`, `partial`, `missing`,
`stale`, `blocked`, or `unknown`.

- A corrupt output blocks its module.
- An unavailable required upstream input blocks its dependent module.
- A missing output with available required inputs is partial and ready for its
  normal approved generation workflow.
- A missing optional input degrades health without becoming a blocker.
- Timestamp or dependency-order staleness produces a review warning.

Confidence describes confidence in the observed file state, not confidence in
content quality or correctness.

## 9. Dependency Observation

Observer evaluates these local chains:

- Content Scout V2 -> Research Brain -> Trend/Topic Watcher -> Candidate Video
  Scorer -> Rights + Permission Gate;
- whole video -> candidate discovery -> clip ranking -> editorial decision ->
  explanation -> Creative Director V2 -> clip briefs;
- clip briefs -> hook/retention -> caption/motion -> music mood;
- creator learning -> approval/rejection learning -> experimentation ->
  performance feedback;
- Candidate Video Scorer -> Rights + Permission Gate.

A downstream artifact without a required upstream artifact is broken. A
missing downstream artifact with readable upstream input is incomplete, not a
missing-input failure. A downstream file older than its upstream file is stale
for review.

## 10. Validation Observation

Observer searches configured local validation-report directories and inspects
the newest JSON report only. It recognizes an explicit boolean `passed` value
or a small documented status vocabulary.

Reports can be `passed`, `failed`, `partial`, `unknown`, or `missing`. Report
freshness is tracked separately. Unknown formats remain unknown.

Observer never executes a validator.

## 11. Safety Observation

Safety observations cover:

- rights and permission;
- ingestion;
- rendering;
- downloading;
- external APIs and URLs;
- secrets;
- destructive actions;
- validation gaps.

Unknown, permission-needed, insufficient, or blocked rights never authorize
ingestion. Even `ready_for_human_review` allows human review only and still
requires explicit approval before any future ingestion.

Rendering remains in the normal approved Olympus pipeline. Observer never
triggers it.

## 12. Next Action Recommendation

Safe recommendations can advise a human to:

- inspect an artifact or upstream dependency;
- run a validator manually;
- use a module's existing approved path to generate a missing output;
- review rights and permission evidence.

Unsafe recommendations identify actions not to perform, including processing
unresolved-rights media, automatic repair, deletion, ingestion, downloading,
or rendering from Observer findings.

Future Error Doctor, Root Cause Analyzer, Repair Planner, Code Surgeon, Tool
Recovery Brain, and Safety Gate modules may consume this evidence later. V1
does not trigger or emulate them.

## 13. Export and Reset

The compact export removes expected artifact paths, validation report paths,
and finding evidence. It includes explicit privacy and non-execution flags.

Reset deletes only the Observer report for the selected project. It does not
delete or mutate any observed BOBA artifact, project memory, media, or
validation report.

## 14. Artifact Path

The persisted artifact is:

```text
work/boba/projects/<project_id>/observer/index.json
```

Writes use the existing BOBA atomic JSON store. Generated validation reports
remain under ignored `work/validation_reports/boba_observer/`.

## 15. API and Validator Commands

API routes:

```text
POST   /api/v1/boba/projects/{project_id}/observer
GET    /api/v1/boba/projects/{project_id}/observer
GET    /api/v1/boba/projects/{project_id}/observer/export
DELETE /api/v1/boba/projects/{project_id}/observer
```

`POST` accepts optional local workflow context and `dry_run`. A dry run returns
the report without persisting it.

Local validator:

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_observer.py --self-check
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_observer.py --synthetic-project
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_observer.py --project-id PROJECT_ID
```

The validator uses local synthetic JSON or saved project artifacts. It requires
no media, network, external API, URL, secret, download, ingestion, render, or
automatic validator execution.

## 16. Limitations

- Observer sees saved local evidence only.
- Timestamp freshness cannot prove semantic correctness.
- A present artifact is not necessarily valid beyond bounded JSON readability.
- A passed report may be stale or may cover a narrower behavior than expected.
- Observer does not inspect raw media or full transcripts.
- Observer does not prove rights, licenses, copyright safety, or legal status.
- Observer does not prove production readiness.
- Human review is required for every consequential next action.
