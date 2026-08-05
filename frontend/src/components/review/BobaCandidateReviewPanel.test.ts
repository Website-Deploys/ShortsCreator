import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

function source(relative: string) {
  return readFileSync(new URL(relative, import.meta.url), "utf8");
}

const panel = source("./BobaCandidateReviewPanel.tsx");
const card = source("./BobaCandidateCard.tsx");
const evidence = source("./BobaCandidateEvidence.tsx");
const preview = source("./BobaCandidatePreview.tsx");
const dialog = source("./BobaCandidateActionDialog.tsx");
const results = source("../project/ResultsSection.tsx");
const clientLogic = readFileSync(
  new URL("../../lib/candidateReview.ts", import.meta.url),
  "utf8",
);
const everything = [panel, card, evidence, preview, dialog, clientLogic].join("\n");

/** Collapse whitespace and JSDoc markers so prose assertions survive wrapping. */
const flat = (value: string) =>
  value.replace(/^[ \t]*\*[ \t]?/gm, " ").replace(/\s+/g, " ");
const flatPanel = flat(panel);
const flatCard = flat(card);
const flatEvidence = flat(evidence);
const flatPreview = flat(preview);
const flatDialog = flat(dialog);

describe("panel integration with the Review UI", () => {
  it("is mounted from the existing project results route", () => {
    expect(results).toContain("BobaCandidateReviewPanel");
    expect(results).toContain('from "@/components/review/BobaCandidateReviewPanel"');
  });

  it("does not replace the existing Review UI workspace", () => {
    expect(results).toContain("BobaReviewWorkspace");
    expect(results).toContain("{reviewWorkspace}");
  });

  it("reuses the Review UI error classifier rather than a new one", () => {
    expect(panel).toContain('from "@/lib/reviewUi"');
    expect(panel).toContain("classifyReviewError");
  });

  it("reuses the Review UI protected preview helper", () => {
    expect(clientLogic).toContain('import { protectedPreviewUrl } from "@/lib/reviewUi"');
  });

  it("declares itself a projection, comparison and routing layer", () => {
    expect(flatPanel).toContain(
      "read-only candidate projection, a comparison workspace and a safe canonical action router",
    );
  });

  it("states it never discovers, reranks or selects", () => {
    expect(flatPanel).toContain("never discovers candidates, reranks them");
    expect(flatPanel).toContain("selects a winner");
  });

  it("composes every required region", () => {
    for (const region of [
      "BobaCandidateQueue",
      "BobaCandidatePreview",
      "BobaCandidateScoreBreakdown",
      "BobaCandidateTranscript",
      "BobaCandidateComparison",
      "BobaCandidateEvidence",
      "BobaCandidateActionBar",
      "BobaCandidateActionDialog",
      "BobaCandidateReviewErrorBoundary",
    ]) {
      expect(panel).toContain(region);
    }
  });

  it("renders the overlap badge alongside queue items", () => {
    expect(card).toContain("BobaCandidateOverlapBadge");
  });
});

describe("source authority in the UI", () => {
  it("names the rank owner on the candidate card", () => {
    expect(card).toContain("Original rank");
    expect(card).toContain("rank_owner_module_id");
    expect(card).toContain("describeRank");
  });

  it("names the score owner on the candidate card", () => {
    expect(card).toContain("Primary source score");
    expect(card).toContain("primary_score_owner_module_id");
  });

  it("attributes editorial status to Editorial Decision", () => {
    expect(card).toContain("editorialStatusLabel");
    expect(card).toContain("Editorial status");
  });

  it("shows the exact source window and duration on the card", () => {
    expect(card).toContain("Source window");
    expect(card).toContain("formatSourceWindow(item.start_seconds, item.end_seconds)");
    expect(card).toContain("formatDuration(item.duration_seconds)");
  });

  it("states that source windows are the exact persisted values", () => {
    expect(flatCard).toContain("exact persisted values from Candidate Clip Discovery");
  });

  it("lists the owning modules on every card", () => {
    expect(card).toContain("item.source_module_ids.join");
  });

  it("shows every score with its scale, direction and definition", () => {
    for (const heading of ["Score", "Value", "Scale", "Direction", "Rank", "Definition"]) {
      expect(evidence).toContain(heading);
    }
  });

  it("states that the panel does not recompute or combine scores", () => {
    expect(flatEvidence).toContain("does not recompute, rescale or combine scores");
  });

  it("states no score is a virality or performance prediction", () => {
    expect(flatEvidence).toContain("no score is a");
    expect(flatEvidence).toContain("virality or performance prediction");
  });

  it("marks the owner composite as the owner's", () => {
    expect(evidence).toContain("owner composite");
    expect(evidence).toContain("source_owned_composite");
  });

  it("explains why no weight is shown", () => {
    expect(flatEvidence).toContain("No weight is persisted by the owner, so none is shown");
  });

  it("flags scores that are not comparable across modules", () => {
    expect(flatEvidence).toContain("Not directly comparable with other modules");
  });

  it("shows ties reported by the owner", () => {
    expect(evidence).toContain("card.tied");
  });

  it("labels advisory source cards as not a decision", () => {
    expect(flatEvidence).toContain("Advisory only — not a decision.");
    expect(flatEvidence).toContain("Authoritative owner record.");
  });

  it("shows the original status and rank on every evidence card", () => {
    expect(evidence).toContain("Original status");
    expect(evidence).toContain("original_rank");
  });
});

