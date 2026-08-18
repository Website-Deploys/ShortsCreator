// @vitest-environment jsdom
/**
 * Real rendering tests for the Validation + Reports panel.
 *
 * These assert what a human actually sees. They replace the source-text
 * assertions that previously stood in for behavioural coverage: a `toContain`
 * against a `.tsx` file passes when the prose is present and the behaviour is
 * broken, and fails when a comment is reworded, so it measured nothing.
 *
 * Every exported presentational component here is prop-driven, so nothing is
 * mocked and no network or query client is involved.
 */
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import {
  BobaValidationConflictList,
  BobaValidationReportsErrorBoundary,
  BobaValidationEvidenceList,
  BobaValidationMatrixTable,
  BobaValidationReportCardView,
  BobaValidationStateStrip,
  BobaValidationSummaryCard,
} from "./BobaValidationReportsPanel";
import {
  MATRIX_STATES,
  parseConflict,
  parseEvidence,
  parseMatrixCell,
  parseReportCard,
  parseSummary,
} from "@/lib/validationReports";

afterEach(cleanup);

const cell = (over: Record<string, unknown> = {}) =>
  parseMatrixCell({
    cell_id: "cell-1",
    validator_id: "v-schema",
    validator_version: "1",
    owner_status: "passed",
    derived_state: "PASS",
    owner_reported_state: "PASS",
    verdict_available: true,
    evidence_present: true,
    required: true,
    result_digest: "a".repeat(64),
    completed_at: "2026-08-01T00:00:00+00:00",
    derived_state_reason: "The Validator Runner recorded a passing verdict.",
    ...over,
  });

const summary = (over: Record<string, unknown> = {}) =>
  parseSummary({
    summary_id: "sum-1",
    validation_run_id: "vrun-1",
    run_status: "completed",
    suite_decision: "accepted",
    technical_validation_passed: true,
    evidence_missing: false,
    state_counts: { PASS: 1 },
    binding: { bound: true, reuse_valid: true, workflow_revision: 3, invalidated_dimensions: [] },
    warnings: [],
    ...over,
  });

describe("the state strip shows every state, never a subset", () => {
  it("renders all seven states even when most are zero", () => {
    render(<BobaValidationStateStrip counts={{ PASS: 2 }} />);
    const strip = screen.getByLabelText("Validation state totals");
    const items = within(strip).getAllByRole("listitem");

    expect(items).toHaveLength(MATRIX_STATES.length);
    expect(MATRIX_STATES).toHaveLength(7);
  });

  it("marks non-verdict states as carrying no verdict once they have a total", () => {
    render(<BobaValidationStateStrip counts={{ PASS: 1, MISSING: 3, STALE: 2 }} />);
    const strip = screen.getByLabelText("Validation state totals");

    // MISSING and STALE hold no verdict; PASS does.
    expect(within(strip).getAllByText("no verdict")).toHaveLength(2);
  });

  it("does not label a zero-count non-verdict state", () => {
    render(<BobaValidationStateStrip counts={{ PASS: 1 }} />);
    const strip = screen.getByLabelText("Validation state totals");

    expect(within(strip).queryAllByText("no verdict")).toHaveLength(0);
  });
});

