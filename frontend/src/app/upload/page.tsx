"use client";

/**
 * Upload / Paste screen - start a new project.
 *
 * Accepts a YouTube URL (file upload arrives with the upload endpoint in
 * Milestone 2) plus the few high-value options from the Frontend spec. It
 * validates input immediately, then creates the project and routes to the
 * Processing screen. The emotional goal is relief: hand it over and let go.
 */
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Nav } from "@/components/Nav";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { ApiClientError, api } from "@/lib/apiClient";

const URL_PATTERN = /^https?:\/\/.+/i;

export default function UploadPage() {
  const router = useRouter();
  const [url, setUrl] = useState("");
  const [captionStyle, setCaptionStyle] = useState("clean");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const valid = URL_PATTERN.test(url.trim());

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    if (!valid) {
      setError("Please paste a valid video URL (starting with http).");
      return;
    }
    setSubmitting(true);
    try {
      const project = await api.createProject({ source_type: "url", url: url.trim() });
      router.push(`/processing/${project.id}`);
    } catch (err) {
      // The create endpoint lands in Milestone 2; show an honest message.
      const message =
        err instanceof ApiClientError
          ? `${err.message} (project creation is delivered in the next milestone)`
          : "Something went wrong.";
      setError(message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div>
      <Nav />
      <main className="mx-auto max-w-2xl px-6 py-10">
        <h1 className="mb-2 text-2xl font-semibold">Create a Short</h1>
        <p className="mb-8 text-muted">
          Paste a video link and Olympus will craft a small set of premium Shorts from it.
        </p>

        <Card>
          <form onSubmit={handleSubmit} className="space-y-6">
            <div>
              <label htmlFor="url" className="mb-2 block text-sm font-medium">
                Video URL
              </label>
              <input
                id="url"
                type="url"
                inputMode="url"
                placeholder="https://www.youtube.com/watch?v=…"
                value={url}
                onChange={(event) => setUrl(event.target.value)}
                className="w-full rounded-lg border border-white/10 bg-elevated px-4 py-3 text-white placeholder:text-muted focus:border-accent focus:outline-none"
              />
            </div>

            <div>
              <label htmlFor="caption" className="mb-2 block text-sm font-medium">
                Caption style
              </label>
              <select
                id="caption"
                value={captionStyle}
                onChange={(event) => setCaptionStyle(event.target.value)}
                className="w-full rounded-lg border border-white/10 bg-elevated px-4 py-3 text-white focus:border-accent focus:outline-none"
              >
                <option value="clean">Clean</option>
                <option value="bold">Bold</option>
                <option value="minimal">Minimal</option>
              </select>
            </div>

            {error && <p className="text-sm text-red-300">{error}</p>}

            <Button type="submit" disabled={!valid || submitting} className="w-full">
              {submitting ? "Starting…" : "Create Short"}
            </Button>
          </form>
        </Card>
      </main>
    </div>
  );
}
