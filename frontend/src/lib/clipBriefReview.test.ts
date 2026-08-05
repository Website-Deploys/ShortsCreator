import { describe, expect, it } from "vitest";

import {
  COMPLETENESS_NOTICE,
  LOCAL_ANNOTATION_NOTICE,
  MAX_ANNOTATIONS,
  MAX_ANNOTATION_LENGTH,
  MAX_COMPARISON_BRIEFS,
  MAX_PREVIEW_CONTEXT_SECONDS,
  NO_AUTHORITATIVE_ACTION_NOTICE,
  NO_WINNER_NOTICE,
  QUEUE_PAGE_SIZE,
  SUPPORTED_BRIEF_SCHEMA_ID,
  availableActions,
  briefStateLabel,
  buildAnnotation,
  buildClipBriefPreview,
  canCompare,
  canSubmitAction,
  comparisonDifferences,
  comparisonMissingFields,
  completenessGlyph,
  completenessLabel,
  completenessNotice,
  conflictResolutionLabel,
  conflictSummary,
  describeSourceCard,
  evidenceSummary,
  fieldDisplayValue,
  fieldStateGlyph,
  fieldStateLabel,
  filterBriefs,
  formatDuration,
  formatSourceWindow,
  formatTimecode,
  isSectionExpanded,
  missingFieldSummary,
  priorityLabel,
  receiptChangedAuthority,
  receiptSummary,
  removeAnnotation,
  requiredBadge,
  revisionNotice,
  sectionSummary,
  sortBriefs,
  toggleComparison,
  unavailableActionNotice,
  unsupportedSchemaNotice,
  upsertAnnotation,
  validateActionReason,
  withheldActions,
  type ClipBriefActionDescriptor,
  type ClipBriefActionReceipt,
  type ClipBriefComparison,
  type ClipBriefCompleteness,
  type ClipBriefConflict,
  type ClipBriefFieldProjection,
  type ClipBriefQueueItem,
  type ClipBriefReference,
  type ClipBriefSectionProjection,
  type ClipBriefSnapshot,
  type ClipBriefSourceCard,
} from "@/lib/clipBriefReview";

const FEEDBACK = "clip_brief_action_submit_feedback_v1";
const NOTE = "clip_brief_action_record_review_note_v1";

function item(overrides: Partial<ClipBriefQueueItem> = {}): ClipBriefQueueItem {
  return {
    brief_queue_item_id: "queue_a",
    brief_reference_id: "ref_a",
    project_id: "proj",
    candidate_id: "cand_a",
    clip_id: "cand_a",
    brief_id: "brief_a",
    title: "Brief brief_a",
    bounded_summary: "The exact clip angle.",
    owner_module_id: "clip_brief",
    original_status: "selected",
    candidate_status: "shortlisted",
    editorial_status: "selected",
    completeness_status: "complete_with_optional_gaps",
    evidence_status: "incomplete",
    start_seconds: 10,
    end_seconds: 40,
    duration_seconds: 30,
    candidate_rank: 1,
    current: true,
    stale: false,
    historical: false,
    superseded: false,
    human_action_required: false,
    blocker_count: 0,
    warning_count: 0,
    missing_required_field_count: 0,
    missing_optional_field_count: 2,
    missing_evidence_count: 6,
    conflict_count: 0,
    available_action_descriptor_ids: [FEEDBACK, NOTE],
    source_module_ids: ["clip_brief"],
    priority_tier: 50,
    priority_reason: "missing_required_source_evidence",
    deterministic_sort_key: "050:0001:0000:000000010.000:brief_a",
    warnings: [],
    limitations: [],
    ...overrides,
  };
}

function field(overrides: Partial<ClipBriefFieldProjection> = {}): ClipBriefFieldProjection {
  return {
    field_projection_id: "field_a",
    field_path: "brief_title",
    field_display_name: "Brief title",
    field_category: "overview",
    original_value: "Brief brief_a",
    value_type: "string",
    required_by_owner_schema: true,
    present: true,
    empty: false,
    unavailable: false,
    truncated_for_display: false,
    source_owned: true,
    advisory: false,
    human_editable: false,
    bounded_explanation: "Brief title was supplied by the owner.",
    limitations: [],
    ...overrides,
  };
}

function section(
  overrides: Partial<ClipBriefSectionProjection> = {},
): ClipBriefSectionProjection {
  return {
    section_projection_id: "section_a",
    section_id: "overview",
    title: "Brief Overview",
    field_projection_ids: ["field_a"],
    visible: true,
    empty: false,
    unavailable: false,
    required_field_count: 6,
    present_required_field_count: 6,
    optional_field_count: 0,
    present_optional_field_count: 0,
    warning_count: 0,
    collapsed_by_default: false,
    bounded_empty_message: "The owner persisted no usable value for this section.",
    bounded_unavailable_message: "The owner schema defines no field for this section.",
    ...overrides,
  };
}

