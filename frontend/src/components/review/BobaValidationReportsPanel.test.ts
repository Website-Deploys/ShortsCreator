import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

function source(relative: string) {
  return readFileSync(new URL(relative, import.meta.url), "utf8");
}

const panel = source("./BobaValidationReportsPanel.tsx");
const results = source("../project/ResultsSection.tsx");
const clientLogic = readFileSync(
  new URL("../../lib/validationReports.ts", import.meta.url),
  "utf8",
);
const apiClient = readFileSync(new URL("../../lib/apiClient.ts", import.meta.url), "utf8");
const queries = readFileSync(new URL("../../lib/queries.ts", import.meta.url), "utf8");

/** Collapse whitespace and JSDoc markers so prose assertions survive wrapping. */
const flat = (value: string) =>
  value.replace(/^[ \t]*\*[ \t]?/gm, " ").replace(/\s+/g, " ");
const flatPanel = flat(panel);
const flatLogic = flat(clientLogic);

describe("integration with the existing project surfaces", () => {
  it("is mounted from the existing project results route", () => {
    expect(results).toContain("BobaValidationReportsPanel");
    expect(results).toContain('from "@/components/review/BobaValidationReportsPanel"');
  });

  it("is mounted at every results render site", () => {
    const rendered = results.match(/\{validationReportsPanel\}/g) ?? [];
    const inspector = results.match(/\{artifactInspectorPanel\}/g) ?? [];
    expect(rendered.length).toBe(inspector.length);
    expect(rendered.length).toBeGreaterThanOrEqual(4);
  });

  it("is wrapped in its own error boundary wherever it is mounted", () => {
    expect(results).toContain("BobaValidationReportsErrorBoundary");
    expect(panel).toContain("export class BobaValidationReportsErrorBoundary");
    expect(panel).toContain("static getDerivedStateFromError");
  });

  it("does not replace or duplicate the owner-specific panels", () => {
    // The Validator Runner and Report Reader panels are those owners' own
    // surfaces. This panel is a projection and must coexist with them.
    expect(results).toContain("BobaValidatorRunnerPanel");
    expect(results).toContain("BobaReportReaderPanel");
    expect(panel).not.toContain("BobaValidatorRunnerPanel");
    expect(panel).not.toContain("BobaReportReaderPanel");
  });
});

