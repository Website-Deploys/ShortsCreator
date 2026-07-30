# BOBA Integration Layer V1

## 1. Purpose

BOBA Integration Layer V1 is the typed interoperability boundary between BOBA
modules and Olympus. It gives cross-module requests one registered identity,
one bounded contract, one validation path, and one durable transaction history.

The layer connects modules but does not choose actions. Decision authority
remains with the module that owns the decision.

## 2. What Integration Layer does

The layer provides:

- Static module and operation registries.
- Typed, project-scoped request and response envelopes.
- Schema, artifact, dependency, approval, Safety Gate, and idempotency checks.
- Fixed source-defined target adapters.
- Durable transactions, bounded events, failures, and handoffs.
- Sanitized inspection and export data for the API and frontend.

Every routed request is tied to a project, optional run, correlation ID,
transaction ID, operation, payload digest, and registry snapshot.

## 3. What it does not do

Integration Layer V1 does not choose repairs, create approvals, change Safety
Gate decisions, or reinterpret a denial as permission. It does not directly run
shell commands, Git, FFmpeg, arbitrary Python, workflow resume, checkpoint
restore, upload, publication, push, merge, deployment, package installation,
service restart, network access, external APIs, scraping, or media downloads.

It does not modify source media or accepted outputs. A registered target module
retains ownership of its operation and must independently enforce its own
approval, Safety, rights, checkpoint, and validation rules.

In explicit terms, it does not create approvals and it does not change Safety
Gate decisions.

## 4. Existing integration.py compatibility

`src/olympus/boba/integration.py` remains the application facade. Existing BOBA
helper names and call sites are preserved. Integration Layer V1 adds registry,
request, route, inspect, export, and reset helpers without replacing the
existing module APIs.

The facade contains a fixed mapping from registered operation IDs to explicit
typed adapters. A request cannot supply an import path, callable, handler name,
or command.

## 5. Difference from Autopilot Controller

Autopilot Controller coordinates which bounded action should happen next.
Integration Layer transports and validates the resulting cross-module request.

An Integration Layer transaction is not an Autopilot authorization. An
execution-capable route still requires an exact current Autopilot action when
the target operation declares that dependency.

## 6. Difference from Safety Gate

Safety Gate evaluates whether a specific action may proceed under a specific
policy and project snapshot. Integration Layer only transports and verifies the
binding to that persisted decision.

Integration Layer cannot create, broaden, refresh, or override a Safety Gate
allowance. Expired, denied, mismatched, or missing decisions block the request.

## 7. Difference from Workflow Controller

Workflow Controller owns workflow progression, pause, resume, and checkpoint
orchestration. Integration Layer V1 has no workflow-control authority.

Workflow resume and checkpoint restore are registered as future-gated
operations so their absence is explicit. Routing them returns a truthful
future-gated result rather than silently invoking workflow code.

## 8. Difference from Tool Registry

A tool registry describes tools and their capabilities. The Integration Layer
registry describes BOBA modules and the typed operations BOBA may request from
them.

Integration Layer does not install tools, discover plugins, scan entry points,
or accept runtime registration from requests. Tool Recovery remains responsible
for selecting and independently validating any registered recovery tool.

## 9. Module registry

`build_boba_module_registry()` returns a deterministic static registry covering
the current BOBA modules and explicit future modules. Each descriptor records
version, implementation and health status, capabilities, declared operations,
dependencies, artifact pattern, warnings, and limitations.

Duplicate IDs and invalid cross-links fail validation. Future, unavailable, and
blocked modules remain visible but cannot be treated as available targets.
Immutable snapshots use a deterministic SHA-256 digest.

## 10. Operation registry

`build_boba_operation_registry()` defines each operation's owning module,
operation class, side-effect class, request and response schema IDs, supported
versions, dependencies, approval and Safety requirements, timeout, and
future/prohibited status.

Operation classes are read-only, planning, approved execution, approved
rollback, future-gated, or prohibited. Handler references stay inside trusted
application composition; they are never accepted from a request.

