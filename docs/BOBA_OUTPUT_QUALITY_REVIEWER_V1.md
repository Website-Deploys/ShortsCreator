# BOBA Output Quality Reviewer V1

## 1. Purpose

BOBA Output Quality Reviewer V1 is the read-only quality-control boundary between generated or recovered Olympus outputs and any future internal continuation decision. It determines whether bounded evidence supports acceptance, rejection, more evidence, or human review.

## 2. What It Does

The reviewer resolves one exact known project output, checks rights and safety eligibility, evaluates technical evidence, reviews persisted creative evidence, optionally compares an exact baseline, records regressions, and creates advisory handoffs. It accepts normal renders, Tool Recovery outputs, Code Surgeon behavior-validation artifacts, checkpoint-restored outputs, rerenders, fallbacks, and imported local outputs only when they are explicitly allowlisted.

## 3. What It Does Not Do

V1 does not edit, repair, replace, delete, or rerender media. It does not invoke fallback tools, modify code, resume Olympus, download media, fetch URLs, call external APIs, install software, upload, publish, bypass rights or safety gates, claim copyright safety, guarantee virality, or guarantee production success.

## 4. Difference From Tool Recovery Brain

Tool Recovery diagnoses bounded tool failures and can produce a recovered output under explicit controls. Output Quality Reviewer does not recover anything; it independently reviews the exact recovered artifact and may reject it or require more evidence. A successful recovery command is not quality acceptance.

## 5. Difference From Validator Runner

Validator Runner executes supported validation tasks. Output Quality Reviewer consumes validator evidence and may run only its fixed local read-only FFprobe or bounded decode commands. It combines those facts with required quality properties and creative uncertainty to make a quality decision.

## 6. Difference From Safety Gate

Safety Gate owns safety eligibility. Output Quality Reviewer requires a clear safety state and never overrides or replaces Safety Gate. Its accepted decisions remain advisory inputs for a future independent safety decision.

## 7. Difference From Workflow Controller

Workflow Controller owns continuation. Output Quality Reviewer always leaves `workflow_resume_authorized=false`; even `accepted_for_next_internal_stage` means only that Workflow Controller may consider the exact artifact.

## 8. Review Modes

- `artifact_only`: checks local identity, bytes, checksums, JSON shape, manifest evidence, and persisted bounded validation.
- `local_technical_review`: adds registered local FFprobe and bounded FFmpeg decode checks.
- `full_available_evidence_review`: combines local technical checks with all available persisted creative evidence.
- `baseline_comparison`: compares the reviewed output with one exact allowlisted baseline.
- `human_review_preparation`: builds a bounded review package without media mutation.
- `unknown`: retained for backward-compatible data handling, never treated as a pass.

If required local validators are unavailable, media review degrades honestly to artifact-only and the required unavailable checks block technical acceptance.

## 9. Review Target Resolution

The caller must provide an exact reference or artifact ID from the known project-output allowlist. URLs, absolute paths, drive escapes, UNC paths, traversal, unsupported roots, ambiguous identities, cross-project artifacts, external symlinks, and accidental source-media targets are rejected. Repository-scoped artifacts are limited to approved BOBA recovery, Code Surgeon, and reviewer roots.

## 10. Rights And Safety Eligibility

Unknown or blocked rights stop inspection and produce `blocked_rights`. Blocked safety produces `blocked_safety`; unknown safety produces `needs_more_evidence`. V1 never recommends a rights or safety bypass and makes no copyright-safety determination.

## 11. Required Quality Properties

Requirements are resolved conservatively from explicit non-negotiable Repair Planner requirements, Tool Recovery quality requirements, approved render specifications, source-window metadata, creative briefs, and caller-supplied requirements. Missing required evidence is not converted into a pass.

## 12. Technical Quality Assessment

Technical checks cover artifact existence and size, checksum and manifest identity, JSON schema, media probe, bounded decode, required streams, duration, resolution, aspect ratio, frame rate, frame count, audio sample rate and channels, A/V sync, source window, truncation, duplicate or missing segments, captions, framing, subject visibility, face tracking, and multi-speaker layout. Required failed, blocked, skipped, timed-out, unknown, or unavailable checks prevent technical acceptance.

Existing Olympus timing tolerances remain authoritative: duration and A/V duration delta are `0.15s`; stream-start delta is `0.04s`; frame-rate delta is `0.1fps`.

## 13. Creative Quality Assessment

Creative dimensions cover hook strength and delivery, story completeness, payoff preservation, pacing, clarity, emotional continuity, caption readability and timing, vertical framing, subject visibility, face tracking, multi-speaker layout, motion and transition balance, dialogue and music balance, repetition, meaning preservation, platform fit, and accessibility.