describe("the API client surface", () => {
  const expected = [
    "getBobaValidationReports",
    "getBobaValidationReportsRegistry",
    "getBobaValidationSummary",
    "getBobaValidationMatrix",
    "getBobaValidationReportCards",
    "getBobaValidationReportDetail",
    "getBobaValidationEvidence",
    "getBobaValidationConflicts",
    "getBobaValidationReportEvents",
    "createBobaValidationProjectionRequest",
    "exportBobaValidationReports",
  ];

  it("exposes every projection endpoint", () => {
    for (const name of expected) {
      expect(apiClient).toContain(`${name}:`);
    }
  });

  it("scopes every call to a project", () => {
    const calls = apiClient.match(/`\/boba\/projects\/\$\{projectId\}\/validation-reports[^`]*`/g) ?? [];
    expect(calls.length).toBeGreaterThanOrEqual(11);
    for (const call of calls) {
      expect(call).toContain("/boba/projects/${projectId}/validation-reports");
    }
  });

  it("uses POST only for its own projection request metadata", () => {
    const block = apiClient.slice(
      apiClient.indexOf("BOBA Validation + Reports V1"),
      apiClient.indexOf("BOBA Repair Plan Panel V1"),
    );
    const posts = block.match(/method: "POST"/g) ?? [];
    expect(posts).toHaveLength(1);
    expect(block).toContain("validation-reports/requests");
    expect(block).not.toContain('method: "DELETE"');
    expect(block).not.toContain('method: "PUT"');
  });
});

describe("the React Query surface", () => {
  const hooks = [
    "useBobaValidationReports",
    "useBobaValidationReportsRegistry",
    "useBobaValidationSummary",
    "useBobaValidationMatrix",
    "useBobaValidationReportCards",
    "useBobaValidationReportDetail",
    "useBobaValidationEvidence",
    "useBobaValidationConflicts",
    "useBobaValidationReportEvents",
    "useCreateBobaValidationProjectionRequest",
    "useExportBobaValidationReports",
  ];

  it("exposes a hook per projection surface", () => {
    for (const hook of hooks) {
      expect(queries).toContain(`export function ${hook}(`);
    }
  });

  it("keys every query by project", () => {
    for (const key of [
      "bobaValidationReports",
      "bobaValidationSummary",
      "bobaValidationMatrix",
      "bobaValidationReportCards",
      "bobaValidationReportDetail",
      "bobaValidationEvidence",
      "bobaValidationConflicts",
      "bobaValidationReportEvents",
    ]) {
      expect(queries).toContain(`${key}: (`);
    }
  });

  it("refetches rather than writing an optimistic projection", () => {
    const block = queries.slice(queries.indexOf("BOBA Validation + Reports V1"));
    expect(block).toContain("invalidateQueries");
    expect(block).not.toContain("setQueryData");
    expect(flat(block)).toContain("never the UI's to guess");
  });
});

describe("the panel holds no authority", () => {
  it("declares itself presentation only", () => {
    expect(flatPanel).toContain("Presentation only");
    expect(flatPanel).toContain("holds no authority");
  });

  it("offers no control that could execute, approve or advance anything", () => {
    for (const forbidden of [
      "useMutation",
      "Approve",
      "Reject",
      "Run validation",
      "Re-run",
      "Retry validation",
      "Publish",
      "Upload",
      "Restore",
      "Execute",
    ]) {
      expect(panel).not.toContain(forbidden);
    }
  });

  it("never makes an affirmative authorisation claim", () => {
    // "approved for upload" may only ever appear inside a denial, never as a
    // claim, so affirmative phrasings are what get asserted against.
    const lowered = flat(panel).toLowerCase();
    for (const claim of [
      "is production ready",
      "is approved",
      "safe to publish",
      "safe to upload",
      "ready to publish",
      "ready for upload",
      "validation guarantees",
      "fully validated",
    ]) {
      expect(lowered).not.toContain(claim);
    }
    // The only mention of upload approval is the explicit denial.
    expect(lowered).toContain(
      "does not mean production ready, quality accepted, rights cleared, or approved for upload or publication",
    );
  });

  it("states plainly that a technical pass is not readiness", () => {
    expect(flatPanel).toContain("does not mean production ready");
    expect(flatPanel).toContain("quality accepted");
  });

  it("says the panel runs no validator and changes no workflow", () => {
    expect(flatPanel).toContain("Nothing here runs a validator");
    expect(flatPanel).toContain("changes a workflow");
  });
});

describe("the matrix presentation", () => {
  it("renders all seven states rather than a subset", () => {
    expect(panel).toContain("BobaValidationStateStrip");
    expect(clientLogic).toContain('"NOT_RUN"');
    expect(clientLogic).toContain('"MISSING"');
    expect(clientLogic).toContain('"STALE"');
    expect(clientLogic).toContain('"SKIPPED"');
    expect(clientLogic).toContain('"BLOCKED"');
  });

  it("shows the owner status next to the derived state", () => {
    expect(panel).toContain("Owner status");
    expect(panel).toContain("cell.owner_status");
    expect(panel).toContain("cell.derived_state");
  });

  it("explains why a derived state differs from the owner presentation", () => {
    expect(panel).toContain("cell.owner_reported_state !== cell.derived_state");
    expect(flatPanel).toContain("Owner-reported presentation was");
  });

  it("reports checks that carry no verdict", () => {
    expect(panel).toContain("cellsWithoutVerdict");
    expect(flatPanel).toContain("carry no validation verdict");
    expect(flatPanel).toContain("not counted as passing");
  });

  it("shows validator identity, digests and timestamps", () => {
    expect(panel).toContain("Validator version");
    expect(panel).toContain("Result digest");
    expect(panel).toContain("Completed");
  });
});

describe("stale state and lineage presentation", () => {
  it("names the exact dimensions that invalidated reuse", () => {
    expect(panel).toContain("staleDimensionLabels");
    expect(flatPanel).toContain("Stale binding.");
    expect(flatPanel).toContain("cannot be reused");
  });

  it("shows report lineage", () => {
    expect(panel).toContain("lineage_read_run_id");
    expect(flatPanel).toContain("Lineage:");
  });

  it("shows digest and integrity indicators for reports", () => {
    expect(panel).toContain("Content digest");
    expect(panel).toContain("Integrity");
    expect(panel).toContain("Digest verified");
  });
});

describe("conflict presentation", () => {
  it("presents conflicts as unresolved and preserves every value", () => {
    expect(panel).toContain("BobaValidationConflictList");
    expect(flatPanel).toContain("unresolved");
    expect(flatPanel).toContain("Both values are preserved");
    expect(flatPanel).toContain("No result was selected as best");
    expect(flatPanel).toContain("no root cause or repair is inferred");
  });
});

describe("report bodies stay with their owner", () => {
  it("says so in the panel and in the logic module", () => {
    expect(flatPanel).toContain("Report bodies remain owned by the");
    expect(flatPanel).toContain("not stored here");
    expect(flatLogic).toContain("never turns missing evidence into a");
  });
});

describe("loading, empty and error states", () => {
  it("provides all three for every asynchronous section", () => {
    expect(panel).toContain("function LoadingState");
    expect(panel).toContain("function EmptyState");
    expect(panel).toContain("function ErrorState");
    const loading = panel.match(/isPending \?/g) ?? [];
    const failing = panel.match(/isError \?/g) ?? [];
    expect(loading.length).toBeGreaterThanOrEqual(5);
    expect(failing.length).toBeGreaterThanOrEqual(5);
  });

  it("never presents an error as a pass", () => {
    expect(flatPanel).toContain(
      "Nothing is reported as passing while data is unavailable",
    );
  });

  it("states honestly when no checks exist", () => {
    expect(flatPanel).toContain("No validation checks exist for this project yet");
    expect(flatPanel).toContain("Nothing is reported as passing.");
  });

  it("states honestly when evidence is absent", () => {
    expect(flatPanel).toContain("Absent evidence is not treated as a pass");
  });
});

describe("accessibility and responsive layout", () => {
  it("marks live and alert regions", () => {
    expect(panel).toContain('role="status"');
    expect(panel).toContain('aria-live="polite"');
    expect(panel).toContain('role="alert"');
  });

  it("labels the matrix, strip and conflict lists", () => {
    expect(panel).toContain('aria-label="Validation state totals"');
    expect(panel).toContain('aria-label="Validation status matrix"');
    expect(panel).toContain('aria-label="Validation conflicts"');
  });

  it("uses accessible toggle semantics for report details", () => {
    expect(panel).toContain("aria-pressed={selected}");
    expect(panel).toContain('type="button"');
    expect(panel).toContain("focus-visible:ring");
  });

  it("hides decorative glyphs from assistive technology", () => {
    const hidden = panel.match(/aria-hidden/g) ?? [];
    expect(hidden.length).toBeGreaterThanOrEqual(2);
  });

  it("lays out responsively", () => {
    expect(panel).toContain("sm:grid-cols-4");
    expect(panel).toContain("lg:grid-cols-7");
    expect(panel).toContain("sm:p-4");
  });
});
