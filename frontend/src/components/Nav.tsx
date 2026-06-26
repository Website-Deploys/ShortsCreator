/** Top navigation shared across authenticated pages. */
import Link from "next/link";

import { BackendStatus } from "@/components/BackendStatus";

export function Nav() {
  return (
    <header className="border-b border-white/10">
      <nav className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
        <Link href="/" className="text-lg font-semibold tracking-tight">
          Olympus
        </Link>
        <div className="flex items-center gap-6 text-sm text-muted">
          <Link href="/dashboard" className="hover:text-white">
            Dashboard
          </Link>
          <Link href="/upload" className="hover:text-white">
            New Short
          </Link>
          <Link href="/settings" className="hover:text-white">
            Settings
          </Link>
          <BackendStatus />
        </div>
      </nav>
    </header>
  );
}
