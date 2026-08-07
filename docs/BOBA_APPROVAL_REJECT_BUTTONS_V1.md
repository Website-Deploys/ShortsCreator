# BOBA Approval / Reject Buttons V1

## 1. Architecture

An **interaction layer** over the existing canonical Review UI action chain. It
adds Approve and Reject controls to the Review UI, derives eligibility from the
canonical owner registry, binds each decision to an exact snapshot, revalidates
before submitting, and reports only what the owner's receipt actually said.

It creates no approval authority, no second decision path, no second database
and no second idempotency mechanism.

## 2. Ownership

```
Frontend control
      ↓
Approval eligibility (this layer, read-only)
      ↓
Review UI action chain      → owns request identity, digests, expiry,
                              staleness validation, idempotency, receipt
      ↓
Workflow Controller         → owns the human decision record and the revision
      ↓
Safety Gate                 → owns safety authorisation (separately)
Final Decision Bus          → owns final action authorisation (separately)
Autopilot / owners          → own execution (separately)
```

The UI is never the authority. Approval is not execution.

## 3. Audit finding that shaped the scope

The canonical Review UI action registry declares **four** actions. Only **three**
carry approve/reject-style decision values, and only **one** is available in V1:

| Action | Owner operation | Decisions | `allowed_in_v1` |
|---|---|---|---|
| `review_action_workflow_human_decision_v1` | `workflow_controller.record_human_workflow_decision` | `approve`, `reject`, `request_revision` | **true** |
| `review_action_safety_human_review_v1` | `safety_gate.record_human_safety_review` | `approve_exact_medium_risk_action`, `deny_action`, … | false |
| `review_action_output_quality_human_review_v1` | `output_quality_reviewer.record_boba_output_human_review` | `accept_…`, `reject_output`, … | false |

The Safety Gate and Output Quality actions have complete approve/reject
vocabularies but their owners set `allowed_in_v1=False`. **This layer does not
re-enable an action its owner disabled** — doing so would be a Safety bypass. It
reports them as unavailable with the exact reason instead.

Candidate Review and Clip Brief expose decision values `approved`/`rejected` but
are `authoritative=False` advisory Creator Learning feedback, so they are not
presented as approval decisions. Repair Plan Review and Error Doctor Review each
expose one acknowledgement action and no approve/reject.

## 4. Approval flow

1. The control reads eligibility from the canonical registry.
2. A snapshot binds project, run, revision, target, target digest, Safety digest
   and Final Decision digest.
3. The dialog shows action, owner, operation, target, workflow status, Safety,
   Rights, validation, quality, checkpoint, budget, expiry and target digest.
4. Explicit confirmation plus a bounded reason is required.
5. The snapshot is revalidated against every bound identity.
6. The request is created through the Review UI action chain.
7. The Review UI submits to the Workflow Controller.
8. An immutable receipt is persisted and a truthful event emitted.

## 5. Rejection flow

Rejection is a first-class recorded decision, not a deletion, cancellation,
failure or dismissal. It carries a bounded reason, persists immutably, emits
`rejection_accepted`, and changes no artifact or workflow. A rejection receipt
carries no error code.

A reviewer may still reject an action that Safety has blocked; only approval is
blocked in that case.

## 6. Safety Gate interaction

Safety Gate remains authoritative. When its own latest decision denies action,
every approve row becomes `blocked` with reason `safety_gate_blocked` and cannot
be submitted. The receipt pins `safety_decision_granted_here: Literal[False]`.
When Rights are unknown or blocked, approval is blocked with
`rights_unknown_or_blocked`.

## 7. Stale-state handling

`revalidate_approval_snapshot` re-reads and refuses on: project snapshot digest,
workflow revision, target digest, Safety record digest, Final Decision record
digest, Safety state, Rights state, validation state, quality state, checkpoint
state, budget state, expiry, and already-decided. A stale result blocks request
creation **before** anything reaches an owner, emits `approval_stale`, and the
frontend refetches instead of mutating.

## 8. Persistence

Under `approval_controls/`: `index.json`, `registries/`, `snapshots/`,
`receipts/`, `events/log.json`. Registries and receipts are immutable. The event
log is append-only. Decisions themselves live in the owner's store — this layer
persists no second decision model.

## 9. Events

Append-only and 1-based, so a cursor of `0` still returns the first event.
Types: `approval_requested`, `approval_confirmed`, `approval_rejected`,
`approval_denied`, `approval_expired`, `approval_stale`, `approval_conflict`,
`rejection_submitted`, `rejection_accepted`, `request_already_decided`. Every
event pins `claims_execution` and `claims_workflow_advance` to `False`.

## 10. Receipts

The receipt keeps four facts apart that are easy to conflate:

1. **User decision** — recorded only when the owner accepted it
2. **Owner decision** — requires a canonical record id *and* digest
3. **Safety decision** — separately owned; never granted here
4. **Execution** — a separate fact requiring a named owning module

An approval receipt is not an execution receipt. A rejection receipt is not an
error receipt.

## 11. API

Eleven project-scoped routes under `/boba/projects/{project_id}/approval-controls`:
root, `registry`, `eligibility`, `snapshots`, `snapshots/{id}/revalidate`,
`decisions`, `decisions/{id}/submit`, `decisions/{id}`, `history`, `events`,
`export`, plus `DELETE` for the metadata reset.

Twelve integration-layer operations are registered; Safety Gate classifies all
twelve, with `submit_decision` as `approval_required_read_only` and the rest
`automatic_read_only`.

## 12. Frontend

`frontend/src/lib/approvalControls.ts` holds pure logic;
`BobaApprovalRejectControls.tsx` renders the controls, dialog and receipt panel
with its own error boundary. Mounted at all four results render sites as
`approvalRejectControls`.

## 13. Accessibility

Semantic `<button>` elements, `aria-disabled`, `aria-label` naming the owning
module, `role="dialog"` with `aria-modal` and `aria-labelledby`,
`aria-invalid` on the reason field, `role="status"` for loading, `role="alert"`
for errors, visible `focus-visible` outlines, and a text label plus a non-colour
token for every state so status is never colour-only.

## 14. Security

A bounded reason is validated **on the raw input before sanitisation**, because
`_safe_text` rewrites `https://` into `http[private-path]/` and strips `/home/`,
which would otherwise let both through. Refused: credentials, command text,
shell metacharacters, URLs, private paths, UNC paths, traversal. Also refused:
cross-project snapshots, forged snapshot ids, unknown decision kinds, and any
decision the owner registry does not offer.

## 15. Testing

- Validator: **110 scenarios across 22 groups**, plus **35 self-checks**
- Backend: **268 tests**
- Frontend: **175 tests** (98 logic, 77 source contract)

## 16. Limitations

- Only the Workflow Controller human decision is genuinely approvable in V1.
  Safety Gate and Output Quality human review remain owner-disabled and are shown
  as unavailable with their reasons.
- Candidate and Clip Brief feedback is advisory and is deliberately not presented
  as approval.
- `request_revision` is a real owner decision value but is out of scope for V1's
  two-button surface; it is not offered rather than being mislabelled.
- Approval does **not** execute anything, advance a workflow, restore a
  checkpoint, grant Safety or Rights, upload or publish.
- This has not been exercised against production data and is not a
  production-readiness claim.
