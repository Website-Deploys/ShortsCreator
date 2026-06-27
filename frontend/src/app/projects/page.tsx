"use client";

/**
 * Projects history.
 *
 * Lists every project the creator has uploaded, persisted by the backend (so it
 * survives refreshes). Polished loading skeletons, a friendly error state, and a
 * premium empty state.
 */
import Link from "next/link";

import { AppShell } from "@/components/AppShell";
import { AlertIcon, FolderIcon } from "@/components/icons";
import { ProjectCard } from "@/components/project/ProjectCard";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { useProjects } from "@/lib/queries";

export default function ProjectsPage() {
  const { data: projects, isLoading, isError, refetch } = useProjects();

  return (
    <AppShell>
      <div className="mx-auto max-w-4xl px-6 py-10">
        <div className="mb-8 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Projects</h1>
            <p className="mt-1 text-sm text-muted">Your uploaded videos and their Shorts.</p>
          </div>
          <Link href="/">
            <Button>New Short</Button>
          </Link>
        </div>

        {isLoading && (
          <div className="space-y-3">
            {[0, 1, 2].map((i) => (
              <div key={i} className="flex items-center gap-4 rounded-xl border border-white/10 bg-surface p-4">
                <Skeleton className="h-14 w-14" />
                <div className="flex-1 space-y-2">
                  <Skeleton className="h-4 w-1/3" />
                  <Skeleton className="h-3 w-1/2" />
                </div>
                <Skeleton className="h-6 w-20 rounded-full" />
              </div>
            ))}
          </div>
        )}

        {isError && (
          <EmptyState
            icon={<AlertIcon className="h-6 w-6 text-red-400" />}
            title="Couldn't load your projects"
            description="We couldn't reach Olympus. Check that the app is running, then try again."
            action={
              <Button variant="secondary" onClick={() => refetch()}>
                Try again
              </Button>
            }
          />
        )}

        {projects && projects.length === 0 && (
          <EmptyState
            icon={<FolderIcon className="h-6 w-6" />}
            title="No projects yet"
            description="Upload your first video and Olympus will turn it into premium Shorts."
            action={
              <Link href="/">
                <Button>Upload a video</Button>
              </Link>
            }
          />
        )}

        {projects && projects.length > 0 && (
          <div className="space-y-3 animate-fade-in">
            {projects.map((project) => (
              <ProjectCard key={project.id} project={project} />
            ))}
          </div>
        )}
      </div>
    </AppShell>
  );
}
