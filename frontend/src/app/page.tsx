import Link from "next/link";

import { BackendStatus } from "@/components/BackendStatus";
import { Button } from "@/components/ui/Button";

/**
 * Landing page.
 *
 * Communicates the single promise (one video -> a few premium Shorts) and
 * offers one clear primary action. Honest and minimal per the Frontend spec -
 * it sells the spine, not a feature list.
 */
export default function LandingPage() {
  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col items-center justify-center px-6 text-center">
      <div className="mb-6">
        <BackendStatus />
      </div>
      <h1 className="text-5xl font-semibold tracking-tight">
        One video in.
        <br />
        Premium Shorts out.
      </h1>
      <p className="mt-6 max-w-xl text-lg text-muted">
        Olympus watches your long-form video, understands the story, and crafts a small set of
        genuinely distinct, creator-ready Shorts - trimmed, reframed, captioned, and polished.
      </p>
      <div className="mt-10 flex gap-4">
        <Link href="/upload">
          <Button>Create your first Short</Button>
        </Link>
        <Link href="/dashboard">
          <Button variant="secondary">Go to dashboard</Button>
        </Link>
      </div>
    </main>
  );
}