describe("current, stale and historical labelling", () => {
  it("uses text labels and glyphs, never colour alone", () => {
    expect(card).toContain("candidateStateGlyph");
    expect(card).toContain("candidateStateLabel");
    expect(preview).toContain("[historical]");
    expect(preview).toContain("[current]");
  });

  it("shows evidence completeness on the card", () => {
    expect(card).toContain("evidenceSummary");
  });

  it("reports blockers, conflicts and warnings separately", () => {
    expect(card).toContain("blocking");
    expect(card).toContain("conflicts");
    expect(card).toContain("warnings");
  });

  it("marks candidates that need a human decision", () => {
    expect(card).toContain("Human action required");
  });
});

describe("local shortlist versus canonical shortlist", () => {
  it("always shows the non-editorial notice with the shortlist", () => {
    expect(card).toContain("LOCAL_SHORTLIST_NOTICE");
    expect(panel).toContain("LOCAL_SHORTLIST_NOTICE");
  });

  it("labels the control as a session shortlist", () => {
    expect(card).toContain("Add to session shortlist");
    expect(card).toContain("Remove from session shortlist");
  });

  it("keeps the shortlist in local state only", () => {
    expect(panel).toContain("toggleLocalShortlist");
    expect(panel).not.toContain("shortlistIds.map((id) => api");
  });
});

describe("comparison", () => {
  it("enforces the fixed comparison limit", () => {
    expect(card).toContain("MAX_COMPARISON_CANDIDATES");
    expect(panel).toContain("toggleComparison");
    expect(panel).toContain("canCompare");
  });

  it("states that no winner is chosen", () => {
    expect(flatEvidence).toContain("No winner is chosen");
  });

  it("warns that cross-module scales differ", () => {
    expect(flatEvidence).toContain("different modules use different scales");
  });

  it("compares every required facet", () => {
    for (const label of [
      "Source window",
      "Duration",
      "Discovery reason",
      "Original rank",
      "Primary source score",
      "Editorial status",
      "Evidence",
      "Warnings",
    ]) {
      expect(evidence).toContain(label);
    }
  });

  it("links overlap records into the comparison", () => {
    expect(evidence).toContain("overlapLabel");
    expect(evidence).toContain("overlapDescription");
  });
});