describe("the matrix shows owner facts beside the derived presentation", () => {
  it("shows the verbatim owner status next to the derived state", () => {
    render(<BobaValidationMatrixTable cells={[cell()]} />);

    expect(screen.getByText("Owner status:")).toBeTruthy();
    // The verbatim owner status and the derived label are both rendered.
    expect(screen.getByText("passed")).toBeTruthy();
    expect(screen.getByText("Passed")).toBeTruthy();
  });

  it("explains when the derived state differs from the owner presentation", () => {
    render(
      <BobaValidationMatrixTable
        cells={[
          cell({
            owner_status: "passed",
            owner_reported_state: "PASS",
            derived_state: "MISSING",
            verdict_available: false,
            evidence_present: false,
          }),
        ]}
      />,
    );

    expect(screen.getByText(/Owner-reported presentation was/)).toBeTruthy();
    // Both the owner presentation and the shown state are named.
    const note = screen.getByText(/Owner-reported presentation was/);
    expect(note.textContent).toContain("Passed");
    expect(note.textContent).toContain("Missing evidence");
  });

  it("reports an owner pass with no evidence as absent evidence, not a pass", () => {
    render(
      <BobaValidationMatrixTable
        cells={[
          cell({
            owner_status: "passed",
            owner_reported_state: "PASS",
            derived_state: "MISSING",
            verdict_available: false,
            evidence_present: false,
          }),
        ]}
      />,
    );
    const row = screen.getByRole("listitem");

    // The row's own status is missing evidence, and it carries no verdict.
    // It appears twice: as this row's status, and inside the preserved
    // owner-fact explanation below it.
    expect(within(row).getAllByText("Missing evidence")).toHaveLength(2);
    expect(within(row).getByText("Absent")).toBeTruthy();
    expect(within(row).getByText("None recorded")).toBeTruthy();

    // The owner's original claim is still visible, but only as a preserved
    // owner fact inside the explanation, never as this row's verdict.
    const preserved = screen.getByText(/Owner-reported presentation was/);
    expect(within(preserved).getByText("Passed")).toBeTruthy();
    expect(preserved.textContent).toContain("it is shown as");
  });

  it("counts checks without a verdict and says they are not passing", () => {
    render(
      <BobaValidationMatrixTable
        cells={[
          cell({ cell_id: "c1" }),
          cell({ cell_id: "c2", derived_state: "BLOCKED", verdict_available: false, owner_status: "blocked" }),
          cell({ cell_id: "c3", derived_state: "NOT_RUN", verdict_available: false, owner_status: "pending" }),
        ]}
      />,
    );

    const note = screen.getByText(/carry no validation verdict/);
    expect(note.textContent).toContain("2 of 3");
    expect(note.textContent).toContain("not counted as passing");
  });

  it("states honestly that nothing passes when no checks exist", () => {
    render(<BobaValidationMatrixTable cells={[]} />);

    expect(screen.getByText(/No validation checks exist for this project yet/)).toBeTruthy();
    expect(screen.getByText(/Nothing is reported as passing/)).toBeTruthy();
    expect(screen.queryByLabelText("Validation status matrix")).toBeNull();
  });

  it("orders cells deterministically regardless of input order", () => {
    const cells = [
      cell({ cell_id: "z", validator_id: "v-zebra", plan_check_id: "p2" }),
      cell({ cell_id: "a", validator_id: "v-alpha", plan_check_id: "p1" }),
    ];
    render(<BobaValidationMatrixTable cells={cells} />);
    const items = screen.getAllByRole("listitem");

    expect(items[0].textContent).toContain("v-alpha");
    expect(items[1].textContent).toContain("v-zebra");
  });

  it("shows validator identity, digest and completion timestamp", () => {
    render(<BobaValidationMatrixTable cells={[cell()]} />);

    expect(screen.getByText("v-schema")).toBeTruthy();
    expect(screen.getByText("Validator version:")).toBeTruthy();
    expect(screen.getByText("2026-08-01T00:00:00+00:00")).toBeTruthy();
  });
});

describe("the summary never presents an unsupported claim", () => {
  it("states plainly that a technical pass is not readiness or approval", () => {
    render(<BobaValidationSummaryCard summary={summary()} conflictCount={0} />);

    expect(
      screen.getByText(
        /does not mean production ready, quality accepted, rights cleared, or approved for upload or publication/,
      ),
    ).toBeTruthy();
  });

  it("reports incomplete evidence rather than a pass", () => {
    render(
      <BobaValidationSummaryCard
        summary={summary({ technical_validation_passed: false, evidence_missing: true })}
        conflictCount={0}
      />,
    );

    expect(screen.getByText("Incomplete")).toBeTruthy();
    expect(screen.getByText("Not passed")).toBeTruthy();
  });

  it("names the exact dimensions that invalidated verdict reuse", () => {
    render(
      <BobaValidationSummaryCard
        summary={summary({
          binding: {
            bound: true,
            reuse_valid: false,
            workflow_revision: 4,
            invalidated_dimensions: ["artifact_digest", "workflow_revision"],
          },
        })}
        conflictCount={0}
      />,
    );

    const warning = screen.getByText(/Stale binding\./).closest("p");
    expect(warning?.textContent).toContain("cannot be reused");
    expect(warning?.textContent).toContain("Artifact digest");
    expect(warning?.textContent).toContain("Workflow revision");
  });

  it("omits the stale warning when nothing invalidated reuse", () => {
    render(<BobaValidationSummaryCard summary={summary()} conflictCount={0} />);

    expect(screen.queryByText(/Stale binding\./)).toBeNull();
  });

  it("leads with conflicts when the evidence disagrees", () => {
    render(<BobaValidationSummaryCard summary={summary()} conflictCount={2} />);
    const heading = screen.getByRole("heading", { level: 4 });

    expect(heading.textContent?.toLowerCase()).toContain("conflict");
  });

  it("leads with missing evidence ahead of any pass wording", () => {
    render(
      <BobaValidationSummaryCard
        summary={summary({ technical_validation_passed: false, evidence_missing: true })}
        conflictCount={0}
      />,
    );
    const heading = screen.getByRole("heading", { level: 4 });

    expect(heading.textContent?.toLowerCase()).not.toContain("passed");
  });
});

