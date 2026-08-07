import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

function source(relative: string) {
  return readFileSync(new URL(relative, import.meta.url), "utf8");
}

const panel = source("./BobaRepairPlanReviewPanel.tsx");
const results = source("../project/ResultsSection.tsx");
const clientLogic = readFileSync(
  new URL("../../lib/repairPlanReview.ts", import.meta.url),
  "utf8",
);
const apiClient = readFileSync(new URL("../../lib/apiClient.ts", import.meta.url), "utf8");
const queries = readFileSync(new URL("../../lib/queries.ts", import.meta.url), "utf8");

/** Collapse whitespace and JSDoc markers so prose assertions survive wrapping. */
const flat = (value: string) =>
  value.replace(/^[ \t]*\*[ \t]?/gm, " ").replace(/\s+/g, " ");
const flatPanel = flat(panel);
const flatLogic = flat(clientLogic);

describe("integration with the existing review surfaces", () => {
  it("is mounted from the existing project results route", () => {
    expect(results).toContain("BobaRepairPlanReviewPanel");
    expect(results).toContain('from "@/components/review/BobaRepairPlanReviewPanel"');
  });

  it("is mounted at every results render site", () => {
    expect(results.split("{repairPlanReviewPanel}").length - 1).toBe(4);
  });

  it("uses a mount variable that does not collide with existing locals", () => {
    expect(results).toContain("const repairPlanReviewPanel = (");
    expect(results).toContain("const errorDoctorPanel =");
    expect(results).toContain("const clipBriefPanel = (");
  });

  it("does not replace the global Review UI workspace", () => {
    expect(results).toContain("{reviewWorkspace}");
  });

  it("does not replace the Error Doctor Panel", () => {
    expect(results).toContain("{errorDoctorReviewPanel}");
  });

  it("does not replace the Clip Brief Panel", () => {
    expect(results).toContain("{clipBriefReviewPanel}");
  });

  it("renders after the Error Doctor Panel at each site", () => {
    const pattern = /\{errorDoctorReviewPanel\}\s*\n\s*\{repairPlanReviewPanel\}/g;
    expect(panel.length).toBeGreaterThan(0);
    expect((results.match(pattern) ?? []).length).toBe(4);
  });

  it("wraps the panel in its own error boundary", () => {
    expect(results).toContain("<BobaRepairPlanReviewErrorBoundary>");
    expect(panel).toContain("export class BobaRepairPlanReviewErrorBoundary");
  });
});

describe("the panel declares what it never does", () => {
  it("states it never generates a repair plan", () => {
    expect(flatPanel).toContain("never generates a repair plan");
  });

  it("states it never revises, approves or rejects a plan", () => {
    expect(flatPanel).toContain("revises one, approves or rejects one");
  });

  it("states it never executes a plan or a step", () => {
    expect(flatPanel).toContain("executes a plan or a step");
  });

  it("states it never runs a command, shell, Git or FFmpeg", () => {
    expect(flatPanel).toContain("runs a command, shell, PowerShell, Git or FFmpeg");
  });

  it("states it never restarts a process or restores a checkpoint", () => {
    expect(flatPanel).toContain("restarts a process, restores a checkpoint");
  });

  it("states it never transitions a workflow", () => {
    expect(flatPanel).toContain("transitions a workflow");
  });

  it("states it never modifies code, artifacts or media", () => {
    expect(flatPanel).toContain("modifies code, artifacts or media");
  });

  it("states it never uploads or publishes", () => {
    expect(flatPanel).toContain("uploads or\n * publishes".replace(/\n \* /, " "));
  });

  it("states no step is a clickable command control", () => {
    expect(flatPanel).toContain("No step is ever a clickable command control");
  });

  it("attributes every plan to Repair Planner", () => {
    expect(flatPanel).toContain("Repair Planner proposed every plan shown here");
  });
});