function completeness(
  overrides: Partial<ClipBriefCompleteness> = {},
): ClipBriefCompleteness {
  return {
    completeness_record_id: "completeness_a",
    owner_schema_id: SUPPORTED_BRIEF_SCHEMA_ID,
    required_field_paths: ["brief_title", "final_clip_angle"],
    present_required_field_paths: ["brief_title", "final_clip_angle"],
    missing_required_field_paths: [],
    optional_field_paths: ["warnings"],
    present_optional_field_paths: [],
    missing_optional_field_paths: ["warnings"],
    required_field_count: 2,
    present_required_field_count: 2,
    optional_field_count: 1,
    present_optional_field_count: 0,
    required_completion_ratio: 1,
    optional_completion_ratio: 0,
    completeness_status: "complete_with_optional_gaps",
    complete_for_owner_schema: true,
    blocking_reasons: [],
    ...overrides,
  };
}

function reference(overrides: Partial<ClipBriefReference> = {}): ClipBriefReference {
  return {
    brief_reference_id: "ref_a",
    project_id: "proj",
    candidate_id: "cand_a",
    clip_id: "cand_a",
    brief_id: "brief_a",
    brief_revision_id: null,
    brief_schema_id: SUPPORTED_BRIEF_SCHEMA_ID,
    schema_supported: true,
    lifecycle_bucket: "selected",
    start_seconds: 10,
    end_seconds: 40,
    duration_seconds: 30,
    current: true,
    stale: false,
    historical: false,
    superseded: false,
    superseding_brief_id: null,
    warnings: [],
    limitations: [],
    ...overrides,
  };
}

function descriptor(
  overrides: Partial<ClipBriefActionDescriptor> = {},
): ClipBriefActionDescriptor {
  return {
    action_descriptor_id: FEEDBACK,
    display_name: "Submit clip brief feedback",
    action_class: "advisory_creator_feedback",
    owning_module_id: "creator_learning",
    owning_operation_id: "record_creator_feedback_event",
    supported_brief_states: ["current"],
    allowed_decision_values: ["approved", "rejected"],
    requires_reason: true,
    maximum_reason_length: 500,
    requires_confirmation: true,
    requires_current_snapshot: true,
    requires_reviewer_context: true,
    authoritative: false,
    destructive: false,
    execution_capable: false,
    upload_or_publication: false,
    allowed_in_v1: true,
    availability: "available",
    consequences: ["Records a reversible creator-feedback event."],
    does_not_do: ["Does not approve or reject the clip brief."],
    warnings: [],
    limitations: [],
    ...overrides,
  };
}

function snapshot(overrides: Partial<ClipBriefSnapshot> = {}): ClipBriefSnapshot {
  return {
    brief_snapshot_id: "snapshot_a",
    clip_brief_review_session_id: "session_a",
    project_id: "proj",
    candidate_id: "cand_a",
    clip_id: "cand_a",
    brief_id: "brief_a",
    brief_digest: "a".repeat(64),
    snapshot_digest: "b".repeat(64),
    brief_status: "selected",
    candidate_status: "shortlisted",
    editorial_status: "selected",
    rights_status: "unavailable",
    workflow_status: "unavailable",
    human_review_status: "no_pending_review",
    current: true,
    stale: false,
    historical: false,
    superseded: false,
    missing_required_field_count: 0,
    missing_optional_field_count: 2,
    missing_evidence_count: 6,
    conflict_count: 0,
    available_action_descriptor_ids: [FEEDBACK, NOTE],
    limitations: [],
    ...overrides,
  };
}

function receipt(overrides: Partial<ClipBriefActionReceipt> = {}): ClipBriefActionReceipt {
  return {
    clip_brief_action_receipt_id: "receipt_a",
    owning_module_id: "creator_learning",
    owning_operation_id: "record_creator_feedback_event",
    accepted_by_owner: true,
    canonical_status: "approved",
    canonical_record_id: "creator_feedback_1",
    canonical_record_digest: "c".repeat(64),
    authoritative_state_changed: false,
    stale_state_rejected: false,
    duplicate_request_reused: false,
    error_code: null,
    bounded_error_message: "",
    limitations: ["Creator Learning feedback is advisory."],
    ...overrides,
  };
}

function conflict(overrides: Partial<ClipBriefConflict> = {}): ClipBriefConflict {
  return {
    conflict_record_id: "conflict_a",
    conflict_type: "source_window_conflict",
    severity: "critical",
    brief_field_paths: ["source_window.start_seconds"],
    source_card_ids: [],
    source_record_ids: [],
    value_a: "12.5-44.0",
    value_b: "10.0-40.0",
    same_candidate: true,
    same_clip: true,
    current_records: true,
    explicit_supersession_found: false,
    resolved: false,
    resolution_source_id: null,
    blocks_review_action: true,
    human_review_required: true,
    bounded_summary: "The brief window differs from the candidate window.",
    warnings: [],
    limitations: ["Conflicts are never resolved by averaging confidence."],
    ...overrides,
  };
}

