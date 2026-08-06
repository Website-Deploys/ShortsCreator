import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

function source(relative: string) {
  return readFileSync(new URL(relative, import.meta.url), "utf8");
}

const panel = source("./BobaErrorDoctorReviewPanel.tsx");
const results = source("../project/ResultsSection.tsx");
const clientLogic = readFileSync(
  new URL("../../lib/errorDoctorReview.ts", import.meta.url),
  "utf8",
);
const apiClient = readFileSync(new URL("../../lib/apiClient.ts", import.meta.url), "utf8");
const queries = readFileSync(new URL("../../lib/queries.ts", import.meta.url), "utf8");

/** Collapse whitespace and JSDoc markers so prose assertions survive wrapping. */
const flat = (value: string) =>
  value.replace(/^[ \t]*\*[ \t]?/gm, " ").replace(/\s+/g, " ");
const flatPanel = flat(panel);
const flatLogic = flat(clientLogic);

describe("integration with the existing Review UI", () => {
  it("is mounted from the existing project results route", () => {
    expect(results).toContain("BobaErrorDoctorReviewPanel");
    expect(results).toContain('from "@/components/review/BobaErrorDoctorReviewPanel"');
  });

  it("is mounted at every results render site", () => {
    expect(results.split("{errorDoctorReviewPanel}").length - 1).toBe(4);
  });

  it("does not replace the global Review UI workspace", () => {
    expect(results).toContain("{reviewWorkspace}");
  });

  it("does not replace the Candidate Review Panel", () => {
    expect(results).toContain("{candidateReviewPanel}");
  });

  it("does not replace the Clip Brief Panel", () => {
    expect(results).toContain("{clipBriefReviewPanel}");
  });

  it("keeps the pre-existing error displays intact", () => {
    expect(results).toContain("{errorDoctorPanel}");
  });

  it("reuses the Review UI error classifier rather than a new one", () => {
    expect(panel).toContain('from "@/lib/reviewUi"');
    expect(panel).toContain("classifyReviewError");
  });

  it("declares itself a specialized read-only mode", () => {
    expect(flatPanel).toContain("A specialized read-only mode of the BOBA Review UI");
  });

  it("declares itself a projection, evidence, comparison and routing layer", () => {
    expect(flatPanel).toContain(
      "trusted incident projection, an evidence workspace, a diagnosis and root-cause comparison surface, a recovery-history viewer and a safe canonical action router",
    );
  });

  it("opens no second event stream", () => {
    expect(panel).toContain("The panel opens no second stream");
  });
});

describe("declared boundaries", () => {
  it("states it never detects an error or creates an incident", () => {
    expect(flatPanel).toContain("never detects an error, creates an incident");
  });

  it("states it never diagnoses or determines a root cause", () => {
    expect(flatPanel).toContain("diagnoses, determines a root");
  });

  it("states it never creates a repair plan", () => {
    expect(flatPanel).toContain("creates a repair plan");
  });

  it("states it never executes a repair or recovery", () => {
    expect(flatPanel).toContain("executes a repair or recovery");
  });

  it("states it never restores a checkpoint or changes a workflow", () => {
    expect(flatPanel).toContain("restores a checkpoint, changes a workflow");
  });

  it("states it never runs a command, shell, Git or FFmpeg", () => {
    expect(flatPanel).toContain("runs a command, shell, Git or FFmpeg");
  });

  it("states it never installs or downloads a tool", () => {
    expect(flatPanel).toContain("installs or downloads a tool");
  });

  it("states it never uploads or publishes", () => {
    expect(flatPanel).toContain("uploads or publishes");
  });

  it("states that a hypothesis is never a fact", () => {
    expect(flatPanel).toContain("A hypothesis is never shown as a fact");
  });

  it("states that owner success is not verification", () => {
    expect(flatPanel).toContain("never shown as independent verification");
  });

  it("states that recovered is not resolved", () => {
    expect(flatPanel).toContain("never shown as resolved");
  });

  it("repeats the boundary in the rendered footer, not only in a comment", () => {
    expect(panel).toContain(
      "This panel does not diagnose, determine root causes, create repair plans or",
    );
    expect(panel).toContain("recovered is not resolved");
  });

  it("uses no dangerous HTML injection", () => {
    expect(panel).not.toContain("dangerouslySetInnerHTML");
    expect(clientLogic).not.toContain("dangerouslySetInnerHTML");
  });

  it("uses no external URL", () => {
    expect(panel).not.toContain("http://");
    expect(panel).not.toContain("https://");
  });

  it("contains no command, shell or FFmpeg invocation", () => {
    for (const token of ["subprocess", "child_process", "execSync", "ffmpeg -"]) {
      expect(panel).not.toContain(token);
    }
  });

  it("contains no repair or recovery execution control", () => {
    for (const token of ["Run repair", "Execute repair", "Retry tool", "Restore checkpoint"]) {
      expect(panel).not.toContain(token);
    }
  });

  it("renders the no-execution notice to the reviewer", () => {
    expect(panel).toContain("{NO_EXECUTION_NOTICE}");
  });

  it("renders the repair-execution-unavailable notice", () => {
    expect(panel).toContain("{REPAIR_EXECUTION_NOTICE}");
  });
});