describe("conflicts stay visible and unresolved", () => {
  const conflict = parseConflict({
    conflict_id: "cf-1",
    conflict_kind: "check_status_conflict",
    subject_id: "pcheck-shared",
    bounded_summary: "Two validators disagree on the same check.",
    participants: [
      { participant_id: "p1", source_module_id: "validator_runner", record_kind: "check_run", record_id: "cr-1", reported_value: "passed" },
      { participant_id: "p2", source_module_id: "validator_runner", record_kind: "check_run", record_id: "cr-2", reported_value: "failed" },
    ],
  });

  it("labels every conflict unresolved and preserves both reported values", () => {
    render(<BobaValidationConflictList conflicts={[conflict]} />);
    const list = screen.getByLabelText("Validation conflicts");

    expect(within(list).getByText("unresolved")).toBeTruthy();
    expect(within(list).getByText("passed")).toBeTruthy();
    expect(within(list).getByText("failed")).toBeTruthy();
  });

  it("says nothing was selected, merged, averaged or root-caused", () => {
    render(<BobaValidationConflictList conflicts={[conflict]} />);
    const note = screen.getByText(/Both values are preserved/);

    expect(note.textContent).toContain("No result was selected as best");
    expect(note.textContent).toContain("no root cause or repair is inferred");
  });

  it("reports an empty conflict set without implying agreement is a pass", () => {
    render(<BobaValidationConflictList conflicts={[]} />);

    expect(screen.getByText(/No conflicts were detected/)).toBeTruthy();
    expect(screen.queryByLabelText("Validation conflicts")).toBeNull();
  });
});

describe("evidence presentation is honest about availability", () => {
  it("says absent evidence is not a pass when there is none", () => {
    render(<BobaValidationEvidenceList evidence={[]} />);

    expect(screen.getByText(/Absent evidence is not treated as a pass/)).toBeTruthy();
  });

  it("shows what a reference supports and whether it is stale", () => {
    render(
      <BobaValidationEvidenceList
        evidence={[
          parseEvidence({
            evidence_ref_id: "ev-1",
            validator_id: "v-schema",
            origin: "validator_runner",
            reliability: "observed",
            evidence_digest: "b".repeat(64),
            supports_pass: false,
            supports_failure: true,
            stale: true,
          }),
        ]}
      />,
    );
    const row = screen.getByRole("listitem");

    expect(row.textContent).toContain("supports failure");
    expect(row.textContent).toContain("stale");
    expect(row.textContent).not.toContain("supports pass");
  });
});