describe("the panel contains no execution capability", () => {
  it("spawns no child process", () => {
    expect(panel).not.toContain("child_process");
    expect(clientLogic).not.toContain("child_process");
  });

  it("never evaluates a string", () => {
    expect(panel).not.toContain("eval(");
    expect(clientLogic).not.toContain("eval(");
  });

  it("never uses a Function constructor", () => {
    expect(panel).not.toContain("new Function(");
  });

  it("never sets innerHTML", () => {
    expect(panel).not.toContain("innerHTML");
    expect(panel).not.toContain("dangerouslySetInnerHTML");
  });

  it("never opens an arbitrary URL", () => {
    expect(panel).not.toContain("window.open(");
    expect(panel).not.toContain("http://");
  });

  it("never calls fetch directly", () => {
    expect(panel).not.toContain("fetch(");
  });

  it("routes every request through the typed api client hooks", () => {
    expect(panel).toContain('from "@/lib/queries"');
    expect(panel).not.toContain('from "@/lib/apiClient"');
  });
});

describe("the panel renders the required notices", () => {
  it.each([
    "COMMAND_WITHHELD_NOTICE",
    "PRIVATE_PATH_NOTICE",
    "NOT_EXECUTABLE_NOTICE",
    "SOURCE_RETAINED_NOTICE",
    "PROPOSED_PLAN_NOTICE",
    "REVERSIBLE_NOTICE",
    "ROLLBACK_NOTICE",
    "VERIFICATION_NOTICE",
    "RECOVERED_NOTICE",
    "NO_EXECUTION_NOTICE",
    "ANNOTATION_NOTICE",
    "CONFIRMATION_STATEMENT",
  ])("imports and renders %s", (name) => {
    expect(panel).toContain(name);
  });

  it("renders the confirmation statement in the action dialog", () => {
    expect(panel).toContain("{CONFIRMATION_STATEMENT}");
  });

  it("renders the withheld actions list", () => {
    expect(panel).toContain("Actions withheld in V1");
    expect(panel).toContain("unavailableActionNotice");
  });

  it("renders the annotation notice next to the annotation field", () => {
    expect(panel).toContain("{ANNOTATION_NOTICE}");
  });

  it("renders a footer of standing limitations", () => {
    expect(panel).toContain("{REVERSIBLE_NOTICE}");
    expect(panel).toContain("{ROLLBACK_NOTICE}");
    expect(panel).toContain("{VERIFICATION_NOTICE}");
    expect(panel).toContain("{RECOVERED_NOTICE}");
  });
});

describe("the panel never renders withheld source material", () => {
  it("never renders a step target field", () => {
    // event.target is a DOM handler, so assert on the owner field precisely.
    expect(panel).not.toContain("step.target");
    expect(panel).not.toContain("_projection.target");
    expect(clientLogic).not.toMatch(/^\s+target:/m);
  });

  it("never renders rollback step text", () => {
    expect(panel).not.toContain("rollback_steps");
  });

  it("never renders a raw command field", () => {
    expect(panel).not.toContain("raw_command");
    expect(panel).not.toContain("command_text");
  });

  it("only reports command presence, never content", () => {
    expect(clientLogic).toContain("raw_command_present_in_source");
    expect(panel).toContain("command_bearing_step_count");
    expect(panel).toContain("hold command text in the source");
  });

  it("never renders a private path field", () => {
    expect(panel).not.toContain("private_path_value");
    expect(panel).not.toContain("absolute_path");
  });
});

describe("the panel exposes the eight review sections", () => {
  it.each([
    "plans",
    "steps",
    "risk",
    "approvals",
    "verification",
    "evidence",
    "recovery",
    "conflicts",
  ])("declares the %s tab", (tab) => {
    expect(panel).toContain(`id: "${tab}"`);
  });

  it("labels the steps tab as proposed", () => {
    expect(panel).toContain('label: "Proposed Steps"');
  });

  it("renders a component per section", () => {
    for (const name of [
      "BobaRepairStepList",
      "BobaRepairRiskList",
      "BobaRepairApprovalList",
      "BobaRepairVerificationList",
      "BobaRepairEvidenceList",
      "BobaRepairRecoveryList",
      "BobaRepairConflictList",
    ]) {
      expect(panel).toContain(`export function ${name}`);
    }
  });
});

