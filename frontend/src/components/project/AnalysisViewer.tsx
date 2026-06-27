"use client";

/**
 * The Analysis Viewer — a read-only window into what Olympus understands.
 *
 * Every section reflects the genuine state of its analysis stage. When a stage
 * has produced real output (e.g. the technical profile, or a transcript once a
 * speech provider is configured), it is rendered here. When a stage's model or
 * tooling is not available, the section shows an honest "not available yet"
 * panel with the backend's explanation — it never invents transcripts, scenes,
 * emotions, or any other signal. No editing happens here.
 */
import type { ReactNode } from "react";

import {
  AlertIcon,
  BrainIcon,
  ClockIcon,
  FileVideoIcon,
  MinusCircleIcon,
  RefreshIcon,
  TextIcon,
  UserIcon,
} from "@/components/icons";
import { Card } from "@/components/ui/Card";
import { formatDuration } from "@/lib/format";
import { useRerunStage } from "@/lib/queries";
import type { Analysis, AnalysisStage } from "@/lib/types";

function stageOf(analysis: Analysis, name: string): AnalysisStage | undefined {
  return analysis.stages.find((s) => s.stage === name);
}

function Section({
  icon,
  title,
  children,
}: {
  icon: ReactNode;
  title: string;
  children: ReactNode;
}) {
  return (
    <Card>
      <div className="mb-4 flex items-center gap-2.5">
        <span className="text-muted">{icon}</span>
        <h3 className="text-sm font-semibold text-white">{title}</h3>
      </div>
      {children}
    </Card>
  );
}

/** Honest panel shown when a stage produced no output (unavailable/pending/failed). */
function UnavailablePanel({
  stage,
  projectId,
}: {
  stage: AnalysisStage | undefined;
  projectId: string;
}) {
  const rerun = useRerunStage(projectId);
  if (!stage) {
    return <p className="text-sm text-muted">This signal has not been analyzed yet.</p>;
  }
  const failed = stage.status === "failed";
  const Icon = failed ? AlertIcon : stage.status === "pending" ? ClockIcon : MinusCircleIcon;
  const heading = failed
    ? "This stage encountered an error"
    : stage.status === "pending" || stage.status === "running"
      ? "Not analyzed yet"
      : "Not available in this environment";
  return (
    <div className="rounded-lg border border-dashed border-white/10 bg-white/[0.02] p-4">
      <div className="flex items-start gap-3">
        <Icon className={`mt-0.5 h-5 w-5 shrink-0 ${failed ? "text-red-300" : "text-muted"}`} />
        <div className="min-w-0 flex-1">
          <p className={`text-sm font-medium ${failed ? "text-red-200" : "text-white/80"}`}>
            {heading}
          </p>
          <p className="mt-1 text-xs leading-relaxed text-muted">
            {stage.reason ?? stage.error ?? "No additional detail is available."}
          </p>
        </div>
        {(failed || stage.status === "unavailable") && (
          <button
            type="button"
            onClick={() => rerun.mutate(stage.stage)}
            disabled={rerun.isPending}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-md px-2 py-1 text-xs text-muted transition-colors hover:bg-white/5 hover:text-white disabled:opacity-50"
          >
            <RefreshIcon className={`h-3.5 w-3.5 ${rerun.isPending ? "animate-spin" : ""}`} />
            Re-run
          </button>
        )}
      </div>
    </div>
  );
}

function Field({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="rounded-lg bg-white/[0.02] px-3 py-2.5">
      <dt className="text-[11px] uppercase tracking-wide text-muted">{label}</dt>
      <dd className="mt-0.5 text-sm text-white">{value ?? "—"}</dd>
    </div>
  );
}

function num(value: unknown): ReactNode {
  return typeof value === "number" && Number.isFinite(value) ? value.toLocaleString() : "—";
}

function MetadataSection({ stage }: { stage: AnalysisStage | undefined }) {
  const data = (stage?.data ?? {}) as Record<string, unknown>;
  const audio = Array.isArray(data.audio_tracks) ? data.audio_tracks : null;
  return (
    <div>
      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        <Field
          label="Duration"
          value={
            typeof data.duration_seconds === "number"
              ? formatDuration(data.duration_seconds)
              : "—"
          }
        />
        <Field
          label="Resolution"
          value={
            data.width && data.height ? `${num(data.width)} × ${num(data.height)}` : "—"
          }
        />
        <Field
          label="Aspect ratio"
          value={typeof data.aspect_ratio === "number" ? data.aspect_ratio : "—"}
        />
        <Field label="FPS" value={num(data.fps)} />
        <Field
          label="Video codec"
          value={typeof data.video_codec === "string" ? data.video_codec : "—"}
        />
        <Field
          label="Container"
          value={typeof data.container === "string" ? data.container : "—"}
        />
        <Field label="Video bitrate" value={num(data.video_bitrate)} />
        <Field label="Frame count" value={num(data.frame_count)} />
        <Field label="Audio tracks" value={audio ? audio.length : "—"} />
      </dl>
      {typeof data.notes === "string" && data.notes && (
        <p className="mt-3 text-xs leading-relaxed text-muted">{data.notes}</p>
      )}
    </div>
  );
}

