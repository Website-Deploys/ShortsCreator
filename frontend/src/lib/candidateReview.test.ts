import { describe, expect, it } from "vitest";

import {
  LOCAL_SHORTLIST_NOTICE,
  MAX_COMPARISON_CANDIDATES,
  MAX_TRANSCRIPT_CONTEXT_SECONDS,
  QUEUE_PAGE_SIZE,
  SUBSTANTIAL_OVERLAP_IOU_THRESHOLD,
  availableActions,
  buildCandidatePreview,
  canCompare,
  candidateStateGlyph,
  candidateStateLabel,
  describeRank,
  describeScore,
  editorialStatusLabel,
  evidenceSummary,
  filterCandidates,
  formatDuration,
  formatSourceWindow,
  formatTimecode,
  overlapDescription,
  overlapLabel,
  receiptChangedAuthority,
  receiptSummary,
  sortCandidates,
  toggleComparison,
  toggleLocalShortlist,
  withheldActions,
  type CandidateActionDescriptor,
  type CandidateActionReceipt,
  type CandidateOverlapRecord,
  type CandidateQueueItem,
  type CandidateScoreCard,
  type CandidateSnapshot,
} from "@/lib/candidateReview";

function item(overrides: Partial<CandidateQueueItem> = {}): CandidateQueueItem {
  return {
    candidate_queue_item_id: "q1",
    candidate_reference_id: "r1",
    project_id: "p1",
    candidate_id: "cand_a",
    title: "Candidate cand_a",
    bounded_summary: "Strong hook detected in the transcript.",
    start_seconds: 10,
    end_seconds: 40,
    duration_seconds: 30,
    original_discovery_status: "hook_moment",
    original_rank: 1,
    original_rank_total: 4,
    rank_owner_module_id: "clip_ranking",
    primary_score: 90,
    primary_score_name: "total_score",
    primary_score_owner_module_id: "clip_ranking",
    editorial_status: "selected",
    review_status: "source_selected",
    current: true,
    stale: false,
    historical: false,
    superseded: false,
    rejected: false,
    selected: true,
    human_action_required: false,
    blocker_count: 0,
    warning_count: 0,
    missing_evidence_count: 0,
    conflict_count: 0,
    duplicate_group_id: null,
    overlap_group_ids: [],
    available_action_descriptor_ids: [],
    source_module_ids: ["clip_discovery", "clip_ranking"],
    priority_tier: 60,
    priority_reason: "source_shortlisted_by_editorial_decision",
    deterministic_sort_key: "060:0001:0000000010.000:0000:cand_a",
    warnings: [],
    limitations: [],
    ...overrides,
  };
}

function score(overrides: Partial<CandidateScoreCard> = {}): CandidateScoreCard {
  return {
    score_card_id: "s1",
    candidate_id: "cand_a",
    source_module_id: "clip_ranking",
    score_name: "total_score",
    score_value: 90,
    score_scale_min: 0,
    score_scale_max: 100,
    score_definition: "Clip Ranking total score for this candidate. Scale 0-100.",
    score_direction: "higher_is_better",
    rank: 1,
    rank_total: 4,
    tied: false,
    weight: null,
    source_owned_composite: true,
    comparable_across_candidates: true,
    stale: false,
    limitations: [],
    ...overrides,
  };
}

function overlap(overrides: Partial<CandidateOverlapRecord> = {}): CandidateOverlapRecord {
  return {
    overlap_record_id: "o1",
    candidate_a_id: "cand_a",
    candidate_b_id: "cand_c",
    overlap_seconds: 30,
    union_seconds: 30,
    intersection_over_union: 1,
    candidate_a_coverage: 1,
    candidate_b_coverage: 1,
    exact_duplicate_window: true,
    substantial_overlap: true,
    partial_overlap: false,
    contained: true,
    source_time_overlap_only: true,
    limitations: ["Overlap is time-range overlap only."],
    ...overrides,
  };
}

function descriptor(
  overrides: Partial<CandidateActionDescriptor> = {},
): CandidateActionDescriptor {
  return {
    action_descriptor_id: "candidate_action_submit_feedback_v1",
    display_name: "Submit candidate feedback",
    action_class: "advisory_creator_feedback",
    owning_module_id: "creator_learning",
    owning_operation_id: "record_creator_feedback_event",
    allowed_decision_values: ["approved", "rejected"],
    requires_reason: true,
    maximum_reason_length: 500,
    authoritative: false,
    allowed_in_v1: true,
    availability: "available",
    consequences: ["Records an advisory creator-feedback event."],
    does_not_do: ["Does not select or reject the candidate editorially."],
    limitations: ["Creator Learning feedback is advisory."],
    ...overrides,
  };
}