describe("the panel exposes every filter and sort the backend supports", () => {
  it.each([
    "all_current",
    "human_review_required",
    "destructive",
    "reversible",
    "code_change",
    "artifact_change",
    "workflow_change",
    "tool_execution",
    "process_restart",
    "checkpoint_restore",
    "missing_approval",
    "missing_verification",
    "failed_recovery",
    "conflicts",
    "stale",
    "completed",
    "historical",
    "superseded",
  ])("offers the %s filter", (filter) => {
    expect(panel).toContain(`id: "${filter}"`);
  });

  it.each([
    "review_priority",
    "source_severity",
    "creation_order",
    "affected_module",
    "step_count",
    "repair_plan_id",
  ])("offers the %s sort", (sort) => {
    expect(panel).toContain(`id: "${sort}"`);
  });

  it("labels the source risk sort as owner owned", () => {
    expect(panel).toContain("Source risk (owner owned)");
  });
});

describe("the api client exposes the fixed repair plan routes", () => {
  it.each([
    "getBobaRepairPlanReview",
    "getBobaRepairPlanReviewRegistry",
    "createBobaRepairPlanReviewSession",
    "getBobaRepairPlanReviewSession",
    "updateBobaRepairPlanReviewSession",
    "deleteBobaRepairPlanReviewSession",
    "getBobaRepairPlanQueue",
    "getBobaRepairPlan",
    "createBobaRepairPlanSnapshot",
    "refreshBobaRepairPlanSnapshot",
    "getBobaRepairPlanSteps",
    "getBobaRepairPlanRisk",
    "getBobaRepairPlanApprovals",
    "getBobaRepairPlanVerification",
    "getBobaRepairPlanEvidence",
    "getBobaRepairPlanRecoveryHistory",
    "getBobaRepairPlanConflicts",
    "compareBobaRepairPlans",
    "describeBobaRepairPlanActionConfirmation",
    "createBobaRepairPlanAction",
    "validateBobaRepairPlanAction",
    "submitBobaRepairPlanAction",
    "getBobaRepairPlanActionReceipt",
    "getBobaRepairPlanTimeline",
    "getBobaRepairPlanEvents",
    "exportBobaRepairPlanReview",
  ])("declares %s", (method) => {
    expect(apiClient).toContain(`${method}: (`);
  });

  it("targets only the fixed repair-plan-review path", () => {
    const matches = apiClient.match(/repair-plan-review/g) ?? [];
    expect(matches.length).toBeGreaterThanOrEqual(26);
  });

  it("declares no approve, reject, revise or execute route", () => {
    expect(apiClient).not.toContain("approveBobaRepairPlan");
    expect(apiClient).not.toContain("rejectBobaRepairPlan");
    expect(apiClient).not.toContain("reviseBobaRepairPlan");
    expect(apiClient).not.toContain("executeBobaRepairPlan");
  });

  it("states the client performs no execution", () => {
    expect(flat(apiClient)).toContain(
      "No method here approves, rejects, revises or executes a repair plan",
    );
  });

  it("pins the withheld flags in the steps response type", () => {
    expect(apiClient).toContain("raw_command_exposed: false");
    expect(apiClient).toContain("private_path_exposed: false");
    expect(apiClient).toContain("executable_by_panel: false");
  });
});

describe("react query hooks are read-only apart from the acknowledgement", () => {
  it.each([
    "useBobaRepairPlanReview",
    "useBobaRepairPlanRegistry",
    "useBobaRepairPlanQueue",
    "useBobaRepairPlan",
    "useBobaRepairPlanSteps",
    "useBobaRepairPlanRisk",
    "useBobaRepairPlanApprovals",
    "useBobaRepairPlanVerification",
    "useBobaRepairPlanEvidence",
    "useBobaRepairPlanRecoveryHistory",
    "useBobaRepairPlanConflicts",
    "useBobaRepairPlanTimeline",
    "useCreateBobaRepairPlanReviewSession",
    "useUpdateBobaRepairPlanReviewSession",
    "useCreateBobaRepairPlanSnapshot",
    "useRefreshBobaRepairPlanSnapshot",
    "useCompareBobaRepairPlans",
    "useCreateBobaRepairPlanAction",
    "useValidateBobaRepairPlanAction",
    "useSubmitBobaRepairPlanAction",
    "useExportBobaRepairPlanReview",
  ])("declares %s", (hook) => {
    expect(queries).toContain(`export function ${hook}(`);
  });

  it("declares a query key per read surface", () => {
    for (const key of [
      "bobaRepairPlanReview",
      "bobaRepairPlanRegistry",
      "bobaRepairPlanQueue",
      "bobaRepairPlanDetail",
      "bobaRepairPlanSteps",
      "bobaRepairPlanRisk",
      "bobaRepairPlanApprovals",
      "bobaRepairPlanVerification",
      "bobaRepairPlanEvidence",
      "bobaRepairPlanRecovery",
      "bobaRepairPlanConflicts",
      "bobaRepairPlanTimeline",
    ]) {
      expect(queries).toContain(`${key}: (`);
    }
  });

  it("re-reads canonical state after a submission instead of assuming it", () => {
    expect(flat(queries)).toContain(
      "Plan state is only ever re-read from the owning module, never assumed",
    );
  });

  it("invalidates the repair plan queries after a submission", () => {
    expect(queries).toContain('"repair-plan-review"');
  });

  it("invalidates the error doctor queries after a submission", () => {
    expect(queries).toContain('"error-doctor-review"');
  });

  it("declares no approve, reject or execute mutation", () => {
    expect(queries).not.toContain("useApproveBobaRepairPlan");
    expect(queries).not.toContain("useRejectBobaRepairPlan");
    expect(queries).not.toContain("useExecuteBobaRepairPlan");
    expect(queries).not.toContain("useRestoreBobaCheckpoint");
  });
});

