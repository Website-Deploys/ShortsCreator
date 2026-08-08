import { describe, expect, it } from "vitest";

import {
  MATRIX_STATES,
  VERDICT_STATES,
  asMatrixState,
  buildStateRows,
  cellsWithoutVerdict,
  dimensionLabel,
  headlineFor,
  isSuccessState,
  isVerdictState,
  orderCells,
  orderConflicts,
  orderReportCards,
  parseBinding,
  parseConflict,
  parseEvidence,
  parseFinding,
  parseMatrix,
  parseMatrixCell,
  parseReportCard,
  parseSummary,
  reportProblemLabels,
  shortDigest,
  staleDimensionLabels,
  stateGlyph,
  stateLabel,
  stateTone,
  type MatrixState,
} from "@/lib/validationReports";

const DIGEST = "a".repeat(64);

function cell(overrides: Record<string, unknown> = {}) {
  return parseMatrixCell({
    cell_id: "cell-1",
    owner_status: "passed",
    owner_fact: true,
    check_run_id: "check-1",
    plan_check_id: "plan-1",
    validator_id: "v-schema",
    validator_version: "1",
    required: true,
    attempt_number: 1,
    result_digest: DIGEST,
    derived_state: "PASS",
    owner_reported_state: "PASS",
    verdict_available: true,
    evidence_present: true,
    ...overrides,
  });
}

describe("the fixed state vocabulary", () => {
  it("keeps all seven states distinct and never collapses them", () => {
    expect(MATRIX_STATES).toEqual([
      "PASS",
      "FAIL",
      "BLOCKED",
      "SKIPPED",
      "NOT_RUN",
      "STALE",
      "MISSING",
    ]);
    expect(new Set(MATRIX_STATES).size).toBe(7);
  });

  it("treats only PASS and FAIL as verdict bearing", () => {
    expect(VERDICT_STATES).toEqual(["PASS", "FAIL"]);
    for (const state of MATRIX_STATES) {
      expect(isVerdictState(state)).toBe(state === "PASS" || state === "FAIL");
    }
  });

  it("treats only PASS as success, so no other state can read as passing", () => {
    for (const state of MATRIX_STATES) {
      expect(isSuccessState(state)).toBe(state === "PASS");
    }
  });

  it("gives every state its own label, glyph and tone", () => {
    const labels = MATRIX_STATES.map(stateLabel);
    const glyphs = MATRIX_STATES.map(stateGlyph);
    const tones = MATRIX_STATES.map(stateTone);
    expect(new Set(labels).size).toBe(7);
    expect(new Set(glyphs).size).toBe(7);
    expect(new Set(tones).size).toBe(7);
    expect(stateLabel("MISSING")).toBe("Missing evidence");
  });

  it("degrades an unknown state to MISSING rather than to a pass", () => {
    expect(asMatrixState("PASSED")).toBe("MISSING");
    expect(asMatrixState(undefined)).toBe("MISSING");
    expect(asMatrixState("brand_new_owner_state")).toBe("MISSING");
    expect(asMatrixState("PASS")).toBe("PASS");
  });
});

describe("the state strip", () => {
  it("always renders all seven states even when counts are absent", () => {
    const rows = buildStateRows({});
    expect(rows).toHaveLength(7);
    expect(rows.map((row) => row.state)).toEqual([...MATRIX_STATES]);
    expect(rows.every((row) => row.total === 0)).toBe(true);
  });

  it("does not let a missing count become a non-zero total", () => {
    const rows = buildStateRows({ PASS: 2, MISSING: -5, FAIL: Number.NaN });
    expect(rows.find((row) => row.state === "PASS")?.total).toBe(2);
    expect(rows.find((row) => row.state === "MISSING")?.total).toBe(0);
    expect(rows.find((row) => row.state === "FAIL")?.total).toBe(0);
  });
});

