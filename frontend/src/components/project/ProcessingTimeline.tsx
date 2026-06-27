"use client";

/**
 * The processing timeline - an intelligent, honest view of the editing pipeline.
 *
 * Each stage shows an animated icon, description, status, elapsed/estimated
 * time, and an expandable explanation. HONESTY: only "Upload" is genuinely
 * complete (with its real elapsed time); every later stage shows "Waiting for
 * processing" (or "Queued") - never fabricated as done. The same component will
 * reflect real per-stage progress once the pipeline is connected.
 */
import { CheckCircleIcon, ChevronDownIcon } from "@/components/icons";
import { formatMillis } from "@/lib/format";
import type { ProjectStatus } from "@/lib/types";

interface Stage {
  title: string;
  description: string;
  explanation: string;
}

const STAGES: Stage[] = [
  {
    title: "Upload",
    description: "Securely storing your video.",
    explanation: "Your original video is streamed to secure storage and kept safe for editing.",
  },
  {
    title: "Audio Extraction",
    description: "Separating the audio track for analysis.",
    explanation: "The audio is isolated so speech and sound can be analysed independently.",
  },
  {
    title: "Speech Recognition",
    description: "Transcribing what is said, with timestamps.",
    explanation: "Every word is transcribed with precise timing — the backbone of accurate captions.",
  },
  {
    title: "Story Understanding",
    description: "Mapping setups, payoffs, and arcs.",
    explanation: "Olympus reads the narrative — not just keywords — to find complete, standalone moments.",
  },
  {
    title: "Finding Emotional Moments",
    description: "Locating the moments that land.",
    explanation: "Emotional peaks are identified so the strongest moments become Shorts.",
  },
  {
    title: "Finding Viral Hooks",
    description: "Spotting share-worthy openings.",
    explanation: "Honest, attention-earning hooks are found — never clickbait the content can't pay off.",
  },
  {
    title: "Planning Edits",
    description: "Designing distinct, non-overlapping Shorts.",
    explanation: "A small set of genuinely different Shorts is planned, each with its own thesis.",
  },
  {
    title: "Caption Planning",
    description: "Writing clean, well-timed captions.",
    explanation: "Readable, emphasis-aware captions are timed to the speech for muted viewing.",
  },
  {
    title: "Rendering",
    description: "Producing your finished vertical Shorts.",
    explanation: "Each Short is composited and encoded into a polished, creator-ready vertical video.",
  },
];

type StageState = "done" | "queued" | "waiting";

function stateFor(index: number, status: ProjectStatus): StageState {
  if (index === 0) return "done";
  if (status === "queued" || status === "processing") return "queued";
  return "waiting";
}

const STATE_LABEL: Record<StageState, string> = {
  done: "Done",
  queued: "Queued",
  waiting: "Waiting for processing",
};

function StageIcon({ state }: { state: StageState }) {
  if (state === "done") {
    return (
      <span className="flex h-8 w-8 items-center justify-center rounded-full bg-green-500/15">
        <CheckCircleIcon className="h-5 w-5 text-green-400" />
      </span>
    );
  }
  return (
    <span
      className={`flex h-8 w-8 items-center justify-center rounded-full ${
        state === "queued" ? "bg-accent/15" : "bg-white/5"
      }`}
    >
      <span
        className={`h-2 w-2 rounded-full ${
          state === "queued" ? "bg-accent animate-pulse-soft" : "bg-white/25"
        }`}
      />
    </span>
  );
}

export function ProcessingTimeline({
  status,
  uploadDurationMs,
}: {
  status: ProjectStatus;
  uploadDurationMs: number | null;
}) {
  return (
    <ol className="relative">
      {STAGES.map((stage, index) => {
        const state = stateFor(index, status);
        const isLast = index === STAGES.length - 1;
        const elapsed = index === 0 ? formatMillis(uploadDurationMs) : "—";
        return (
          <li key={stage.title} className="relative flex gap-4 pb-5 last:pb-0">
            {!isLast && (
              <span aria-hidden className="absolute left-[15px] top-9 h-[calc(100%-1rem)] w-px bg-white/10" />
            )}
            <StageIcon state={state} />
            <details className="group min-w-0 flex-1">
              <summary className="flex cursor-pointer list-none items-start justify-between gap-3 pt-1">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <p className={`text-sm font-medium ${state === "waiting" ? "text-muted" : "text-white"}`}>
                      {stage.title}
                    </p>
                    <ChevronDownIcon className="h-3.5 w-3.5 text-muted transition-transform group-open:rotate-180" />
                  </div>
                  <p className="mt-0.5 text-sm text-muted">{stage.description}</p>
                </div>
                <div className="shrink-0 text-right">
                  <p
                    className={`text-xs ${
                      state === "done" ? "text-green-400" : state === "queued" ? "text-accent" : "text-muted"
                    }`}
                  >
                    {STATE_LABEL[state]}
                  </p>
                  <p className="mt-0.5 text-[11px] tabular-nums text-muted">
                    {elapsed} · est —
                  </p>
                </div>
              </summary>
              <p className="mt-2 rounded-lg bg-white/[0.03] px-3 py-2 text-xs leading-relaxed text-muted">
                {stage.explanation}
              </p>
            </details>
          </li>
        );
      })}
    </ol>
  );
}