function comparison(overrides: Partial<ClipBriefComparison> = {}): ClipBriefComparison {
  return {
    comparison_id: "cmp_a",
    brief_ids: ["brief_a", "brief_b"],
    candidate_ids: ["cand_a", "cand_b"],
    comparison_type: "side_by_side",
    same_candidate: false,
    same_clip: false,
    field_comparisons: [
      {
        field_path: "brief_title",
        field_display_name: "Brief title",
        required_by_owner_schema: true,
        values: [
          { brief_id: "brief_a", present: true, original_value: "Brief brief_a" },
          { brief_id: "brief_b", present: true, original_value: "Brief brief_b" },
        ],
      },
      {
        field_path: "production_priority",
        field_display_name: "Production priority",
        required_by_owner_schema: true,
        values: [
          { brief_id: "brief_a", present: true, original_value: "high" },
          { brief_id: "brief_b", present: true, original_value: "high" },
        ],
      },
      {
        field_path: "warnings",
        field_display_name: "Warnings",
        required_by_owner_schema: false,
        values: [
          { brief_id: "brief_a", present: false, original_value: null },
          { brief_id: "brief_b", present: true, original_value: ["check audio"] },
        ],
      },
    ],
    limitations: ["Completeness is not a quality comparison."],
    ...overrides,
  };
}

function sourceCard(overrides: Partial<ClipBriefSourceCard> = {}): ClipBriefSourceCard {
  return {
    source_card_id: "card_a",
    source_module_id: "clip_brief",
    authority_domain: "clip_brief",
    title: "Clip Brief Generator",
    original_status: "selected",
    original_decision: null,
    bounded_summary: "The owner persisted this brief in the selected bucket.",
    easy_explanation: "Clip Brief Generator reports selected.",
    current: true,
    authoritative: true,
    advisory_only: false,
    blocking: false,
    human_review_required: false,
    warnings: [],
    limitations: [],
    ...overrides,
  };
}

describe("bounds and notices", () => {
  it("pins the comparison ceiling to four briefs", () => {
    expect(MAX_COMPARISON_BRIEFS).toBe(4);
  });

  it("pins the queue page size", () => {
    expect(QUEUE_PAGE_SIZE).toBe(50);
  });

  it("pins the annotation bounds", () => {
    expect(MAX_ANNOTATION_LENGTH).toBe(4_000);
    expect(MAX_ANNOTATIONS).toBe(32);
  });

  it("pins the preview context ceiling", () => {
    expect(MAX_PREVIEW_CONTEXT_SECONDS).toBe(60);
  });

  it("names the supported owner schema exactly", () => {
    expect(SUPPORTED_BRIEF_SCHEMA_ID).toBe("boba_clip_brief_generator_v1");
  });

  it("states that completeness is only field presence", () => {
    expect(COMPLETENESS_NOTICE).toContain(
      "Completeness means only that required owner-schema fields are present",
    );
  });

  it("denies that completeness means quality or approval", () => {
    expect(COMPLETENESS_NOTICE).toContain("not quality, approval");
  });

  it("uses the exact non-canonical annotation notice", () => {
    expect(LOCAL_ANNOTATION_NOTICE).toBe(
      "Review-session annotation — not part of the canonical clip brief.",
    );
  });

  it("states that comparison chooses no winner", () => {
    expect(NO_WINNER_NOTICE).toContain("No brief is scored, preferred or chosen");
  });

  it("states that no authoritative action exists in V1", () => {
    expect(NO_AUTHORITATIVE_ACTION_NOTICE).toContain(
      "no authoritative brief approval, rejection, revision or regeneration action",
    );
  });
});

describe("formatting", () => {
  it("formats a timecode", () => {
    expect(formatTimecode(75)).toBe("01:15");
  });

  it("formats a source window", () => {
    expect(formatSourceWindow(10, 40)).toBe("00:10 – 00:40");
  });

  it("refuses to invent a timecode for an invalid value", () => {
    expect(formatTimecode(Number.NaN)).toBe("--:--");
    expect(formatTimecode(-5)).toBe("--:--");
  });

  it("formats a short duration with one decimal", () => {
    expect(formatDuration(8.25)).toBe("8.3s");
  });

  it("formats a long duration without decimals", () => {
    expect(formatDuration(30)).toBe("30s");
  });

  it("reports an unknown duration honestly", () => {
    expect(formatDuration(Number.NaN)).toBe("unknown");
  });
});

