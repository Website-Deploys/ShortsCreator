import Link from "next/link";

import { Button } from "@/components/ui/Button";

/** A calm, on-brand 404 page. */
export default function NotFound() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center px-6 text-center">
      <p className="text-sm font-medium text-accent">404</p>
      <h1 className="mt-2 text-2xl font-semibold tracking-tight">Page not found</h1>
      <p className="mt-2 max-w-sm text-muted">
        The page you are looking for doesn&apos;t exist or may have moved.
      </p>
      <div className="mt-8">
        <Link href="/">
          <Button>Back to Olympus</Button>
        </Link>
      </div>
    </main>
  );
}
