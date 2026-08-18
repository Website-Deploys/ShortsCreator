/**
 * Wiring and boundary checks for the Validation + Reports panel.
 *
 * Scope note, deliberately narrow: this file only asserts things that are
 * genuinely structural — which module is mounted where, which endpoints and
 * hooks exist, and which controls are absent. Those are wiring facts that a
 * render test cannot observe.
 *
 * What a user actually sees is covered behaviourally in
 * `BobaValidationReportsPanel.render.test.tsx`, and the projection logic is
 * covered in `src/lib/validationReports.test.ts`. This file previously also
 * asserted the panel's prose and comments via `toContain`, which measured
 * nothing: it passed whenever the wording was present and the behaviour was
 * broken, and broke whenever a comment was reworded. Those assertions were
 * replaced by real rendering tests rather than kept for their count.
 */
import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

function source(relative: string) {
  return readFileSync(new URL(relative, import.meta.url), "utf8");
}

const panel = source("./BobaValidationReportsPanel.tsx");
const results = source("../project/ResultsSection.tsx");
const apiClient = readFileSync(new URL("../../lib/apiClient.ts", import.meta.url), "utf8");
const queries = readFileSync(new URL("../../lib/queries.ts", import.meta.url), "utf8");

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
    const calls =
      apiClient.match(/`\/boba\/projects\/\$\{projectId\}\/validation-reports[^`]*`/g) ?? [];
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
  });
});

describe("the panel exposes no control that could act", () => {
  it("offers no mutation and no execute, approve or advance control", () => {
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

  it("never introduces an affirmative authorisation claim", () => {
    // A guard against future wording, not a behavioural assertion: the panel
    // must never gain prose that reads as an authorisation. The denial that is
    // actually rendered is asserted in the render tests.
    const lowered = panel.replace(/\s+/g, " ").toLowerCase();
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
  });
});

describe("every asynchronous section has a loading and an error branch", () => {
  it("provides a loading, empty and error component", () => {
    expect(panel).toContain("function LoadingState");
    expect(panel).toContain("function EmptyState");
    expect(panel).toContain("function ErrorState");
  });

  it("branches on pending and error state for each query", () => {
    const loading = panel.match(/isPending \?/g) ?? [];
    const failing = panel.match(/isError \?/g) ?? [];
    expect(loading.length).toBeGreaterThanOrEqual(5);
    expect(failing.length).toBeGreaterThanOrEqual(5);
  });

  it("marks live and alert regions", () => {
    expect(panel).toContain('role="status"');
    expect(panel).toContain('aria-live="polite"');
    expect(panel).toContain('role="alert"');
  });
});