describe("field presentation", () => {
  it("labels a present field as owner supplied", () => {
    expect(fieldStateLabel(field())).toBe("Supplied by the owner");
  });

  it("labels an advisory field as advisory", () => {
    expect(fieldStateLabel(field({ advisory: true }))).toContain("advisory guidance");
  });

  it("labels an absent field as missing from the brief", () => {
    expect(fieldStateLabel(field({ unavailable: true, present: false }))).toContain(
      "Missing from the persisted brief",
    );
  });

  it("labels an owner-empty field as empty", () => {
    expect(fieldStateLabel(field({ empty: true, present: false }))).toContain(
      "Persisted as empty by the owner",
    );
  });

  it("reports a present glyph state", () => {
    expect(fieldStateGlyph(field())).toBe("present");
  });

  it("reports an absent glyph state", () => {
    expect(fieldStateGlyph(field({ unavailable: true, present: false }))).toBe("absent");
  });

  it("reports an empty glyph state", () => {
    expect(fieldStateGlyph(field({ empty: true, present: false }))).toBe("empty");
  });

  it("marks a required field as required by the owner schema", () => {
    expect(requiredBadge(field())).toBe("Required by owner schema");
  });

  it("marks an optional field as optional", () => {
    expect(requiredBadge(field({ required_by_owner_schema: false }))).toBe("Optional");
  });

  it("shows a string value verbatim", () => {
    expect(fieldDisplayValue(field())).toBe("Brief brief_a");
  });

  it("shows a missing value as missing rather than filling it in", () => {
    expect(fieldDisplayValue(field({ unavailable: true, present: false }))).toBe(
      "— missing —",
    );
  });

  it("shows an owner-empty value as empty", () => {
    expect(fieldDisplayValue(field({ empty: true, present: false }))).toBe("— empty —");
  });

  it("serialises an object value without rewriting it", () => {
    const value = { instruction_type: "hook", summary: "Open on the claim." };
    expect(fieldDisplayValue(field({ original_value: value }))).toContain(
      '"instruction_type": "hook"',
    );
  });

  it("reports a null value as not persisted", () => {
    expect(fieldDisplayValue(field({ original_value: null }))).toBe("— not persisted —");
  });
});

describe("sections", () => {
  it("summarises present required and optional counts", () => {
    expect(sectionSummary(section())).toBe("6/6 required, 0/0 optional present");
  });

  it("uses the owner empty message for an empty section", () => {
    expect(sectionSummary(section({ empty: true }))).toContain(
      "no usable value for this section",
    );
  });

  it("uses the unavailable message when the schema defines no field", () => {
    expect(sectionSummary(section({ unavailable: true }))).toContain(
      "defines no field for this section",
    );
  });

  it("expands a section that is not collapsed by default", () => {
    expect(isSectionExpanded(section(), null)).toBe(true);
  });

  it("keeps a collapsed-by-default section collapsed", () => {
    expect(isSectionExpanded(section({ collapsed_by_default: true }), null)).toBe(false);
  });

  it("expands the active section even when collapsed by default", () => {
    const target = section({ section_id: "warnings", collapsed_by_default: true });
    expect(isSectionExpanded(target, "warnings")).toBe(true);
  });
});

describe("completeness", () => {
  it("labels a fully complete brief", () => {
    expect(completenessLabel("complete")).toBe("All owner-schema fields present");
  });

  it("labels optional gaps without implying a problem with quality", () => {
    expect(completenessLabel("complete_with_optional_gaps")).toBe(
      "All required fields present, optional gaps remain",
    );
  });

  it("labels missing required fields", () => {
    expect(completenessLabel("missing_required_fields")).toBe(
      "Required owner-schema fields missing",
    );
  });

  it("labels an unsupported schema", () => {
    expect(completenessLabel("unsupported_schema")).toContain("not supported");
  });

  it("labels a stale projection", () => {
    expect(completenessLabel("stale")).toBe("Projection is stale");
  });

  it("labels an unavailable completeness record", () => {
    expect(completenessLabel("unavailable")).toBe("Completeness unavailable");
  });

  it("maps a complete status to the complete glyph", () => {
    expect(completenessGlyph("complete")).toBe("complete");
  });

  it("maps optional gaps to the partial glyph", () => {
    expect(completenessGlyph("complete_with_optional_gaps")).toBe("partial");
  });

  it("maps missing required fields to the incomplete glyph", () => {
    expect(completenessGlyph("missing_required_fields")).toBe("incomplete");
  });

  it("always carries the completeness notice", () => {
    expect(completenessNotice(completeness())).toContain(COMPLETENESS_NOTICE);
  });

  it("counts blocking reasons in the notice", () => {
    const record = completeness({ blocking_reasons: ["Missing required owner field: x"] });
    expect(completenessNotice(record)).toContain("1 required field(s) missing");
  });

  it("returns the notice even without a record", () => {
    expect(completenessNotice(null)).toBe(COMPLETENESS_NOTICE);
  });

  it("reports no missing required field when none is missing", () => {
    expect(missingFieldSummary(completeness())).toBe(
      "No required owner-schema field is missing.",
    );
  });

  it("names each missing required field", () => {
    const record = completeness({ missing_required_field_paths: ["brief_title"] });
    expect(missingFieldSummary(record)).toBe("Missing required fields: brief_title");
  });

  it("reports an absent completeness record honestly", () => {
    expect(missingFieldSummary(null)).toBe("No completeness record is available.");
  });
});