## 11. Request/response envelopes

`BobaIntegrationEnvelopeV1` carries producer and consumer identities, schema
identity, project and run scope, correlation and transaction IDs, expiry,
idempotency key, digests, artifact references, approval and Safety bindings,
and a bounded JSON payload.

Requests and responses have separate typed records. Correlation, transaction,
project, and run identities remain stable through routing. Payloads reject
callables, dynamic imports, arbitrary function names, commands, external URLs,
secrets, full patches, full logs, raw media, oversized values, and authority
override fields.

## 12. Artifact references

Cross-module artifacts use `BobaIntegrationArtifactReferenceV1`; the layer does
not copy large artifact blobs. References include producer, project, schema,
version, record identity, digest, availability, staleness, malformed state,
immutability, and rights/Safety relevance.

Required missing, stale, malformed, cross-project, invalid-digest, external URL,
absolute private path, traversal, and UNC references fail closed. Optional
missing artifacts remain visible as warnings.

## 13. Schema compatibility

The compatibility engine records exact matches, declared backward-compatible
versions, safe normalization, migration requirements, and incompatible
versions. Unsupported major versions and safety-critical compatibility
differences block routing.

Compatibility is explicit and persisted. The layer does not silently coerce
execution authority, approval, Safety, or scope fields.

## 14. Dependency checks

Dependency checks evaluate declared module and artifact requirements before a
request becomes ready. They record available and unavailable modules, required
and missing artifacts, stale or malformed artifacts, status, blocking state,
reason, and warnings.

Missing required dependencies block routing and create a typed failure and
handoff. Optional uncertainty remains visible instead of being reported as
confirmed readiness.

## 15. Approval-binding transport

Execution-capable operations require an exact
`BobaIntegrationApprovalBindingV1`. Project, run, plan, strategy, patch, tool,
parameter digest, approval record, confirmation, and expiry are matched against
the current persisted context as applicable.

Integration Layer does not create approval. A missing, expired, partial, or
mismatched approval blocks routing, and target-module revalidation is still
required.

## 16. Safety-binding transport

`BobaIntegrationSafetyBindingV1` binds a request to a current persisted Safety
Gate decision, case, request digest, project snapshot, policy snapshot, target
module, operation, scope, and expiry.

A denied, expired, mismatched, human-review-required, or
more-evidence-required decision blocks routing. Integration Layer cannot change
the decision and cannot remove the target's independent Safety check.

## 17. Idempotency

Each request has a bounded idempotency key and canonical request digest.
Identical completed local requests may reuse a saved typed response. Reusing the
same key with changed request content creates an idempotency conflict.

Failed attempts remain in history. This is local durable deduplication, not a
claim of distributed or global exactly-once execution.

## 18. Transaction lifecycle

Transactions move through explicit validation, compatibility, dependency,
approval, Safety, idempotency, readiness, routing, target, response, and
terminal states. Completed transaction records are immutable.

Terminal outcomes include succeeded, blocked, failed, timed out, cancelled,
duplicate reused, and future gated. A validated request is not reported as a
routed or executed request.

## 19. Typed target invocation

Routing selects only a source-defined handler for a registered operation ID.
Unknown handlers are rejected at engine construction, and request payloads
cannot register or replace handlers.

Target results must be bounded JSON objects. Execution-capable targets must
explicitly report independent revalidation. Target rejection, timeout, failure,
and reported side effects are recorded truthfully.

## 20. Read-only routing

Read-only operations may route without execution approval when their descriptor
does not require it. They still require valid project, run, schema, artifact,
dependency, registry, expiry, and idempotency checks.

Read-only status does not permit network access, arbitrary file reads, commands,
or unregistered operation dispatch.

## 21. Approved execution routing

Approved execution and rollback operations require all descriptor-declared
guards: exact Autopilot coordination, exact target approval, a current Safety
Gate allowance, compatible dependencies, idempotency, and independent target
revalidation.

