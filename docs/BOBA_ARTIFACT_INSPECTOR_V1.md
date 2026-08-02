# BOBA Artifact Inspector V1

## 1. Purpose

BOBA Artifact Inspector V1 is a read-only, typed, and persisted inspection layer for exact project-scoped Olympus and BOBA artifacts. It reports what is registered, present, changed, missing, boundedly inspectable, or in need of deeper validation. It never repairs or changes an artifact.

## 2. What Artifact Inspector Owns

The inspector owns fixed artifact descriptors, exact reference validation, bounded local metadata and signature observation, streaming SHA-256 checks when allowed, integrity/freshness/protection assessments, inventories, declared lineage, comparisons, findings, incidents, events, and advisory handoffs.

## 3. What It Does Not Own

It does not own artifact production, repair, deletion, movement, copying, workflow transitions, quality approval, safety approval, validator execution, checkpoint restoration, code execution, rights decisions, uploads, publishing, deployment, or external access.

## 4. Difference from Validator Runner

Artifact Inspector establishes bounded local evidence only. Validator Runner owns deep technical checks such as media stream, timing, decode, rendering-manifest, checkpoint, and code static validation. A matching digest is not a technical pass.

## 5. Difference from Report Reader

Artifact Inspector can verify a report artifact's identity, scope, presence, size, digest, and lightweight structure. Report Reader remains responsible for report meaning, findings, chronology, contradictions, source authority, and summaries.

## 6. Difference from Workflow Controller

Artifact Inspector emits advisory `workflow_controller` handoffs when required artifacts are missing or at risk. Workflow Controller alone decides transitions and still requires its own current revision, safety, quality, approval, and validator evidence.

## 7. Difference from Output Quality Reviewer

Artifact Inspector does not judge creative or technical output quality. Output Quality Reviewer owns acceptance and quality decisions; byte equality or file presence never substitutes for that review.

## 8. Difference from Checkpoint Recovery Manager

V1 can observe a registered checkpoint artifact only when a fixed descriptor is available. It does not restore checkpoints or claim that a present checkpoint is runtime-restorable. Future checkpoint recovery remains separate.

## 9. Trusted Artifact Registry

`build_fixed_artifact_type_registry()` is source-code-defined and deterministic. Requests cannot define descriptors, roots, resolvers, parsers, commands, or storage scopes. Registry snapshots are immutable and include a deterministic registry digest.

## 10. Artifact Categories

The V1 registry only exposes artifact types with real, fixed storage ownership as available or degraded. It includes rendering manifests and outputs, BOBA report/validation/workflow/safety records, event streams, source-media references, and accepted-output references where safely representable. Future or unavailable descriptors are rejected for inspection.

## 11. Exact References

Every request carries typed `BobaArtifactReferenceV1` records with project, source, workflow, stage, clip, output, producer, type, storage kind, digest, size, protection, and declared-lineage fields. Reference IDs are stable hashes of exact identity material; they are not arbitrary file paths.

## 12. Storage-Scope Validation

References must be relative, project-scoped, descriptor-matching paths. The inspector rejects URLs, file URIs, absolute and UNC paths, traversal, unsupported fields, cross-project scopes, owner mismatches, storage-kind mismatches, source media presented as generated output, and mutable accepted outputs. Canonical resolution confirms paths remain beneath the descriptor's approved local root and rejects symlink escapes.

## 13. Metadata Inspection

For a single exact reference, V1 records bounded facts such as existence, accessibility, file/directory kind, observed format, size, modification metadata, expected digest, and protection context. Private absolute paths are not exported.

## 14. Streaming Digest Verification

When a descriptor and rights state permit it, V1 computes SHA-256 with fixed 64 KiB streaming chunks. It never loads an entire artifact into memory and enforces the configured request digest budget.

## 15. Persisted Versus Recomputed Digests

A persisted digest is producer-provided evidence. A recomputed digest is clearly marked only after V1 streams the exact artifact bytes. The API and exports retain separate persisted/recomputed statuses; neither is presented as a quality or workflow decision.

## 16. Lightweight Format Inspection

V1 uses bounded checks only: structured JSON/JSONL samples and common MP4 header evidence. File extensions alone are not proof, and V1 does not decode media, invoke FFprobe/FFmpeg, extract archives, run OCR, or execute embedded content.

## 17. Partial-Write Detection

Zero-length files, expected-size mismatches, bounded digest budget exhaustion during a read, and changed pre/post metadata mark an artifact as partial or requiring deeper validation. V1 leaves the artifact unchanged.

## 18. Changed-During-Read Detection

V1 compares size and nanosecond modification metadata before and after a bounded read. If either changes, the artifact is never marked verified and the snapshot records `changed_during_read` and `partial_write_suspected`.

## 19. Integrity Assessments

Integrity is reported as `verified`, `verified_with_limitations`, `missing`, `inaccessible`, `digest_mismatch`, `wrong_type`, `malformed`, `partial`, `deeper_validation_required`, `rights_blocked`, or `unknown`. These are bounded observations, not guarantees of media validity, safety, rights, or workflow readiness.

## 20. Freshness Assessments

Freshness uses explicit project snapshot, workflow, producer, historical, and digest evidence provided by the request. Filesystem modification time is never used alone to infer chronology, supersession, or current workflow eligibility.

## 21. Source-Media Protection

Source media remains read-only. When persisted rights do not allow local content processing, V1 permits metadata-only observation but blocks content hashing. Source media cannot be represented as a generated output target.

## 22. Accepted-Output Protection

Accepted outputs must be immutable and read-only. V1 detects an observed digest mismatch or partial state but never changes permissions, overwrites output, picks a replacement, or accepts quality.

## 23. Inventories

