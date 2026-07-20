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
    expect(resultsSection.toLowerCase()).not.toContain("copyright safe");
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
});
