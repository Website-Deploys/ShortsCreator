import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

function source(relative: string) {
  return readFileSync(new URL(relative, import.meta.url), "utf8");
}

const panel = source("./BobaClipBriefReviewPanel.tsx");
const card = source("./BobaClipBriefCard.tsx");
const fields = source("./BobaClipBriefFields.tsx");
const evidence = source("./BobaClipBriefEvidence.tsx");
const preview = source("./BobaClipBriefPreview.tsx");
const comparison = source("./BobaClipBriefComparison.tsx");
const dialog = source("./BobaClipBriefActionDialog.tsx");
const annotations = source("./BobaClipBriefAnnotations.tsx");
const results = source("../project/ResultsSection.tsx");
const clientLogic = readFileSync(
  new URL("../../lib/clipBriefReview.ts", import.meta.url),
  "utf8",
);
const apiClient = readFileSync(
  new URL("../../lib/apiClient.ts", import.meta.url),
  "utf8",
);
const queries = readFileSync(new URL("../../lib/queries.ts", import.meta.url), "utf8");
const components = [
  panel,
  card,
  fields,
  evidence,
  preview,
  comparison,
  dialog,
  annotations,
];
const everything = [...components, clientLogic].join("\n");

/** Collapse whitespace and JSDoc markers so prose assertions survive wrapping. */
const flat = (value: string) =>
  value.replace(/^[ \t]*\*[ \t]?/gm, " ").replace(/\s+/g, " ");
const flatPanel = flat(panel);
const flatFields = flat(fields);
const flatEvidence = flat(evidence);
const flatPreview = flat(preview);
const flatComparison = flat(comparison);
const flatDialog = flat(dialog);
const flatAnnotations = flat(annotations);
const flatLogic = flat(clientLogic);

describe("integration with the existing Review UI", () => {
  it("is mounted from the existing project results route", () => {
    expect(results).toContain("BobaClipBriefReviewPanel");
    expect(results).toContain('from "@/components/review/BobaClipBriefReviewPanel"');
  });

  it("is mounted at every results render site", () => {
    expect(results.split("{clipBriefReviewPanel}").length - 1).toBe(4);
  });

  it("does not replace the global Review UI workspace", () => {
    expect(results).toContain("BobaReviewWorkspace");
    expect(results).toContain("{reviewWorkspace}");
  });

  it("does not replace the Candidate Review Panel", () => {
    expect(results).toContain("{candidateReviewPanel}");
    expect(results).toContain("BobaCandidateReviewPanel");
  });

  it("keeps the existing clip brief generator section intact", () => {
    expect(results).toContain("{clipBriefPanel}");
  });

  it("reuses the Review UI error classifier rather than a new one", () => {
    expect(panel).toContain('from "@/lib/reviewUi"');
    expect(panel).toContain("classifyReviewError");
  });

  it("reuses the Review UI protected preview helper", () => {
    expect(clientLogic).toContain(
      'import { isSafePreviewReference, protectedPreviewUrl } from "@/lib/reviewUi"',
    );
  });

  it("defines no second preview URL builder of its own", () => {
    expect(clientLogic).not.toContain("API_V1");
    expect(clientLogic).not.toContain("http");
  });

  it("declares itself a specialized mode rather than a new panel", () => {
    expect(flatPanel).toContain("A specialized read-only mode of the BOBA Review UI");
  });

  it("declares itself a projection, evidence, comparison and routing layer", () => {
    expect(flatPanel).toContain(
      "clip brief projection, an evidence workspace, a comparison surface and a safe canonical action router",
    );
  });
});

