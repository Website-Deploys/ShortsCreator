import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

function source(relative: string) {
  return readFileSync(new URL(relative, import.meta.url), "utf8");
}

describe("BOBA Validator Runner UI contract", () => {
  it("mounts a bounded validation panel without arbitrary execution controls", () => {
    const resultsSection = source("./ResultsSection.tsx");
    const panel = source("./BobaValidatorRunnerPanel.tsx");

    expect(resultsSection).toContain("BobaValidatorRunnerPanel");
    expect(panel).toContain("Validator Runner executes only registered local validation checks.");
    expect(panel).toContain(
      "A passed suite confirms only the exact technical validation plan.",
    );
    expect(panel).toContain(
      "Required unavailable checks make the suite incomplete rather than passed.",
    );
    for (const heading of [
      "VALIDATOR REGISTRY",
      "VALIDATION PLAN",
      "TARGET AND INPUTS",
      "REQUIRED CHECKS",
      "OPTIONAL CHECKS",
      "EXECUTION POLICY",
      "RESOURCE BUDGET",
      "LIVE VALIDATION",
      "RESULTS",
      "EVIDENCE",
      "SUITE DECISION",
      "WHAT HAPPENS NEXT",
    ]) {
      expect(panel).toContain(heading);
    }
    expect(panel).toContain("Inspect validators");
    expect(panel).toContain("Export report");
    expect(panel).toContain("Reset active metadata");
    expect(panel).not.toContain("Run arbitrary command");
    expect(panel).not.toContain("Add custom validator path");
    expect(panel).not.toContain("Install missing validator");
  });
});
