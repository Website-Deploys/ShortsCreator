import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

const uploadCard = readFileSync(new URL("./UploadCard.tsx", import.meta.url), "utf8");

describe("Link Ingestion V2 upload card", () => {
  it("keeps both upload and link intake paths", () => {
    expect(uploadCard).toContain("Upload Video");
    expect(uploadCard).toContain("Paste Link");
    expect(uploadCard).toContain("Browse files");
    expect(uploadCard).toContain("Paste YouTube video or Shorts link");
  });

  it("requires rights confirmation and displays honest progress", () => {
    expect(uploadCard).toContain("I confirm I own this video");
    expect(uploadCard).toContain("Only paste links to videos you own");
    expect(uploadCard).toContain("getLinkIngestion");
    expect(uploadCard).toContain("Fetching metadata");
    expect(uploadCard).toContain("Downloading source");
    expect(uploadCard).toContain("Validating source video");
  });
});
