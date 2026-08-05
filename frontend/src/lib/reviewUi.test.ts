import { describe, expect, it } from "vitest";

import {
  MAX_RETAINED_EVENTS,
  STATUS_MATRIX_ROWS,
  buildStatusMatrix,
  categoryLabel,
  classifyReviewError,
  filterQueue,
  isSafePreviewReference,
  isWorkEvent,
  mergeCanonicalEvents,
  protectedPreviewUrl,
  realProgress,
  receiptChangedAuthority,
  receiptSummary,
  reconnectDelayMs,
  sortQueue,
  stateGlyph,
  stateLabel,
  type ReviewActionReceipt,
  type ReviewEvent,
  type ReviewQueueItem,
  type ReviewSourceCard,
} from "@/lib/reviewUi";

function card(overrides: Partial<ReviewSourceCard> = {}): ReviewSourceCard {
  return {
    source_card_id: "card_1",
    source_module_id: "safety_gate",
    authority_domain: "safety",
    source_record_id: "rec_1",
    source_record_digest: "d".repeat(64),
    original_status: "allowed",
    original_decision: "allow",
    title: "Safety Gate",
    bounded_summary: "Safety evaluated the exact action.",
    easy_explanation: "Safety Gate reports allowed.",
    current: true,
    stale: false,
    expired: false,
    invalidated: false,
    superseded: false,
    human_review_required: false,
    blocking: false,
    details_route: "/api/v1/boba/projects/p1/safety-gate",
    warnings: [],
    limitations: [],
    ...overrides,
  };
}

function queueItem(overrides: Partial<ReviewQueueItem> = {}): ReviewQueueItem {
  return {
    queue_item_id: "q1",
    project_id: "p1",
    target_type: "workflow_stage",
    target_id: "t1",
    review_mode: "workflow_review",
    priority: 100,
    display_category: "ready_for_review",
    title: "Workflow Controller",
    bounded_summary: "Stage is ready.",
    source_module_ids: ["workflow_controller"],
    source_record_ids: ["rec"],
    primary_reason: "candidate_or_output_review",
    blocker_count: 0,
    warning_count: 0,
    missing_evidence_count: 0,
    conflict_count: 0,
    human_action_required: false,
    available_action_descriptor_ids: [],
    current: true,
    stale: false,
    historical: false,
    queue_sort_key: "100:workflow_controller:rec",
    updated_at: "2026-08-05T10:00:00+00:00",
    warnings: [],
    limitations: [],
    ...overrides,
  };
}

function event(overrides: Partial<ReviewEvent> = {}): ReviewEvent {
  return {
    ui_event_id: "e1",
    source_module_id: "workflow_controller",
    source_event_id: "src_1",
    source_sequence: 1,
    created_at: "2026-08-05T10:00:00+00:00",
    event_type: "stage_ready",
    severity: "info",
    technical_message: "Stage ready.",
    easy_message: "The stage is ready.",
    confirmed_fact: "No stage ran.",
    assessment: "",
    requires_attention: false,
    canonical: true,
    replayed: false,
    ...overrides,
  };
}

describe("status matrix", () => {
  it("exposes exactly the ten source-owned authority rows", () => {
    expect(STATUS_MATRIX_ROWS).toHaveLength(10);
    expect(STATUS_MATRIX_ROWS.map((row) => row.key)).toEqual([
      "rights",
      "safety",
      "approval",
      "human",
      "workflow",
      "artifacts",
      "validation",
      "quality",
      "recovery",
      "final_decision",
    ]);
  });

  it("never reports a missing owner record as a pass", () => {
    const rows = buildStatusMatrix([]);
    expect(rows).toHaveLength(10);
    for (const row of rows) {
      expect(row.originalStatus).toBe("unavailable");
      expect(row.state).toBe("unavailable");
      expect(row.blocking).toBe(false);
      expect(row.details).toContain("not a pass");
    }
  });

  it("preserves the original status and decision from the owning module", () => {
    const rows = buildStatusMatrix([
      card({ original_status: "blocked_safety_policy", original_decision: "deny", blocking: true }),
    ]);
    const safety = rows.find((row) => row.key === "safety");
    expect(safety?.originalStatus).toBe("blocked_safety_policy");
    expect(safety?.originalDecision).toBe("deny");
    expect(safety?.blocking).toBe(true);
    expect(safety?.sourceModule).toBe("safety_gate");
  });

  it("distinguishes stale, expired and superseded source records", () => {
    expect(buildStatusMatrix([card({ stale: true, current: false })])[1].state).toBe("stale");
    expect(buildStatusMatrix([card({ expired: true })])[1].state).toBe("expired");
    expect(buildStatusMatrix([card({ superseded: true })])[1].state).toBe("superseded");
  });

  it("labels every state with text, not colour alone", () => {
    for (const state of ["current", "stale", "expired", "superseded", "unavailable"] as const) {
      expect(stateLabel(state).length).toBeGreaterThan(0);
      expect(stateGlyph(state)).toMatch(/^\[.+\]$/);
    }
  });
});

