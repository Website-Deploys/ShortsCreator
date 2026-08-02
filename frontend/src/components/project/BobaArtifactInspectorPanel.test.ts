import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

function source(relative: string) {
  return readFileSync(new URL(relative, import.meta.url), "utf8");
}

describe("BOBA Artifact Inspector UI contract", () => {
  it("renders read-only artifact inspection controls and boundaries", () => {
    const resultsSection = source("./ResultsSection.tsx");
    const panel = source("./BobaArtifactInspectorPanel.tsx");

    expect(resultsSection).toContain("BobaArtifactInspectorPanel");
    expect(panel).toContain(
      "Artifact Inspector checks registered local artifacts without changing them.",
    );
    for (const heading of [
      "ARTIFACT REGISTRY",
      "ARTIFACT IDENTITY",
      "STORAGE AND FORMAT",
      "INTEGRITY",
      "FRESHNESS",
      "PROTECTION",
      "INVENTORY",
      "LINEAGE",
      "MISSING OR ORPHANED ARTIFACTS",
      "DUPLICATES AND CONFLICTS",
      "DEEPER VALIDATION REQUIRED",
      "WHAT HAPPENS NEXT",
    ]) {
      expect(panel).toContain(heading);
    }
    for (const control of [
      "Inspect artifact types",
      "Create inspection request",
      "Validate references",
      "Inspect selected artifacts",
      "Build project inventory",
      "Inspect lineage",
      "Compare artifacts",
      "Export inspection",
      "Reset active metadata",
    ]) {
      expect(panel).toContain(control);
    }
    expect(panel).toContain("Deep technical checks are sent to Validator Runner.");
    expect(panel).not.toContain("Repair artifact");
    expect(panel).not.toContain("Resume workflow");
    expect(panel).not.toContain("Run command");
  });
});
