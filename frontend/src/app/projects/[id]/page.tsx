"use client";

/**
 * The Project Workspace - a spacious, sectioned creator workspace.
 *
 * Loads the project from the backend (survives refresh). Two tabs:
 *   Overview  -> video player, the Cognitive Engine's real understanding
 *                progress, the (honest, future) editing pipeline, and Shorts.
 *   Analysis  -> a read-only viewer of what Olympus understands (transcript,
 *                speakers, scenes, OCR, emotion, technical profile).
 * Honest throughout: no fabricated processing or results.
 */
import { useState } from "react";

import Link from "next/link";
import { useParams } from "next/navigation";

import { AppShell } from "@/components/AppShell";
import { AlertIcon, ArrowLeftIcon, BrainIcon, SpinnerIcon } from "@/components/icons";
import { AnalysisTimeline } from "@/components/project/AnalysisTimeline";
import { AnalysisViewer } from "@/components/project/AnalysisViewer";
import { MetadataGrid } from "@/components/project/MetadataGrid";
import { ProcessingTimeline } from "@/components/project/ProcessingTimeline";
import { QuickActions } from "@/components/project/QuickActions";
import { ResultsSection } from "@/components/project/ResultsSection";
import { TechnicalDetails } from "@/components/project/TechnicalDetails";
import { VideoPlayer } from "@/components/VideoPlayer";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { useAnalysis, useProject } from "@/lib/queries";
import type { Project } from "@/lib/types";

type Tab = "overview" | "analysis";

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="mb-4 text-xs font-semibold uppercase tracking-wide text-muted">{children}</h2>
  );
}

function Tabs({ active, onChange }: { active: Tab; onChange: (tab: Tab) => void }) {
  const tabs: { id: Tab; label: string }[] = [
    { id: "overview", label: "Overview" },
    { id: "analysis", label: "Analysis" },
  ];
  return (
    <div className="mt-6 flex gap-1 border-b border-white/10" role="tablist">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          role="tab"
          aria-selected={active === tab.id}
          onClick={() => onChange(tab.id)}
          className={`-mb-px border-b-2 px-4 py-2.5 text-sm font-medium transition-colors ${
            active === tab.id
              ? "border-accent text-white"
              : "border-transparent text-muted hover:text-white"
          }`}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

function ProjectWorkspace({ project }: { project: Project }) {
  const [tab, setTab] = useState<Tab>("overview");
  const { data: analysis, isLoading: analysisLoading } = useAnalysis(project.id);

  return (
    <div className="mx-auto max-w-6xl px-6 py-8 animate-fade-in">
      <Link
        href="/projects"
        className="inline-flex items-center gap-1.5 text-sm text-muted transition-colors hover:text-white"
      >
        <ArrowLeftIcon className="h-4 w-4" />
        All projects
      </Link>

      <div className="mt-5 flex flex-wrap items-center gap-x-4 gap-y-2">
        <h1 className="truncate text-2xl font-semibold tracking-tight">{project.name}</h1>
        <StatusBadge status={project.status} />
      </div>

      <Tabs active={tab} onChange={setTab} />

      <div className="mt-8 grid grid-cols-1 gap-8 lg:grid-cols-3">
        {/* Main column */}
        <div className="space-y-10 lg:col-span-2">
          {tab === "overview" ? (
            <>
              <section>
                <VideoPlayer projectId={project.id} hasThumbnail={project.has_thumbnail} />
              </section>

              <section>
                <SectionTitle>Video understanding</SectionTitle>
                <Card>
                  <AnalysisTimeline analysis={analysis} isLoading={analysisLoading} />
                </Card>
              </section>

              <section>
                <SectionTitle>Editing pipeline</SectionTitle>
                <Card>
                  <ProcessingTimeline
                    status={project.status}
                    uploadDurationMs={project.upload_duration_ms}
                  />
                </Card>
              </section>

              <section>
                <SectionTitle>Shorts</SectionTitle>
                <ResultsSection clips={[]} />
              </section>
            </>
          ) : (
            <section>
              <SectionTitle>What Olympus understands</SectionTitle>
              {analysisLoading && !analysis ? (
                <Card>
                  <div className="flex items-center gap-3 text-sm text-muted">
                    <SpinnerIcon className="h-4 w-4 animate-spin" />
                    Loading understanding…
                  </div>
                </Card>
              ) : analysis ? (
                <AnalysisViewer analysis={analysis} />
              ) : (
                <EmptyState
                  icon={<BrainIcon className="h-6 w-6" />}
                  title="Understanding not started yet"
                  description="Olympus begins understanding your video automatically after upload. This view will fill in as each signal is analyzed."
                />
              )}
            </section>
          )}
        </div>

        {/* Side column */}
        <aside className="space-y-6">
          <QuickActions project={project} />

          <section>
            <SectionTitle>Video details</SectionTitle>
            <MetadataGrid project={project} />
          </section>

          <TechnicalDetails project={project} />
        </aside>
      </div>
    </div>
  );
}

export default function ProjectPage() {
  const params = useParams<{ id: string }>();
  const { data: project, isLoading, isError, error, refetch } = useProject(params.id);

  return (
    <AppShell>
      {isLoading && (
        <div className="mx-auto max-w-6xl px-6 py-10">
          <Skeleton className="h-4 w-24" />
          <Skeleton className="mt-5 h-8 w-1/2" />
          <div className="mt-8 grid grid-cols-1 gap-8 lg:grid-cols-3">
            <div className="space-y-8 lg:col-span-2">
              <Skeleton className="aspect-video w-full rounded-xl" />
              <Skeleton className="h-64 w-full rounded-xl" />
            </div>
            <div className="space-y-6">
              <Skeleton className="h-48 w-full rounded-xl" />
              <Skeleton className="h-64 w-full rounded-xl" />
            </div>
          </div>
        </div>
      )}

      {isError && (
        <div className="mx-auto max-w-2xl px-6 py-16">
          <EmptyState
            icon={<AlertIcon className="h-6 w-6 text-red-400" />}
            title="Project not found"
            description={
              (error as Error | undefined)?.message ??
              "This project may have been deleted, or Olympus is unreachable."
            }
            action={
              <div className="flex gap-3">
                <Button variant="secondary" onClick={() => refetch()}>
                  Try again
                </Button>
                <Link href="/projects">
                  <Button>All projects</Button>
                </Link>
              </div>
            }
          />
        </div>
      )}

      {project && <ProjectWorkspace project={project} />}
    </AppShell>
  );
}