describe("review queue", () => {
  it("orders by priority tier then the stable server sort key", () => {
    const items = [
      queueItem({ queue_item_id: "c", priority: 100, queue_sort_key: "100:c" }),
      queueItem({ queue_item_id: "a", priority: 10, queue_sort_key: "010:a" }),
      queueItem({ queue_item_id: "b", priority: 40, queue_sort_key: "040:b" }),
    ];
    expect(sortQueue(items, "priority").map((item) => item.queue_item_id)).toEqual(["a", "b", "c"]);
  });

  it("is deterministic for equal priorities", () => {
    const items = [
      queueItem({ queue_item_id: "z", priority: 40, queue_sort_key: "040:z" }),
      queueItem({ queue_item_id: "y", priority: 40, queue_sort_key: "040:y" }),
    ];
    expect(sortQueue(items, "priority").map((i) => i.queue_item_id)).toEqual(["y", "z"]);
    expect(sortQueue([...items].reverse(), "priority").map((i) => i.queue_item_id)).toEqual([
      "y",
      "z",
    ]);
  });

  it("hides historical records unless explicitly requested", () => {
    const items = [queueItem({ historical: true }), queueItem({ queue_item_id: "q2" })];
    expect(filterQueue(items, {})).toHaveLength(1);
    expect(filterQueue(items, { includeHistorical: true })).toHaveLength(2);
  });

  it("filters by presentation category and free text", () => {
    const items = [
      queueItem({ display_category: "critical_attention", title: "Safety Gate" }),
      queueItem({ queue_item_id: "q2", display_category: "ready_for_review" }),
    ];
    expect(filterQueue(items, { category: "critical_attention" })).toHaveLength(1);
    expect(filterQueue(items, { search: "safety" })).toHaveLength(1);
    expect(filterQueue(items, { search: "nothing-here" })).toHaveLength(0);
  });

  it("labels every category", () => {
    expect(categoryLabel("critical_attention")).toBe("Critical attention");
    expect(categoryLabel("unavailable")).toBe("Unavailable");
  });
});

describe("canonical events", () => {
  it("suppresses duplicates by source identity", () => {
    const merged = mergeCanonicalEvents([event()], [event({ ui_event_id: "e-dup" })]);
    expect(merged).toHaveLength(1);
  });

  it("keeps distinct events from different modules", () => {
    const merged = mergeCanonicalEvents(
      [event()],
      [event({ ui_event_id: "e2", source_module_id: "validator_runner" })],
    );
    expect(merged).toHaveLength(2);
  });

  it("is idempotent across replays", () => {
    const first = mergeCanonicalEvents([], [event(), event({ ui_event_id: "e2", source_event_id: "src_2" })]);
    const second = mergeCanonicalEvents(first, [event({ replayed: true })]);
    expect(second).toHaveLength(2);
  });

  it("bounds retained events to protect browser memory", () => {
    const many = Array.from({ length: MAX_RETAINED_EVENTS + 50 }, (_, index) =>
      event({ ui_event_id: `e${index}`, source_event_id: `src_${index}`, source_sequence: index }),
    );
    expect(mergeCanonicalEvents([], many)).toHaveLength(MAX_RETAINED_EVENTS);
  });

  it("never treats control or heartbeat frames as work", () => {
    for (const type of ["review_stream_open", "review_stream_idle", "heartbeat", "keepalive"]) {
      expect(isWorkEvent({ event_type: type, canonical: true })).toBe(false);
    }
    expect(isWorkEvent({ event_type: "stage_ready", canonical: true })).toBe(true);
    expect(isWorkEvent({ event_type: "stage_ready", canonical: false })).toBe(false);
  });

  it("reports progress only when the owner supplied real counters", () => {
    expect(realProgress(event())).toBeNull();
    expect(realProgress(event({ progress_current: 1, progress_total: 0 }))).toBeNull();
    expect(realProgress(event({ progress_current: 2, progress_total: 4 }))).toBe(50);
    expect(realProgress(event({ progress_current: 9, progress_total: 4 }))).toBe(100);
  });

  it("uses bounded exponential reconnect backoff", () => {
    expect(reconnectDelayMs(0)).toBe(1_000);
    expect(reconnectDelayMs(3)).toBe(8_000);
    expect(reconnectDelayMs(99)).toBe(30_000);
    expect(reconnectDelayMs(-5)).toBe(1_000);
  });
});

describe("protected preview", () => {
  it("accepts only plain project-scoped identifiers", () => {
    expect(isSafePreviewReference("proj_123")).toBe(true);
    expect(isSafePreviewReference("clip-a.1")).toBe(true);
  });

  it("refuses absolute paths, UNC paths, file URIs, traversal and external URLs", () => {
    for (const reference of [
      "C:\\Users\\me\\video.mp4",
      "/etc/passwd",
      "\\\\server\\share\\clip.mp4",
      "file:///tmp/clip.mp4",
      "https://evil.example.com/clip.mp4",
      "//evil.example.com/clip.mp4",
      "../../secret",
    ]) {
      expect(isSafePreviewReference(reference)).toBe(false);
      expect(protectedPreviewUrl("p1", reference)).toBeNull();
    }
  });

  it("treats an absent clip reference as the project source, not an unsafe path", () => {
    expect(isSafePreviewReference("")).toBe(false);
    expect(protectedPreviewUrl("p1", "")).toContain("/projects/p1/source");
    expect(protectedPreviewUrl("p1", null)).toContain("/projects/p1/source");
  });

  it("builds same-origin project-scoped URLs only", () => {
    expect(protectedPreviewUrl("p1")).toContain("/projects/p1/source");
    expect(protectedPreviewUrl("p1", "clip1")).toContain("/projects/p1/rendering/clips/clip1/");
    expect(protectedPreviewUrl("../p1", "clip1")).toBeNull();
  });
});

