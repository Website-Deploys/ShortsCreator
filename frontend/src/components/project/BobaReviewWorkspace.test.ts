import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

function source(relative: string) {
  return readFileSync(new URL(relative, import.meta.url), "utf8");
}

const workspace = source("./BobaReviewWorkspace.tsx");
const queue = source("./BobaReviewQueue.tsx");
const matrix = source("./BobaReviewStatusMatrix.tsx");
const evidence = source("./BobaReviewEvidenceDrawer.tsx");
const dialog = source("./BobaReviewActionDialog.tsx");
const preview = source("./BobaReviewPreview.tsx");
const results = source("./ResultsSection.tsx");
const everything = [workspace, queue, matrix, evidence, dialog, preview].join("\n");

/** Collapse whitespace and JSDoc markers so prose assertions survive wrapping. */
const flat = (value: string) =>
  value.replace(/^[ \t]*\*[ \t]?/gm, " ").replace(/\s+/g, " ");
const flatWorkspace = flat(workspace);
const flatDialog = flat(dialog);
const flatEvidence = flat(evidence);

describe("BOBA Review UI workspace composition", () => {
  it("is mounted from the existing project results route", () => {
    expect(results).toContain("BobaReviewWorkspace");
    expect(results).toContain('from "@/components/project/BobaReviewWorkspace"');
  });

  it("declares itself a presentation and routing layer", () => {
    expect(flatWorkspace).toContain("presentation and canonical action-routing layer");
    expect(flatWorkspace).toContain("Authoritative state is displayed as changed only");
  });

  it("composes every required region of the workspace", () => {
    for (const region of [
      "BobaReviewHeader",
      "BobaReviewQueue",
      "BobaWorkflowRail",
      "BobaReviewStatusMatrix",
      "BobaReviewEvidenceDrawer",
      "BobaReviewTimeline",
      "BobaReviewEventStream",
      "BobaReviewActionBar",
      "BobaReviewActionDialog",
      "BobaReviewPreview",
      "BobaReviewMobileTabs",
      "BobaReviewErrorBoundary",
    ]) {
      expect(workspace).toContain(region);
    }
  });
});

describe("source authority is preserved in the UI", () => {
  it("shows every source-owned status column", () => {
    for (const heading of [
      "SOURCE-OWNED STATUS",
      "Source module",
      "Original status",
      "Original decision",
      "Blocking",
      "Human action",
    ]) {
      expect(matrix).toContain(heading);
    }
  });

  it("states that the workspace does not create the decisions it shows", () => {
    expect(flat(matrix)).toContain("it does not create or change them");
    expect(matrix).toContain("This module owns the decision.");
  });

  it("names the owning module and operation in the confirmation dialog", () => {
    expect(dialog).toContain("owning_module_id");
    expect(dialog).toContain("owning_operation_id");
    expect(flatDialog).toContain("That module owns the outcome");
  });
});

describe("canonical action routing", () => {
  it("refreshes canonical state before submitting", () => {
    expect(workspace).toContain("refreshSnapshot.mutate");
    expect(workspace).toContain("snapshot_digest !== snapshot.snapshot_digest");
    expect(flatWorkspace).toContain("Canonical state changed while this review was open");
  });

  it("validates before submitting and honours the validation result", () => {
    const validateIndex = workspace.indexOf("validateAction.mutate");
    const submitIndex = workspace.indexOf("submitAction.mutate");
    expect(validateIndex).toBeGreaterThan(-1);
    expect(submitIndex).toBeGreaterThan(validateIndex);
    expect(workspace).toContain("if (!validation.valid)");
  });

  it("echoes a server-issued confirmation token rather than inventing one", () => {
    expect(workspace).toContain("action_confirmations");
    expect(workspace).toContain("confirmation_context_digest: token");
    expect(workspace).not.toContain('confirmation_context_digest: ""');
  });

  it("only offers actions the snapshot and the server token both allow", () => {
    expect(dialog).toContain("confirmableActionIds");
    expect(dialog).toContain("snapshotOffered.filter");
    expect(workspace).toContain("confirmableActionIds={Object.keys(confirmations)}");
  });

  it("requires explicit confirmation before enabling submission", () => {
    expect(dialog).toContain("I confirm this exact decision for this exact target.");
    expect(dialog).toContain("!acknowledged");
  });

  it("never claims authority changed without an owner receipt", () => {
    expect(workspace).toContain("receiptChangedAuthority(owned)");
    expect(flatWorkspace).toContain("The owning module did not report an authoritative change");
    expect(dialog).toContain("receiptChangedAuthority(receipt)");
  });

  it("performs no optimistic authority update", () => {
    expect(workspace).not.toContain("optimisticUpdate");
    expect(workspace).not.toContain("setQueryData");
    expect(flatWorkspace).toContain("No optimistic authority update");
  });
});