describe("facts, diagnosis and root cause rendering", () => {
  it("labels every evidence classification through the shared helper", () => {
    expect(panel).toContain("classificationLabel(card.classification)");
  });

  it("keeps the original wording and the plain language separate", () => {
    expect(panel).toContain("Original wording, exactly as stored:");
    expect(panel).toContain("Plain language, kept separate:");
  });

  it("shows confidence with its owner definition", () => {
    expect(panel).toContain("confidenceLabel(");
    expect(panel).toContain("{CONFIDENCE_NOTICE}");
  });

  it("heads a root-cause candidate through the shared helper", () => {
    expect(panel).toContain("rootCauseHeading(item)");
  });

  it("renders the root-cause notice about human review", () => {
    expect(panel).toContain("{ROOT_CAUSE_NOTICE}");
  });

  it("shows supporting and contradictory evidence counts", () => {
    expect(panel).toContain("contradictory evidence");
  });

  it("surfaces the human-confirmation requirement", () => {
    expect(panel).toContain("requires human confirmation for this candidate");
  });

  it("declares that a hypothesis is never promoted in the logic module", () => {
    expect(flatLogic).toContain("A hypothesis is never labelled a fact");
  });
});

describe("repair and recovery rendering", () => {
  it("lists proposed steps as descriptions only", () => {
    expect(panel).toContain("proposed step(s), described only:");
    expect(panel).toContain("no command text is shown");
  });

  it("shows owner rank and score attribution", () => {
    expect(panel).toContain("repairOwnerRankLabel(item)");
  });

  it("shows the owner risk summary", () => {
    expect(panel).toContain("repairRiskLabel(item)");
  });

  it("separates recovery outcome from verification", () => {
    expect(panel).toContain("recoveryOutcomeLabel(item)");
  });

  it("lists change disclosure per attempt", () => {
    expect(panel).toContain("recoveryChangeLabels(item)");
  });

  it("renders the recovered-is-not-resolved notice", () => {
    expect(panel).toContain("{RECOVERED_NOTICE}");
  });

  it("shows rollback status from the owner", () => {
    expect(panel).toContain("{item.rollback_status}");
  });
});

describe("evidence and conflict rendering", () => {
  it("announces redaction and truncation for every card", () => {
    expect(panel).toContain("excerptNotices(card)");
  });

  it("bounds expanded excerpt cards", () => {
    expect(panel).toContain("boundedLogCardIds(");
  });

  it("labels a bounded log region for assistive technology", () => {
    expect(panel).toContain("aria-label={`Bounded excerpt for ${card.title}`}");
  });

  it("shows both conflicting values without choosing one", () => {
    expect(panel).toContain("{conflict.value_a");
    expect(panel).toContain("{conflict.value_b");
  });

  it("shows the conflict resolution label from the shared helper", () => {
    expect(panel).toContain("conflictResolutionLabel(conflict)");
  });

  it("attributes every owner status through the shared helper", () => {
    expect(panel).toContain("ownerStatusLabel(");
  });
});

describe("action routing", () => {
  it("gates offered actions through the shared helper", () => {
    expect(panel).toContain("availableActions(descriptors, snapshot, confirmations)");
  });

  it("lists withheld actions with their stated reason", () => {
    expect(panel).toContain("unavailableActionNotice(descriptor)");
  });

  it("shows the exact confirmation wording", () => {
    expect(panel).toContain("confirmationText(descriptor, incidentId)");
  });

  it("requires explicit reviewer confirmation", () => {
    expect(panel).toContain("canSubmitAction(");
    expect(panel).toContain("I have reviewed this exact incident");
  });

  it("labels the submit button as sending to the owning module", () => {
    expect(panel).toContain("Send to the owning module");
  });

  it("refreshes canonical state before creating the request", () => {
    expect(panel).toContain("refreshSnapshot.mutate(snapshot.incident_snapshot_id");
  });

  it("stops when the canonical digest changed", () => {
    expect(panel).toContain("Canonical incident state changed while this review was open");
  });

  it("stops when the server no longer offers a token", () => {
    expect(panel).toContain("no longer available for this exact incident");
  });

  it("declares that nothing is updated optimistically", () => {
    expect(flatPanel).toContain("is updated optimistically");
  });

  it("uses the server-issued token", () => {
    expect(panel).toContain("confirmation_context_digest: token");
  });

  it("validates before submitting", () => {
    expect(panel).toContain("validateAction.mutate(requestId");
    expect(panel).toContain("setActionMessage(validation.message)");
  });

  it("shows the receipt and its change labels", () => {
    expect(panel).toContain("receiptSummary(receipt)");
    expect(panel).toContain("receiptChangeLabels(receipt)");
  });
});