describe("queue filtering", () => {
  const rows = [
    item(),
    item({
      brief_id: "brief_b",
      brief_queue_item_id: "queue_b",
      editorial_status: "rejected",
      human_action_required: true,
      conflict_count: 1,
      missing_required_field_count: 1,
      warning_count: 2,
      stale: true,
      completeness_status: "missing_required_fields",
    }),
    item({
      brief_id: "brief_c",
      brief_queue_item_id: "queue_c",
      historical: true,
      superseded: true,
      editorial_status: "rejected",
    }),
  ];

  it("hides historical briefs by default", () => {
    const result = filterBriefs(rows, { filter: "all_current", showHistorical: false });
    expect(result.map((row) => row.brief_id)).toEqual(["brief_a", "brief_b"]);
  });

  it("includes historical briefs when asked", () => {
    const result = filterBriefs(rows, { filter: "all_current", showHistorical: true });
    expect(result).toHaveLength(3);
  });

  it("filters to briefs needing human review", () => {
    const result = filterBriefs(rows, {
      filter: "human_review_required",
      showHistorical: false,
    });
    expect(result.map((row) => row.brief_id)).toEqual(["brief_b"]);
  });

  it("filters to the selected candidate's briefs", () => {
    const result = filterBriefs(rows, {
      filter: "current_selected_candidate",
      showHistorical: false,
    });
    expect(result.map((row) => row.brief_id)).toEqual(["brief_a"]);
  });

  it("filters to briefs missing required fields", () => {
    const result = filterBriefs(rows, {
      filter: "missing_required_fields",
      showHistorical: false,
    });
    expect(result.map((row) => row.brief_id)).toEqual(["brief_b"]);
  });

  it("filters to briefs missing evidence", () => {
    const result = filterBriefs(rows, {
      filter: "missing_evidence",
      showHistorical: false,
    });
    expect(result).toHaveLength(2);
  });

  it("filters to briefs with conflicts", () => {
    const result = filterBriefs(rows, { filter: "conflicts", showHistorical: false });
    expect(result.map((row) => row.brief_id)).toEqual(["brief_b"]);
  });

  it("filters to stale briefs", () => {
    const result = filterBriefs(rows, { filter: "stale", showHistorical: false });
    expect(result.map((row) => row.brief_id)).toEqual(["brief_b"]);
  });

  it("filters to briefs complete for the owner schema", () => {
    const result = filterBriefs(rows, {
      filter: "complete_for_owner_schema",
      showHistorical: false,
    });
    expect(result.map((row) => row.brief_id)).toEqual(["brief_a"]);
  });

  it("filters to briefs with warnings", () => {
    const result = filterBriefs(rows, { filter: "warnings", showHistorical: false });
    expect(result.map((row) => row.brief_id)).toEqual(["brief_b"]);
  });

  it("filters to historical briefs regardless of the toggle", () => {
    const result = filterBriefs(rows, { filter: "historical", showHistorical: false });
    expect(result.map((row) => row.brief_id)).toEqual(["brief_c"]);
  });

  it("filters to superseded briefs", () => {
    const result = filterBriefs(rows, { filter: "superseded", showHistorical: false });
    expect(result.map((row) => row.brief_id)).toEqual(["brief_c"]);
  });
});

describe("queue sorting", () => {
  const rows = [
    item({ brief_id: "brief_b", priority_tier: 90, deterministic_sort_key: "090:b", candidate_rank: 2 }),
    item({ brief_id: "brief_a", priority_tier: 40, deterministic_sort_key: "040:a", candidate_rank: 1 }),
    item({ brief_id: "brief_c", priority_tier: 90, deterministic_sort_key: "090:a", candidate_rank: null }),
  ];

  it("sorts by review priority tier then deterministic key", () => {
    const result = sortBriefs(rows, "review_priority");
    expect(result.map((row) => row.brief_id)).toEqual(["brief_a", "brief_c", "brief_b"]);
  });

  it("sorts by the source-owned candidate rank", () => {
    const result = sortBriefs(rows, "candidate_rank");
    expect(result.map((row) => row.brief_id)).toEqual(["brief_a", "brief_b", "brief_c"]);
  });

  it("places briefs without an owner rank last rather than inventing one", () => {
    const result = sortBriefs(rows, "candidate_rank");
    expect(result[result.length - 1].candidate_rank).toBeNull();
  });

  it("sorts by created sequence deterministically", () => {
    const result = sortBriefs(rows, "created_sequence");
    expect(result.map((row) => row.brief_id)).toEqual(["brief_a", "brief_c", "brief_b"]);
  });

  it("sorts by source start time deterministically", () => {
    const result = sortBriefs(rows, "source_start_time");
    expect(result.map((row) => row.brief_id)).toEqual(["brief_a", "brief_c", "brief_b"]);
  });

  it("sorts by brief id", () => {
    const result = sortBriefs(rows, "brief_id");
    expect(result.map((row) => row.brief_id)).toEqual(["brief_a", "brief_b", "brief_c"]);
  });

  it("never mutates the input order", () => {
    const original = rows.map((row) => row.brief_id);
    sortBriefs(rows, "brief_id");
    expect(rows.map((row) => row.brief_id)).toEqual(original);
  });

  it("is stable across repeated calls", () => {
    expect(sortBriefs(rows, "review_priority")).toEqual(
      sortBriefs(rows, "review_priority"),
    );
  });
});

