# BOBA Frontend / Review UI V1

A unified human review workspace for Olympus.

The Review UI is a **presentation and canonical action-routing layer**. It is not
authoritative. It projects records owned by other BOBA modules and routes
explicitly confirmed human actions back to the module that owns the authority.

## Non-negotiable boundaries

The Review UI never independently creates or changes:

- Rights decisions
- Safety decisions
- approvals
- technical-validation results
- quality decisions
- workflow transitions
- Artifact Inspector decisions
- Final Decision Bus readiness
- recovery completion

A successful API submission alone is never presented as an authoritative state
change. `authoritative_state_changed` may be `true` only when a canonical owner
record ID **and** digest are present; `_persist_receipt` raises if that invariant
is violated.

## Architecture

| Layer | Location |
| --- | --- |
| Projection and routing engine | `src/olympus/boba/review_ui.py` |
| Persistence | `src/olympus/boba/store.py` (`review_ui/…`) |
| Facade helpers | `src/olympus/boba/integration.py` |
| Operation registration | `src/olympus/boba/integration_layer.py` |
| Safety classification | `src/olympus/boba/safety_gate.py` |
| API routes | `src/olympus/api/v1/routes/boba.py` |
| Pure client logic | `frontend/src/lib/reviewUi.ts` |
| Workspace components | `frontend/src/components/project/BobaReview*.tsx` |

### Fixed registries

Both registries are source code. A browser request cannot add a module, an
operation, a URL, a filesystem path, or a command.

- **13 view descriptors** — one per review mode.
- **4 action descriptors** — each naming an exact owning module and operation:

| Action | Owner | Operation | V1 |
| --- | --- | --- | --- |
| Acknowledge review notification | `review_ui` | `acknowledge_notification` | available (metadata only) |
| Submit workflow human decision | `workflow_controller` | `record_human_workflow_decision` | available |
| Submit output quality decision | `output_quality_reviewer` | `record_boba_output_human_review` | unavailable — no exact case binding |
| Submit Safety review | `safety_gate` | `record_human_safety_review` | unavailable — no exact case binding |

The two unavailable actions are declared, not hidden: the UI lists them with the
owning module and the reason they cannot be offered.

## Deterministic review queue

Twelve fixed priority tiers, derived only from canonical signals:

| Tier | Reason | Category |
| --- | --- | --- |
| 10 | Rights or Safety critical block | critical attention |
| 20 | Source-media or accepted-output protection incident | critical attention |
| 30 | Workflow recovery hold | blocked |
| 40 | Required exact human approval | human review required |
| 50 | Output Quality human review | human review required |
| 60 | Final Decision Bus hold or conflict | blocked |
| 70 | Missing or failed technical validation | awaiting evidence |
| 80 | Missing or stale artifact | awaiting evidence |
| 90 | Recovery incident | ready for review |
| 100 | Candidate clip / rendered output review | ready for review |
| 110 | Completed informational | informational |
| 120 | Historical record | historical |

Every queue item retains its source module, source record ID, source record
digest, original status, original decision, current/stale/expired state, blocker
counts, missing evidence, conflicts, warnings and limitations. Presentation
categories never replace source-owned decisions.

**A missing owner record is reported as `unavailable`, never as a pass.**

## Canonical action routing

```
refresh snapshot
  → validate project snapshot digest
  → validate workflow revision
  → validate target digest
  → validate each source record digest
  → confirm the action descriptor is still available
  → require explicit confirmation (server-issued token)
  → submit idempotently to the owning module
  → wait for the canonical owner response
  → persist an immutable receipt
  → invalidate and re-read all affected canonical queries
```

There is no optimistic authority update anywhere in this flow.

### Confirmation tokens

A snapshot response publishes `action_confirmations`: one 64-character digest per
available action, binding `(snapshot digest, action id, target digest)`. The
client echoes the token back; it cannot compute or forge one, and a token cannot
be replayed against different canonical state.

### Staleness guards

Each guard is checked independently and rejects before the owner is contacted:

| Guard | Code |
| --- | --- |
| Project snapshot drifted | `stale_project_snapshot` |
| Workflow revision changed | `workflow_revision_mismatch` |
| Target digest changed | `target_digest_mismatch` |
| A source record digest changed | `source_record_digest_mismatch` |
| Target no longer exists | `target_removed` |
| Request expired (10 minutes) | `expired_snapshot` |
| Action no longer offered | `action_unavailable` |

The guards are layered outermost-first, so in practice any drift is caught by the
project snapshot check. The narrower guards are defence in depth and are covered
individually by tests.

## Persistence

Project-scoped, atomic, bounded and JSON-safe under `review_ui/`:

- `index.json` — active summary
- `registries/` — immutable, content-addressed registry snapshots
- `sessions/` — UI state only
- `snapshots/` — digest bindings
- `actions/` — immutable action requests
- `receipts/` — immutable action receipts
- `event_cursors/` — bounded replay cursors

Only UI-owned metadata, references, IDs and digests are stored. Source decisions,
reports, artifacts, media, validation evidence, workflow history, quality history,
Final Decision Bus decisions and complete logs are never duplicated.