describe("report cards keep bodies with their owner and never over-claim integrity", () => {
  const card = (over: Record<string, unknown> = {}) =>
    parseReportCard({
      report_card_id: "rc-1",
      report_document_id: "rdoc-1",
      report_status: "read",
      content_digest: "d".repeat(64),
      expected_digest_match: true,
      integrity_verified: true,
      schema_supported: true,
      ...over,
    });

  it("does not claim integrity for a digest mismatch", () => {
    render(
      <BobaValidationReportCardView
        card={card({
          report_document_id: "rdoc-bad",
          report_status: "malformed",
          expected_digest_match: false,
          integrity_verified: false,
          malformed: true,
        })}
        onSelect={() => {}}
        selected={false}
      />,
    );

    expect(screen.queryByText("Digest verified")).toBeNull();
    // Every distinct problem is named rather than collapsed into one label.
    const problems = screen.getByText(/^Problems:/);
    expect(problems.textContent).toContain("Malformed");
    expect(problems.textContent).toContain("Digest mismatch");
  });

  it("reports integrity only when the digest actually matched", () => {
    render(<BobaValidationReportCardView card={card()} onSelect={() => {}} selected={false} />);

    expect(screen.getByText("Digest verified")).toBeTruthy();
    expect(screen.queryByText(/^Problems:/)).toBeNull();
  });

  it("asks for the owner's report body rather than holding one", async () => {
    const chosen: string[] = [];
    render(
      <BobaValidationReportCardView
        card={card()}
        onSelect={(id) => chosen.push(id)}
        selected={false}
      />,
    );
    const toggle = screen.getByRole("button", { name: "View report details" });

    expect(toggle.getAttribute("aria-pressed")).toBe("false");
    await userEvent.click(toggle);

    expect(chosen).toEqual(["rdoc-1"]);
  });

  it("reflects the selected state in its toggle", () => {
    render(<BobaValidationReportCardView card={card()} onSelect={() => {}} selected />);
    const toggle = screen.getByRole("button", { name: "Hide report details" });

    expect(toggle.getAttribute("aria-pressed")).toBe("true");
  });

  it("attributes the report to the producer and read run that made it", () => {
    render(
      <BobaValidationReportCardView
        card={card({
          lineage_producer_module_id: "output_quality_reviewer",
          lineage_read_run_id: "rrun-7",
        })}
        onSelect={() => {}}
        selected={false}
      />,
    );
    const lineage = screen.getByText(/^Lineage:/);

    expect(lineage.textContent).toContain("output quality reviewer");
    expect(lineage.textContent).toContain("rrun-7");
  });

  it("claims no lineage when the owner recorded no read run", () => {
    render(<BobaValidationReportCardView card={card()} onSelect={() => {}} selected={false} />);

    expect(screen.queryByText(/^Lineage:/)).toBeNull();
  });
});

describe("decorative state glyphs are hidden from assistive technology", () => {
  it("hides the strip glyphs and keeps the text label readable", () => {
    render(<BobaValidationStateStrip counts={{ PASS: 1, FAIL: 1 }} />);
    const strip = screen.getByLabelText("Validation state totals");
    const hidden = strip.querySelectorAll("[aria-hidden]");

    // One decorative glyph per state, none of them announced.
    expect(hidden.length).toBe(MATRIX_STATES.length);
    for (const node of Array.from(hidden)) {
      expect(node.textContent?.trim()).not.toBe("");
    }
    // The meaning is still available as text.
    expect(within(strip).getByText("Passed")).toBeTruthy();
  });

  it("hides the per-check glyph but not its status label", () => {
    render(<BobaValidationMatrixTable cells={[cell()]} />);
    const row = screen.getByRole("listitem");

    expect(row.querySelectorAll("[aria-hidden]").length).toBeGreaterThanOrEqual(1);
    expect(within(row).getByText("Passed")).toBeTruthy();
  });
});

describe("a crash is reported as a failure to display, never as a pass", () => {
  it("shows an alert and states that nothing ran or changed", () => {
    const Boom = (): never => {
      throw new Error("render failure");
    };
    // React logs the caught error; silence it so the run stays readable.
    const consoleError = console.error;
    console.error = () => {};
    try {
      render(
        <BobaValidationReportsErrorBoundary>
          <Boom />
        </BobaValidationReportsErrorBoundary>,
      );
    } finally {
      console.error = consoleError;
    }
    const alert = screen.getByRole("alert");

    expect(alert.textContent).toContain("could not be displayed");
    expect(alert.textContent).toContain("No validation ran and no report changed");
    // Critically, a display failure must not read as success.
    expect(alert.textContent).not.toContain("Passed");
    expect(alert.textContent?.toLowerCase()).not.toContain("production ready");
  });

  it("renders its children untouched when nothing fails", () => {
    render(
      <BobaValidationReportsErrorBoundary>
        <BobaValidationStateStrip counts={{ PASS: 1 }} />
      </BobaValidationReportsErrorBoundary>,
    );

    expect(screen.getByLabelText("Validation state totals")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