describe("protected preview", () => {
  it("uses only the guarded helper", () => {
    expect(preview).toContain("buildCandidatePreview");
    expect(preview).not.toMatch(/src=\{`https?:/);
  });

  it("seeks to the exact candidate start", () => {
    expect(preview).toContain("#t=${playStart}");
    expect(preview).toContain("Replay candidate window");
  });

  it("stops playback at the candidate end", () => {
    expect(preview).toContain("video.currentTime >= playEnd");
    expect(preview).toContain("video.pause()");
  });

  it("offers bounded context playback labelled as context", () => {
    expect(preview).toContain("Include ${contextSeconds}s context");
    expect(preview).toContain("preview.contextNotice");
  });

  it("states that playback is not technical validation", () => {
    expect(flatPreview).toContain("not technical validation");
    expect(flatPreview).toContain("owned by the Validator Runner");
  });

  it("declares the preview read-only with no download, upload or publication", () => {
    expect(flatPreview).toContain("cannot edit, replace or overwrite");
    expect(flatPreview).toContain("cannot download, upload or publish");
  });

  it("shows an explicit unavailable state", () => {
    expect(preview).toContain("preview.unavailableReason");
    expect(preview).toContain('role="status"');
  });

  it("never mutates the candidate record while seeking", () => {
    expect(flatPreview).toContain("without ever mutating the record");
  });
});

describe("transcript", () => {
  it("separates candidate transcript from context", () => {
    expect(evidence).toContain("Candidate transcript");
    expect(evidence).toContain("Context before and after");
  });

  it("states that context does not change the candidate boundaries", () => {
    expect(flatEvidence).toContain("does not change the candidate boundaries");
  });

  it("attributes transcript text to its owner", () => {
    expect(flatEvidence).toContain("Reproduced verbatim from");
    expect(evidence).toContain("sourceModuleId");
  });

  it("states that speakers are never identified", () => {
    expect(flatEvidence).toContain("never identifies people from audio or video frames");
  });

  it("handles a candidate with no persisted transcript", () => {
    expect(flatEvidence).toContain("No transcript snippet is persisted on this candidate record");
  });

  it("bounds the context control to sixty seconds", () => {
    expect(evidence).toContain("max={60}");
  });
});

describe("canonical action routing", () => {
  it("refreshes canonical state before submitting", () => {
    expect(panel).toContain("refreshSnapshot.mutate");
    expect(panel).toContain("snapshot_digest !== snapshot.snapshot_digest");
    expect(flatPanel).toContain("Canonical candidate state changed while this review was open");
  });

  it("validates before submitting and honours the result", () => {
    const validateIndex = panel.indexOf("validateAction.mutate");
    const submitIndex = panel.indexOf("submitAction.mutate");
    expect(validateIndex).toBeGreaterThan(-1);
    expect(submitIndex).toBeGreaterThan(validateIndex);
    expect(panel).toContain("if (!validation.valid)");
  });

  it("echoes a server-issued confirmation token", () => {
    expect(panel).toContain("action_confirmations");
    expect(panel).toContain("confirmation_context_digest: token");
    expect(panel).not.toContain('confirmation_context_digest: ""');
  });

  it("only offers actions the snapshot and token both allow", () => {
    expect(dialog).toContain("availableActions");
    expect(dialog).toContain("withheldActions");
    expect(panel).toContain("confirmations={confirmations}");
  });

  it("names the owning module and operation in the dialog", () => {
    expect(dialog).toContain("descriptor.owning_module_id");
    expect(dialog).toContain("descriptor.owning_operation_id");
    expect(flatDialog).toContain("That module owns the outcome");
  });

  it("names the exact candidate in the dialog", () => {
    expect(flatDialog).toContain("You are submitting this for candidate");
    expect(dialog).toContain("{candidateId}");
  });

  it("shows consequences and what the action does not do", () => {
    expect(dialog).toContain("What this does");
    expect(dialog).toContain("What this does not do");
    expect(dialog).toContain("descriptor.consequences");
    expect(dialog).toContain("descriptor.does_not_do");
  });

  it("requires explicit confirmation before enabling submission", () => {
    expect(flatDialog).toContain("I confirm this exact action for this exact candidate.");
    expect(dialog).toContain("!acknowledged");
  });

  it("requires a bounded reason when policy requires it", () => {
    expect(dialog).toContain("descriptor.requires_reason");
    expect(dialog).toContain("maxLength={descriptor.maximum_reason_length}");
  });

  it("warns against pasting credentials or paths", () => {
    expect(flatDialog).toContain("Do not paste credentials, tokens or local file paths");
  });

  it("shows the bound workflow revision and candidate digest", () => {
    expect(dialog).toContain("Workflow revision");
    expect(dialog).toContain("Candidate digest");
  });

  it("never claims authority changed without an owner receipt", () => {
    expect(panel).toContain("receiptChangedAuthority(owned)");
    expect(flatPanel).toContain("No authoritative candidate state changed");
    expect(dialog).toContain("receiptChangedAuthority(receipt)");
  });

  it("performs no optimistic candidate-status update", () => {
    expect(panel).not.toContain("setQueryData");
    expect(panel).not.toContain("onMutate");
    expect(panel).not.toContain("setSelectedItem({ ...");
    expect(flatPanel).toContain("No optimistic candidate-status update");
  });

  it("reports a reused receipt honestly", () => {
    expect(flatDialog).toContain("An existing receipt was reused");
  });

  it("lists why other actions are unavailable", () => {
    expect(dialog).toContain("Why other candidate actions are unavailable");
    expect(dialog).toContain("descriptor.limitations[0]");
  });

  it("states the hard boundaries in the action bar", () => {
    expect(flatDialog).toContain(
      "cannot select or reject candidates editorially, rerank them, run FFmpeg",
    );
    expect(flatDialog).toContain("bypass Rights or Safety");
  });
});

describe("accessibility", () => {
  it("uses a semantic keyboard-navigable candidate list", () => {
    expect(card).toContain('role="listbox"');
    expect(card).toContain('role="option"');
    for (const key of ["ArrowDown", "ArrowUp", "Home", "End", "Enter"]) {
      expect(card).toContain(key);
    }
  });

  it("labels the candidate list for screen readers", () => {
    expect(card).toContain("Candidate clips, ordered by review priority");
  });

  it("exposes rank to screen readers with its owner", () => {
    expect(card).toContain('className="sr-only"');
    expect(card).toContain("describeRank(item)");
  });

  it("exposes score scale and definition to screen readers", () => {
    expect(evidence).toContain("describeScore(card)");
    expect(evidence).toContain("sr-only");
  });

  it("uses table captions and row headers for evidence tables", () => {
    expect(evidence).toContain("<caption");
    expect(evidence).toContain('scope="row"');
    expect(evidence).toContain('scope="col"');
  });

  it("labels compare and shortlist controls with pressed state", () => {
    expect(card).toContain("aria-pressed={comparing}");
    expect(card).toContain("aria-pressed={shortlisted}");
  });

  it("implements a labelled modal dialog with a focus trap", () => {
    expect(dialog).toContain('role="dialog"');
    expect(dialog).toContain('aria-modal="true"');
    expect(dialog).toContain('aria-labelledby="candidate-action-dialog-title"');
    expect(dialog).toContain('aria-describedby="candidate-action-dialog-description"');
    expect(dialog).toContain("trapFocus");
  });

  it("returns focus and closes on Escape", () => {
    expect(dialog).toContain("returnFocusRef");
    expect(dialog).toContain('event.key === "Escape"');
  });

  it("provides accessible tabs for the mobile layout", () => {
    expect(panel).toContain('role="tablist"');
    expect(panel).toContain('role="tab"');
    expect(panel).toContain('role="tabpanel"');
    expect(panel).toContain("aria-selected");
    expect(panel).toContain("aria-controls");
    for (const label of ["Candidates", "Preview", "Details", "Compare", "Evidence"]) {
      expect(panel).toContain(`label: "${label}"`);
    }
  });

  it("supports arrow-key tab navigation", () => {
    expect(panel).toContain("ArrowRight");
    expect(panel).toContain("ArrowLeft");
  });

  it("labels every form control", () => {
    for (const id of ["candidate-search", "candidate-filter", "candidate-sort"]) {
      expect(card).toContain(`htmlFor="${id}"`);
      expect(card).toContain(`id="${id}"`);
    }
    expect(evidence).toContain('htmlFor="transcript-context"');
  });

  it("labels the preview element", () => {
    expect(preview).toContain("aria-label=\"Candidate clip preview from the project source\"");
  });

  it("keeps visible focus states and touch-sized controls", () => {
    expect(everything).toContain("focus-visible:ring");
    expect(everything).toContain("min-h-[44px]");
  });

  it("uses semantic landmarks in the desktop layout", () => {
    expect(panel).toContain("<header");
    expect(panel).toContain("<main");
    expect(panel).toContain("<aside");
  });

  it("labels loading and error states", () => {
    expect(card).toContain('role="status"');
    expect(card).toContain('role="alert"');
    expect(panel).toContain('role="alert"');
  });

  it("announces receipts politely", () => {
    expect(dialog).toContain('aria-live="polite"');
  });
});

describe("responsive layout", () => {
  it("uses a desktop grid and a mobile-only tab layout", () => {
    expect(panel).toContain("xl:grid");
    expect(panel).toContain("xl:hidden");
    expect(panel).toContain("hidden gap-4 xl:grid");
  });

  it("keeps the action bar sticky", () => {
    expect(dialog).toContain("sticky bottom-0");
  });

  it("hides the action bar until a candidate is selected", () => {
    expect(dialog).toContain("if (candidateId === null) return null;");
  });

  it("allows evidence tables to scroll horizontally", () => {
    expect(evidence).toContain("overflow-x-auto");
  });
});

describe("safe rendering and hard boundaries", () => {
  it("renders no untrusted HTML", () => {
    expect(everything).not.toContain("dangerouslySetInnerHTML");
    expect(everything).not.toContain("innerHTML");
  });

  it("routes every failure through the safe classifier", () => {
    expect(panel).toContain("classifyReviewError");
    expect(panel).not.toContain("error.stack");
    expect(panel).not.toContain("JSON.stringify(error");
  });

  it("contains render failures without leaking internals", () => {
    expect(panel).toContain("getDerivedStateFromError");
    expect(flatPanel).toContain("could not be displayed");
    expect(flatPanel).toContain("No candidate state changed");
  });

  it("exposes no upload, publication, render or execution controls", () => {
    for (const forbidden of [
      "uploadThumbnail",
      "publishTo",
      "runValidator",
      "executeRepair",
      "restoreCheckpoint",
      "startRender",
      'download="',
      '<input type="file"',
    ]) {
      expect(everything).not.toContain(forbidden);
    }
  });

  it("references no external URL or absolute path", () => {
    expect(everything).not.toContain("http://");
    expect(everything).not.toContain("https://evil");
    expect(everything).not.toContain("file://");
    expect(everything).not.toContain("C:\\");
  });

  it("offers no bulk approve or reject control", () => {
    for (const forbidden of ["Approve all", "Reject all", "approveAll", "rejectAll"]) {
      expect(everything).not.toContain(forbidden);
    }
  });

  it("offers no AI-best or virality ordering", () => {
    expect(flatCard).toContain("There is no");
    expect(flatCard).toContain("or virality ordering");
    expect(everything).not.toContain("Most viral");
  });
});