describe("queue and annotations", () => {
  it("offers every owner-supported filter", () => {
    for (const filter of [
      "all_current",
      "critical",
      "workflow_blocking",
      "human_review_required",
      "missing_diagnosis",
      "missing_root_cause",
      "repair_plan_available",
      "failed_recovery",
      "unverified_recovery",
      "recurring",
      "conflicts",
      "missing_evidence",
      "stale",
      "recovered",
      "resolved",
      "historical",
      "superseded",
    ]) {
      expect(panel).toContain(`"${filter}"`);
    }
  });

  it("offers every owner-supported sort", () => {
    for (const sort of [
      "review_priority",
      "source_severity",
      "first_seen",
      "last_seen",
      "affected_stage",
      "affected_module",
      "incident_id",
    ]) {
      expect(panel).toContain(`"${sort}"`);
    }
  });

  it("offers no danger, easiest-fix or success-probability sort", () => {
    const sorts = panel.slice(panel.indexOf("const SORTS"), panel.indexOf("/** Contains"));
    for (const token of ["dangerous", "easiest", "probability", "best_repair"]) {
      expect(sorts).not.toContain(token);
    }
  });

  it("says an empty queue hides nothing by a score", () => {
    expect(panel).toContain("Nothing is hidden by a score.");
  });

  it("shows the owner priority tier", () => {
    expect(panel).toContain("priorityLabel(item)");
  });

  it("renders the non-canonical annotation notice", () => {
    expect(panel).toContain("{LOCAL_ANNOTATION_NOTICE}");
    expect(panel).toContain("{annotation.notice}");
  });

  it("shows failed recovery counts on the card", () => {
    expect(panel).toContain("failed recovery attempt(s) recorded by the");
  });
});

describe("accessibility and client wiring", () => {
  it("labels the panel region", () => {
    expect(panel).toContain('aria-label="BOBA error doctor panel"');
  });

  it("uses a semantic incident list", () => {
    expect(panel).toContain("<ul className=\"mt-3 space-y-2\">");
    expect(panel).toContain("<li");
  });

  it("marks the active tab with aria-pressed", () => {
    expect(panel).toContain("aria-pressed={tab === option.id}");
  });

  it("labels every incident button and checkbox", () => {
    expect(panel).toContain("aria-label={`Open incident ${item.incident_id}`}");
    expect(panel).toContain("aria-label={`Compare incident ${item.incident_id}`}");
  });

  it("traps the confirmation dialog with a modal role", () => {
    expect(panel).toContain('role="dialog"');
    expect(panel).toContain('aria-modal="true"');
  });

  it("announces stale-state messages politely", () => {
    expect(panel).toContain('role="status"');
  });

  it("does not communicate status by colour alone", () => {
    expect(panel).toContain("incidentStateLabel(item)");
    expect(panel).toContain("severityLabel(item.original_severity)");
  });

  it("calls only the real error-doctor-review endpoints", () => {
    expect(apiClient).toContain("/error-doctor-review`");
    expect(apiClient).toContain("/error-doctor-review/registry`");
    expect(apiClient).toContain("/error-doctor-review/compare`");
  });

  it("exposes no repair or execution endpoint", () => {
    expect(apiClient).not.toContain("error-doctor-review/repair");
    expect(apiClient).not.toContain("error-doctor-review/execute");
  });

  it("invalidates canonical queries after a submission", () => {
    expect(queries).toContain(
      'queryKey: ["boba", "projects", projectId, "error-doctor-review"]',
    );
  });

  it("declares that incident state is re-read from the owner", () => {
    expect(flat(queries)).toContain(
      "Incident state is only ever re-read from the owning module, never assumed",
    );
  });

  it("registers a distinct query key namespace", () => {
    expect(queries).toContain("bobaErrorDoctorReview:");
    expect(queries).toContain("bobaIncidentQueue:");
  });

  it("contains an error boundary that changes no incident state", () => {
    expect(panel).toContain("BobaErrorDoctorReviewErrorBoundary");
    expect(panel).toContain("No incident state changed.");
  });
});
