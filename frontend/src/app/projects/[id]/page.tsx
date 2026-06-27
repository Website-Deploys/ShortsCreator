"use client";

/**
 * The Project Workspace - a spacious, sectioned creator workspace.
 *
 * Loads the project from the backend (survives refresh). Five tabs:
 *   Overview  -> video player, the Cognitive Engine's progress, the (honest,
 *                future) editing pipeline, and Shorts.
 *   Analysis  -> read-only viewer of what Olympus understands (transcript,
 *                speakers, scenes, OCR, emotion, technical profile).
 *   Story     -> the narrative understanding (sections, hook, arc, payoffs...).
 *   Virality  -> the viral-potential assessment (scores, timeline, heatmap,
 *                strengths, recommendations) - always shown with confidence.
 * Honest throughout: no fabricated processing or results.
 */
import { useState } from "react";

import Link from "next/link";
import { useParams } from "next/navigation";

import { AppShell } from "@/components/AppShell";
import {
  AlertIcon,
  ArrowLeftIcon,
  BookIcon,
  BrainIcon,
  ScissorsIcon,
  SpinnerIcon,
  ZapIcon,
} from "@/components/icons";
import { AnalysisTimeline } from "@/components/project/AnalysisTimeline";
import { AnalysisViewer } from "@/components/project/AnalysisViewer";
import { MetadataGrid } from "@/components/project/MetadataGrid";
import { ProcessingTimeline } from "@/components/project/ProcessingTimeline";
import { QuickActions } from "@/components/project/QuickActions";
import { ResultsSection } from "@/components/project/ResultsSection";
import { StoryStages } from "@/components/project/StoryStages";
import { StoryTimeline } from "@/components/project/StoryTimeline";
import { StoryViewer } from "@/components/project/StoryViewer";
import { TechnicalDetails } from "@/components/project/TechnicalDetails";
import { ViralityStages } from "@/components/project/ViralityStages";
import { ViralityTimeline } from "@/components/project/ViralityTimeline";
import { ViralityViewer } from "@/components/project/ViralityViewer";
import { ClipPlannerStages } from "@/components/project/ClipPlannerStages";
import { ClipPlannerView } from "@/components/project/ClipPlannerView";
import { VideoPlayer } from "@/components/VideoPlayer";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { parseSummary } from "@/lib/virality";
import { useAnalysis, useProject, usePlanning, useStory, useVirality } from "@/lib/queries";
import type { Project } from "@/lib/types";

type Tab = "overview" | "analysis" | "story" | "virality" | "clip-planner";

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="mb-4 text-xs font-semibold uppercase tracking-wide text-muted">{children}</h2>
  );
}

function Tabs({ active, onChange }: { active: Tab; onChange: (tab: Tab) => void }) {
  const tabs: { id: Tab; label: string }[] = [
    { id: "overview", label: "Overview" },
    { id: "analysis", label: "Analysis" },
    { id: "story", label: "Story" },
    { id: "virality", label: "Virality" },
    { id: "clip-planner", label: "Clip Planner" },
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
  const { data: story, isLoading: storyLoading } = useStory(project.id);
  const { data: virality, isLoading: viralityLoading } = useVirality(project.id);
  const viralitySummary = virality ? parseSummary(virality) : null;
  const { data: planning, isLoading: planningLoading } = usePlanning(project.id);

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
          {tab === "overview" && (
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
          )}

          {tab === "analysis" && (
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

          {tab === "story" && (
            <div className="space-y-10">
              <section>
                <SectionTitle>Story understanding</SectionTitle>
                <Card>
                  <StoryStages story={story} isLoading={storyLoading} />
                </Card>
              </section>

              {story && (
                <section>
                  <SectionTitle>Narrative timeline</SectionTitle>
                  <Card>
                    <StoryTimeline story={story} durationSeconds={project.duration_seconds} />
                  </Card>
                </section>
              )}

              {storyLoading && !story ? null : story ? (
                <section>
                  <SectionTitle>What Olympus understands about the story</SectionTitle>
                  <StoryViewer story={story} />
                </section>
              ) : (
                !storyLoading && (
                  <EmptyState
                    icon={<BookIcon className="h-6 w-6" />}
                    title="Story analysis hasn't started yet"
                    description="The Story Engine begins automatically once the video understanding completes. This view fills in as each narrative signal is derived."
                  />
                )
              )}
            </div>
          )}

          {tab === "virality" && (
            <div className="space-y-10">
              <section>
                <SectionTitle>Virality assessment</SectionTitle>
                <Card>
                  <ViralityStages virality={virality} isLoading={viralityLoading} />
                </Card>
              </section>

              {viralitySummary && (
                <section>
                  <SectionTitle>Virality timeline &amp; heatmap</SectionTitle>
                  <Card>
                    <ViralityTimeline
                      summary={viralitySummary}
                      durationSeconds={project.duration_seconds}
                    />
                  </Card>
                </section>
              )}

              {viralityLoading && !virality ? null : virality ? (
                <section>
                  <SectionTitle>How viral is this video, and why</SectionTitle>
                  <ViralityViewer virality={virality} durationSeconds={project.duration_seconds} />
                </section>
              ) : (
                !viralityLoading && (
                  <EmptyState
                    icon={<ZapIcon className="h-6 w-6" />}
                    title="Virality analysis hasn't started yet"
                    description="The Virality Engine begins automatically once the story understanding completes. This view fills in as each viral signal is assessed."
                  />
                )
              )}
            </div>
          )}

          {tab === "clip-planner" && (
            <div className="space-y-10">
              <section>
                <SectionTitle>Clip planning</SectionTitle>
                <Card>
                  <ClipPlannerStages planning={planning} isLoading={planningLoading} />
                </Card>
              </section>

              {planningLoading && !planning ? null : planning ? (
                <section>
                  <SectionTitle>Proposed editing plans</SectionTitle>
                  <ClipPlannerView planning={planning} durationSeconds={project.duration_seconds} />
                </section>
              ) : (
                !planningLoading && (
                  <EmptyState
                    icon={<ScissorsIcon className="h-6 w-6" />}
                    title="Clip planning hasn't started yet"
                    description="The Clip Planner begins automatically once the virality assessment completes. It decides what to edit — it never edits or renders video."
                  />
                )
              )}
            </div>
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