function snapshot(overrides: Partial<CandidateSnapshot> = {}): CandidateSnapshot {
  return {
    candidate_snapshot_id: "snap1",
    candidate_id: "cand_a",
    project_snapshot_digest: "a".repeat(64),
    workflow_revision: 7,
    candidate_digest: "b".repeat(64),
    available_action_descriptor_ids: ["candidate_action_submit_feedback_v1"],
    confirmation_context_digest: "c".repeat(64),
    snapshot_digest: "d".repeat(64),
    discovery_status: "discovered",
    rank_status: "strong_candidate",
    editorial_status: "selected",
    current: true,
    stale: false,
    selected: true,
    rejected: false,
    missing_evidence_count: 0,
    conflict_count: 0,
    limitations: [],
    ...overrides,
  };
}

function receipt(overrides: Partial<CandidateActionReceipt> = {}): CandidateActionReceipt {
  return {
    candidate_action_receipt_id: "rec1",
    candidate_id: "cand_a",
    owning_module_id: "creator_learning",
    owning_operation_id: "record_creator_feedback_event",
    accepted_by_owner: false,
    canonical_record_id: null,
    canonical_record_digest: null,
    canonical_status: "pending",
    authoritative_state_changed: false,
    stale_state_rejected: false,
    duplicate_request_reused: false,
    error_code: null,
    bounded_error_message: "",
    limitations: [],
    ...overrides,
  };
}

describe("fixed panel bounds", () => {
  it("caps comparison at four candidates", () => {
    expect(MAX_COMPARISON_CANDIDATES).toBe(4);
  });

  it("uses the documented overlap threshold", () => {
    expect(SUBSTANTIAL_OVERLAP_IOU_THRESHOLD).toBe(0.6);
  });

  it("uses a bounded queue page size", () => {
    expect(QUEUE_PAGE_SIZE).toBe(50);
  });

  it("caps transcript context at sixty seconds", () => {
    expect(MAX_TRANSCRIPT_CONTEXT_SECONDS).toBe(60);
  });
});

describe("exact source windows", () => {
  it("formats a whole-second timecode", () => {
    expect(formatTimecode(70)).toBe("01:10");
  });

  it("preserves millisecond precision", () => {
    expect(formatTimecode(12.345)).toBe("00:12.345");
  });

  it("reports unknown for invalid input", () => {
    expect(formatTimecode(-1)).toBe("unknown");
    expect(formatTimecode(Number.NaN)).toBe("unknown");
  });

  it("formats an exact window", () => {
    expect(formatSourceWindow(10, 40)).toBe("00:10 – 00:40");
  });

  it("formats a decimal window without rounding it away", () => {
    expect(formatSourceWindow(12.345, 48.678)).toBe("00:12.345 – 00:48.678");
  });

  it("formats durations exactly", () => {
    expect(formatDuration(30)).toBe("30s");
    expect(formatDuration(36.333)).toBe("36.333s");
  });

  it("reports unknown for a non-positive duration", () => {
    expect(formatDuration(0)).toBe("unknown");
    expect(formatDuration(-5)).toBe("unknown");
  });
});

describe("source-owned rank and score presentation", () => {
  it("names the owning module when describing rank", () => {
    expect(describeRank(item())).toBe("clip_ranking ranked this candidate 1 of 4.");
  });

  it("never invents a rank when the owner has none", () => {
    const text = describeRank(item({ original_rank: null }));
    expect(text).toBe("No source-owned rank is available for this candidate.");
    expect(text).not.toContain("1");
  });

  it("omits the total when the owner did not supply one", () => {
    expect(describeRank(item({ original_rank_total: null }))).toBe(
      "clip_ranking ranked this candidate 1.",
    );
  });

  it("describes a score with owner, value, scale and direction", () => {
    expect(describeScore(score())).toBe(
      "clip_ranking · total_score 90 of 0–100 (higher is better)",
    );
  });

  it("preserves a discovery score's zero-to-one scale", () => {
    const text = describeScore(
      score({
        source_module_id: "clip_discovery",
        score_name: "confidence",
        score_value: 0.81,
        score_scale_min: 0,
        score_scale_max: 1,
      }),
    );
    expect(text).toContain("0.81 of 0–1");
    expect(text).not.toContain("81%");
  });

  it("marks penalty components as lower is better", () => {
    expect(describeScore(score({ score_direction: "lower_is_better" }))).toContain(
      "lower is better",
    );
  });

  it("states when the source did not declare a direction", () => {
    expect(describeScore(score({ score_direction: "unknown" }))).toContain(
      "direction not stated by the source",
    );
  });

  it("never converts a score into a probability or percentage claim", () => {
    const text = describeScore(score());
    expect(text).not.toMatch(/%/);
    expect(text).not.toContain("probability");
    expect(text).not.toContain("viral");
  });
});

