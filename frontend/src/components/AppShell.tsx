"use client";

/**
 * The application shell - a professional desktop-style sidebar (and mobile top
 * bar) wrapping the app's pages. Provides primary navigation, recent projects,
 * a real storage-usage summary, and clearly-disabled "coming soon" items.
 */
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import {
  FolderIcon,
  LayersIcon,
  PlusIcon,
  ServerIcon,
  SettingsIcon,
  UserIcon,
} from "@/components/icons";
import { Thumbnail } from "@/components/ui/Thumbnail";
import { Tooltip } from "@/components/ui/Tooltip";
import { formatBytes } from "@/lib/format";
import { useProjects, useSystemInfo } from "@/lib/queries";

const NAV = [
  { href: "/", label: "New Upload", icon: PlusIcon },
  { href: "/projects", label: "Projects", icon: FolderIcon },
  { href: "/library", label: "Library", icon: LayersIcon },
  { href: "/admin", label: "Admin", icon: ServerIcon },
];

function Brand() {
  return (
    <Link href="/" className="flex items-center gap-2 px-3 py-1">
      <span aria-hidden className="flex h-7 w-7 items-center justify-center rounded-md bg-accent text-sm font-bold text-white">
        O
      </span>
      <span className="text-sm font-semibold tracking-tight">Olympus</span>
    </Link>
  );
}

function NavLinks({ pathname }: { pathname: string }) {
  return (
    <>
      {NAV.map(({ href, label, icon: Icon }) => {
        const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
        return (
          <Link
            key={href}
            href={href}
            className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
              active ? "bg-white/10 text-white" : "text-muted hover:bg-white/5 hover:text-white"
            }`}
          >
            <Icon className="h-4 w-4" />
            {label}
          </Link>
        );
      })}
    </>
  );
}

function RecentProjects() {
  const { data: projects } = useProjects();
  const recent = (projects ?? []).slice(0, 4);
  if (recent.length === 0) return null;
  return (
    <div className="mt-6">
      <p className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-wide text-muted">Recent</p>
      <div className="space-y-0.5">
        {recent.map((project) => (
          <Link
            key={project.id}
            href={`/projects/${project.id}`}
            className="flex items-center gap-2.5 rounded-lg px-3 py-1.5 text-sm text-muted transition-colors hover:bg-white/5 hover:text-white"
          >
            <Thumbnail
              projectId={project.id}
              hasThumbnail={project.has_thumbnail}
              className="h-7 w-7 shrink-0 rounded"
              iconClassName="h-3.5 w-3.5"
            />
            <span className="truncate">{project.name}</span>
          </Link>
        ))}
      </div>
    </div>
  );
}

function StorageUsage() {
  const { data: projects } = useProjects();
  const list = projects ?? [];
  const total = list.reduce((sum, p) => sum + p.size_bytes, 0);
  return (
    <div className="px-3 py-2">
      <div className="flex items-center justify-between text-[11px] font-semibold uppercase tracking-wide text-muted">
        <span>Storage</span>
      </div>
      <p className="mt-1 text-sm font-medium text-white">{formatBytes(total)}</p>
      <p className="text-xs text-muted">
        across {list.length} {list.length === 1 ? "project" : "projects"}
      </p>
    </div>
  );
}

function FutureLinks() {
  return (
    <div className="space-y-0.5">
      <Tooltip label="Coming soon">
        <span className="flex w-full cursor-not-allowed items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-muted/50">
          <SettingsIcon className="h-4 w-4" />
          Settings
        </span>
      </Tooltip>
      <Tooltip label="Coming soon">
        <span className="flex w-full cursor-not-allowed items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-muted/50">
          <UserIcon className="h-4 w-4" />
          Creator profile
        </span>
      </Tooltip>
    </div>
  );
}

function BackendDot() {
  const { isLoading, isError } = useSystemInfo();
  const tone = isError ? "bg-red-400" : isLoading ? "bg-yellow-400" : "bg-green-400";
  const label = isError ? "Offline" : isLoading ? "Connecting" : "Connected";
  return (
    <div className="flex items-center gap-2 px-3 py-2 text-xs text-muted">
      <span className={`h-2 w-2 rounded-full ${tone}`} aria-hidden />
      {label}
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  return (
    <div className="min-h-screen md:flex">
      <aside className="hidden w-64 shrink-0 flex-col border-r border-white/10 px-3 py-5 md:flex">
        <Brand />
        <nav className="mt-8 flex flex-col gap-1">
          <NavLinks pathname={pathname} />
        </nav>
        <div className="mt-1 flex-1 overflow-y-auto">
          <RecentProjects />
        </div>
        <div className="border-t border-white/10 pt-2">
          <FutureLinks />
          <StorageUsage />
          <BackendDot />
        </div>
      </aside>

      <header className="flex items-center justify-between border-b border-white/10 px-4 py-3 md:hidden">
        <Brand />
        <nav className="flex gap-1">
          <NavLinks pathname={pathname} />
        </nav>
      </header>

      <main className="min-w-0 flex-1">{children}</main>
    </div>
  );
}