`reset` removes only Review UI metadata and reports every preserved history
explicitly.

## API

All routes are project-scoped under `/api/v1/boba/projects/{project_id}/review-ui`:

| Method | Path |
| --- | --- |
| GET | `` |
| GET | `/registry`, `/views`, `/actions` |
| POST | `/sessions` |
| GET, PATCH, DELETE | `/sessions/{session_id}` |
| GET | `/queue` |
| GET | `/targets/{target_id}` |
| POST | `/targets/{target_id}/snapshot` |
| POST | `/snapshots/{snapshot_id}/refresh` |
| POST | `/actions` |
| POST | `/actions/{action_request_id}/validate` |
| POST | `/actions/{action_request_id}/submit` |
| GET | `/actions/{action_request_id}` |
| GET | `/timeline`, `/events`, `/events/stream` |
| POST | `/notifications/{notification_id}/acknowledge` |
| GET | `/export` |

Rejected: stale and expired snapshots, workflow-revision mismatch, target-digest
mismatch, unknown or unavailable actions, arbitrary modules, operations, URLs and
paths, external media, upload, publication, raw commands and secret-bearing input.

## Frontend workspace

Mounted in the existing project route via `ResultsSection`. No second router.

| Component | Responsibility |
| --- | --- |
| `BobaReviewWorkspace` | Orchestration, header, workflow rail, mobile tabs, error boundary |
| `BobaReviewQueue` | Deterministic queue as a keyboard-navigable listbox |
| `BobaReviewStatusMatrix` | Ten source-owned status rows plus source cards |
| `BobaReviewEvidenceDrawer` | Evidence drawer, timeline, event stream |
| `BobaReviewActionDialog` | Action bar and modal confirmation with focus trap |
| `BobaReviewPreview` | Protected same-origin preview |
| `frontend/src/lib/reviewUi.ts` | All pure logic, unit tested |

### Status matrix

Ten rows — Rights, Safety, Target approval, Human decision, Workflow, Artifacts,
Technical validation, Output quality, Recovery, Final Decision Bus — each showing
source module, original status, original decision, current/stale state, blocking
state, human action, details, warnings and limitations.

Status is conveyed by icon **and** text label (`[ok]`, `[stale]`, `[expired]`,
`[superseded]`, `[n/a]`), never by colour alone.

### Protected preview

Playback uses only the existing same-origin project-scoped media routes via
`protectedPreviewUrl`. Absolute paths, UNC paths, `file:` URIs, traversal and any
external URL are refused. Local absolute paths are never exposed. The preview is
read-only, and the UI states explicitly that successful playback is **not**
technical validation.

### Truthful events

Canonical events only, de-duplicated by `(source module, source event id)`,
bounded to 200 retained events, ordered by source timestamp and sequence.

- Progress is shown only when the owner supplied real counters; malformed or
  absent counters yield no progress.
- `review_stream_open`, `review_stream_idle`, `review_stream_complete`,
  heartbeats and keep-alives carry `represents_work: false` and are never shown
  as activity.
- Disconnection is stated plainly, with bounded exponential reconnect backoff
  (1 s doubling to a 30 s ceiling).

### Responsive and accessible

Desktop: queue, workflow rail, main panel, evidence drawer, event drawer.
Mobile: Queue / Review / Evidence / Events tabs with a sticky safe action bar.

Semantic landmarks and headings, keyboard-navigable queue (arrows, Home, End,
Enter, Space) and tabs (arrow keys), labelled modal dialog with focus trap and
focus return, Escape to close, visible focus rings, 44 px touch targets,
non-colour-only statuses, labelled loading and error states, and polite live
regions for canonical updates.

### Safe error handling

`classifyReviewError` maps every failure onto one of eleven kinds — API
unavailable, target removed, stale snapshot, permission denied, Safety block,
action unavailable, unsupported schema, stream disconnected, preview unavailable,
malformed response, unexpected — each with human guidance. Server stack traces,
secrets, tokens, absolute paths and complete logs are never surfaced.

## Validation

```
python -m ruff check src tests tools
python -m mypy src/olympus/boba tools/validate_boba_review_ui.py
python -m pytest tests/unit/test_boba_review_ui.py
python tools/validate_boba_review_ui.py --self-check
python tools/validate_boba_review_ui.py --synthetic-project
```

```
cd frontend
npm run typecheck && npm run lint && npm test && npm run build
```

The validator covers 42 named conditions using only synthetic metadata in the
ignored workspace. It never executes a target, command, Git, FFmpeg, validator,
repair, workflow transition, media work, network access, upload or publication,
and never mutates a source-owner decision.

## Known limitations

- Output Quality and Safety human-review actions are declared but unavailable in
  V1: binding them needs an exact review-case / evaluation-case selector that the
  current projection does not resolve.
- Clip-level and rendered-output targets are projected from module-level records,
  so per-clip previews fall back to the project source.
- The event stream is a bounded polling SSE endpoint (no existing SSE mechanism
  was available to reuse); it emits a finite number of frames and expects the
  client to reconnect.
- Frontend tests are vitest logic and source-contract tests, matching the
  repository's existing convention; there is no DOM testing library in the
  project.