describe("declared boundaries", () => {
  it("states it never generates, regenerates or rewrites a brief", () => {
    expect(flatPanel).toContain("never generates, regenerates or rewrites a brief");
  });

  it("states it never invents a field the owner schema lacks", () => {
    expect(flatPanel).toContain(
      "never invents a field the owner schema does not define",
    );
  });

  it("states it never computes a quality or virality score", () => {
    expect(flatPanel).toContain("never computes a quality or virality score");
  });

  it("states it never chooses a winning brief", () => {
    expect(flatPanel).toContain("never chooses a winning brief");
  });

  it("states it never approves, rejects or optimistically changes brief state", () => {
    expect(flatPanel).toContain(
      "never approves, rejects or optimistically changes brief state",
    );
  });

  it("repeats the boundary in the rendered footer, not only in a comment", () => {
    expect(panel).toContain(
      "This panel does not generate, regenerate or rewrite a clip brief",
    );
  });

  it("renders the completeness boundary to the reviewer", () => {
    expect(panel).toContain(
      "Completeness means only that required owner-schema fields are present",
    );
    expect(panel).toContain("not quality, approval, technical validation or render readiness");
  });

  it("never calls a brief generation or regeneration endpoint", () => {
    for (const text of components) {
      expect(text).not.toContain("clip-briefs");
      expect(text).not.toContain("generateClipBrief");
    }
  });

  it("uses no dangerous HTML injection anywhere", () => {
    expect(everything).not.toContain("dangerouslySetInnerHTML");
  });

  it("uses no external URL anywhere", () => {
    for (const text of components) {
      expect(text).not.toContain("http://");
      expect(text).not.toContain("https://");
    }
  });

  it("uses no media generation or transcoding", () => {
    expect(everything).not.toContain("ffmpeg");
    expect(everything).not.toContain("transcode");
  });

  it("contains no local approval or rejection state", () => {
    expect(everything).not.toContain("setApproved");
    expect(everything).not.toContain("localApproval");
  });
});

describe("brief field and section rendering", () => {
  it("declares that owner values are shown exactly as persisted", () => {
    expect(flatFields).toContain("Values are shown exactly as the owner persisted them");
  });

  it("declares that nothing is filled in when missing", () => {
    expect(flatFields).toContain("filled in when missing");
  });

  it("keeps plain language beside the value rather than replacing it", () => {
    expect(flatFields).toContain(
      "Plain language sits beside the value, never in place of it",
    );
  });

  it("renders the owner value through the shared display helper", () => {
    expect(fields).toContain("fieldDisplayValue(field)");
  });

  it("renders the owner explanation separately from the value", () => {
    expect(fields).toContain("{field.bounded_explanation}");
  });

  it("marks required and optional fields from the owner schema", () => {
    expect(fields).toContain("requiredBadge(field)");
  });

  it("marks advisory guidance as not a decision", () => {
    expect(fields).toContain("Advisory guidance from the owning module. It is not a decision.");
  });

  it("says a shortened value leaves the stored value unchanged", () => {
    expect(fields).toContain("The stored value is unchanged.");
  });

  it("states that hidden empty optional fields are missing, not filled in", () => {
    expect(fields).toContain("They are\n              missing, not filled in.");
  });

  it("shows the owner empty and unavailable section messages", () => {
    expect(fields).toContain("{section.bounded_empty_message}");
    expect(fields).toContain("{section.bounded_unavailable_message}");
  });

  it("renders the completeness notice with every readout", () => {
    expect(fields).toContain("{COMPLETENESS_NOTICE}");
  });

  it("states that the owner records no revision identity", () => {
    expect(fields).toContain("revisionNotice(reference)");
  });

  it("surfaces an unsupported schema notice", () => {
    expect(fields).toContain("unsupportedSchemaNotice(reference)");
  });
});