describe("status labels", () => {
  it("labels current, stale, historical and superseded distinctly", () => {
    expect(candidateStateLabel(item())).toBe("Current");
    expect(candidateStateLabel(item({ stale: true }))).toBe("Stale");
    expect(candidateStateLabel(item({ historical: true }))).toBe("Historical");
    expect(candidateStateLabel(item({ superseded: true }))).toBe("Superseded");
    expect(candidateStateLabel(item({ current: false }))).toBe("Unavailable");
  });

  it("pairs every state with a text glyph so colour is never the only signal", () => {
    for (const row of [
      item(),
      item({ stale: true }),
      item({ historical: true }),
      item({ superseded: true }),
      item({ current: false }),
    ]) {
      expect(candidateStateGlyph(row)).toMatch(/^\[.+\]$/);
    }
  });

  it("attributes editorial status to Editorial Decision", () => {
    expect(editorialStatusLabel("selected")).toBe("Selected by Editorial Decision");
    expect(editorialStatusLabel("not_selected")).toBe("Not selected by Editorial Decision");
    expect(editorialStatusLabel("rejected")).toBe("Rejected by Editorial Decision");
    expect(editorialStatusLabel("unavailable")).toBe("Editorial Decision unavailable");
  });

  it("falls back to a readable label for an unknown status", () => {
    expect(editorialStatusLabel("some_new_status")).toBe("some new status");
  });
});

describe("evidence completeness", () => {
  it("reports complete evidence", () => {
    expect(evidenceSummary(item())).toBe("All required source evidence is present.");
  });

  it("never turns missing evidence into a pass", () => {
    const text = evidenceSummary(item({ missing_evidence_count: 2 }));
    expect(text).toContain("2 required sources missing");
    expect(text).toContain("not a pass");
  });

  it("uses the singular form for one missing source", () => {
    expect(evidenceSummary(item({ missing_evidence_count: 1 }))).toContain(
      "1 required source missing",
    );
  });
});

describe("queue filtering and sorting", () => {
  it("matches on candidate id, title and summary", () => {
    const rows = [item(), item({ candidate_id: "cand_b", title: "Other", bounded_summary: "x" })];
    expect(filterCandidates(rows, { filter: "all_current", search: "cand_b" })).toHaveLength(1);
    expect(filterCandidates(rows, { filter: "all_current", search: "Other" })).toHaveLength(1);
    expect(filterCandidates(rows, { filter: "all_current", search: "hook" })).toHaveLength(1);
  });

  it("returns everything when the search is empty", () => {
    const rows = [item(), item({ candidate_id: "cand_b" })];
    expect(filterCandidates(rows, { filter: "all_current" })).toHaveLength(2);
    expect(filterCandidates(rows, { filter: "all_current", search: "   " })).toHaveLength(2);
  });

  it("returns nothing for a non-matching search", () => {
    expect(
      filterCandidates([item()], { filter: "all_current", search: "nothing-here" }),
    ).toHaveLength(0);
  });

  it("orders by priority tier then the server sort key", () => {
    const rows = [
      item({ candidate_id: "c", priority_tier: 90, deterministic_sort_key: "090:c" }),
      item({ candidate_id: "a", priority_tier: 10, deterministic_sort_key: "010:a" }),
      item({ candidate_id: "b", priority_tier: 60, deterministic_sort_key: "060:b" }),
    ];
    expect(sortCandidates(rows, "review_priority").map((r) => r.candidate_id)).toEqual([
      "a",
      "b",
      "c",
    ]);
  });

  it("is deterministic for equal tiers regardless of input order", () => {
    const rows = [
      item({ candidate_id: "z", priority_tier: 60, deterministic_sort_key: "060:z" }),
      item({ candidate_id: "y", priority_tier: 60, deterministic_sort_key: "060:y" }),
    ];
    expect(sortCandidates(rows, "review_priority").map((r) => r.candidate_id)).toEqual(["y", "z"]);
    expect(
      sortCandidates([...rows].reverse(), "review_priority").map((r) => r.candidate_id),
    ).toEqual(["y", "z"]);
  });

  it("orders by original rank and sorts unranked candidates last", () => {
    const rows = [
      item({ candidate_id: "c", original_rank: null }),
      item({ candidate_id: "a", original_rank: 1 }),
      item({ candidate_id: "b", original_rank: 2 }),
    ];
    expect(sortCandidates(rows, "original_rank").map((r) => r.candidate_id)).toEqual([
      "a",
      "b",
      "c",
    ]);
  });

  it("orders by candidate id when asked", () => {
    const rows = [item({ candidate_id: "cand_z" }), item({ candidate_id: "cand_a" })];
    expect(sortCandidates(rows, "candidate_id").map((r) => r.candidate_id)).toEqual([
      "cand_a",
      "cand_z",
    ]);
  });

  it("does not mutate the input array", () => {
    const rows = [item({ candidate_id: "b", priority_tier: 90 }), item({ candidate_id: "a" })];
    const before = rows.map((r) => r.candidate_id);
    sortCandidates(rows, "review_priority");
    expect(rows.map((r) => r.candidate_id)).toEqual(before);
  });
});