describe("the client logic module declares its boundaries", () => {
  it("states command text never reaches it", () => {
    expect(flatLogic).toContain(
      "Command text and private absolute paths never reach this module",
    );
  });

  it("states a proposed strategy is never the correct repair", () => {
    expect(flatLogic).toContain("never presented as the correct repair");
  });

  it("states a reversible plan is never risk-free", () => {
    expect(flatLogic).toContain("never presented as\n * risk-free".replace(/\n \* /, " "));
  });

  it("states owner success is never independent verification", () => {
    expect(flatLogic).toContain("never presented as independent verification");
  });

  it("states recovered is never resolved", () => {
    expect(flatLogic).toContain("recovered is never presented as resolved");
  });

  it("exports the withholding contract fields used by the panel", () => {
    // Field names mirror the backend contract exactly, so they stay snake_case.
    expect(clientLogic).toContain("executable_by_panel");
    expect(clientLogic).toContain("command_withheld");
    expect(clientLogic).toContain("stepIsExecutable");
  });

  it("pins the step exposure fields to false in its types", () => {
    expect(clientLogic).toContain("raw_command_exposed: false");
    expect(clientLogic).toContain("private_path_exposed: false");
    expect(clientLogic).toContain("executable_by_panel: false");
  });
});

describe("the action dialog is explicit before anything is submitted", () => {
  it("requires an explicit confirmation checkbox", () => {
    expect(panel).toContain("I have read what this request does and does not do.");
  });

  it("disables submission until the request is ready", () => {
    expect(panel).toContain("disabled={!ready || submitting}");
  });

  it("submits to the canonical owner by name", () => {
    expect(panel).toContain("Submit to canonical owner");
  });

  it("names the owning module and operation", () => {
    expect(panel).toContain("descriptor.owning_operation_id");
  });

  it("validates the reason before enabling submission", () => {
    expect(panel).toContain("validateActionReason");
    expect(panel).toContain("canSubmitAction");
  });

  it("refreshes the snapshot when validation fails instead of submitting", () => {
    expect(panel).toContain("if (!validation.valid)");
    expect(panel).toContain("refreshSnapshot.mutateAsync");
  });

  it("reports that the plan is unchanged after an accepted acknowledgement", () => {
    expect(panel).toContain("The repair plan is exactly as Repair Planner recorded it.");
  });
});

describe("the panel degrades honestly", () => {
  it("reports panel unavailability without claiming a plan change", () => {
    expect(panel).toContain("No repair plan changed.");
  });

  it("uses the shared review error classifier", () => {
    expect(panel).toContain("classifyReviewError");
  });

  it("reports an empty queue without inventing plans", () => {
    expect(panel).toContain("Repair Planner records plans; this panel");
  });

  it("says a comparison selects nothing", () => {
    expect(panel).toContain(
      "A comparison selects no winner, no recommended plan and no plan to execute.",
    );
  });

  it("reports when no action is available for the exact plan", () => {
    expect(panel).toContain("No action is available for this exact plan.");
  });

  it("surfaces an unsupported schema notice", () => {
    expect(panel).toContain("unsupportedSchemaNotice");
  });
});