## 14. Facts Versus Subjective Estimates

Probe, checksum, exact timing, stream, and persisted validator results are technical facts within their stated tolerance. Hook, pacing, framing appeal, music fit, emotional effect, and meaning preservation may remain subjective. Numeric creative scores summarize available evidence; they do not objectively prove quality or expected performance.

## 15. Frame And Audio Evidence

V1 may consume bounded generated frame, face-motion, multi-speaker, audio-level, silence, dialogue-clarity, and music-validation evidence when already available. It does not claim subject visibility from dimensions alone or music quality from mood metadata alone. No unbounded media or raw frame bytes are persisted in safe exports.

## 16. Baseline Comparison

Baseline comparison requires one exact allowlisted baseline identity. It compares technical properties, source timing, required streams and captions, persisted creative statuses, and file identity. Persisted baseline status objects are normalized before comparison so equivalent evidence can be recognized without treating unknown properties as equal.

## 17. Quality Regression Detection

Regressions are categorized by severity, disclosure, approval, non-negotiable status, evidence, and acceptance impact. Required source-window, timing, stream, integrity, story, or payoff loss is blocking. Any regression with `reject` or `blocked` impact prevents baseline equivalence. An approved disclosed minor regression may still require human approval.

## 18. Acceptance Decisions

- `accepted_for_next_internal_stage`
- `accepted_with_disclosed_limitations`
- `needs_human_review`
- `needs_more_evidence`
- `rejected_technical`
- `rejected_quality`
- `rejected_regression`
- `blocked_rights`
- `blocked_safety`
- `not_reviewable`

Every decision keeps `workflow_resume_authorized=false` and `publication_authorized=false`.

## 19. Human Review Package

The package contains the sanitized output reference, optional baseline reference, bounded technical and creative summaries, regression summary, unavailable evidence, critical and optional items, ten focused reviewer questions, safe internal decision options, and prohibited actions. Reviewer identity is stored only as a one-way bounded reference; authentication material is excluded.

## 20. Handoffs

Advisory handoffs can target Workflow Controller, Safety Gate, Tool Recovery Brain, Repair Planner, Root Cause Analyzer, Code Surgeon, Checkpoint Recovery Manager, Validator Runner, Rights + Permission Gate, Final Decision Bus, or a human operator. `apply_automatically=false` and `human_approval_required=true` are mandatory V1 defaults.

## 21. API Routes

- `POST /api/v1/boba/projects/{project_id}/output-quality-reviewer/review`
- `POST /api/v1/boba/projects/{project_id}/output-quality-reviewer/compare`
- `POST /api/v1/boba/projects/{project_id}/output-quality-reviewer/human-review`
- `GET /api/v1/boba/projects/{project_id}/output-quality-reviewer`
- `GET /api/v1/boba/projects/{project_id}/output-quality-reviewer/export`
- `DELETE /api/v1/boba/projects/{project_id}/output-quality-reviewer`

Mutation, source-modification, and network-review request flags are literal `false`. The DELETE route removes only reviewer metadata.

## 22. Artifact Paths

The main report is stored at:

`work/boba/projects/<project_id>/output_quality_reviewer/index.json`

Each review record is stored at:

`work/boba/projects/<project_id>/output_quality_reviewer/reviews/<review_case_id>/index.json`

Bounded sample evidence, when used, remains under the reviewer evidence root. Reviewed output, source media, render manifests, Tool Recovery records, and Code Surgeon records remain untouched.

## 23. Export And Reset

Export returns JSON-safe reviewer metadata with private absolute paths, secrets, credentials, full command logs, raw frames, and raw media excluded. Reset removes only the project’s `output_quality_reviewer` metadata directory. It does not remove outputs, source media, render manifests, recovery artifacts, Code Surgeon artifacts, or samples outside that directory.

## 24. Validator Commands

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_output_quality_reviewer.py --self-check
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_output_quality_reviewer.py --synthetic-project
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_output_quality_reviewer.py --project-id PROJECT_ID
```

Synthetic mode runs 93 offline scenarios. When FFmpeg and FFprobe are available, it generates tiny temporary local A/V fixtures and performs real probe and decode checks. If they are unavailable, media scenarios are reported honestly rather than fabricated. Reports are written under `work/validation_reports/boba_output_quality_reviewer/` and must not be committed.

## 25. Limitations

V1 cannot replace every human viewing or listening judgment. Saved plans do not prove visible or audible execution. Bounded generated fixtures do not prove behavior for arbitrary creator footage. Missing multimodal evidence remains unavailable. Technical success is not creative acceptance. Passing checks does not guarantee virality, publication safety, production readiness, or business performance. `accepted_for_next_internal_stage` authorizes neither workflow resume nor upload/publication.
