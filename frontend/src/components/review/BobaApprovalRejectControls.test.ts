import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

const read = (r: string) => readFileSync(new URL(r, import.meta.url), "utf8");
const comp = read("./BobaApprovalRejectControls.tsx");
const lib = readFileSync(new URL("../../lib/approvalControls.ts", import.meta.url), "utf8");
const results = read("../project/ResultsSection.tsx");
const apiClient = readFileSync(new URL("../../lib/apiClient.ts", import.meta.url), "utf8");
const queries = readFileSync(new URL("../../lib/queries.ts", import.meta.url), "utf8");
const flat = (v: string) => v.replace(/^[ \t]*\*[ \t]?/gm, " ").replace(/\s+/g, " ");

describe("mounted natively in the existing Review UI", () => {
  it("is imported by the project results route", () => {
    expect(results).toContain('from "@/components/review/BobaApprovalRejectControls"');
  });
  it("is mounted at every render site", () => {
    expect(results.split("{approvalRejectControls}").length - 1).toBe(4);
  });
  it("does not replace the Review UI workspace", () => {
    expect(results).toContain("{reviewWorkspace}");
  });
  it("does not replace the Repair Plan panel", () => {
    expect(results).toContain("{repairPlanReviewPanel}");
  });
  it("does not replace the Error Doctor panel", () => {
    expect(results).toContain("{errorDoctorReviewPanel}");
  });
  it("is wrapped in its own error boundary", () => {
    expect(comp).toContain("export class BobaApprovalControlsErrorBoundary");
    expect(results).toContain("<BobaApprovalControlsErrorBoundary>");
  });
});

describe("declares what it never does", () => {
  it.each([
    "decision input, not an execution engine",
    "never approve anything themselves",
    "grant Safety Gate approval",
    "bypass budgets",
    "bypass validation",
    "advance a workflow",
    "restore a checkpoint",
    "run\n * a command",
    "upload or publish",
    "No approval is ever shown optimistically",
  ])("states %s", (phrase) => {
    expect(flat(comp)).toContain(flat(phrase));
  });
});

