"use client";

/**
 * Dashboard - the creator's home.
 *
 * Lists projects with honest status. The projects endpoint arrives in Milestone
 * 2; until then this page degrades gracefully (it shows a clear empty/unavailable
 * state rather than erroring), demonstrating the resilient data-fetching pattern.
 */
import Link from "next/link";

import { Nav } from "@/components/Nav";
import { ProjectStatusBadge } from "@/components/ProjectStatusBadge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { useProjects } from "@/lib/queries";

export default function DashboardPage() {
  const { data: projects, isLoading, isError } = useProjects();

  return (
    <div>
      <Nav />
      <main className="mx-auto max-w-5xl px-6 py-10">
        <div className="mb-8 flex items-center justify-between">
          <h1 className="text-2xl font-semibold">Your projects</h1>
          <Link href="/upload">
            <Button>New Short</Button>
          </Link>
        </div>

        {isLoading && <p className="text-muted">Loading your projects…</p>}

        {isError && (
          <Card>
            <p className="text-muted">
              Your projects will appear here. The projects API is delivered in the next
              implementation milestone.
            </p>
          </Card>
        )}

        {projects && projects.length === 0 && (
          <Card>
            <p className="text-muted">
              You have no projects yet. Create your first Short to get started.
            </p>
          </Card>
        )}

        {projects && projects.length > 0 && (
          <ul className="space-y-3">
            {projects.map((project) => (
              <li key={project.id}>
                <Link href={`/processing/${project.id}`}>
                  <Card className="flex items-center justify-between hover:border-white/20">
                    <div>
                      <p className="font-medium">{project.id}</p>
                      <p className="text-sm text-muted">
                        {new Date(project.created_at).toLocaleString()}
                      </p>
                    </div>
                    <ProjectStatusBadge state={project.state} />
                  </Card>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </main>
    </div>
  );
}