Passing Integration Layer validation does not guarantee target success. The
target can reject or fail the request, and that outcome remains visible.

## 22. Future-gated operations

Workflow resume, checkpoint restore, upload, publication, push, merge, and
deployment are represented explicitly but remain future-gated. Package
installation and service restart are prohibited.

Future registration documents a boundary; it does not make the capability
available or authorize it.

## 23. Failure handling

Failures retain class, code, source layer, source module and operation, bounded
summary, retry properties, project-state uncertainty, evidence references, and
recommended handoff target.

Unknown modules, unknown operations, incompatibility, dependency failures,
approval failures, Safety failures, idempotency conflicts, unavailable targets,
rejections, timeouts, and target failures fail closed. Secrets, private paths,
full logs, and raw patches are redacted from public failure records.

## 24. Integration events

Each transaction has an append-only bounded JSONL event stream with monotonic
sequence numbers. Events separate technical messages, easy-language messages,
confirmed facts, assessments, evidence references, severity, and attention
requirements.

Events report validation and routing truth. They are not workflow commands and
do not grant authority.

## 25. API routes

The existing BOBA router exposes:

- `GET /api/v1/boba/projects/{project_id}/integration-layer`
- `GET /api/v1/boba/projects/{project_id}/integration-layer/modules`
- `GET /api/v1/boba/projects/{project_id}/integration-layer/operations`
- `POST /api/v1/boba/projects/{project_id}/integration-layer/requests`
- `POST /api/v1/boba/projects/{project_id}/integration-layer/route`
- `GET /api/v1/boba/projects/{project_id}/integration-layer/transactions/{transaction_id}`
- `GET /api/v1/boba/projects/{project_id}/integration-layer/transactions/{transaction_id}/events`
- `GET /api/v1/boba/projects/{project_id}/integration-layer/export`
- `DELETE /api/v1/boba/projects/{project_id}/integration-layer`

Creating a request validates it but returns `routed: false`. Routing is a
separate explicit endpoint and repeats the relevant checks.

## 26. Artifact paths

Under the configured BOBA store root, Integration Layer metadata uses:

- `projects/<project_id>/integration_layer/index.json`
- `projects/<project_id>/integration_layer/registries/<registry_id>.json`
- `projects/<project_id>/integration_layer/transactions/<transaction_id>/index.json`
- `projects/<project_id>/integration_layer/transactions/<transaction_id>/events.jsonl`
- `projects/<project_id>/integration_layer/idempotency/index.json`

Writes are local and atomic where applicable. Public API and export payloads do
not disclose the absolute store root.

## 27. Export/reset

Export returns bounded JSON and marks private paths, secrets, raw patches, full
logs, source media, and accepted-output behavior explicitly. It does not export
raw media.

Reset removes active Integration Layer and idempotency metadata only when no
non-terminal transaction would be erased. It preserves immutable registry and
transaction history, upstream BOBA artifacts, approvals, Safety decisions,
Autopilot history, source media, and accepted outputs.

## 28. Validator commands

Run the offline contract self-check:

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_integration_layer.py --self-check
```

Run all 149 bounded synthetic scenarios:

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_integration_layer.py --synthetic-project
```

Inspect persisted metadata for one local project without routing:

```powershell
D:\Olympus\.venv\Scripts\python.exe tools\validate_boba_integration_layer.py --project-id <project_id>
```

Generated reports are written under
`work/validation_reports/boba_integration_layer/` and must not be committed.

## 29. Limitations

Integration Layer V1 uses local storage and local idempotency; it does not
provide distributed transactions or global exactly-once execution. Only fixed
facade adapters are callable, so a registered operation may truthfully report
that its handler is unavailable in the current application composition.

Future Workflow Controller, checkpoint restore, upload, publication, push,
merge, and deployment integration remains unavailable. The layer does not
prove that an output is correct, safe, published, or production-ready; those
claims require the owning module's evidence and validation.