describe("comparison selection", () => {
  it("adds and removes candidates", () => {
    expect(toggleComparison([], "cand_a")).toEqual(["cand_a"]);
    expect(toggleComparison(["cand_a"], "cand_a")).toEqual([]);
  });

  it("refuses to exceed the fixed limit", () => {
    const full = ["a", "b", "c", "d"];
    expect(toggleComparison(full, "e")).toEqual(full);
  });

  it("still allows removal when full", () => {
    expect(toggleComparison(["a", "b", "c", "d"], "b")).toEqual(["a", "c", "d"]);
  });

  it("requires two to four candidates to compare", () => {
    expect(canCompare([])).toBe(false);
    expect(canCompare(["a"])).toBe(false);
    expect(canCompare(["a", "b"])).toBe(true);
    expect(canCompare(["a", "b", "c", "d"])).toBe(true);
    expect(canCompare(["a", "b", "c", "d", "e"])).toBe(false);
  });
});

describe("local shortlist", () => {
  it("always carries the non-editorial notice", () => {
    expect(LOCAL_SHORTLIST_NOTICE).toContain("not an editorial decision");
  });

  it("toggles membership without touching canonical state", () => {
    expect(toggleLocalShortlist([], "cand_a")).toEqual(["cand_a"]);
    expect(toggleLocalShortlist(["cand_a"], "cand_a")).toEqual([]);
    expect(toggleLocalShortlist(["cand_a"], "cand_b")).toEqual(["cand_a", "cand_b"]);
  });
});

describe("overlap presentation", () => {
  it("labels an exact duplicate window", () => {
    expect(overlapLabel(overlap())).toBe("Exact duplicate window");
  });

  it("labels a substantial overlap", () => {
    expect(
      overlapLabel(overlap({ exact_duplicate_window: false, intersection_over_union: 0.8 })),
    ).toBe("Substantial time overlap");
  });

  it("labels a contained window", () => {
    expect(
      overlapLabel(
        overlap({
          exact_duplicate_window: false,
          substantial_overlap: false,
          contained: true,
        }),
      ),
    ).toBe("Contained window");
  });

  it("labels a partial overlap", () => {
    expect(
      overlapLabel(
        overlap({
          exact_duplicate_window: false,
          substantial_overlap: false,
          contained: false,
          partial_overlap: true,
        }),
      ),
    ).toBe("Partial time overlap");
  });

  it("always disclaims semantic duplication", () => {
    const text = overlapDescription(overlap());
    expect(text).toContain("time-range overlap only");
    expect(text).toContain("not a semantic duplicate");
  });

  it("reports the shared seconds and IoU", () => {
    const text = overlapDescription(overlap({ overlap_seconds: 5, intersection_over_union: 0.09 }));
    expect(text).toContain("5s of shared source time");
    expect(text).toContain("9.0%");
  });
});