describe("action receipts", () => {
  function receipt(overrides: Partial<ReviewActionReceipt> = {}): ReviewActionReceipt {
    return {
      action_receipt_id: "r1",
      owning_module_id: "workflow_controller",
      owning_operation_id: "record_human_workflow_decision",
      canonical_record_id: null,
      canonical_record_digest: null,
      canonical_status: "pending",
      accepted_by_owner: false,
      authoritative_state_changed: false,
      canonical_refresh_required: true,
      stale_state_rejected: false,
      duplicate_request_reused: false,
      bounded_error_message: "",
      limitations: [],
      ...overrides,
    };
  }

  it("refuses to claim authority changed without a canonical record and digest", () => {
    expect(receiptChangedAuthority(receipt({ authoritative_state_changed: true }))).toBe(false);
    expect(
      receiptChangedAuthority(
        receipt({ authoritative_state_changed: true, canonical_record_id: "wf_1" }),
      ),
    ).toBe(false);
    expect(
      receiptChangedAuthority(
        receipt({
          authoritative_state_changed: true,
          canonical_record_id: "wf_1",
          canonical_record_digest: "a".repeat(64),
        }),
      ),
    ).toBe(true);
  });

  it("treats a successful submission alone as no authority change", () => {
    const summary = receiptSummary(receipt({ accepted_by_owner: true }));
    expect(summary).toContain("No authoritative state changed");
  });

  it("reports stale rejection without implying success", () => {
    expect(receiptSummary(receipt({ stale_state_rejected: true }))).toContain("No authority changed");
  });

  it("names the owning module when authority did change", () => {
    expect(
      receiptSummary(
        receipt({
          accepted_by_owner: true,
          authoritative_state_changed: true,
          canonical_record_id: "wf_1",
          canonical_record_digest: "a".repeat(64),
        }),
      ),
    ).toContain("workflow_controller recorded wf_1");
  });

  it("reports no submission when there is no receipt", () => {
    expect(receiptSummary(null)).toBe("No submission has been made.");
  });
});

describe("error classification", () => {
  it("distinguishes each failure mode", () => {
    expect(classifyReviewError({ code: "network_error", status: 0 }).kind).toBe("api_unavailable");
    expect(classifyReviewError({ code: "stale_project_snapshot" }).kind).toBe("stale_snapshot");
    expect(classifyReviewError({ code: "workflow_revision_mismatch" }).kind).toBe("stale_snapshot");
    expect(classifyReviewError({ code: "target_digest_mismatch" }).kind).toBe("stale_snapshot");
    expect(classifyReviewError({ code: "http_error", status: 404 }).kind).toBe("target_removed");
    expect(classifyReviewError({ code: "http_error", status: 403 }).kind).toBe("permission_denied");
    expect(classifyReviewError({ code: "action_unavailable" }).kind).toBe("action_unavailable");
    expect(classifyReviewError({ code: "blocked_safety_policy" }).kind).toBe("safety_block");
    expect(classifyReviewError({ code: "unsupported_schema" }).kind).toBe("unsupported_schema");
    expect(classifyReviewError({ code: "stream_disconnected" }).kind).toBe("stream_disconnected");
    expect(classifyReviewError({ code: "preview_unavailable" }).kind).toBe("preview_unavailable");
    expect(classifyReviewError({ code: "malformed_canonical_response" }).kind).toBe(
      "malformed_response",
    );
    expect(classifyReviewError({ code: "http_error", status: 503 }).kind).toBe("api_unavailable");
    expect(classifyReviewError(new Error("boom")).kind).toBe("unexpected");
  });

  it("never leaks stack traces, secrets or absolute paths", () => {
    const leaky = {
      code: "boom",
      status: 500,
      message: 'Traceback: token=sk-abc123 at C:\\Olympus\\src\\secret.py line 5',
    };
    const classified = classifyReviewError(leaky);
    const text = `${classified.title} ${classified.guidance}`;
    expect(text).not.toContain("Traceback");
    expect(text).not.toContain("sk-abc123");
    expect(text).not.toContain("C:\\");
    expect(text).not.toContain("secret.py");
  });

  it("always supplies human guidance", () => {
    for (const code of ["network_error", "action_unavailable", "unknown_thing"]) {
      const classified = classifyReviewError({ code });
      expect(classified.title.length).toBeGreaterThan(0);
      expect(classified.guidance.length).toBeGreaterThan(0);
    }
  });
});