describe("matrix cell parsing", () => {
  it("preserves the owner status verbatim alongside the derived state", () => {
    const row = cell({ owner_status: "skipped_not_required", derived_state: "SKIPPED" });
    expect(row.owner_status).toBe("skipped_not_required");
    expect(row.derived_state).toBe("SKIPPED");
  });

  it("refuses to believe a verdict on a state that cannot carry one", () => {
    const row = cell({ derived_state: "MISSING", verdict_available: true });
    expect(row.derived_state).toBe("MISSING");
    expect(row.verdict_available).toBe(false);
  });

  it("keeps the owner reported state when staleness overrides presentation", () => {
    const row = cell({
      derived_state: "STALE",
      owner_reported_state: "PASS",
      stale: true,
      stale_reasons: ["artifact_digest"],
      verdict_available: false,
    });
    expect(row.derived_state).toBe("STALE");
    expect(row.owner_reported_state).toBe("PASS");
    expect(row.stale_reasons).toEqual(["artifact_digest"]);
    expect(row.verdict_available).toBe(false);
  });

  it("defaults a malformed cell to MISSING without a verdict", () => {
    const row = parseMatrixCell({});
    expect(row.derived_state).toBe("MISSING");
    expect(row.verdict_available).toBe(false);
    expect(row.evidence_present).toBe(false);
    expect(row.owner_status).toBe("unknown");
  });

  it("orders cells deterministically regardless of input order", () => {
    const rows = [
      cell({ cell_id: "c3", validator_id: "b", plan_check_id: "p1" }),
      cell({ cell_id: "c1", validator_id: "a", plan_check_id: "p2" }),
      cell({ cell_id: "c2", validator_id: "a", plan_check_id: "p1" }),
    ];
    const ordered = orderCells(rows).map((row) => row.cell_id);
    expect(ordered).toEqual(["c2", "c1", "c3"]);
    expect(orderCells([...rows].reverse()).map((row) => row.cell_id)).toEqual(ordered);
  });

  it("counts every cell without a verdict", () => {
    const rows = [
      cell({ cell_id: "a" }),
      cell({ cell_id: "b", derived_state: "MISSING", verdict_available: false }),
      cell({ cell_id: "c", derived_state: "BLOCKED", verdict_available: false }),
    ];
    expect(cellsWithoutVerdict(rows).map((row) => row.cell_id)).toEqual(["b", "c"]);
  });
});

describe("matrix parsing", () => {
  it("normalises counts to all seven states", () => {
    const matrix = parseMatrix({ state_counts: { PASS: 1 }, cells: [] });
    expect(Object.keys(matrix.state_counts).sort()).toEqual([...MATRIX_STATES].sort());
  });

  it("survives a completely empty payload", () => {
    const matrix = parseMatrix(undefined);
    expect(matrix.cells).toEqual([]);
    expect(matrix.required_verdict_complete).toBe(false);
    expect(matrix.evidence_complete).toBe(false);
  });
});

describe("summary parsing", () => {
  it("never reports authorisation, however the payload is shaped", () => {
    const summary = parseSummary({
      production_ready: true,
      output_quality_authorized: true,
      workflow_transition_authorized: true,
      upload_authorized: true,
      publication_authorized: true,
    });
    expect(summary.production_ready).toBe(false);
    expect(summary.output_quality_authorized).toBe(false);
    expect(summary.workflow_transition_authorized).toBe(false);
    expect(summary.upload_authorized).toBe(false);
    expect(summary.publication_authorized).toBe(false);
  });

  it("treats absent evidence information as missing evidence", () => {
    expect(parseSummary({}).evidence_missing).toBe(true);
    expect(parseSummary({ evidence_missing: false }).evidence_missing).toBe(false);
  });
});

describe("the headline", () => {
  const base = parseSummary({
    evidence_missing: false,
    suite_decision: "passed",
    binding: { bound: true, reuse_valid: true },
  });

  it("says nothing exists when no run is bound", () => {
    const summary = parseSummary({ evidence_missing: false });
    expect(headlineFor(summary, 0)).toContain("No validation run exists");
  });

  it("reports missing evidence ahead of any owner pass", () => {
    const summary = parseSummary({
      suite_decision: "passed",
      binding: { bound: true },
    });
    expect(headlineFor(summary, 0)).toBe("Validation evidence is incomplete.");
  });

  it("reports staleness ahead of an owner pass", () => {
    const summary = parseSummary({
      evidence_missing: false,
      stale: true,
      suite_decision: "passed",
      binding: { bound: true },
    });
    expect(headlineFor(summary, 0)).toContain("stale");
  });

  it("reports conflicts ahead of an owner pass", () => {
    expect(headlineFor(base, 2)).toContain("unresolved conflicts");
  });

  it("quotes the owner decision when nothing is wrong", () => {
    expect(headlineFor(base, 0)).toBe("Validator Runner suite decision: passed.");
  });

  it("never claims readiness, approval or safety", () => {
    const outputs = [
      headlineFor(base, 0),
      headlineFor(base, 1),
      headlineFor(parseSummary({ binding: { bound: true } }), 0),
    ];
    for (const line of outputs) {
      expect(line.toLowerCase()).not.toContain("production ready");
      expect(line.toLowerCase()).not.toContain("approved");
      expect(line.toLowerCase()).not.toContain("safe to");
    }
  });
});

describe("staleness binding presentation", () => {
  it("labels every dimension it is given", () => {
    const binding = parseBinding({
      invalidated_dimensions: [
        "project_id",
        "workflow_run_id",
        "stage_instance_id",
        "target_id",
        "workflow_revision",
        "artifact_digest",
        "validator_version",
        "validation_request_id",
      ],
    });
    expect(staleDimensionLabels(binding)).toEqual([
      "Project identity",
      "Workflow run",
      "Workflow stage",
      "Validation target",
      "Workflow revision",
      "Artifact digest",
      "Validator version",
      "Request identity",
    ]);
  });

  it("falls back readably for an unknown dimension", () => {
    expect(dimensionLabel("some_new_dimension")).toBe("some new dimension");
  });
});

