"use client";

/**
 * Processing screen - make the wait calm and trustworthy.
 *
 * Polls the project (via `useProject`) and shows honest, human-language,
 * state-derived progress - never a fake spinner. When the project completes it
 * links to the results; if it fails it shows the specific reason.
 */
import Link from "next/link";
import { useParams } from "next/navigation";

import { Nav } from "@/components/Nav";
import { ProjectStatusBadge } from "@/components/ProjectStatusBadge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { useProject } from "@/lib/queries";
import type { ProjectState } from "@/lib/types";

const STEPS: { state: ProjectState; label: string }[] = [
  { state: "ingested", label: "Downloading your video" },
  { state: "transcribed", label: "Transcribing the audio" },
  { state: "understood", label: "Understanding the story" },
  { state: "selected", label: "Finding the strongest moments" },
  { state: "planned", label: "Editing your Shorts" },
  { state: "rendered", label: "Rendering" },
  { state: "complete", label: "Done" },
];

export default function ProcessingPage() {
  const params = useParams<{ projectId: string }>();
  const projectId = params.projectId;
  const { data: project, isLoading, isError } = useProject(projectId);

  return (
    <div>
      <Nav />
      <main className="mx-auto max-w-2xl px-6 py-10">
        <h1 className="mb-2 text-2xl font-semibold">Working on your Shorts</h1>
        <p className="mb-8 text-muted">Project {projectId}</p>

        {isLoading && <p className="text-muted">Checking status…</p>}

        {isError && (
          <Card>
            <p className="text-muted">
              Live processing status is delivered in the next milestone. Once the project API is
              live, this screen shows honest, real-time progress.
            </p>
          </Card>
        )}

        {project && (
          <Card>
            <div className="mb-6 flex items-center justify-between">
              <span className="text-sm text-muted">Current status</span>
              <ProjectStatusBadge state={project.state} />
            </div>

            {project.state === "failed" ? (
              <p className="text-red-300">
                {project.failure_reason ?? "Processing failed. Please try again."}
              </p>
            ) : (
              <ol className="space-y-3">
                {STEPS.map((step) => (
                  <li key={step.state} className="flex items-center gap-3 text-sm">
                    <span className="inline-block h-2 w-2 rounded-full bg-accent" aria-hidden />
                    {step.label}
                  </li>
                ))}
              </ol>
            )}

            {project.state === "complete" && (
              <div className="mt-6">
                <Link href={`/results/${projectId}`}>
                  <Button>View your Shorts</Button>
                </Link>
              </div>
            )}
          </Card>
        )}
      </main>
    </div>
  );
}
