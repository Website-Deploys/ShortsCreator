# BOBA Report Reader V1

## 1. Purpose
BOBA Report Reader V1 is a local, read-only interpretation layer for exact registered Olympus and BOBA report artifacts. It verifies provenance and structure, extracts bounded findings and evidence references, and explains sources without replacing them.

## 2. What Report Reader Owns
It owns only its registry snapshots, read requests, read runs, bounded document metadata, extracted findings, evidence references, chronology, contradictions, coverage, questions, handoffs, events, and sanitized exports.

## 3. What It Does Not Own
It does not decide validation, quality, safety, rights, workflow progression, diagnosis, repair, recovery, approval, upload, publication, or deployment. A reader bundle is never an approval or workflow transition.

## 4. Source-Authority Preservation
Every interpretation retains the producer module, authority domain, original status, original decision, warnings, limitations, and stale state. Report Reader always sets `permits_current_action` to `false`.

## 5. Trusted Source Registry
The registry is fixed in source code and persisted as an immutable snapshot. It contains actual BOBA project index, run, and event report scopes, including Validator Runner, Workflow Controller, Safety Gate, Output Quality Reviewer, Autopilot, Integration Layer, and recovery-related modules.

## 6. Supported Formats
V1 has bounded UTF-8 parsers for JSON, JSONL, inert Markdown, and inert plain text. Current available registry entries use actual BOBA JSON and JSONL paths; Markdown and plain-text parser capability is not dynamically exposed until a real producer has an explicit fixed scope.

## 7. Unsupported Formats
PDFs, images, screenshots, OCR, video, audio, binaries, XML, HTML, YAML, archives, encrypted files, remote URLs, and cloud documents are not read. Unavailable and future-gated sources report that status honestly.

## 8. Report References
Every request carries exact project-scoped storage references, descriptor IDs, producer identity, report type, schema, expected format, immutable/historical flags, and optional SHA-256 digest. Request data cannot provide a parser path, callable, filesystem root, command, executable, or URL.

## 9. Digest and Identity Validation
Before parsing, Report Reader validates the fixed descriptor, project scope, source module, report type, schema, format, local file existence, and optional digest. A changed expected digest creates a new immutable reference identity.

## 10. Schema Handling
Each descriptor declares supported schema versions. Unknown versions are unavailable in V1 and are not silently normalized. Safety-critical source values remain source-owned and typed.

## 11. Parser Limits
All parsers have fixed byte, record, depth, object/list, and string limits. JSON rejects duplicate keys, malformed UTF-8, non-finite numbers, and secret-bearing fields. Markdown/plain text are inert: code, HTML, and links are never executed, rendered, or fetched.

## 12. Current Versus Historical Reports
Current-project reviews compare the source snapshot digest with the request snapshot. Missing or mismatched snapshots are stale. Historical reports remain readable for context but cannot establish current state or authorize action.

## 13. Finding Extraction
Report Reader extracts bounded source status, decisions, warnings, limitations, and incidents. Findings separate confirmed source facts, source assessments, and reader interpretation. Valid numeric source confidence is preserved without invention.

## 14. Evidence References
Evidence is represented as source field references for artifact IDs/digests, validator IDs, validation runs, clip IDs, output IDs, and report references. It does not persist raw report bodies or complete raw logs.

## 15. Status Interpretation
Status is categorized for display only. A Validator Runner technical pass remains only a pass for the exact technical plan; it is not quality acceptance, Safety allowance, target approval, workflow permission, upload, or publication permission.

## 16. Chronology
Chronology uses only source-declared parseable timestamps and preserves the field path. It does not infer order from filenames/directories or invent causality. A request can disable chronology extraction.

## 17. Contradictions
Contradictions require an explicit shared artifact/output target or exact producer record. Conflicting status, decision, or artifact-digest values remain unresolved and require a source owner or human reviewer; they are never averaged into a pass.

## 18. Coverage
Coverage compares requested reading mode against available, unreadable, unsupported, and stale report types. Each read run stores its own coverage ID so later reads cannot rewrite earlier immutable run coverage.

## 19. Missing Evidence
Missing, unreadable, unsupported, or stale required evidence produces bounded questions and advisory handoffs. Missing evidence is never inferred as a positive decision.