describe("protected media preview", () => {
  it("uses only the guarded same-origin helper", () => {
    expect(preview).toContain("protectedPreviewUrl");
    expect(preview).not.toMatch(/src=\{`https?:/);
  });

  it("states that playback is not technical validation", () => {
    expect(flat(preview)).toContain("not technical validation");
    expect(flat(preview)).toContain("owned by the Validator Runner");
  });

  it("declares the preview read-only with no upload or publication", () => {
    expect(flat(preview)).toContain("cannot edit, replace or overwrite");
    expect(flat(preview)).toContain("cannot upload or publish");
  });
});

describe("truthful events", () => {
  it("filters out non-work frames before display", () => {
    expect(evidence).toContain("isWorkEvent");
    expect(flatEvidence).toContain("Idle and keep-alive frames are not work");
  });

  it("shows progress only from real source counters", () => {
    expect(evidence).toContain("realProgress");
    expect(evidence).toContain("Reported progress");
  });

  it("announces disconnection clearly and offers reconnect", () => {
    expect(flatEvidence).toContain("Live updates disconnected");
    expect(evidence).toContain("Reconnect");
    expect(evidence).toContain('aria-live="polite"');
  });

  it("labels timestamps that the source did not report", () => {
    expect(evidence).toContain("Timestamp not reported by the source");
  });
});

describe("accessibility and responsiveness", () => {
  it("uses semantic landmarks and headings", () => {
    expect(workspace).toContain("<header");
    expect(workspace).toContain("<main");
    expect(queue).toContain("aria-labelledby=\"review-queue-heading\"");
    expect(evidence).toContain("<aside");
    expect(matrix).toContain("<caption");
    expect(matrix).toContain('scope="row"');
  });

  it("makes the queue a keyboard-navigable listbox", () => {
    expect(queue).toContain('role="listbox"');
    expect(queue).toContain('role="option"');
    for (const key of ["ArrowDown", "ArrowUp", "Home", "End", "Enter"]) {
      expect(queue).toContain(key);
    }
  });

  it("implements a labelled modal dialog with a focus trap and focus return", () => {
    expect(dialog).toContain('role="dialog"');
    expect(dialog).toContain('aria-modal="true"');
    expect(dialog).toContain("aria-labelledby=\"review-action-dialog-title\"");
    expect(dialog).toContain("aria-describedby=\"review-action-dialog-description\"");
    expect(dialog).toContain("trapFocus");
    expect(dialog).toContain("returnFocusRef");
    expect(dialog).toContain('event.key === "Escape"');
  });

  it("provides accessible tabs for the mobile layout", () => {
    expect(workspace).toContain('role="tablist"');
    expect(workspace).toContain('role="tab"');
    expect(workspace).toContain('role="tabpanel"');
    expect(workspace).toContain("aria-selected");
    expect(workspace).toContain("aria-controls");
    for (const tab of ["Queue", "Review", "Evidence", "Events"]) {
      expect(workspace).toContain(`label: "${tab}"`);
    }
  });

  it("keeps visible focus states and touch-sized controls", () => {
    expect(everything).toContain("focus-visible:ring");
    expect(everything).toContain("min-h-[44px]");
  });

  it("uses a desktop grid and a mobile-only tab layout", () => {
    expect(workspace).toContain("lg:grid");
    expect(workspace).toContain("lg:hidden");
    expect(workspace).toContain("hidden gap-4 lg:grid");
  });

  it("never relies on colour alone for status", () => {
    expect(matrix).toContain("stateGlyph");
    expect(matrix).toContain("stateLabel");
    expect(evidence).toContain("[live]");
    expect(evidence).toContain("[offline]");
  });

  it("labels loading and error states for assistive technology", () => {
    expect(queue).toContain('role="status"');
    expect(queue).toContain('role="alert"');
    expect(workspace).toContain('role="alert"');
  });
});

describe("safe errors and hard boundaries", () => {
  it("routes every failure through the safe classifier", () => {
    expect(workspace).toContain("classifyReviewError");
    expect(workspace).not.toContain("error.stack");
    expect(workspace).not.toContain("JSON.stringify(error");
  });

  it("contains unexpected render failures without leaking internals", () => {
    expect(workspace).toContain("getDerivedStateFromError");
    expect(flatWorkspace).toContain("could not be displayed");
    expect(flatWorkspace).toContain("No authoritative state changed");
  });

  it("renders no untrusted HTML", () => {
    expect(everything).not.toContain("dangerouslySetInnerHTML");
    expect(everything).not.toContain("innerHTML");
  });

  it("exposes no upload, publication or execution controls", () => {
    for (const forbidden of [
      "uploadThumbnail",
      "publishTo",
      "runValidator",
      "executeRepair",
      "restoreCheckpoint",
      "<input type=\"file\"",
    ]) {
      expect(everything).not.toContain(forbidden);
    }
    expect(flatDialog).toContain("cannot upload, publish, run validators, execute repairs");
  });

  it("states that Rights and Safety cannot be bypassed", () => {
    expect(flatDialog).toContain("bypass Rights or Safety");
  });
});