describe("queue labels", () => {
  it("reports the owner priority tier and reason", () => {
    expect(priorityLabel(item())).toBe("Tier 50: missing_required_source_evidence");
  });

  it("labels a current brief", () => {
    expect(briefStateLabel(item())).toBe("Current");
  });

  it("labels a stale brief", () => {
    expect(briefStateLabel(item({ stale: true }))).toBe("Stale");
  });

  it("labels a historical brief", () => {
    expect(briefStateLabel(item({ historical: true }))).toBe("Historical");
  });

  it("labels a superseded brief ahead of other states", () => {
    expect(briefStateLabel(item({ superseded: true, stale: true }))).toBe("Superseded");
  });

  it("says all evidence is present when nothing is missing", () => {
    expect(evidenceSummary(item({ missing_evidence_count: 0 }))).toBe(
      "All linked source evidence is present.",
    );
  });

  it("states that missing evidence is not a pass", () => {
    expect(evidenceSummary(item())).toContain("Missing evidence is not a pass");
  });

  it("uses the singular noun for one missing source", () => {
    expect(evidenceSummary(item({ missing_evidence_count: 1 }))).toContain("1 source missing");
  });
});

describe("conflicts", () => {
  it("reports no conflict on a clean brief", () => {
    expect(conflictSummary([])).toBe(
      "No conflict was detected against canonical sources.",
    );
  });

  it("counts blocking conflicts", () => {
    expect(conflictSummary([conflict()])).toContain("1 conflict(s)");
    expect(conflictSummary([conflict()])).toContain("1 blocking");
  });

  it("states that the panel never picks a winner", () => {
    expect(conflictSummary([conflict()])).toContain("never picks a winner");
  });

  it("states that confidence never resolves a conflict", () => {
    expect(conflictSummary([conflict()])).toContain("comparing confidence");
  });

  it("labels an unresolved conflict as unresolved", () => {
    expect(conflictResolutionLabel(conflict())).toBe(
      "Unresolved. Only the owning module can resolve this.",
    );
  });

  it("names the owning module when it resolved the conflict", () => {
    const resolved = conflict({ resolved: true, resolution_source_id: "editorial_decision" });
    expect(conflictResolutionLabel(resolved)).toBe("Resolved by editorial_decision.");
  });
});

describe("comparison", () => {
  it("adds a brief up to the ceiling", () => {
    expect(toggleComparison(["brief_a"], "brief_b")).toEqual(["brief_a", "brief_b"]);
  });

  it("removes a brief that is already selected", () => {
    expect(toggleComparison(["brief_a", "brief_b"], "brief_a")).toEqual(["brief_b"]);
  });

  it("refuses to exceed the comparison ceiling", () => {
    const full = ["a", "b", "c", "d"];
    expect(toggleComparison(full, "e")).toEqual(full);
  });

  it("requires at least two briefs to compare", () => {
    expect(canCompare(["brief_a"])).toBe(false);
    expect(canCompare(["brief_a", "brief_b"])).toBe(true);
  });

  it("refuses to compare more than four briefs", () => {
    expect(canCompare(["a", "b", "c", "d", "e"])).toBe(false);
  });

  it("shows only differing fields when asked", () => {
    const rows = comparisonDifferences(comparison());
    expect(rows.map((row) => row.field_path)).toEqual(["brief_title", "warnings"]);
  });

  it("treats a missing value as different from a present one", () => {
    const rows = comparisonDifferences(comparison());
    expect(rows.some((row) => row.field_path === "warnings")).toBe(true);
  });

  it("lists fields missing from at least one brief", () => {
    expect(comparisonMissingFields(comparison())).toEqual(["warnings"]);
  });

  it("returns nothing without a comparison record", () => {
    expect(comparisonDifferences(null)).toEqual([]);
    expect(comparisonMissingFields(null)).toEqual([]);
  });
});