describe("queue card", () => {
  it("declares that every value belongs to the owning module", () => {
    expect(flat(card)).toContain("Every value shown here belongs to the owning module");
  });

  it("declares that the card never scores or ranks", () => {
    expect(flat(card)).toContain("never scores a brief, never ranks the set itself");
  });

  it("declares that completeness is not presented as quality", () => {
    expect(flat(card)).toContain("never presents completeness as quality");
  });

  it("says an unranked brief is not ranked by the owner", () => {
    expect(card).toContain("not ranked by the owner");
  });

  it("offers every owner-supported queue filter", () => {
    for (const filter of [
      "all_current",
      "human_review_required",
      "current_selected_candidate",
      "missing_required_fields",
      "missing_evidence",
      "conflicts",
      "stale",
      "complete_for_owner_schema",
      "warnings",
      "historical",
      "superseded",
    ]) {
      expect(card).toContain(`"${filter}"`);
    }
  });

  it("offers every owner-supported sort", () => {
    for (const sort of [
      "review_priority",
      "candidate_rank",
      "created_sequence",
      "source_start_time",
      "brief_id",
    ]) {
      expect(card).toContain(`"${sort}"`);
    }
  });

  it("offers no quality or virality sort option", () => {
    const sorts = card.slice(card.indexOf("const SORTS"), card.indexOf("export function"));
    expect(sorts).not.toContain("quality");
    expect(sorts).not.toContain("virality");
    expect(sorts).not.toContain("predicted");
    expect(sorts.match(/id: "/g)).toHaveLength(5);
  });

  it("says an empty queue hides nothing by a score", () => {
    expect(card).toContain("Nothing is hidden by a score.");
  });

  it("shows the owner priority tier and reason", () => {
    expect(card).toContain("priorityLabel(item)");
  });
});

describe("evidence and conflicts", () => {
  it("declares that evidence uses persisted identities only", () => {
    expect(flatEvidence).toContain(
      "Evidence is linked only through identities the owning modules persisted",
    );
  });

  it("declares that missing evidence is never a pass", () => {
    expect(flatEvidence).toContain("never treated as a pass");
  });

  it("declares that a conflict is reported unresolved", () => {
    expect(flatEvidence).toContain("reported unresolved rather than being decided here");
  });

  it("renders the missing-evidence statement to the reviewer", () => {
    expect(evidence).toContain("Missing evidence is never a pass.");
  });

  it("shows both conflicting values without choosing one", () => {
    expect(evidence).toContain("{conflict.value_a");
    expect(evidence).toContain("{conflict.value_b");
  });

  it("shows the resolution label from the shared helper", () => {
    expect(evidence).toContain("conflictResolutionLabel(conflict)");
  });

  it("says only the owning module can clear a blocking state", () => {
    expect(evidence).toContain("Only that module can clear it.");
  });

  it("marks whether each evidence link is authoritative or advisory", () => {
    expect(evidence).toContain('link.advisory ? "advisory" : "authoritative"');
  });

  it("shows owner transcript segment identities rather than inferred text", () => {
    expect(evidence).toContain("Owner transcript segments:");
  });
});

describe("preview", () => {
  it("declares that the player is bound to the owner window", () => {
    expect(flatPreview).toContain(
      "The player is bound to the owner's start and end seconds",
    );
  });

  it("declares that the browser cannot substitute its own range", () => {
    expect(flatPreview).toContain("cannot substitute its own range");
  });

  it("declares that playing the preview validates and approves nothing", () => {
    expect(flatPreview).toContain("validates and approves nothing");
  });

  it("builds the preview through the shared bounded helper", () => {
    expect(preview).toContain("buildClipBriefPreview(projectId, reference, contextSeconds)");
  });

  it("shows the persisted window to the reviewer", () => {
    expect(preview).toContain("Persisted brief window");
  });

  it("bounds the context control to the shared ceiling", () => {
    expect(preview).toContain("max={MAX_PREVIEW_CONTEXT_SECONDS}");
  });

  it("states that nothing is generated to replace a missing preview", () => {
    expect(preview).toContain("Nothing is generated to stand in for a missing preview.");
  });
});

describe("comparison", () => {
  it("declares that comparison shows differences only", () => {
    expect(flatComparison).toContain("Comparison shows differences only");
  });

  it("declares that no brief is scored, preferred or chosen", () => {
    expect(flatComparison).toContain("No brief is scored, preferred or chosen");
  });

  it("declares that completeness is not a quality comparison", () => {
    expect(flatComparison).toContain("completeness is not treated as a quality comparison");
  });

  it("declares that a missing field stays visibly missing", () => {
    expect(flatComparison).toContain("stays visibly missing");
  });

  it("renders the no-winner notice to the reviewer", () => {
    expect(comparison).toContain("{NO_WINNER_NOTICE}");
  });

  it("renders a missing value as missing", () => {
    expect(comparison).toContain('return "— missing —"');
  });

  it("marks required owner-schema fields in the table", () => {
    expect(comparison).toContain("row.required_by_owner_schema");
  });
});

describe("action routing", () => {
  it("declares that only server-offered actions with a token can be submitted", () => {
    expect(flatDialog).toContain(
      "with a server-issued confirmation token, can be submitted",
    );
  });

  it("declares that unavailable actions are listed with their reason", () => {
    expect(flatDialog).toContain("no substitute authority is offered");
  });

  it("declares that nothing here approves, rejects, revises or regenerates", () => {
    expect(flatDialog).toContain(
      "Nothing here approves, rejects, revises or regenerates a brief",
    );
  });

  it("renders the no-authoritative-action notice", () => {
    expect(dialog).toContain("{NO_AUTHORITATIVE_ACTION_NOTICE}");
  });

  it("gates the offered actions through the shared helper", () => {
    expect(dialog).toContain("availableActions(descriptors, snapshot, confirmations)");
  });

  it("lists withheld actions with their stated reason", () => {
    expect(dialog).toContain("unavailableActionNotice(descriptor)");
  });

  it("names the owning module and operation in the dialog", () => {
    expect(dialog).toContain("{descriptor.owning_module_id}");
    expect(dialog).toContain("{descriptor.owning_operation_id}");
  });

  it("shows what the action does not do", () => {
    expect(dialog).toContain("descriptor.does_not_do.map");
  });

  it("requires explicit reviewer confirmation before submitting", () => {
    expect(dialog).toContain("canSubmitAction(");
    expect(dialog).toContain("I have reviewed this exact clip brief");
  });

  it("labels the submit button as sending to the owning module", () => {
    expect(dialog).toContain("Send to the owning module");
  });

  it("shows the receipt through the shared summary helper", () => {
    expect(dialog).toContain("receiptSummary(receipt)");
    expect(dialog).toContain("receiptChangedAuthority(receipt)");
  });

  it("refreshes canonical state before creating the action request", () => {
    expect(panel).toContain("refreshSnapshot.mutate(snapshot.brief_snapshot_id");
  });

  it("stops when the canonical digest changed while the review was open", () => {
    expect(panel).toContain("Canonical clip brief state changed while this review was open");
  });

  it("stops when the server no longer offers a confirmation token", () => {
    expect(panel).toContain("This action is no longer available for this exact clip brief");
  });

  it("declares that no value is updated optimistically", () => {
    expect(flatPanel).toContain("is updated optimistically anywhere in this flow");
  });

  it("uses the server-issued token rather than a client-computed digest", () => {
    expect(panel).toContain("confirmation_context_digest: token");
  });

  it("validates before submitting and reports the validation message", () => {
    expect(panel).toContain("validateAction.mutate(requestId");
    expect(panel).toContain("setActionMessage(validation.message)");
  });
});

describe("review-session annotations", () => {
  it("declares that annotations are UI metadata only", () => {
    expect(flatAnnotations).toContain("These notes are UI metadata held in the review session");
  });

  it("declares that annotations never become canonical", () => {
    expect(flatAnnotations).toContain("never become part of the canonical clip brief");
  });

  it("always renders the non-canonical notice", () => {
    expect(annotations).toContain("{LOCAL_ANNOTATION_NOTICE}");
    expect(annotations).toContain("{annotation.notice}");
  });

  it("bounds the note input to the shared ceiling", () => {
    expect(annotations).toContain("maxLength={MAX_ANNOTATION_LENGTH}");
  });

  it("refuses a note carrying credentials through the shared builder", () => {
    expect(annotations).toContain("buildAnnotation(fieldPath, text)");
    expect(flatLogic).toContain("SENSITIVE_TEXT.test(bounded)");
  });
});

describe("client wiring", () => {
  it("calls only the real clip-brief-review endpoints", () => {
    for (const path of [
      "/clip-brief-review`",
      "/clip-brief-review/registry`",
      "/clip-brief-review/queue$",
      "/clip-brief-review/compare`",
      "/clip-brief-review/actions`",
      "/clip-brief-review/export`",
    ]) {
      expect(apiClient).toContain(path.replace("$", "${"));
    }
  });

  it("exposes no generation or approval endpoint for briefs", () => {
    expect(apiClient).not.toContain("clip-brief-review/generate");
    expect(apiClient).not.toContain("clip-brief-review/approve");
  });

  it("invalidates canonical queries after a submission instead of assuming success", () => {
    expect(queries).toContain('queryKey: ["boba", "projects", projectId, "clip-brief-review"]');
    expect(queries).toContain("useSubmitBobaClipBriefAction");
  });

  it("declares that brief state is re-read from the owning module", () => {
    expect(flat(queries)).toContain(
      "Brief state is only ever re-read from the owning module, never assumed",
    );
  });

  it("registers a distinct query key namespace", () => {
    expect(queries).toContain("bobaClipBriefReview:");
    expect(queries).toContain("bobaClipBriefQueue:");
  });

  it("contains an error boundary that changes no brief state", () => {
    expect(panel).toContain("BobaClipBriefReviewErrorBoundary");
    expect(panel).toContain("No clip brief state changed.");
  });
});
