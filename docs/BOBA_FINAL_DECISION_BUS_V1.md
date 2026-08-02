# BOBA Final Decision Bus V1

## 1. Purpose
Final Decision Bus V1 combines current, persisted owner decisions for one exact registered internal action.

## 2. Scope
It evaluates fixed policy requirements and records an immutable disposition for a project-scoped request.

## 3. Not an Execution Engine
The bus does not run a command, target module, workflow transition, validator, repair, renderer, FFmpeg, Git action, upload, publication, push, merge, or deployment.

## 4. Authority Ownership
Rights + Permission Gate, Safety Gate, target approval, Workflow Controller, Validator Runner, Output Quality Reviewer, Artifact Inspector, Autopilot, Code Surgeon, Tool Recovery, and Report Reader keep ownership of their own records.

## 5. Fixed Source Registry
Decision sources are defined in source code. Requests cannot add a source, replace a resolver, or discover a source dynamically.

## 6. Fixed Action Policy Registry
Policies are defined in source code and bind one action-policy ID to one Integration Layer module and operation ID.

## 7. Exact Target Identity
A request must exactly match the module and operation declared by its fixed action policy.

## 8. Project Scope
Every request, source binding, evaluation, decision, envelope, event, lease, and invalidation is project-scoped.

## 9. Optional Identity Scope
Workflow run, stage instance, clip, output, artifact, and snapshot digests are bound when supplied by the request and owner record.

## 10. Source Selectors
A request carries only exact source IDs and producer-record IDs. The bus never selects a record automatically.

## 11. Canonical Record Digests
The bus calculates a canonical digest of the typed owner record at collection time and compares an optional supplied digest.

## 12. Digest Limit
A collection-time canonical digest is not represented as an owner-provided signed digest when the owner record lacks one.

## 13. Source Binding
A source binding stores bounded sanitized metadata, identity checks, lifecycle checks, and a digest. It never changes the source record.

## 14. Evidence Requirements
Requirements are generated only from the selected fixed action policy. API payloads cannot add, weaken, remove, or reinterpret requirements.

## 15. Evidence Binding
Evidence can be satisfied, missing, stale, invalid, blocked, or unknown. Missing and unknown evidence do not become approval.

## 16. Rights
A selected blocking Rights + Permission Gate record blocks the final decision. The current Rights Gate does not itself grant arbitrary execution authority.

## 17. Safety
Safety must allow the exact internal target and remain current. Final Decision Bus cannot create, alter, or override a Safety decision.

## 18. Target Approval
A target approval must match the project, target module, target operation, explicit confirmation, and current-match state.

## 19. Human Decisions
Policies that require a human decision hold until a current explicit owner decision is selected and ready.

## 20. Workflow
Workflow data is source-owned. A workflow result may inform policy evaluation, but the workflow controller independently revalidates any later action.

## 21. Artifact Integrity
Required artifact integrity evidence is accepted only when its owner record is current, exact, and ready. Presence alone is not integrity.

## 22. Technical Validation
Validator evidence is owned by Validator Runner. Final Decision Bus never runs validation or converts failed validation into a pass.

## 23. Output Quality
Output Quality Reviewer retains acceptance authority. Final Decision Bus cannot turn a review into an accepted output.

## 24. Recovery and Checkpoints
Recovery, Code Surgeon, Tool Recovery, Autopilot, and checkpoint records remain owner-controlled. A recovery plan never gains execution authority from the bus alone.

## 25. Report Reader
Report Reader is advisory only. A report bundle can add context but cannot satisfy an authoritative policy requirement.

## 26. Freshness and Expiration
Expired, invalidated, superseded, stale, or non-current required evidence produces a hold or block. It never becomes ready by fallback.

## 27. Conflicts
Conflicting authoritative records produce hold_conflicting_evidence. The bus never picks a winner automatically.

## 28. Evaluation Order
Evaluation checks request validity, registry and policy, identity, Rights, Safety, approval, human decision, workflow, artifact integrity, validation, quality, recovery/checkpoint, freshness, conflicts, leases, and completeness in order.

## 29. Dispositions
Only ready_for_exact_internal_dispatch can produce an envelope. Holds and blocks preserve the owner reason without hiding it.

## 30. Immutable Decisions
Final decisions are immutable records. Later state changes produce append-only invalidation records instead of rewriting prior decisions.

## 31. Idempotency
Requests and evaluations use stable digests. Equivalent current requests reuse their current record; changed evidence creates a distinct evaluation.

## 32. Leases
A bounded exact-action lease prevents duplicate ready dispatches for the same active action. Expired or invalidated leases remain historical.

## 33. Dispatch Envelopes
A dispatch envelope is exact, bounded, project-scoped, single-use, expiring metadata. It is not execution authority and never reports an executed target.

## 34. Envelope Consumption
Consumption requires a matching Integration Layer transaction with independent target revalidation. Consumption records revalidation only, not target success.

## 35. Invalidation
Meaningful state change, expiry, missing source data, or owner invalidation must prevent use of the envelope. Invalidating a decision revokes outstanding envelopes and leases.

## 36. Persistence
Active state is stored under work/boba/projects/project-id/final_decision_bus. The active index, registries, requests, source bindings, evidence, evaluations, decisions, dispatch envelopes, events, and active lock are separate project-scoped records.

## 37. Reset and Export
Reset removes only active metadata when no active lease or envelope exists. Immutable history and event streams remain. Export is bounded and redacts private paths, secrets, raw reports, logs, media, code, and commands.

## 38. API and Frontend
The BOBA API exposes registry inspection, exact request creation, source binding, evidence, conflict detection, evaluation, finalization, envelope inspection, invalidation, events, export, and safe reset. The frontend displays authority status and never includes an Execute button.

## 39. Validation and Limitations
Run the validator with --self-check and --synthetic-project, then run the focused test suite. The V1 bus currently consumes only the typed persisted fields that source owners expose; unavailable or incomplete source records hold safely rather than being inferred.