describe("preview", () => {
  it("builds a same-origin protected preview URL", () => {
    const preview = buildClipBriefPreview("proj_a", reference());
    expect(preview.url).toContain("/projects/proj_a/source");
    expect(preview.unavailableReason).toBeNull();
  });

  it("publishes the exact persisted window", () => {
    const preview = buildClipBriefPreview("proj_a", reference());
    expect(preview.startSeconds).toBe(10);
    expect(preview.endSeconds).toBe(40);
  });

  it("refuses an external URL as a project reference", () => {
    expect(buildClipBriefPreview("https://evil.example/x", reference()).url).toBeNull();
  });

  it("refuses an absolute path as a project reference", () => {
    expect(buildClipBriefPreview("/etc/passwd", reference()).url).toBeNull();
  });

  it("refuses a file URI as a project reference", () => {
    expect(buildClipBriefPreview("file:///etc/passwd", reference()).url).toBeNull();
  });

  it("refuses path traversal in a project reference", () => {
    expect(buildClipBriefPreview("../../secret", reference()).url).toBeNull();
  });

  it("bounds the context hint", () => {
    const preview = buildClipBriefPreview("proj_a", reference(), 5_000);
    expect(preview.contextStartSeconds).toBe(0);
    expect(preview.contextEndSeconds).toBe(40 + MAX_PREVIEW_CONTEXT_SECONDS);
  });

  it("never lets the context change the persisted boundaries", () => {
    const preview = buildClipBriefPreview("proj_a", reference(), 30);
    expect(preview.startSeconds).toBe(10);
    expect(preview.endSeconds).toBe(40);
  });

  it("labels the context as non-authoritative", () => {
    expect(buildClipBriefPreview("proj_a", reference()).contextNotice).toContain(
      "not authoritative",
    );
  });

  it("states that playback is not validation", () => {
    expect(buildClipBriefPreview("proj_a", reference()).playbackNotice).toContain(
      "not validation and approves nothing",
    );
  });

  it("states why a preview is unavailable", () => {
    const preview = buildClipBriefPreview("https://evil.example/x", reference());
    expect(preview.unavailableReason).toContain("No protected same-origin source");
  });

  it("states when no persisted window is bound", () => {
    expect(buildClipBriefPreview("proj_a", null).unavailableReason).toContain(
      "No exact persisted source window is bound",
    );
  });
});

describe("actions", () => {
  it("offers an action only when the snapshot and the token both allow it", () => {
    const offered = availableActions(
      [descriptor()],
      snapshot(),
      { [FEEDBACK]: "token" },
    );
    expect(offered).toHaveLength(1);
  });

  it("withholds an action without a server-issued token", () => {
    expect(availableActions([descriptor()], snapshot(), {})).toHaveLength(0);
    expect(withheldActions([descriptor()], snapshot(), {})).toHaveLength(1);
  });

  it("withholds an action the snapshot did not offer", () => {
    const offered = availableActions(
      [descriptor()],
      snapshot({ available_action_descriptor_ids: [NOTE] }),
      { [FEEDBACK]: "token" },
    );
    expect(offered).toHaveLength(0);
  });

  it("withholds an unavailable descriptor", () => {
    const offered = availableActions(
      [descriptor({ availability: "unavailable", allowed_in_v1: false })],
      snapshot(),
      { [FEEDBACK]: "token" },
    );
    expect(offered).toHaveLength(0);
  });

  it("withholds every action without a snapshot", () => {
    expect(availableActions([descriptor()], null, { [FEEDBACK]: "t" })).toHaveLength(0);
  });

  it("explains why an unavailable action is unavailable", () => {
    const withheld = descriptor({
      availability: "unavailable",
      allowed_in_v1: false,
      limitations: ["No owning operation records a per-brief approval."],
    });
    expect(unavailableActionNotice(withheld)).toBe(
      "No owning operation records a per-brief approval.",
    );
  });

  it("offers no substitute authority when no reason was stated", () => {
    const withheld = descriptor({ availability: "unavailable", allowed_in_v1: false });
    expect(unavailableActionNotice(withheld)).toContain("No canonical owner operation");
  });

  it("returns no notice for an available action", () => {
    expect(unavailableActionNotice(descriptor())).toBe("");
  });

  it("requires a reason when the owner requires one", () => {
    expect(validateActionReason("   ", descriptor())).toContain("reason is required");
  });

  it("bounds the reason length", () => {
    expect(validateActionReason("x".repeat(501), descriptor())).toContain(
      "500 characters or fewer",
    );
  });

  it("refuses a reason carrying credentials", () => {
    expect(validateActionReason("the api_token is abc", descriptor())).toContain(
      "cannot contain credentials",
    );
  });

  it("accepts a bounded credential-free reason", () => {
    expect(validateActionReason("Reviewed the exact brief.", descriptor())).toBeNull();
  });

  it("blocks submission until the reviewer confirms", () => {
    const ready = canSubmitAction(
      descriptor(),
      snapshot(),
      { [FEEDBACK]: "token" },
      "Reviewed the exact brief.",
      "approved",
      false,
    );
    expect(ready).toBe(false);
  });

  it("allows submission once every requirement is met", () => {
    const ready = canSubmitAction(
      descriptor(),
      snapshot(),
      { [FEEDBACK]: "token" },
      "Reviewed the exact brief.",
      "approved",
      true,
    );
    expect(ready).toBe(true);
  });

  it("refuses a decision value the owner does not allow", () => {
    const ready = canSubmitAction(
      descriptor(),
      snapshot(),
      { [FEEDBACK]: "token" },
      "Reviewed the exact brief.",
      "ship_it",
      true,
    );
    expect(ready).toBe(false);
  });

  it("refuses submission without a snapshot", () => {
    const ready = canSubmitAction(
      descriptor(),
      null,
      { [FEEDBACK]: "token" },
      "Reviewed the exact brief.",
      "approved",
      true,
    );
    expect(ready).toBe(false);
  });
});

