import Link from "next/link";

import { SupportedFormats } from "@/components/upload/SupportedFormats";
import { UploadCard } from "@/components/upload/UploadCard";

/**
 * Landing page.
 *
 * A minimal, premium, single-column experience: a quiet header (wordmark +
 * link to projects), the upload card as the hero, and the supported-formats
 * strip. No clutter, no gradients, no flashy motion - clean, confident spacing.
 * Uploading auto-continues to the project page.
 */
export default function LandingPage() {
  return (
    <div className="flex min-h-screen flex-col">
      <header className="px-6 py-5">
        <div className="mx-auto flex max-w-5xl items-center justify-between">
          <div className="flex items-center gap-2">
            <span
              aria-hidden
              className="flex h-7 w-7 items-center justify-center rounded-md bg-accent text-sm font-bold text-white"
            >
              O
            </span>
            <span className="text-base font-semibold tracking-tight">Project Olympus</span>
          </div>
          <Link
            href="/projects"
            className="text-sm text-muted transition-colors hover:text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-accent rounded-md px-2 py-1"
          >
            Projects
          </Link>
        </div>
      </header>

      <main className="flex flex-1 items-center justify-center px-6 pb-24">
        <div className="w-full max-w-xl animate-fade-in">
          <div className="mb-10 text-center">
            <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">
              Turn long videos into viral Shorts
            </h1>
            <p className="mx-auto mt-3 max-w-md text-base text-muted">
              Transform long videos into viral Shorts using AI.
            </p>
          </div>

          <UploadCard />
          <SupportedFormats />
        </div>
      </main>
    </div>
  );
}