Inventories are built only from exact registered references for an inspection run. They report present, missing-required, missing-optional, and orphan-candidate reference IDs. V1 never recursively scans arbitrary project storage.

## 24. Orphan Detection

A V1 orphan candidate is an exact non-historical reference without a producer record. It is advisory only: V1 never deletes, quarantines, or automatically selects an orphan.

## 25. Duplicate Detection

Comparison can identify matching recomputed SHA-256 bytes for two inspected registered references. Equality is limited to byte evidence and does not automatically choose a winner or infer quality.

## 26. Conflicting Artifacts

A comparison reports a conflict when immutable identities share an output identity but declare incompatible expected digests. V1 preserves the conflict for a responsible producer, Validator Runner, or human reviewer; it does not resolve it.

## 27. Lineage

Lineage is built only from explicit persisted `declared_lineage` relationships with known references. V1 never infers lineage from filenames, timestamps, directory proximity, extension, or size similarity.

## 28. Comparisons

`compare_artifacts` compares two exact references from one completed inspection run. Comparison records are immutable and persisted separately so they never rewrite a completed run record.

## 29. Coverage

Coverage reports requested versus inspected reference counts, missing required artifacts, and blocked inspection counts. `complete` only means each requested exact artifact was observed within the V1 boundary; it does not certify technical validity.

## 30. Validator Runner Handoffs

When a descriptor requires deeper validation, V1 emits an advisory `validator_runner` handoff containing the exact reference IDs, observed snapshot IDs/digests when available, required validator IDs, blocking conditions, and protected-state requirements. V1 never runs the validator.

## 31. Report Reader Handoffs

Report artifacts produce advisory `report_reader` handoffs. The handoff preserves exact artifact evidence and makes clear that Report Reader and the original producer retain responsibility for interpretation.

## 32. Workflow Integration

Missing required artifacts produce a `workflow_controller` advisory handoff. The handoff cannot advance, unblock, resume, or otherwise authorize a workflow. The existing Workflow Controller remains the only transition authority.

## 33. Autopilot and Recovery Integration

Partial-write risk produces an advisory `autopilot_controller` handoff. It can inform a future recovery review but cannot choose, execute, accept, or release recovery work.

## 34. Checkpoint Preflight

Checkpoint descriptors are future-gated unless a fixed, real descriptor is available. V1 can never restore checkpoint data, execute a checkpoint, or claim runtime restorability from presence or digest evidence.

## 35. Code-Worktree Inspection

Code-worktree descriptors remain future-gated unless a fixed Code Surgeon manifest and allowlisted file contract is introduced. V1 does not run Git, inspect unrelated source trees, apply patches, or run tests.

## 36. API Routes

All routes are project-scoped under `/api/v1/boba/projects/{project_id}/artifact-inspector`:

- `GET /` reads active metadata.
- `GET /registry` and `GET /types` expose the trusted registry.
- `POST /requests` creates a typed inspection request from exact references.
- `POST /requests/{request_id}/validate` validates scope without content reads.
- `POST /requests/{request_id}/inspect` performs bounded inspection.
- `GET /runs/{run_id}` reads a combined, sanitized run view.
- `POST /inventory`, `POST /lineage`, and `POST /compare` build/read advisory analysis.
- `GET /runs/{run_id}/events` and `GET /export` return sanitized read-only data.
- `DELETE /` removes only active inspector metadata after active runs have completed.

## 37. Artifact Paths

With the BOBA store rooted at `work/boba`, V1 persists generated metadata only at:

- `projects/<project_id>/artifact_inspector/index.json`
- `projects/<project_id>/artifact_inspector/registries/<registry_id>.json`
- `projects/<project_id>/artifact_inspector/requests/<request_id>.json`
- `projects/<project_id>/artifact_inspector/runs/<run_id>/index.json`
- `projects/<project_id>/artifact_inspector/runs/<run_id>/artifacts/<snapshot_id>.json`
- `projects/<project_id>/artifact_inspector/inventories/<inventory_id>.json`
- `projects/<project_id>/artifact_inspector/comparisons/<comparison_id>.json`
- `projects/<project_id>/artifact_inspector/runs/<run_id>/events.jsonl`

Registry, request, run, artifact snapshot, inventory, and comparison records use atomic immutable writes. Events are append-safe and fsynced. No raw media, source-code bodies, complete logs, credentials, tokens, or private absolute paths are exported.

## 38. Export and Reset

Exports use `sanitize_artifact_export` and explicitly exclude raw media, source-code bodies, and complete logs. Reset removes only the active `artifact_inspector/index.json` after no run is pending/running. It preserves immutable registry/request/run/snapshot/inventory/comparison history, event streams, source media, accepted outputs, Workflow history, Validator history, Report Reader history, and Safety decisions.

## 39. Validation Commands

Run from `D:\Olympus`:

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests tools
.\.venv\Scripts\python.exe -m pytest tests/unit/test_boba_artifact_inspector.py
.\.venv\Scripts\python.exe tools\validate_boba_artifact_inspector.py --self-check
.\.venv\Scripts\python.exe tools\validate_boba_artifact_inspector.py --synthetic-project
.\.venv\Scripts\python.exe -m mypy src/olympus/boba tools/validate_boba_artifact_inspector.py

cd frontend
npm run typecheck
npm run lint
npm test
npm run build
```

## 40. Limitations

V1 accepts at most 128 exact references per request and uses deliberately conservative 32 MiB per-artifact/total digest limits plus a 256-entry directory inventory limit. These limits favor safe local observation and may yield `deeper_validation_required` for larger artifacts. V1 does not inspect arbitrary paths, scan drives, decode media, execute FFmpeg, execute validators, interpret report meaning, repair/move/copy/delete artifacts, restore checkpoints, access external services, upload/publish content, or claim production readiness, legal certainty, or guaranteed integrity.