describe("receipts", () => {
  it("reports no submission before one is made", () => {
    expect(receiptSummary(null)).toBe("No submission has been made.");
  });

  it("reports a stale-state rejection without implying a change", () => {
    expect(receiptSummary(receipt({ stale_state_rejected: true }))).toContain(
      "No authority changed",
    );
  });

  it("reports an unavailable owner route honestly", () => {
    const outcome = receipt({
      accepted_by_owner: false,
      error_code: "owner_route_unavailable",
    });
    expect(receiptSummary(outcome)).toContain("No canonical owner route exists");
  });

  it("reports an owner refusal without implying a change", () => {
    expect(receiptSummary(receipt({ accepted_by_owner: false }))).toContain(
      "Not accepted by creator_learning",
    );
  });

  it("states that an accepted advisory receipt changed no authority", () => {
    expect(receiptSummary(receipt())).toContain("no authoritative clip brief state changed");
  });

  it("reports an authoritative change only with a record and digest", () => {
    const authoritative = receipt({ authoritative_state_changed: true });
    expect(receiptChangedAuthority(authoritative)).toBe(true);
    expect(receiptSummary(authoritative)).toContain("creator_feedback_1");
  });

  it("denies an authority change without an owner record", () => {
    const forged = receipt({
      authoritative_state_changed: true,
      canonical_record_id: null,
      canonical_record_digest: null,
    });
    expect(receiptChangedAuthority(forged)).toBe(false);
  });

  it("denies an authority change without a receipt", () => {
    expect(receiptChangedAuthority(null)).toBe(false);
  });
});

describe("review-session annotations", () => {
  it("builds an annotation carrying the non-canonical notice", () => {
    const annotation = buildAnnotation("hook_instruction", "Check the hook.");
    expect(annotation?.notice).toBe(LOCAL_ANNOTATION_NOTICE);
  });

  it("bounds the annotation text", () => {
    const annotation = buildAnnotation("hook_instruction", "x".repeat(5_000));
    expect(annotation?.text).toHaveLength(MAX_ANNOTATION_LENGTH);
  });

  it("refuses empty annotation text", () => {
    expect(buildAnnotation("hook_instruction", "   ")).toBeNull();
  });

  it("refuses an annotation carrying credentials", () => {
    expect(buildAnnotation("hook_instruction", "the password is x")).toBeNull();
  });

  it("adds a new annotation", () => {
    const annotation = buildAnnotation("hook_instruction", "Check the hook.")!;
    expect(upsertAnnotation([], annotation)).toHaveLength(1);
  });

  it("replaces an annotation with the same identity", () => {
    const annotation = buildAnnotation("hook_instruction", "Check the hook.")!;
    const updated = { ...annotation, text: "Revised note." };
    const rows = upsertAnnotation([annotation], updated);
    expect(rows).toHaveLength(1);
    expect(rows[0].text).toBe("Revised note.");
  });

  it("refuses to exceed the annotation ceiling", () => {
    const rows = Array.from({ length: MAX_ANNOTATIONS }, (_value, index) => ({
      annotation_id: `annotation_${index}`,
      field_path: "brief_id",
      text: `Note ${index}`,
      notice: LOCAL_ANNOTATION_NOTICE,
    }));
    const extra = buildAnnotation("brief_id", "One too many.")!;
    expect(upsertAnnotation(rows, extra)).toHaveLength(MAX_ANNOTATIONS);
  });

  it("removes an annotation by identity", () => {
    const annotation = buildAnnotation("hook_instruction", "Check the hook.")!;
    expect(removeAnnotation([annotation], annotation.annotation_id)).toEqual([]);
  });
});

describe("source cards and schema support", () => {
  it("describes an available authoritative card", () => {
    expect(describeSourceCard(sourceCard())).toBe("Clip Brief Generator: selected");
  });

  it("marks an advisory card as advisory", () => {
    const card = sourceCard({ advisory_only: true, title: "Creative Director" });
    expect(describeSourceCard(card)).toContain("advisory, not a decision");
  });

  it("states that an unavailable card has no record", () => {
    expect(describeSourceCard(sourceCard({ current: false }))).toContain(
      "no canonical record is available",
    );
  });

  it("returns no schema notice for a supported schema", () => {
    expect(unsupportedSchemaNotice(reference())).toBe("");
  });

  it("states that an unsupported schema is not interpreted", () => {
    const unsupported = reference({
      schema_supported: false,
      brief_schema_id: "boba_clip_brief_v9",
    });
    expect(unsupportedSchemaNotice(unsupported)).toContain("no field is interpreted");
  });

  it("states that the owner records no revision identity", () => {
    expect(revisionNotice(reference())).toContain("records no revision identity");
  });

  it("shows a revision identity only when the owner recorded one", () => {
    expect(revisionNotice(reference({ brief_revision_id: "rev_2" }))).toBe("Revision rev_2.");
  });

  it("returns nothing without a reference", () => {
    expect(revisionNotice(null)).toBe("");
    expect(unsupportedSchemaNotice(null)).toBe("");
  });
});
