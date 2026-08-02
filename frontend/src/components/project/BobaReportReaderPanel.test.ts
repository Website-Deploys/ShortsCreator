import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

function source(relative: string) {
  return readFileSync(new URL(relative, import.meta.url), "utf8");
}

describe("BOBA Report Reader UI contract", () => {
  it("renders read-only evidence controls and source-authority boundaries", () => {
    const resultsSection = source("./ResultsSection.tsx");
    const panel = source("./BobaReportReaderPanel.tsx");
    const normalizedPanel = panel.replace(/\s+/g, " ");

    expect(resultsSection).toContain("BobaReportReaderPanel");
    expect(panel).toContain(
      "Report Reader explains registered Olympus and BOBA reports without",
    );
    expect(panel).toContain(
      "A technical validation pass is not the same as quality approval or",
    );
    expect(normalizedPanel).toContain(
      "Historical reports remain visible but cannot prove the current project state.",
    );
    for (const heading of [
      "REPORT SOURCES",
      "REPORT IDENTITY",
      "SOURCE DECISIONS",
      "CONFIRMED FACTS",
      "SOURCE ASSESSMENTS",
      "BOBA INTERPRETATION",
      "EVIDENCE",
      "TIMELINE",
      "CONTRADICTIONS",
      "MISSING INFORMATION",
      "EASY EXPLANATION",
      "WHAT HAPPENS NEXT",
    ]) {
      expect(panel).toContain(heading);
    }
    for (const control of [
      "Inspect report sources",
      "Create read request",
      "Validate references",
      "Read selected reports",
      "Compare reports",
      "Build report bundle",
      "Export summary",
      "Reset active metadata",
    ]) {
      expect(panel).toContain(control);
    }
    expect(panel).not.toContain("Edit report");
    expect(panel).not.toContain("Override decision");
    expect(panel).not.toContain("Mark as passed");
    expect(panel).not.toContain("Approve repair");
    expect(panel).not.toContain("Resume workflow");
    expect(panel).not.toContain("Run command");
  });
});