describe("contains no execution capability", () => {
  it.each(["child_process", "eval(", "new Function(", "innerHTML", "window.open(", "http://"])(
    "never uses %s",
    (token) => {
      expect(comp).not.toContain(token);
    },
  );
  it("never calls fetch directly", () => {
    // refetch() legitimately contains "fetch(", so assert on the global call.
    expect(comp).not.toMatch(/(?<![A-Za-z.])fetch\(/);
    expect(comp).not.toContain("window.fetch");
    expect(comp).not.toContain("XMLHttpRequest");
  });
  it("routes only through the typed hooks", () => {
    expect(comp).toContain('from "@/lib/queries"');
    expect(comp).not.toContain('from "@/lib/apiClient"');
  });
});

describe("renders both controls with truthful state", () => {
  it("renders approve and reject", () => {
    expect(comp).toContain('(["approve", "reject"] as const)');
  });
  it("uses semantic buttons", () => {
    expect(comp).toContain('type="button"');
  });
  it("disables an unavailable control", () => {
    expect(comp).toContain("disabled={!actionable || inFlight}");
    expect(comp).toContain("aria-disabled={!actionable || inFlight}");
  });
  it("shows a non-colour token alongside every label", () => {
    expect(comp).toContain('<span aria-hidden="true">{token}</span>');
  });
  it("exposes a visible focus state", () => {
    expect(comp).toContain("focus-visible:outline");
  });
  it("labels each button with its owning module", () => {
    expect(comp).toContain("aria-label={`${label} — ${row.owning_module_id}`}");
  });
  it("announces loading with a live role", () => {
    expect(comp).toContain('role="status"');
  });
  it("announces errors with an alert role", () => {
    expect(comp).toContain('role="alert"');
  });
  it("renders a modal confirmation dialog", () => {
    expect(comp).toContain('role="dialog"');
    expect(comp).toContain('aria-modal="true"');
    expect(comp).toContain("aria-labelledby={titleId}");
  });
  it("marks an invalid reason for assistive tech", () => {
    expect(comp).toContain("aria-invalid={Boolean(reasonError)}");
  });
});

describe("confirmation is explicit", () => {
  it("requires a read-and-understood checkbox", () => {
    expect(comp).toContain("I have read what this decision does and does not do.");
  });
  it("shows every bound fact", () => {
    expect(comp).toContain("confirmationFacts(row, snapshot)");
  });
  it("uses the owner-specific title", () => {
    expect(comp).toContain("confirmationTitle(row.decision_kind)");
  });
  it("gates submission behind canSubmit", () => {
    expect(comp).toContain("canSubmit(row, snapshot, reason, confirmed, submitting)");
  });
  it("submits to the canonical owner by name", () => {
    expect(comp).toContain("Submitting to canonical owner");
  });
});

describe("stale state forces a refresh instead of mutating", () => {
  it("revalidates before creating the decision", () => {
    expect(comp).toContain("revalidate.mutateAsync");
    expect(comp).toContain("revalidationNotice(check)");
  });
  it("refetches eligibility when stale", () => {
    expect(comp).toContain("await eligibility.refetch()");
  });
  it("stops when the request was not created", () => {
    expect(comp).toContain("if (created.created !== true)");
  });
});

describe("duplicate submission is prevented", () => {
  it("tracks an in-flight request", () => {
    expect(comp).toContain("const [inFlight, setInFlight]");
    expect(comp).toContain("if (!activeRow || !snapshot || inFlight) return;");
  });
  it("always clears the in-flight flag", () => {
    expect(comp).toContain("} finally {");
    expect(comp).toContain("setInFlight(false);");
  });
  it("derives a stable idempotency key from the snapshot", () => {
    expect(comp).toContain("idempotency_key: `approval_${snapshot.approval_control_snapshot_id}");
  });
});

describe("receipt reporting is truthful", () => {
  it("renders the receipt only after the owner replied", () => {
    expect(comp).toContain("{receipt ? <BobaApprovalReceiptPanel receipt={receipt} /> : null}");
  });
  it("reports that nothing was executed when true", () => {
    expect(comp).toContain(
      "Nothing was executed, advanced, restored, changed, uploaded or published.",
    );
  });
  it("uses the owner-derived state, never an optimistic one", () => {
    expect(comp).toContain("receiptButtonState(receipt)");
    expect(comp).not.toContain('setReceipt({ owner_accepted: true');
  });
});

describe("api client exposes only the fixed routes", () => {
  it.each([
    "getBobaApprovalControls", "getBobaApprovalControlRegistry", "getBobaApprovalEligibility",
    "createBobaApprovalControlSnapshot", "revalidateBobaApprovalControlSnapshot",
    "createBobaApprovalDecision", "submitBobaApprovalDecision",
    "getBobaApprovalDecisionStatus", "getBobaApprovalDecisionHistory",
    "getBobaApprovalControlEvents", "exportBobaApprovalControls",
  ])("declares %s", (m) => {
    expect(apiClient).toContain(`${m}: (`);
  });
  it("declares no execution route for approval controls", () => {
    // Pre-existing unrelated workflow methods are out of scope; assert that no
    // approval-controls route is execution capable.
    const lines = apiClient
      .split("\n")
      .filter((line) => line.includes("approval-controls"));
    expect(lines.length).toBeGreaterThanOrEqual(11);
    for (const token of ["execute", "advance", "publish", "upload", "render"]) {
      expect(lines.some((line) => line.includes(token))).toBe(false);
    }
  });
  it("states the client performs no execution", () => {
    expect(flat(apiClient)).toContain("No method here approves anything itself");
  });
});

describe("react query invalidates canonical state after a decision", () => {
  it.each([
    "useBobaApprovalEligibility", "useBobaApprovalControlRegistry",
    "useBobaApprovalDecisionHistory", "useCreateBobaApprovalControlSnapshot",
    "useRevalidateBobaApprovalControlSnapshot", "useCreateBobaApprovalDecision",
    "useSubmitBobaApprovalDecision", "useExportBobaApprovalControls",
  ])("declares %s", (h) => {
    expect(queries).toContain(`export function ${h}(`);
  });
  it("invalidates the approval queries", () => {
    expect(queries).toContain('"approval-controls"');
  });
  it("invalidates the workflow queries", () => {
    expect(queries).toContain('"workflow"');
  });
  it("states the owner receipt is the only source of truth", () => {
    expect(flat(queries)).toContain("the owner's receipt is the only source");
  });
  it("declares no approve mutation that bypasses the owner", () => {
    expect(queries).not.toContain("useForceApprove");
  });
});

describe("the lib declares its boundaries", () => {
  it("states it is never an authority", () => {
    expect(flat(lib)).toContain("interaction layer, never an authority");
  });
  it("states approval is never optimistic", () => {
    expect(flat(lib)).toContain("never shown optimistically");
  });
  it("pins the no-grant fields to false", () => {
    expect(lib).toContain("grants_execution: false");
    expect(lib).toContain("grants_safety_approval: false");
    expect(lib).toContain("grants_rights_approval: false");
    expect(lib).toContain("advances_workflow: false");
  });
  it("pins the receipt side-effect fields to false", () => {
    expect(lib).toContain("safety_decision_granted_here: false");
    expect(lib).toContain("checkpoint_restored: false");
    expect(lib).toContain("upload_performed: false");
    expect(lib).toContain("publication_performed: false");
  });
});