interface TranscriptSegment {
  start?: number | null;
  end?: number | null;
  text?: string;
  speaker?: string | null;
}

function TranscriptSection({ stage }: { stage: AnalysisStage | undefined }) {
  const data = (stage?.data ?? {}) as Record<string, unknown>;
  const segments = (Array.isArray(data.segments) ? data.segments : []) as TranscriptSegment[];
  if (segments.length === 0) {
    return <p className="text-sm text-muted">The transcript is empty.</p>;
  }
  return (
    <div>
      <div className="mb-3 flex flex-wrap gap-x-5 gap-y-1 text-xs text-muted">
        {typeof data.language === "string" && <span>Language: {data.language}</span>}
        {typeof data.word_count === "number" && <span>{data.word_count} words</span>}
        {typeof data.confidence === "number" && (
          <span>Confidence: {Math.round(data.confidence * 100)}%</span>
        )}
      </div>
      <ol className="max-h-80 space-y-2 overflow-y-auto pr-1">
        {segments.map((seg, i) => (
          <li key={i} className="flex gap-3 text-sm">
            <span className="shrink-0 tabular-nums text-xs text-muted">
              {formatDuration(seg.start ?? 0)}
            </span>
            <span className="text-white/85">
              {seg.speaker && <span className="mr-1.5 text-accent">{seg.speaker}:</span>}
              {seg.text}
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}

interface SpeakerTurn {
  speaker?: string;
  start?: number | null;
  end?: number | null;
}

function SpeakerSection({ stage }: { stage: AnalysisStage | undefined }) {
  const data = (stage?.data ?? {}) as Record<string, unknown>;
  const timeline = (Array.isArray(data.timeline) ? data.timeline : []) as SpeakerTurn[];
  const speakers = (Array.isArray(data.speakers) ? data.speakers : []) as string[];
  return (
    <div>
      <div className="mb-3 flex flex-wrap gap-2">
        {speakers.map((s) => (
          <span key={s} className="rounded-full bg-white/5 px-2.5 py-1 text-xs text-white/80">
            {s}
          </span>
        ))}
      </div>
      <ol className="max-h-72 space-y-1.5 overflow-y-auto pr-1">
        {timeline.map((turn, i) => (
          <li key={i} className="flex items-center gap-3 text-sm">
            <span className="shrink-0 tabular-nums text-xs text-muted">
              {formatDuration(turn.start ?? 0)} – {formatDuration(turn.end ?? 0)}
            </span>
            <span className="text-accent">{turn.speaker}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}

/** Render either real content (when completed) or an honest unavailable panel. */
function Signal({
  analysis,
  name,
  render,
}: {
  analysis: Analysis;
  name: string;
  render: (stage: AnalysisStage) => ReactNode;
}) {
  const stage = stageOf(analysis, name);
  if (stage && stage.status === "completed") return <>{render(stage)}</>;
  return <UnavailablePanel stage={stage} projectId={analysis.project_id} />;
}

export function AnalysisViewer({ analysis }: { analysis: Analysis }) {
  return (
    <div className="space-y-6">
      <Section icon={<FileVideoIcon className="h-4 w-4" />} title="Technical profile">
        <Signal
          analysis={analysis}
          name="video_inspection"
          render={(s) => <MetadataSection stage={s} />}
        />
      </Section>

      <Section icon={<TextIcon className="h-4 w-4" />} title="Transcript">
        <Signal
          analysis={analysis}
          name="speech_transcription"
          render={(s) => <TranscriptSection stage={s} />}
        />
      </Section>

      <Section icon={<UserIcon className="h-4 w-4" />} title="Speaker timeline">
        <Signal
          analysis={analysis}
          name="speaker_segmentation"
          render={(s) => <SpeakerSection stage={s} />}
        />
      </Section>

      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <Section icon={<FileVideoIcon className="h-4 w-4" />} title="Scene timeline">
          <Signal
            analysis={analysis}
            name="scene_detection"
            render={() => <p className="text-sm text-muted">Scenes detected.</p>}
          />
        </Section>
        <Section icon={<TextIcon className="h-4 w-4" />} title="On-screen text (OCR)">
          <Signal
            analysis={analysis}
            name="ocr"
            render={() => <p className="text-sm text-muted">Text extracted.</p>}
          />
        </Section>
      </div>

      <Section icon={<BrainIcon className="h-4 w-4" />} title="Emotion timeline">
        <Signal
          analysis={analysis}
          name="emotion_timeline"
          render={() => (
            <p className="text-sm text-muted">
              Emotion is an estimation and is shown with confidence when available.
            </p>
          )}
        />
      </Section>
    </div>
  );
}
