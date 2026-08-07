import { describe, expect, it } from "vitest";

import {
  MAX_REASON_LENGTH,
  NOT_EXECUTION_NOTICE,
  NOT_SAFETY_NOTICE,
  NOT_WORKFLOW_NOTICE,
  REJECTION_NOTICE,
  STALE_NOTICE,
  approveRow,
  buttonStateLabel,
  canSubmit,
  confirmationFacts,
  confirmationTitle,
  eligibilityNotices,
  humanise,
  ineligibilityNotice,
  isActionable,
  receiptButtonState,
  receiptClaimsNoSideEffects,
  receiptFacts,
  receiptSummary,
  rejectRow,
  revalidationNotice,
  validateReason,
  type ApprovalButtonState,
  type ApprovalControlSnapshot,
  type ApprovalDecisionReceipt,
  type ApprovalEligibility,
} from "@/lib/approvalControls";

function row(o: Partial<ApprovalEligibility> = {}): ApprovalEligibility {
  return {
    eligibility_id: "e1",
    project_id: "p1",
    target_type: "workflow_stage",
    target_id: "render",
    action_descriptor_id: "review_action_workflow_human_decision_v1",
    owning_module_id: "workflow_controller",
    owning_operation_id: "record_human_workflow_decision",
    decision_kind: "approve",
    button_state: "approve_available",
    eligible: true,
    reason_code: "eligible",
    bounded_explanation: "workflow_controller accepts approve.",
    requires_reason: true,
    requires_confirmation: true,
    requires_workflow_revision: true,
    requires_target_digest: true,
    authoritative_for_owner: true,
    grants_execution: false,
    grants_safety_approval: false,
    grants_rights_approval: false,
    advances_workflow: false,
    warnings: [],
    limitations: [],
    ...o,
  };
}

function snap(o: Partial<ApprovalControlSnapshot> = {}): ApprovalControlSnapshot {
  return {
    approval_control_snapshot_id: "snap1",
    review_session_id: "rs1",
    review_snapshot_id: "rsn1",
    project_id: "p1",
    workflow_run_id: "run_a",
    stage_instance_id: "render",
    target_type: "workflow_stage",
    target_id: "render",
    project_snapshot_digest: "a".repeat(64),
    workflow_revision: 3,
    target_digest: "b".repeat(64),
    safety_record_digest: "c".repeat(64),
    final_decision_record_digest: "d".repeat(64),
    eligible_decision_kinds: ["approve", "reject"],
    safety_status: "approved_exact_action",
    rights_status: "clear",
    validation_status: "passed",
    quality_status: "accepted",
    checkpoint_status: "ready",
    budget_status: "within_budget",
    workflow_status: "running",
    expires_at: null,
    already_decided: false,
    snapshot_digest: "e".repeat(64),
    confirmation_context_digest: "f".repeat(64),
    warnings: [],
    limitations: [],
    ...o,
  };
}

function receipt(o: Partial<ApprovalDecisionReceipt> = {}): ApprovalDecisionReceipt {
  return {
    approval_decision_receipt_id: "r1",
    review_action_request_id: "q1",
    project_id: "p1",
    target_type: "workflow_stage",
    target_id: "render",
    decision_kind: "approve",
    owning_module_id: "workflow_controller",
    owning_operation_id: "record_human_workflow_decision",
    user_decision_recorded: true,
    user_decision_value: "approve",
    bounded_reason: "Looks correct.",
    owner_accepted: true,
    canonical_record_id: "d1",
    canonical_status: "recorded",
    safety_decision_present: true,
    safety_decision_granted_here: false,
    execution_reported_by_owner: false,
    execution_owner_module_id: null,
    workflow_advanced: false,
    checkpoint_restored: false,
    code_changed: false,
    artifact_changed: false,
    media_modified: false,
    upload_performed: false,
    publication_performed: false,
    stale_state_rejected: false,
    duplicate_request_reused: false,
    already_decided: false,
    error_code: null,
    bounded_error_message: "",
    warnings: [],
    limitations: [],
    ...o,
  };
}

describe("notices are the exact required sentences", () => {
  it("states a decision is not an execution", () => {
    expect(NOT_EXECUTION_NOTICE).toBe(
      "This records a human decision only. It does not execute anything.",
    );
  });
  it("states Safety Gate stays authoritative", () => {
    expect(NOT_SAFETY_NOTICE).toContain("Safety Gate remains authoritative");
  });
  it("states the workflow is not advanced", () => {
    expect(NOT_WORKFLOW_NOTICE).toContain("owns transitions");
  });
  it("states a rejection deletes nothing", () => {
    expect(REJECTION_NOTICE).toContain("deletes nothing");
    expect(REJECTION_NOTICE).toContain("rolls nothing back");
  });
  it("states stale state must be refreshed", () => {
    expect(STALE_NOTICE).toContain("changed after this control was displayed");
  });
  it("bounds the reason to the backend limit", () => {
    expect(MAX_REASON_LENGTH).toBe(500);
  });
});

