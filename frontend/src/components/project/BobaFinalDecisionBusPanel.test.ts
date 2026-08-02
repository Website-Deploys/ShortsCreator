import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

function source(relative: string) {
  return readFileSync(new URL(relative, import.meta.url), "utf8");
}

describe("BOBA Final Decision Bus UI contract", () => {
  it("renders bounded adjudication controls without execution or override controls", () => {
    const resultsSection = source("./ResultsSection.tsx");
    const panel = source("./BobaFinalDecisionBusPanel.tsx");

    expect(resultsSection).toContain("BobaFinalDecisionBusPanel");
    expect(panel).toContain(
      "Final Decision Bus combines current authoritative decisions for one exact internal action.",
    );
    expect(panel).toContain(
      "It cannot override Rights, Safety, approval, validation, quality, artifact or workflow decisions.",
    );
    expect(panel).toContain(
      "A ready decision permits creation of a single-use internal dispatch envelope. It does not execute the action.",
    );
    for (const heading of [
      "PROPOSED ACTION",
      "AUTHORITATIVE SOURCES",
      "RIGHTS",
      "SAFETY",
      "APPROVAL",
      "WORKFLOW",
      "ARTIFACTS",
      "TECHNICAL VALIDATION",
      "OUTPUT QUALITY",
      "RECOVERY STATE",
      "MISSING EVIDENCE",
      "CONFLICTS",
      "FINAL DISPOSITION",
      "DISPATCH ENVELOPE",
      "WHAT HAPPENS NEXT",
    ]) {
      expect(panel).toContain(heading);
    }
    for (const control of [
      "Inspect decision sources",
      "Inspect action policies",
      "Create exact request",
      "Validate request",
      "Collect source decisions",
      "Bind evidence",
      "Evaluate policy",
      "Finalize decision",
      "Build dispatch envelope",
      "Invalidate decision",
      "Export",
      "Reset active metadata",
    ]) {
      expect(panel).toContain(control);
    }
    expect(panel).toContain("Exact source selectors JSON");
    expect(panel).toContain("This panel never selects evidence automatically.");
    for (const forbiddenControl of [
      "Override source decision",
      "Ignore blocker",
      "Mark ready manually",
      "Create approval",
      "Approve Safety",
      "Run command",
      "Execute repair",
      "Resume workflow",
      "Upload",
      "Publish",
    ]) {
      expect(panel).not.toContain(forbiddenControl);
    }
  });
});