describe("protected candidate preview", () => {
  it("builds a same-origin project-scoped URL", () => {
    const preview = buildCandidatePreview("p1", { start_seconds: 10, end_seconds: 40 });
    expect(preview.url).toContain("/projects/p1/source");
    expect(preview.unavailableReason).toBeNull();
  });

  it("refuses an unsafe project reference", () => {
    for (const projectId of ["../p1", "C:\\p1", "file:///p1", "https://evil.example.com"]) {
      const preview = buildCandidatePreview(projectId, { start_seconds: 0, end_seconds: 1 });
      expect(preview.url).toBeNull();
      expect(preview.unavailableReason).toContain("Preview unavailable");
    }
  });

  it("reports unavailable when no candidate window is bound", () => {
    const preview = buildCandidatePreview("p1", null);
    expect(preview.unavailableReason).toContain("No exact candidate window is bound");
  });

  it("exposes the exact candidate window for seeking", () => {
    const preview = buildCandidatePreview("p1", { start_seconds: 12.345, end_seconds: 48.678 });
    expect(preview.startSeconds).toBe(12.345);
    expect(preview.endSeconds).toBe(48.678);
  });

  it("bounds the context window and never goes negative", () => {
    const preview = buildCandidatePreview("p1", { start_seconds: 5, end_seconds: 20 }, 9_999);
    expect(preview.contextStartSeconds).toBe(0);
    expect(preview.contextEndSeconds).toBe(80);
  });

  it("labels context as context only", () => {
    const preview = buildCandidatePreview("p1", { start_seconds: 10, end_seconds: 40 }, 10);
    expect(preview.contextNotice).toBe(
      "Preview context only. This does not change the candidate boundaries.",
    );
  });

  it("never widens the candidate window itself", () => {
    const preview = buildCandidatePreview("p1", { start_seconds: 10, end_seconds: 40 }, 30);
    expect(preview.startSeconds).toBe(10);
    expect(preview.endSeconds).toBe(40);
  });
});

describe("action availability", () => {
  it("offers an action only when snapshot and token both allow it", () => {
    const descriptors = [descriptor()];
    const tokens = { candidate_action_submit_feedback_v1: "t".repeat(64) };
    expect(availableActions(descriptors, snapshot(), tokens)).toHaveLength(1);
    expect(availableActions(descriptors, snapshot(), {})).toHaveLength(0);
    expect(
      availableActions(descriptors, snapshot({ available_action_descriptor_ids: [] }), tokens),
    ).toHaveLength(0);
  });

  it("offers nothing without a snapshot", () => {
    expect(availableActions([descriptor()], null, { x: "y" })).toHaveLength(0);
  });

  it("never offers an unavailable descriptor", () => {
    const unavailable = descriptor({
      action_descriptor_id: "candidate_action_select_candidate_v1",
      availability: "unavailable",
      allowed_in_v1: false,
      authoritative: true,
    });
    const tokens = { candidate_action_select_candidate_v1: "t".repeat(64) };
    const snap = snapshot({
      available_action_descriptor_ids: ["candidate_action_select_candidate_v1"],
    });
    expect(availableActions([unavailable], snap, tokens)).toHaveLength(0);
  });

  it("lists withheld actions so the reviewer sees why", () => {
    const descriptors = [
      descriptor(),
      descriptor({
        action_descriptor_id: "candidate_action_select_candidate_v1",
        availability: "unavailable",
        allowed_in_v1: false,
      }),
    ];
    const tokens = { candidate_action_submit_feedback_v1: "t".repeat(64) };
    const withheld = withheldActions(descriptors, snapshot(), tokens);
    expect(withheld).toHaveLength(1);
    expect(withheld[0].action_descriptor_id).toBe("candidate_action_select_candidate_v1");
  });
});

describe("action receipts", () => {
  it("refuses to claim authority changed without a record and digest", () => {
    expect(receiptChangedAuthority(receipt({ authoritative_state_changed: true }))).toBe(false);
    expect(
      receiptChangedAuthority(
        receipt({ authoritative_state_changed: true, canonical_record_id: "e1" }),
      ),
    ).toBe(false);
    expect(
      receiptChangedAuthority(
        receipt({
          authoritative_state_changed: true,
          canonical_record_id: "e1",
          canonical_record_digest: "a".repeat(64),
        }),
      ),
    ).toBe(true);
  });

  it("reports no submission without a receipt", () => {
    expect(receiptSummary(null)).toBe("No submission has been made.");
  });

  it("reports stale rejection without implying success", () => {
    expect(receiptSummary(receipt({ stale_state_rejected: true }))).toContain(
      "No authority changed",
    );
  });

  it("reports owner refusal without implying success", () => {
    expect(receiptSummary(receipt({ accepted_by_owner: false }))).toContain(
      "Not accepted by creator_learning",
    );
  });

  it("describes an accepted advisory receipt as advisory", () => {
    const text = receiptSummary(
      receipt({ accepted_by_owner: true, canonical_record_id: "creator_feedback_1" }),
    );
    expect(text).toContain("creator_learning recorded creator_feedback_1");
    expect(text).toContain("advisory");
    expect(text).toContain("no authoritative candidate state changed");
  });

  it("names the owner when authority genuinely changed", () => {
    expect(
      receiptSummary(
        receipt({
          accepted_by_owner: true,
          authoritative_state_changed: true,
          canonical_record_id: "e1",
          canonical_record_digest: "a".repeat(64),
        }),
      ),
    ).toBe("creator_learning recorded e1.");
  });
});