describe("button states never rely on colour alone", () => {
  const states: ApprovalButtonState[] = [
    "approve_available", "reject_available", "pending", "approved", "rejected",
    "expired", "invalidated", "blocked", "requires_review", "unavailable",
  ];
  it.each(states)("gives %s a text label and a token", (state) => {
    const { label, token } = buttonStateLabel(state);
    expect(label.length).toBeGreaterThan(0);
    expect(token.length).toBeGreaterThan(0);
  });
  it("labels approve and reject distinctly", () => {
    expect(buttonStateLabel("approve_available").label).toBe("Approve");
    expect(buttonStateLabel("reject_available").label).toBe("Reject");
  });
  it("distinguishes approved from approve", () => {
    expect(buttonStateLabel("approved").label).toBe("Approved");
  });
});

describe("actionability follows the owner", () => {
  it("treats an eligible approve row as actionable", () => {
    expect(isActionable(row())).toBe(true);
  });
  it("treats a blocked row as not actionable", () => {
    expect(isActionable(row({ eligible: false, button_state: "blocked" }))).toBe(false);
  });
  it("treats an already-decided row as not actionable", () => {
    expect(
      isActionable(row({ eligible: false, button_state: "approved", reason_code: "already_decided" })),
    ).toBe(false);
  });
  it("finds the approve row", () => {
    expect(approveRow([row(), row({ decision_kind: "reject" })])?.decision_kind).toBe("approve");
  });
  it("finds the reject row", () => {
    expect(rejectRow([row(), row({ decision_kind: "reject" })])?.decision_kind).toBe("reject");
  });
  it("returns null when a kind is absent", () => {
    expect(rejectRow([row()])).toBeNull();
  });
});

describe("ineligibility is always explained and attributed", () => {
  it("returns no notice for an eligible row", () => {
    expect(ineligibilityNotice(row())).toBeNull();
  });
  it("explains an owner-disabled action", () => {
    const notice = ineligibilityNotice(
      row({ eligible: false, reason_code: "action_not_available_in_v1",
            bounded_explanation: "the owner disabled it" }),
    );
    expect(notice).toContain("unavailable");
    expect(notice).toContain("the owner disabled it");
  });
  it("always appends the three standing notices", () => {
    const notices = eligibilityNotices(row());
    expect(notices).toContain(NOT_EXECUTION_NOTICE);
    expect(notices).toContain(NOT_SAFETY_NOTICE);
    expect(notices).toContain(NOT_WORKFLOW_NOTICE);
  });
  it("adds the rejection notice for a reject row", () => {
    expect(eligibilityNotices(row({ decision_kind: "reject" }))).toContain(REJECTION_NOTICE);
  });
});

describe("confirmation shows exactly what is being decided", () => {
  const facts = confirmationFacts(row(), snap());
  it.each([
    "Action", "Owning module", "Owning operation", "Target type", "Target",
    "Workflow run", "Workflow revision", "Workflow status", "Safety state",
    "Rights state", "Validation state", "Quality state", "Checkpoint state",
    "Budget state", "Expires", "Target digest",
  ])("includes %s", (label) => {
    expect(facts.map((f) => f.label)).toContain(label);
  });
  it("names the owning operation exactly", () => {
    expect(facts.find((f) => f.label === "Owning operation")?.value).toBe(
      "record_human_workflow_decision",
    );
  });
  it("truncates the digest rather than dumping it", () => {
    expect(facts.find((f) => f.label === "Target digest")?.value).toContain("…");
  });
  it("reports an unbound run honestly", () => {
    const f = confirmationFacts(row(), snap({ workflow_run_id: null }));
    expect(f.find((x) => x.label === "Workflow run")?.value).toBe("not bound");
  });
  it("reports a missing expiry honestly", () => {
    expect(facts.find((f) => f.label === "Expires")?.value).toBe("no expiry recorded");
  });
  it("asks before approving", () => {
    expect(confirmationTitle("approve")).toBe("Approve this action?");
  });
  it("asks before rejecting", () => {
    expect(confirmationTitle("reject")).toBe("Reject this action?");
  });
});

describe("reason validation mirrors the backend refusals", () => {
  it("requires a reason when the owner does", () => {
    expect(validateReason(row({ requires_reason: true }), "  ")).toContain("requires a reason");
  });
  it("allows an empty reason when the owner does not require one", () => {
    expect(validateReason(row({ requires_reason: false }), "")).toBeNull();
  });
  it("bounds the length", () => {
    expect(validateReason(row(), "x".repeat(MAX_REASON_LENGTH + 1))).toContain("at most");
  });
  it.each([
    ["password=hunter2", "credential"],
    ["ffmpeg -i a.mp4 b.mp4", "command"],
    ["a && rm -rf .", "command"],
    ["https://evil.example", "URL"],
    ["/home/operator/x", "private path"],
    ["../../etc/passwd", "traversal"],
  ])("refuses %s", (reason, fragment) => {
    expect(validateReason(row(), reason)).toContain(fragment);
  });
  it("accepts ordinary reviewer prose", () => {
    expect(validateReason(row(), "This looks correct to me.")).toBeNull();
  });
});

