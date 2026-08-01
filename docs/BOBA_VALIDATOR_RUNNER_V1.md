# BOBA Validator Runner V1

## 1. Purpose
Validator Runner is the typed, persisted execution and evidence layer for fixed Olympus and BOBA validators.

## 2. Ownership
It owns registry snapshots, plans, input bindings, bounded check execution, evidence, incidents, events, suite decisions, leases, and sanitized exports.

## 3. Non-Ownership
It does not choose repairs, approve targets, alter Safety decisions, accept creative quality, advance workflows, install tools, access external services, upload, publish, push, merge, or deploy.

## 4. Output Quality Reviewer
Validator Runner produces technical evidence. Output Quality Reviewer remains the owner of creative and output-quality acceptance.

## 5. Safety Gate
Safety Gate owns permission decisions. Validator Runner can consume an exact decision but cannot create or reinterpret an allowance.

## 6. Workflow Controller
Workflow Controller owns stage selection and transitions. A passing validation suite never advances a workflow automatically.

## 7. Integration Layer
Integration Layer exposes typed routing for registry inspection, plan creation, execution, cancellation, retry, results, export, and reset.

## 8. Tool Registry and Fallback Routing
Validator declarations are source-controlled and fixed. Missing tools remain unavailable; Validator Runner does not install or dynamically substitute them.

## 9. Validator Registry
Registry snapshots bind validator IDs, versions, adapters, categories, tools, providers, target types, timeouts, and limitations using an immutable digest.

## 10. Categories
Categories cover artifacts, workflow state, checkpoints, code checks, frontend checks, tool health, media, captions, boundaries, face motion, multi-speaker layout, rendering, recovery, and quality-evidence support.

## 11. Internal Validators
Typed Python adapters handle JSON schema, digests, manifests, workflow graphs, transitions, lineage, checkpoints, captions, and existing face/motion and multi-speaker validation functions.

## 12. Fixed-Process Validators
Reviewed adapters run only fixed FFprobe, FFmpeg, Ruff, mypy, pytest, and frontend commands with `shell=False`.

## 13. Validation Plans
Plans bind one exact target, registry snapshot, checks, criteria, inputs, policy, budget, environment, project snapshot, and expiry.

## 14. Required and Optional Checks
Required unavailable, blocked, failed, errored, timed-out, or cancelled checks prevent a passing decision. Optional failures may produce `passed_with_optional_warnings`.

## 15. Input Bindings
Bindings carry project, workflow, stage, clip, output, artifact, storage reference, digest, rights, and protection state. Cross-project, traversal, external URL, stale, and malformed inputs fail closed.

## 16. Environment Snapshots
Snapshots record bounded platform and tool identity without environment-variable values, credentials, or tokens.

## 17. Execution Policy
Policies prohibit shells, networks, package installation, external services, source mutation, accepted-output mutation, tracked-source mutation, workflow transitions, upload, and publication.

## 18. Resource Budgets
Plans cap check count, attempts, per-check and total time, captured output, temporary storage, media/frame sampling, and parallelism.

## 19. Isolated Code Validation
Code and frontend checks require an approved isolated worktree or runner-owned copy. Protected repository roots are rejected and tracked digests are compared before and after.

## 20. Media Validation
Media checks require an exact local, rights-eligible target. FFprobe and decode-to-null are bounded and never create media output.

## 21. Result Normalization
Every check records lifecycle state, exit code, bounded output, assertions, measurements, expectations, evidence IDs, and warnings. Exit code zero alone is insufficient when structured evidence is required.

## 22. Suite Decisions
Suite decisions preserve required and optional outcomes, criteria, target/environment/project currency, technical status, limitations, and explicitly false authority flags.

## 23. Idempotency
Stable keys reuse identical completed results only while target, registry, validator versions, environment, policy, approval, and Safety bindings remain current. This is not a global exactly-once guarantee.

## 24. Validation Leases
Project-scoped leases prevent conflicting suites against the same mutable workspace. Expiry and replacement are explicit; leases are never silently stolen.

## 25. Cancellation
Cancellation stops scheduling, preserves partial evidence, releases the lease, and can terminate only the runner-owned child process.

## 26. Incidents
Incidents cover invalid plans, unknown or unavailable validators, stale or malformed inputs, crashes, timeouts, malformed output, mutation, budgets, conflicts, cancellation, and uncertainty.

## 27. Workflow Integration
Workflow Controller accepts only current, complete Runner decisions for technical-validation requirements and retains transition authority.

## 28. Output Quality Integration
Evidence and unavailable states can be handed to Output Quality Reviewer; Validator Runner cannot mark quality accepted.

## 29. Code Surgeon Integration
Code Surgeon may request exact isolated validation. Validator Runner never applies patches, commits, pushes, or merges.

## 30. Tool Recovery Integration
Tool Recovery outputs may be validated against exact requirements, then handed to Output Quality Reviewer. Validator Runner does not accept recovery quality.

## 31. Autopilot Integration
Autopilot can request plans and monitor results but cannot alter results, waive required checks, or continue the workflow directly.

## 32. API Routes
Project routes provide runner, registry, validators, availability, plans, plan validation, runs, execution, cancellation, bounded retry, results, events, export, and reset.

## 33. Artifact Paths
State is stored under `projects/<project_id>/validator_runner/`, including immutable registry, plan, run, check, event, and lease records. Temporary execution state remains under ignored runner-owned workspaces.

## 34. Export and Reset
Exports redact private paths, secrets, environment values, and complete logs. Reset clears active metadata only and preserves completed history and all target, Workflow, Safety, and Integration artifacts.

## 35. Validator Commands
Only source-declared argument arrays are executable. Arbitrary executables, commands, flags, callables, import paths, pipes, redirects, chaining, and substitutions are unavailable.

## 36. Limitations
V1 offers bounded local process isolation, not a global sandbox. Optional missing providers remain unavailable. Passing confirms only the exact technical plan and does not guarantee correctness, production readiness, creative quality, workflow continuation, upload, or publication.