## 20. Report Bundles
Bundles group source references, findings, evidence, chronology, contradictions, coverage, questions, technical summaries, and easy summaries. They are deterministic for unchanged inputs and always set `suitable_for_current_action` to `false`.

## 21. Easy-Language Summaries
Easy summaries say whether BOBA read reports, found incomplete evidence, or found conflicts. They avoid global-pass claims and never replace original source evidence.

## 22. Open Questions
Questions are generated only for missing/unreadable evidence, stale evidence, and unresolved conflicts. They target a responsible source owner or human operator and cannot create a decision or execute an action.

## 23. Integration Layer Integration
Integration Layer exposes fixed Report Reader operations for registry inspection, request creation, reference validation, reading, comparison, bundle construction, inspection, export, and non-destructive reset reporting. All are typed, local-only, and read-only in effect.

## 24. Validator Runner Integration
Validator Runner reports can be read through fixed registry scopes, with signal metadata set only when consumed. Malformed, unsupported, unsafe, or digest-mismatched reports produce advisory Validator Runner handoffs; they do not execute validators.

## 25. Workflow Controller Integration
Workflow Controller indexes, runs, and events are registered fixed sources. They are displayed without transitions. Stale workflow evidence creates a workflow handoff that prohibits continuation from stale state.

## 26. Autopilot Integration
Autopilot reports can be read as recovery context and set `autopilot_context_used` only when consumed. Autopilot completion does not resume or advance an Olympus workflow.

## 27. Output Quality Integration
Output Quality reports can be read and compared as source-owned quality evidence. Report Reader does not convert quality assessment into Safety approval or publication permission.

## 28. Safety Gate Integration
Safety Gate reports are fixed safety-sensitive sources. Safety policy classifies Report Reader operations as automatic read-only. The reader cannot modify Safety decisions, create allowances, bypass Safety, or authorize actions.

## 29. Live Companion Preparation
Building a bundle creates a `live_companion` advisory handoff containing bounded references and explanations. It explicitly prohibits execute, approve, resume, upload, and publish behavior.

## 30. Idempotency
Identical requests reuse a completed unchanged read. Request digesting excludes generated timestamps inside nested references, while expected digest changes make a new immutable reference. Current file digests are rechecked before reuse.

## 31. API Routes
The BOBA API provides project-scoped endpoints under `/api/v1/boba/projects/{project_id}/report-reader` for registry/sources, requests, validation, reading, runs, comparison, bundles, events, export, and reset. Strict request models reject uncontracted parser, command, URL, and filesystem-root fields.

## 32. Artifact Paths
Reader metadata is local under `work/boba/projects/<project_id>/report_reader/`: `index.json`, `registries/<snapshot>.json`, `requests/<request>.json`, `runs/<run>/index.json`, `runs/<run>/documents/<document>.json`, `bundles/<bundle>.json`, and `events.jsonl`. These are sanitized interpretation records, not raw reports, logs, media, or private absolute paths.

## 33. Export and Reset
Exports redact secrets, credentials, private paths, raw content, raw logs, and media. The V1 reset endpoint is deliberately non-destructive: source reports, validator history, workflow history, Safety decisions, and Integration transactions remain preserved.

## 34. Validation Commands
Run from the repository root:

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests tools
.\.venv\Scripts\python.exe -m pytest tests/unit/test_boba_report_reader.py
.\.venv\Scripts\python.exe tools/validate_boba_report_reader.py --self-check
.\.venv\Scripts\python.exe tools/validate_boba_report_reader.py --synthetic-project
.\.venv\Scripts\python.exe -m mypy src/olympus/boba tools/validate_boba_report_reader.py
```

The validator writes only sanitized generated reports below `work/validation_reports/boba_report_reader/`; do not commit them.

## 35. Limitations
V1 is not a general document reader and does not claim production readiness. It does not read PDFs, images, OCR, media, arbitrary paths, arbitrary report schemas, external services, or URLs. It does not resolve contradictions without source evidence, run validators or repairs, restore checkpoints, alter source decisions, authorize workflow continuation, upload, publish, push, merge, or deploy.