describe("submission is gated", () => {
  it("allows a confirmed, reasoned, eligible decision", () => {
    expect(canSubmit(row(), snap(), "Looks right.", true, false)).toBe(true);
  });
  it("blocks without confirmation", () => {
    expect(canSubmit(row(), snap(), "Looks right.", false, false)).toBe(false);
  });
  it("blocks while a request is in flight", () => {
    expect(canSubmit(row(), snap(), "Looks right.", true, true)).toBe(false);
  });
  it("blocks an ineligible row", () => {
    expect(canSubmit(row({ eligible: false, button_state: "blocked" }), snap(), "x", true, false)).toBe(false);
  });
  it("blocks an already-decided target", () => {
    expect(canSubmit(row(), snap({ already_decided: true }), "Looks right.", true, false)).toBe(false);
  });
  it("blocks an unsafe reason", () => {
    expect(canSubmit(row(), snap(), "ffmpeg -i a b", true, false)).toBe(false);
  });
  it("blocks with no row", () => {
    expect(canSubmit(null, snap(), "x", true, false)).toBe(false);
  });
  it("blocks with no snapshot", () => {
    expect(canSubmit(row(), null, "x", true, false)).toBe(false);
  });
});

describe("receipt state is never optimistic", () => {
  it("shows approved only after the owner accepted", () => {
    expect(receiptButtonState(receipt())).toBe("approved");
  });
  it("shows rejected for an accepted rejection", () => {
    expect(receiptButtonState(receipt({ decision_kind: "reject" }))).toBe("rejected");
  });
  it("shows blocked when the owner refused", () => {
    expect(receiptButtonState(receipt({ owner_accepted: false }))).toBe("blocked");
  });
  it("shows invalidated on a stale rejection", () => {
    expect(receiptButtonState(receipt({ stale_state_rejected: true }))).toBe("invalidated");
  });
  it("summarises an approval without claiming execution", () => {
    const s = receiptSummary(receipt());
    expect(s).toContain("recorded a human approval");
    expect(s).toContain("Nothing was executed");
  });
  it("summarises a rejection without claiming deletion", () => {
    const s = receiptSummary(receipt({ decision_kind: "reject" }));
    expect(s).toContain("recorded a human rejection");
    expect(s).toContain("Nothing was deleted");
  });
  it("summarises a stale refusal", () => {
    expect(receiptSummary(receipt({ stale_state_rejected: true }))).toBe(STALE_NOTICE);
  });
  it("summarises a duplicate submission", () => {
    expect(receiptSummary(receipt({ duplicate_request_reused: true }))).toContain(
      "already submitted",
    );
  });
  it("summarises an owner refusal", () => {
    expect(receiptSummary(receipt({ owner_accepted: false, canonical_status: "rejected_by_owner" }))).toContain(
      "did not accept",
    );
  });
});

describe("receipt keeps the four facts apart", () => {
  const facts = receiptFacts(receipt());
  it.each(["User decision", "Owner decision", "Safety decision", "Execution"])(
    "includes %s",
    (label) => {
      expect(facts.map((f) => f.label)).toContain(label);
    },
  );
  it("reports execution as not executed", () => {
    expect(facts.find((f) => f.label === "Execution")?.value).toBe("not executed");
  });
  it("reports Safety as separately owned", () => {
    expect(facts.find((f) => f.label === "Safety decision")?.value).toContain(
      "separately owned",
    );
  });
  it("reports no side effects for a plain approval", () => {
    expect(receiptClaimsNoSideEffects(receipt())).toBe(true);
  });
  it.each([
    "execution_reported_by_owner", "workflow_advanced", "checkpoint_restored",
    "code_changed", "artifact_changed", "media_modified", "upload_performed",
    "publication_performed", "safety_decision_granted_here",
  ])("detects a claimed %s", (field) => {
    expect(receiptClaimsNoSideEffects(receipt({ [field]: true } as never))).toBe(false);
  });
});

describe("revalidation notices force a refresh", () => {
  it("returns nothing when valid", () => {
    expect(revalidationNotice({ valid: true, code: "current", message: "ok", stale: false })).toBeNull();
  });
  it("appends the stale notice on drift", () => {
    const n = revalidationNotice({
      valid: false, code: "target_digest_mismatch", message: "The target changed.", stale: true,
    });
    expect(n).toContain("The target changed.");
    expect(n).toContain(STALE_NOTICE);
  });
  it("reports an already-decided request without the stale notice", () => {
    const n = revalidationNotice({
      valid: false, code: "already_decided", message: "Already decided.", stale: false,
    });
    expect(n).toBe("Already decided.");
  });
});

describe("humanise never invents a value", () => {
  it("titles snake case", () => {
    expect(humanise("workflow_controller")).toBe("Workflow Controller");
  });
  it("reports empty as Unknown", () => {
    expect(humanise("")).toBe("Unknown");
  });
});
