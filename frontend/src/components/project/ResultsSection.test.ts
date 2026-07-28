import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

function source(relative: string) {
  return readFileSync(new URL(relative, import.meta.url), "utf8");
}

describe("V2 output flow UI contracts", () => {
  it("does not expose a manual clip count selector", () => {
    const uploadCard = source("../upload/UploadCard.tsx");

    expect(uploadCard).not.toContain("desiredClipCount");
    expect(uploadCard).not.toContain("setDesiredClipCount");
    expect(uploadCard).not.toContain("<span className=\"mb-1 block text-muted\">Clips</span>");
  });

  it("uses the render manifest for visible clip cards", () => {
    const resultsSection = source("./ResultsSection.tsx");

    expect(resultsSection).toContain("useRenderManifest");
    expect(resultsSection).toContain("Download MP4");
    expect(resultsSection).toContain("Rendering selected clips");
    expect(resultsSection).toContain("Captions:");
    expect(resultsSection).toContain("Caption timing:");
    expect(resultsSection).toContain("Hook treatment:");
    expect(resultsSection).toContain("Highlighted words:");
    expect(resultsSection).toContain("Speaker-aware captions:");
    expect(resultsSection).toContain("Caption safe zone:");
    expect(resultsSection).toContain("Caption validation:");
    expect(resultsSection).toContain("Caption intelligence");
    expect(resultsSection).toContain("Caption warning:");
    expect(resultsSection).toContain("Viral score:");
    expect(resultsSection).toContain("Niche:");
    expect(resultsSection).toContain("Hook type:");
    expect(resultsSection).toContain("Story:");
    expect(resultsSection).toContain("Payoff ending:");
    expect(resultsSection).toContain("Trend fit:");
    expect(resultsSection).toContain("Research:");
    expect(resultsSection).toContain("Trend provider:");
    expect(resultsSection).toContain("Trend domains:");
    expect(resultsSection).toContain('cacheStatus === "stale_fallback"');
    expect(resultsSection).toContain('? "Live"');
    expect(resultsSection).toContain("sources");
    expect(resultsSection).toContain("Trend research warning:");
    expect(resultsSection).toContain("Trend:");
    expect(resultsSection).toContain("Hook warning");
    expect(resultsSection).toContain("Music:");
    expect(resultsSection).toContain("Music intelligence");
    expect(resultsSection).toContain("Ducking:");
    expect(resultsSection).toContain("License:");
    expect(resultsSection).toContain("Source:");
    expect(resultsSection).toContain("Quality:");
    expect(resultsSection).toContain("music_library_selection");
    expect(resultsSection).toContain("Generated validation asset used");
    expect(resultsSection).toContain("Music warning:");
    expect(resultsSection).toContain("Face tracking:");
    expect(resultsSection).toContain("Layout:");
    expect(resultsSection).toContain("Participants:");
    expect(resultsSection).toContain("Speaker association:");
    expect(resultsSection).toContain("Active-speaker switching:");
    expect(resultsSection).toContain("Layout regions/switches:");
    expect(resultsSection).toContain("Layout warning:");
    expect(resultsSection).toContain("SFX safety:");
    expect(resultsSection).toContain("Motion style:");
    expect(resultsSection).toContain("Motion graphics");
    expect(resultsSection).toContain("Motion warning:");
    expect(resultsSection).toContain("motion_render_validation");
    expect(resultsSection).toContain("Sync:");
    expect(resultsSection).toContain("Duration:");
    expect(resultsSection).toContain("Hook:");
    expect(resultsSection).toContain("Render validation warning");
    expect(resultsSection).toContain("Voice:");
    expect(resultsSection).toContain("Video:");
    expect(resultsSection).toContain("Why this clip works");
    expect(resultsSection).toContain("Unified clip reasoning is not available.");
    expect(resultsSection).toContain("copyrightSafetySummary");
    expect(resultsSection).toContain("Copyright and upload readiness");
    expect(resultsSection).toContain("Risk:");
    expect(resultsSection).toContain("Upload readiness:");
    expect(resultsSection).toContain("Manual review:");
    expect(resultsSection).toContain("Source rights:");
    expect(resultsSection).toContain("Music license:");
    expect(resultsSection).toContain("SFX license:");
    expect(resultsSection).toContain("Copyright review required:");
    expect(resultsSection).toContain("uploadMetadataSummary");
    expect(resultsSection).toContain("Upload Metadata");
    expect(resultsSection).toContain("YouTube Shorts");
    expect(resultsSection).toContain("Instagram Reels");
    expect(resultsSection).toContain("TikTok");
    expect(resultsSection).toContain("Copy title");
    expect(resultsSection).toContain("Copy YouTube");
    expect(resultsSection).toContain("Copy Instagram");
    expect(resultsSection).toContain("Copy TikTok");
    expect(resultsSection).toContain("Copy hashtags");
    expect(resultsSection).toContain("Manual review required");
    expect(resultsSection).toContain("Upload metadata is not available for this older render.");
    expect(resultsSection.toLowerCase()).not.toContain("is copyright safe");
    expect(resultsSection.toLowerCase()).not.toContain("copyright-safe");
    expect(resultsSection.toLowerCase()).not.toContain("guaranteed viral");
    expect(resultsSection).not.toContain("Content ID safe");
    expect(resultsSection).not.toContain("Your Shorts will appear here");
  });

  it("shows transparent local profiles and explicit feedback controls", () => {
    const resultsSection = source("./ResultsSection.tsx");

    expect(resultsSection).toContain("Creator Personalization V2");
    expect(resultsSection).toContain(
      "Personalization is local and based only on your feedback.",
    );
    expect(resultsSection).toContain("You can reset this anytime.");
    expect(resultsSection).toContain("Learn only from feedback I submit");
    expect(resultsSection).toContain("Personalization truth");
    expect(resultsSection).toContain("Personalization metadata is not available");
    expect(resultsSection).toContain("More like this");
    expect(resultsSection).toContain("Avoid this");
    expect(resultsSection).toContain("Too much motion");
    expect(resultsSection).toContain("Title good");
    expect(resultsSection).toContain("Title bad");
    expect(resultsSection).toContain("Export profile");
    expect(resultsSection).toContain("Reset profile");
    expect(resultsSection).not.toContain("trackPageView");
    expect(resultsSection).not.toContain("implicitFeedback");
  });

  it("shows advisory BOBA reasoning without autonomy claims", () => {
    const resultsSection = source("./ResultsSection.tsx");

    expect(resultsSection).toContain("BOBA Brain Summary");
    expect(resultsSection).toContain("BOBA reasoning");
    expect(resultsSection).toContain("BOBA noticed:");
    expect(resultsSection).toContain("BOBA recommends:");
    expect(resultsSection).toContain("BOBA confidence:");
    expect(resultsSection).toContain("Missing signals:");
    expect(resultsSection).toContain("No, advisory only");
    expect(resultsSection).toContain("BOBA reasoning is not available for this older render.");
    expect(resultsSection.toLowerCase()).not.toContain("boba guarantees");
    expect(resultsSection.toLowerCase()).not.toContain("boba fully controls");
  });

  it("shows bounded local BOBA memory summaries", () => {
    const resultsSection = source("./ResultsSection.tsx");

    expect(resultsSection).toContain("BOBA Memory");
    expect(resultsSection).toContain("What BOBA remembers:");
    expect(resultsSection).toContain("Selected / rejected:");
    expect(resultsSection).toContain("Known limitations:");
    expect(resultsSection).toContain("Creator memory");
    expect(resultsSection).toContain("explicit feedback item(s)");
    expect(resultsSection).toContain("Memory used:");
    expect(resultsSection).toContain("No cloud sync or passive learning.");
    expect(resultsSection).toContain("Approval / Rejection Learning");
    expect(resultsSection).toContain(
      "BOBA learns only from feedback you submit. Guidance is advisory unless",
    );
    expect(resultsSection).toContain("Analyze decisions");
    expect(resultsSection).toContain("Reset analysis");
    expect(resultsSection).not.toContain("collectImplicitApproval");
  });

  it("shows bounded whole-video understanding and signal limits", () => {
    const resultsSection = source("./ResultsSection.tsx");

    expect(resultsSection).toContain("BOBA Whole Video Understanding");
    expect(resultsSection).toContain("Topic timeline");
    expect(resultsSection).toContain("Story arc");
    expect(resultsSection).toContain("Emotional beats");
    expect(resultsSection).toContain("Weak / filler sections");
    expect(resultsSection).toContain("Shortability hints");
    expect(resultsSection).toContain("Signal limitations");
    expect(resultsSection).toContain("no cloud AI or audience-performance proof");
  });

  it("shows advisory BOBA candidate discovery without rendering claims", () => {
    const resultsSection = source("./ResultsSection.tsx");

    expect(resultsSection).toContain("BOBA Candidate Clip Discovery");
    expect(resultsSection).toContain("Discover candidates");
    expect(resultsSection).toContain("Why discovered:");
    expect(resultsSection).toContain("Standalone");
    expect(resultsSection).toContain("Payoff");
    expect(resultsSection).toContain("does not rank, plan, edit, or render clips");
  });

  it("shows advisory BOBA clip ranking with reasons and score truth", () => {
    const resultsSection = source("./ResultsSection.tsx");

    expect(resultsSection).toContain("BOBA Clip Ranking Brain");
    expect(resultsSection).toContain("Rank candidates");
    expect(resultsSection).toContain("Score breakdown and risks");
    expect(resultsSection).toContain("Priority");
    expect(resultsSection).toContain("Signals unavailable:");
    expect(resultsSection).toContain(
      "does not plan, edit, render, or predict audience results",
    );
    expect(resultsSection.toLowerCase()).not.toContain("boba predicts virality");
  });

  it("shows advisory BOBA editorial decisions without render claims", () => {
    const resultsSection = source("./ResultsSection.tsx");

    expect(resultsSection).toContain("BOBA Editorial Decision Engine");
    expect(resultsSection).toContain("Create editorial decisions");
    expect(resultsSection).toContain("Hook strategy:");
    expect(resultsSection).toContain("Readiness reason:");
    expect(resultsSection).toContain("Editing instructions, risks, and improvements");
    expect(resultsSection).toContain("Production order:");
    expect(resultsSection).toContain(
      "not proof that any edit or render effect was applied",
    );
  });

  it("shows evidence-bound BOBA explanations and uncertainty", () => {
    const resultsSection = source("./ResultsSection.tsx");

    expect(resultsSection).toContain("BOBA Explanation Engine");
    expect(resultsSection).toContain("Create explanations");
    expect(resultsSection).toContain("Top recommendation:");
    expect(resultsSection).toContain("Evidence and source fields");
    expect(resultsSection).toContain("Uncertainty, fallbacks, and human review");
    expect(resultsSection).toContain("saved metadata only");
    expect(resultsSection).toContain("no rendered proof or audience-performance prediction");
  });

  it("shows advisory experimentation plans without execution claims", () => {
    const resultsSection = source("./ResultsSection.tsx");

    expect(resultsSection).toContain("BOBA Experimentation System V1");
    expect(resultsSection).toContain(
      "Experiments are plans only. BOBA does not upload, render, or collect",
    );
    expect(resultsSection).toContain(
      "Creator approval is required before treating any experiment as active.",
    );
    expect(resultsSection).toContain("Baseline");
    expect(resultsSection).toContain("Changed variable:");
    expect(resultsSection).toContain("Hypothesis");
    expect(resultsSection).toContain("Success + risk");
    expect(resultsSection).toContain("Rejected unsafe or unsupported ideas");
    expect(resultsSection).toContain("Automatic application:");
    expect(resultsSection).not.toContain("autoStartExperiment");
    expect(resultsSection).not.toContain("collectViewerAnalytics");
  });

  it("shows manual-only BOBA performance feedback controls", () => {
    const resultsSection = source("./ResultsSection.tsx");

    expect(resultsSection).toContain("BOBA Performance Feedback Brain V1");
    expect(resultsSection).toContain(
      "Performance data is manual in V1. BOBA does not connect to platforms",
    );
    expect(resultsSection).toContain(
      "Learning guidance is advisory unless you explicitly approve applying",
    );
    expect(resultsSection).toContain("Optional creator-entered metrics");
    expect(resultsSection).toContain("Record manual feedback");
    expect(resultsSection).toContain("Experiment outcome reviews");
    expect(resultsSection).toContain("Pattern summary and uncertainty");
    expect(resultsSection).toContain("Advisory learning handoff");
    expect(resultsSection).not.toContain("collectPlatformAnalytics");
    expect(resultsSection).not.toContain("autoApplyPerformanceWinner");
  });

  it("shows metadata-only BOBA Content Scout V2 truth and controls", () => {
    const resultsSection = source("./ResultsSection.tsx");

    expect(resultsSection).toContain("BOBA Content Scout V2");
    expect(resultsSection).toContain(
      "Content Scout V2 uses local/user-provided metadata only.",
    );
    expect(resultsSection).toContain(
      "BOBA does not fetch URLs, scrape platforms, download videos, or",
    );
    expect(resultsSection).toContain("Build review queue");
    expect(resultsSection).toContain("Possible short angles");
    expect(resultsSection).toContain("Export safe metadata");
    expect(resultsSection).toContain("Reset Scout V2");
    expect(resultsSection).not.toContain("fetchScoutSourceUrl");
    expect(resultsSection).not.toContain("downloadScoutVideo");
    expect(resultsSection).not.toContain("autoIngestScoutItem");
  });

  it("shows local-only BOBA Research Brain V1 truth and controls", () => {
    const resultsSection = source("./ResultsSection.tsx");

    expect(resultsSection).toContain("BOBA Research Brain V1");
    expect(resultsSection).toContain(
      "Research Brain V1 uses local/user-provided material only.",
    );
    expect(resultsSection).toContain(
      "BOBA does not fetch URLs, scrape websites, call external APIs, or",
    );
    expect(resultsSection).toContain(
      "Evidence snippets are bounded; human verification may still be",
    );
    expect(resultsSection).toContain("Build research brief");
    expect(resultsSection).toContain("Content Scout handoff");
    expect(resultsSection).toContain("Export safe research");
    expect(resultsSection).toContain("Reset Research V1");
    expect(resultsSection).not.toContain("fetchResearchSourceUrl");
    expect(resultsSection).not.toContain("scrapeResearchWebsite");
    expect(resultsSection).not.toContain("verifyRealtimeResearchTrends");
    expect(resultsSection).not.toContain("autoApplyResearchHandoff");
  });

  it("shows local-only BOBA Trend / Topic Watcher V1 truth and controls", () => {
    const resultsSection = source("./ResultsSection.tsx");

    expect(resultsSection).toContain("BOBA Trend / Topic Watcher V1");
    expect(resultsSection).toContain(
      "Trend / Topic Watcher V1 uses local/user-provided topic data only.",
    );
    expect(resultsSection).toContain(
      "Movement is measured only within provided data.",
    );
    expect(resultsSection).toContain(
      "BOBA does not scrape platforms, fetch URLs, call external APIs, or verify real-time trends.",
    );
    expect(resultsSection).toContain("Build topic watchlist");
    expect(resultsSection).toContain("Content Scout handoff");
    expect(resultsSection).toContain("Research Brain handoff");
    expect(resultsSection).toContain("Export safe watcher");
    expect(resultsSection).toContain("Reset Watcher V1");
    expect(resultsSection).not.toContain("fetchTrendTopicUrl");
    expect(resultsSection).not.toContain("scrapeTrendPlatform");
    expect(resultsSection).not.toContain("monitorRealtimeTrends");
    expect(resultsSection).not.toContain("autoApplyTrendTopicHandoff");
  });

  it("shows metadata-only BOBA Candidate Video Scorer V1 truth and controls", () => {
    const resultsSection = source("./ResultsSection.tsx");

    expect(resultsSection).toContain("BOBA Candidate Video Scorer V1");
    expect(resultsSection).toContain(
      "Candidate Video Scorer V1 uses local/user-provided metadata only.",
    );
    expect(resultsSection).toContain(
      "BOBA does not fetch URLs, scrape platforms, download videos, or confirm copyright safety.",
    );
    expect(resultsSection).toContain(
      "Human approval and rights review are required before any future ingestion.",
    );
    expect(resultsSection).toContain("Build candidate review queue");
    expect(resultsSection).toContain("Shorts potential review");
    expect(resultsSection).toContain("Rights review:");
    expect(resultsSection).toContain("Human review queue");
    expect(resultsSection).toContain("Advisory source handoffs");
    expect(resultsSection).toContain("Export safe scorer");
    expect(resultsSection).toContain("Reset Scorer V1");
    expect(resultsSection).not.toContain("fetchCandidateVideoUrl");
    expect(resultsSection).not.toContain("downloadCandidateVideo");
    expect(resultsSection).not.toContain("autoIngestCandidateVideo");
    expect(resultsSection).not.toContain("confirmCandidateCopyrightSafety");
  });

  it("shows advisory BOBA Rights + Permission Gate V1 truth and controls", () => {
    const resultsSection = source("./ResultsSection.tsx");

    expect(resultsSection).toContain("BOBA Rights + Permission Gate V1");
    expect(resultsSection).toContain(
      "Rights + Permission Gate V1 is not legal advice.",
    );
    expect(resultsSection).toContain(
      "BOBA does not verify copyright ownership, validate licenses, fetch",
    );
    expect(resultsSection).toContain(
      "Unknown rights are never treated as safe.",
    );
    expect(resultsSection).toContain(
      "Future ingestion requires human approval and acceptable rights",
    );
    expect(resultsSection).toContain("Build rights review gate");
    expect(resultsSection).toContain("Permission checklist");
    expect(resultsSection).toContain("Risk review:");
    expect(resultsSection).toContain("Future ingestion handoff");
    expect(resultsSection).toContain("Ready for human review");
    expect(resultsSection).toContain("Permission needed");
    expect(resultsSection).toContain("Unknown rights / review needed");
    expect(resultsSection).toContain("Blocked items");
    expect(resultsSection).toContain("Export safe Rights Gate");
    expect(resultsSection).toContain("Reset Rights Gate V1");
    expect(resultsSection).not.toContain("fetchRightsSourceUrl");
    expect(resultsSection).not.toContain("downloadRightsMedia");
    expect(resultsSection).not.toContain("autoIngestRightsMedia");
    expect(resultsSection).not.toContain("validateLegalOwnership");
  });

  it("shows observation-only BOBA Observer V1 truth and controls", () => {
    const resultsSection = source("./ResultsSection.tsx");

    expect(resultsSection).toContain("BOBA Observer V1");
    expect(resultsSection).toContain(
      "BOBA Observer V1 observes only. It does not fix, edit code, run validators, delete files, download media, or render.",
    );
    expect(resultsSection).toContain(
      "Unsafe next actions require human review or future safety modules.",
    );
    expect(resultsSection).toContain("Observe saved project state");
    expect(resultsSection).toContain("Workflow health");
    expect(resultsSection).toContain("Module health");
    expect(resultsSection).toContain("Artifact observations");
    expect(resultsSection).toContain("Broken or stale dependencies");
    expect(resultsSection).toContain("Validation gaps");
    expect(resultsSection).toContain("Safety observations");
    expect(resultsSection).toContain("Safe next actions");
    expect(resultsSection).toContain("Unsafe next actions");
    expect(resultsSection).toContain("Export safe Observer report");
    expect(resultsSection).toContain("Reset Observer V1");
    expect(resultsSection).not.toContain("autoRunObserverValidators");
    expect(resultsSection).not.toContain("autoRepairObserverFinding");
    expect(resultsSection).not.toContain("autoRenderObserverProject");
  });

  it("shows advisory BOBA Error Doctor V1 diagnosis boundaries", () => {
    const resultsSection = source("./ResultsSection.tsx");

    expect(resultsSection).toContain("BOBA Error Doctor V1");
    expect(resultsSection).toContain(
      "BOBA Error Doctor V1 diagnoses Observer findings but does not fix files, edit code, run commands, run validators, or perform repairs.",
    );
    expect(resultsSection).toContain(
      "A probable cause is not a proven root cause.",
    );
    expect(resultsSection).toContain(
      "Human review is required before repair or destructive action.",
    );
    expect(resultsSection).toContain("CONFIRMED FACTS");
    expect(resultsSection).toContain("PROBABLE EXPLANATIONS");
    expect(resultsSection).toContain("POSSIBLE HYPOTHESES");
    expect(resultsSection).toContain("MISSING INFORMATION");
    expect(resultsSection).toContain("Diagnose saved Observer findings");
    expect(resultsSection).toContain("Read-only investigation recommendations");
    expect(resultsSection).toContain("Export safe diagnosis");
    expect(resultsSection).toContain("Reset Error Doctor V1");
    expect(resultsSection).toContain("Automatic application: No");
    expect(resultsSection).not.toContain("autoFixErrorDoctorCase");
    expect(resultsSection).not.toContain("autoRunErrorDoctorValidator");
    expect(resultsSection).not.toContain("autoApplyErrorDoctorRepair");
  });

  it("shows advisory BOBA Root Cause Analyzer V1 boundaries", () => {
    const resultsSection = source("./ResultsSection.tsx");

    expect(resultsSection).toContain("BOBA Root Cause Analyzer V1");
    expect(resultsSection).toContain(
      "BOBA Root Cause Analyzer V1 ranks evidence-supported causes but does not guarantee that the highest-ranked candidate is proven.",
    );
    expect(resultsSection).toContain(
      "It does not repair files, edit code, run commands, run validators, or activate fallback tools.",
    );
    expect(resultsSection).toContain(
      "Human approval is required before verification or repair actions.",
    );
    expect(resultsSection).toContain("CONFIRMED FACTS");
    expect(resultsSection).toContain("MOST LIKELY CAUSE");
    expect(resultsSection).toContain("COMPETING EXPLANATIONS");
    expect(resultsSection).toContain("CONTRIBUTING FACTORS");
    expect(resultsSection).toContain("DOWNSTREAM EFFECTS");
    expect(resultsSection).toContain("MISSING EVIDENCE");
    expect(resultsSection).toContain("NEXT SAFE CHECK");
    expect(resultsSection).toContain("Analyze saved Error Doctor report");
    expect(resultsSection).toContain("Export safe analysis");
    expect(resultsSection).toContain("Reset Root Cause Analyzer V1");
    expect(resultsSection).toContain("Resume authorized by this analyzer: No");
    expect(resultsSection).not.toContain("autoRepairRootCause");
    expect(resultsSection).not.toContain("autoRunRootCauseValidator");
    expect(resultsSection).not.toContain("autoActivateFallbackTool");
  });

  it("shows advisory BOBA Repair Planner V1 boundaries", () => {
    const resultsSection = source("./ResultsSection.tsx");

    expect(resultsSection).toContain("BOBA Repair Planner V1");
    expect(resultsSection).toContain(
      "BOBA Repair Planner V1 creates repair plans only. It does not execute commands, edit code, modify files, install tools, restart services, activate fallback tools, or resume workflows.",
    );
    expect(resultsSection).toContain(
      "A repair plan is not proof that the repair will succeed.",
    );
    expect(resultsSection).toContain(
      "Approved repairs must pass validation and output-quality review before Olympus continues.",
    );
    expect(resultsSection).toContain("RECOMMENDED PLAN");
    expect(resultsSection).toContain("ALTERNATIVE PLANS");
    expect(resultsSection).toContain("WHY THIS PLAN");
    expect(resultsSection).toContain("RISKS");
    expect(resultsSection).toContain("CHECKPOINT");
    expect(resultsSection).toContain("ROLLBACK");
    expect(resultsSection).toContain("VALIDATION REQUIRED");
    expect(resultsSection).toContain("QUALITY REQUIREMENTS");
    expect(resultsSection).toContain("APPROVAL REQUIRED");
    expect(resultsSection).toContain("BLOCKED ACTIONS");
    expect(resultsSection).toContain(
      "Create plans from saved Root Cause Analyzer",
    );
    expect(resultsSection).toContain("Export safe repair plan");
    expect(resultsSection).toContain("Reset Repair Planner V1");
    expect(resultsSection).not.toContain("autoExecuteRepairPlan");
    expect(resultsSection).not.toContain("autoApplyRepairPatch");
    expect(resultsSection).not.toContain("autoResumeRepairWorkflow");
  });

  it("shows BOBA Code Surgeon V1 approval and execution boundaries", () => {
    const resultsSection = source("./ResultsSection.tsx");

    expect(resultsSection).toContain("BOBA Code Surgeon V1");
    expect(resultsSection).toContain("Code Surgeon never edits main directly.");
    expect(resultsSection).toContain(
      "I approve applying this exact patch to an isolated repair branch",
    );
    expect(resultsSection).toContain(
      "Create a local review commit on the isolated repair branch.",
    );
    expect(resultsSection).toContain(
      "No push, remote PR, merge, deployment, or release occurs here.",
    );
    expect(resultsSection).toContain(
      "BOBA is testing the patch in a separate workspace.",
    );
    expect(resultsSection).toContain(
      "The patch did not pass a required test. BOBA rejected it",
    );
    expect(resultsSection).toContain(
      "Code Surgeon does not push, merge, deploy, install packages, or",
    );
  });

  it("shows BOBA Tool Recovery V1 approval and truth boundaries", () => {
    const resultsSection = source("./ResultsSection.tsx");
    const apiClient = source("../../lib/apiClient.ts");

    expect(resultsSection).toContain("BOBA Tool Recovery Brain V1");
    expect(resultsSection).toContain(
      "Tool Recovery Brain can execute only approved local recovery",
    );
    expect(resultsSection).toContain(
      "It does not install software, use paid services, access external",
    );
    expect(resultsSection).toContain(
      "A recovered output is not accepted until required validation and",
    );
    expect(resultsSection).toContain("WHAT FAILED");
    expect(resultsSection).toContain("WHAT CAPABILITY IS NEEDED");
    expect(resultsSection).toContain("RECOVERY OPTIONS");
    expect(resultsSection).toContain("WHY THIS OPTION");
    expect(resultsSection).toContain("QUALITY REQUIREMENTS");
    expect(resultsSection).toContain("APPROVAL REQUIRED");
    expect(resultsSection).toContain("CURRENT ATTEMPT");
    expect(resultsSection).toContain("VALIDATION");
    expect(resultsSection).toContain("ROLLBACK");
    expect(resultsSection).toContain("WHAT HAPPENS NEXT");
    expect(resultsSection).toContain(
      "I approve this exact recovery strategy, registered tool, settings, retry budget, time budget, checkpoint reference, and quality requirements.",
    );
    expect(resultsSection).not.toContain("Fix everything");
    expect(apiClient).toContain("/tool-recovery/execute-approved");
    expect(apiClient).toContain("/tool-recovery/validate-output");
    expect(apiClient).toContain("/tool-recovery/rollback");
  });
});