describe("report card parsing", () => {
  it("only reports verified integrity when a digest actually matched", () => {
    expect(
      parseReportCard({
        integrity_verified: true,
        content_digest: DIGEST,
        expected_digest_match: true,
      }).integrity_verified,
    ).toBe(true);
    expect(
      parseReportCard({
        integrity_verified: true,
        content_digest: "",
        expected_digest_match: true,
      }).integrity_verified,
    ).toBe(false);
    expect(
      parseReportCard({
        integrity_verified: true,
        content_digest: DIGEST,
        expected_digest_match: false,
      }).integrity_verified,
    ).toBe(false);
  });

  it("never claims a report body is stored locally", () => {
    expect(parseReportCard({ body_stored: true }).body_stored).toBe(false);
  });

  it("names every distinct report problem", () => {
    const card = parseReportCard({
      malformed: true,
      schema_supported: false,
      expected_digest_match: false,
      stale: true,
      truncated: true,
    });
    expect(reportProblemLabels(card)).toEqual([
      "Malformed",
      "Unsupported schema",
      "Digest mismatch",
      "Stale",
      "Truncated",
    ]);
  });

  it("reports no problems for a clean report", () => {
    expect(reportProblemLabels(parseReportCard({ content_digest: DIGEST }))).toEqual([]);
  });

  it("orders report cards deterministically", () => {
    const cards = [
      parseReportCard({ report_document_id: "d2", source_module_id: "b", report_type: "x" }),
      parseReportCard({ report_document_id: "d1", source_module_id: "a", report_type: "y" }),
      parseReportCard({ report_document_id: "d3", source_module_id: "a", report_type: "x" }),
    ];
    expect(orderReportCards(cards).map((row) => row.report_document_id)).toEqual([
      "d3",
      "d1",
      "d2",
    ]);
  });
});

describe("evidence parsing", () => {
  it("never lets unavailable evidence support a pass", () => {
    const row = parseEvidence({ supports_pass: true, available: false });
    expect(row.available).toBe(false);
    expect(row.supports_pass).toBe(false);
  });

  it("keeps an available supporting reference intact", () => {
    const row = parseEvidence({ supports_pass: true, available: true });
    expect(row.supports_pass).toBe(true);
  });

  it("labels unavailable evidence honestly by default", () => {
    expect(parseEvidence({ available: false }).derived_availability_label).toBe(
      "Unavailable evidence reference",
    );
  });
});

describe("conflict parsing", () => {
  it("never presents a conflict as resolved or won", () => {
    const conflict = parseConflict({
      conflict_id: "c1",
      conflict_kind: "check_status_conflict",
      resolved: true,
      winner_selected: true,
      requires_human_interpretation: false,
      distinct_values: ["passed", "failed"],
      participants: [
        { participant_id: "p1", reported_value: "passed" },
        { participant_id: "p2", reported_value: "failed" },
      ],
    });
    expect(conflict.resolved).toBe(false);
    expect(conflict.winner_selected).toBe(false);
    expect(conflict.requires_human_interpretation).toBe(true);
    expect(conflict.distinct_values).toEqual(["passed", "failed"]);
    expect(conflict.participants).toHaveLength(2);
  });

  it("orders conflicts deterministically", () => {
    const conflicts = [
      parseConflict({ conflict_id: "b", conflict_kind: "report_status_conflict" }),
      parseConflict({ conflict_id: "a", conflict_kind: "check_status_conflict" }),
      parseConflict({ conflict_id: "c", conflict_kind: "check_status_conflict" }),
    ];
    expect(orderConflicts(conflicts).map((row) => row.conflict_id)).toEqual([
      "a",
      "c",
      "b",
    ]);
  });
});

describe("finding parsing", () => {
  it("falls back to an honest severity label", () => {
    expect(parseFinding({}).derived_severity_label).toBe("Unclassified finding");
    expect(parseFinding({}).severity).toBe("unknown");
  });
});

describe("digest presentation", () => {
  it("shortens a digest without pretending one exists", () => {
    expect(shortDigest(DIGEST)).toBe("aaaaaaaaaaaa…");
    expect(shortDigest("")).toBe("Not available");
  });
});

describe("state coverage of every owner status the backend can map", () => {
  it("exposes a tone for each state so none renders untyped", () => {
    for (const state of MATRIX_STATES as readonly MatrixState[]) {
      expect(stateTone(state)).toContain("border");
    }
  });
});
