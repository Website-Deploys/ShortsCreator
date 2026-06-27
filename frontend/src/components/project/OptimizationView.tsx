"use client";

/**
 * The Optimization view — a read-only window into the post-render polish the
 * engine produced from the rendered Short and the upstream decisions.
 *
 * It surfaces only REAL engine outputs: a quality dashboard (graded dimensions +
 * honest UNKNOWNs), the audio enhancement report (honestly unavailable here, with
 * the reason), copyright-free music recommendations (with license + provider
 * availability), caption improvements (measured reading speed), thumbnail
 * candidates (timestamps real, image scores UNKNOWN), a variant comparison, the
 * per-platform export specs, and a download center for the package's real assets
 * (metadata, captions, MP4) — with unavailable assets shown honestly, never as a
 * broken download.
 */
import { useMemo, useState } from "react";

import { AlertIcon, CheckCircleIcon, DownloadIcon, SlidersIcon } from "@/components/icons";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { mediaUrls } from "@/lib/apiClient";
import {
  assetLabel,
  formatConfidence,
  formatScore,
  humanize,
  isTerminal,
  parseCaptionSummaries,
  parseMusic,
  parseQuality,
  platformLabel,
} from "@/lib/optimization";
import type { Optimization } from "@/lib/types";

/* ------------------------------ small helpers ----------------------------- */

function stageData(opt: Optimization, name: string): Record<string, unknown> | null {
  const stage = opt.stages.find((s) => s.stage === name);
  return stage?.status === "completed" ? (stage.data ?? null) : null;
}

function stageReason(opt: Optimization, name: string): string | null {
  const stage = opt.stages.find((s) => s.stage === name);
  if (!stage) return null;
  return stage.reason ?? stage.error ?? null;
}

function asArray(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? (value as Record<string, unknown>[]) : [];
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h4 className="mb-3 text-sm font-semibold text-white">{children}</h4>;
}

/* ------------------------------ quality dashboard ------------------------- */

function ScoreBar({ score }: { score: number | null }) {
  if (score == null) {
    return (
      <span className="rounded bg-amber-500/10 px-2 py-0.5 text-[11px] text-amber-300">
        Unknown
      </span>
    );
  }
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-24 overflow-hidden rounded-full bg-white/10">
        <div
          className="h-full rounded-full bg-emerald-400"
          style={{ width: `${Math.round(score * 100)}%` }}
        />
      </div>
      <span className="w-9 text-right text-xs tabular-nums text-white">{formatScore(score)}</span>
    </div>
  );
}

function QualityDashboard({ clipId, report }: { clipId: string; report: Record<string, unknown> }) {
  const clips = parseQuality(report);
  const clip = clips.find((c) => c.clipId === clipId) ?? clips[0];
  if (!clip) return null;
  return (
    <Card>
      <div className="flex items-center justify-between">
        <SectionTitle>Quality dashboard</SectionTitle>
        <div className="text-right">
          <div className="text-2xl font-semibold text-white">{formatScore(clip.overall)}</div>
          <div className="text-[11px] text-muted">overall (graded dims only)</div>
        </div>
      </div>
      <ul className="mt-2 space-y-2.5">
        {clip.dimensions.map((d) => (
          <li key={d.dimension} className="flex items-center justify-between gap-4">
            <div className="min-w-0">
              <p className="truncate text-sm text-white">{humanize(d.dimension)}</p>
              <p className="truncate text-[11px] text-muted" title={d.limitations}>
                {d.score == null ? d.limitations : d.reasoning}
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-3">
              <ScoreBar score={d.score} />
              <span className="w-16 text-right text-[11px] text-muted">
                conf {formatConfidence(d.confidence)}
              </span>
            </div>
          </li>
        ))}
      </ul>
      {clip.unknownDimensions.length > 0 && (
        <p className="mt-4 rounded-lg bg-amber-500/[0.06] px-3 py-2 text-xs leading-relaxed text-amber-200/90">
          {clip.unknownDimensions.length} dimension(s) are honestly UNKNOWN (they need the rendered
          media or a model that isn&apos;t available):{" "}
          {clip.unknownDimensions.map(humanize).join(", ")}.
        </p>
      )}
    </Card>
  );
}

/* ------------------------------ music panel ------------------------------- */

function MusicPanel({ clipId, music }: { clipId: string; music: Record<string, unknown> }) {
  const { clips, providers } = parseMusic(music);
  const clip = clips.find((c) => c.clipId === clipId) ?? clips[0];
  return (
    <Card>
      <SectionTitle>Copyright-free music</SectionTitle>
      {clip && clip.recommendations.length > 0 ? (
        <ul className="space-y-2">
          {clip.recommendations.map((r, i) => (
            <li
              key={`${r.title}-${i}`}
              className="flex items-center justify-between gap-3 rounded-lg border border-white/10 px-3 py-2"
            >
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-white">{r.title}</p>
                <p className="truncate text-[11px] text-muted">
                  {[r.genre, r.bpm ? `${r.bpm} BPM` : null, r.license]
                    .filter(Boolean)
                    .join(" · ")}
                </p>
              </div>
              <span className="shrink-0 text-xs text-emerald-300">{formatScore(r.score)}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted">No recommendations for this clip.</p>
      )}
      <div className="mt-4 border-t border-white/10 pt-3">
        <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted">
          Providers
        </p>
        <div className="flex flex-wrap gap-2">
          {providers.map((p) => (
            <span
              key={p.provider}
              title={p.reason ?? undefined}
              className={`rounded px-2 py-0.5 text-[11px] ${
                p.available
                  ? "bg-emerald-500/10 text-emerald-300"
                  : "bg-white/5 text-muted"
              }`}
            >
              {humanize(p.provider)}: {p.available ? "available" : "unavailable"}
            </span>
          ))}
        </div>
      </div>
    </Card>
  );
}

/* ------------------------------ captions panel ---------------------------- */

function CaptionPanel({ clipId, data }: { clipId: string; data: Record<string, unknown> }) {
  const summaries = parseCaptionSummaries(data);
  const s = summaries.find((c) => c.clipId === clipId) ?? summaries[0];
  if (!s) return null;
  return (
    <Card>
      <SectionTitle>Caption improvements</SectionTitle>
      <div className="grid grid-cols-4 gap-2 text-center">
        {[
          { label: "Total", value: s.total, tone: "text-white" },
          { label: "Comfortable", value: s.comfortable, tone: "text-emerald-300" },
          { label: "Brisk", value: s.brisk, tone: "text-amber-300" },
          { label: "Too fast", value: s.tooFast, tone: "text-rose-300" },
        ].map((stat) => (
          <div key={stat.label} className="rounded-lg bg-white/[0.03] px-2 py-3">
            <div className={`text-lg font-semibold ${stat.tone}`}>{stat.value}</div>
            <div className="text-[10px] uppercase tracking-wide text-muted">{stat.label}</div>
          </div>
        ))}
      </div>
      <p className="mt-3 text-xs text-muted">
        Reading speed measured against a ~17 CPS comfort target; line breaks balanced to two lines
        for vertical legibility.
      </p>
    </Card>
  );
}

/* ------------------------------ thumbnails panel -------------------------- */

function ThumbnailPanel({ clipId, data }: { clipId: string; data: Record<string, unknown> }) {
  const clip = asArray(data.clips).find((c) => c.clip_id === clipId);
  const candidates = asArray(clip?.candidates);
  return (
    <Card>
      <SectionTitle>Thumbnail candidates</SectionTitle>
      {candidates.length > 0 ? (
        <ul className="space-y-1.5">
          {candidates.map((c, i) => (
            <li key={i} className="flex items-center justify-between gap-3 text-sm">
              <span className="text-white">{humanize(String(c.reason ?? "candidate"))}</span>
              <span className="tabular-nums text-muted">{Number(c.timestamp ?? 0).toFixed(1)}s</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted">No candidate frames.</p>
      )}
      <p className="mt-3 rounded-lg bg-amber-500/[0.06] px-3 py-2 text-xs leading-relaxed text-amber-200/90">
        Candidate timestamps are real (chosen from timeline moments). Image-level scores
        (expression, composition, contrast) are UNKNOWN — no vision model or frame decoder is
        available, and scores are never invented.
      </p>
    </Card>
  );
}

/* ------------------------------ variants panel ---------------------------- */

function VariantPanel({ clipId, data }: { clipId: string; data: Record<string, unknown> }) {
  const clip = asArray(data.clips).find((c) => c.clip_id === clipId);
  const variants = asArray(clip?.variants);
  return (
    <Card>
      <SectionTitle>Export variants</SectionTitle>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {variants.map((v) => (
          <div key={String(v.id)} className="rounded-lg border border-white/10 p-3">
            <div className="flex items-center gap-2">
              <span className="flex h-5 w-5 items-center justify-center rounded bg-accent/15 text-[11px] font-semibold text-accent">
                {String(v.id)}
              </span>
              <p className="text-sm font-medium text-white">{String(v.name ?? "")}</p>
            </div>
            <p className="mt-1.5 text-xs text-muted">{String(v.description ?? "")}</p>
            <p className="mt-2 text-[11px] text-muted">
              <span className="text-white/70">Why:</span> {String(v.why ?? "")}
            </p>
            <p className="mt-1 text-[11px] text-muted">
              Confidence {formatConfidence(typeof v.confidence === "number" ? v.confidence : null)}
            </p>
          </div>
        ))}
      </div>
      <p className="mt-3 text-xs text-muted">
        Each variant is a plan describing what changes vs the base edit. Rendering the variants is
        the Rendering Engine&apos;s job (not done here).
      </p>
    </Card>
  );
}

/* ------------------------------ platform panel ---------------------------- */

function PlatformPanel({ data }: { data: Record<string, unknown> }) {
  const profiles = (data.profiles ?? {}) as Record<string, Record<string, unknown>>;
  const order = Array.isArray(data.platform_order) ? (data.platform_order as string[]) : [];
  return (
    <Card>
      <SectionTitle>Platform export specs</SectionTitle>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead className="text-muted">
            <tr>
              <th className="pb-2 pr-4 font-medium">Platform</th>
              <th className="pb-2 pr-4 font-medium">Resolution</th>
              <th className="pb-2 pr-4 font-medium">Codec</th>
              <th className="pb-2 pr-4 font-medium">Bitrate</th>
              <th className="pb-2 font-medium">Max</th>
            </tr>
          </thead>
          <tbody className="text-white/90">
            {order.map((key) => {
              const p = profiles[key] ?? {};
              return (
                <tr key={key} className="border-t border-white/5">
                  <td className="py-1.5 pr-4">{platformLabel(key)}</td>
                  <td className="py-1.5 pr-4 tabular-nums">{String(p.resolution ?? "—")}</td>
                  <td className="py-1.5 pr-4">{String(p.video_codec ?? "—")}</td>
                  <td className="py-1.5 pr-4 tabular-nums">
                    {p.recommended_bitrate_kbps ? `${p.recommended_bitrate_kbps} kbps` : "—"}
                  </td>
                  <td className="py-1.5 tabular-nums">
                    {p.max_duration_s ? `${p.max_duration_s}s` : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

/* ------------------------------ download center --------------------------- */

function DownloadCenter({
  projectId,
  clipId,
  packages,
}: {
  projectId: string;
  clipId: string;
  packages: Record<string, unknown>[];
}) {
  const pkg = packages.find((p) => p.clip_id === clipId) ?? packages[0];
  const assets = asArray(pkg?.assets);
  return (
    <Card>
      <SectionTitle>Publish package &amp; downloads</SectionTitle>
      <ul className="space-y-1.5">
        {assets.map((a, i) => {
          const kind = String(a.kind);
          const available = a.status === "available";
          return (
            <li
              key={`${kind}-${i}`}
              className="flex items-center justify-between gap-3 rounded-lg border border-white/10 px-3 py-2"
            >
              <div className="flex min-w-0 items-center gap-2">
                {available ? (
                  <CheckCircleIcon className="h-4 w-4 shrink-0 text-emerald-400" />
                ) : (
                  <AlertIcon className="h-4 w-4 shrink-0 text-amber-300" />
                )}
                <div className="min-w-0">
                  <p className="truncate text-sm text-white">{assetLabel(kind)}</p>
                  {!available && a.reason != null && (
                    <p className="truncate text-[11px] text-muted" title={String(a.reason)}>
                      {String(a.reason)}
                    </p>
                  )}
                </div>
              </div>
              {available ? (
                <a
                  href={mediaUrls.packageAsset(projectId, String(pkg.clip_id), kind)}
                  className="flex shrink-0 items-center gap-1.5 rounded-lg border border-white/10 px-2.5 py-1 text-xs text-white transition-colors hover:border-white/30"
                  download
                >
                  <DownloadIcon className="h-3.5 w-3.5" />
                  Download
                </a>
              ) : (
                <span className="shrink-0 text-[11px] text-amber-300">Unavailable</span>
              )}
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

/* ------------------------------ audio report ------------------------------ */

function AudioReport({ optimization }: { optimization: Optimization }) {
  const stages = [
    "audio_analysis",
    "voice_enhancement",
    "noise_reduction",
    "loudness_normalization",
    "silence_refinement",
    "music_mixing",
  ];
  return (
    <Card>
      <SectionTitle>Audio enhancement report</SectionTitle>
      <ul className="space-y-1.5">
        {stages.map((name) => {
          const stage = optimization.stages.find((s) => s.stage === name);
          if (!stage) return null;
          const ok = stage.status === "completed";
          return (
            <li key={name} className="flex items-start justify-between gap-3 text-sm">
              <span className="text-white">{stage.label}</span>
              <span
                className={`shrink-0 text-xs ${ok ? "text-emerald-300" : "text-amber-300"}`}
                title={stage.reason ?? undefined}
              >
                {ok ? "Done" : "Unavailable"}
              </span>
            </li>
          );
        })}
      </ul>
      <p className="mt-3 text-xs leading-relaxed text-muted">
        Audio enhancement runs only when a real audio model is installed. Where it is absent, the
        engine reports it honestly rather than claiming an enhancement it did not perform.
      </p>
    </Card>
  );
}

/* --------------------------------- view ----------------------------------- */

export function OptimizationView({ optimization }: { optimization: Optimization }) {
  const terminal = isTerminal(optimization);

  const packages = useMemo(
    () => asArray(stageData(optimization, "publish_package_creation")?.packages),
    [optimization],
  );
  const quality = stageData(optimization, "quality_evaluation");
  const music = stageData(optimization, "music_recommendation");
  const captions = stageData(optimization, "caption_optimization");
  const thumbnails = stageData(optimization, "thumbnail_optimization");
  const variants = stageData(optimization, "variant_generation");
  const platform = stageData(optimization, "platform_optimization");
  const loadReason = stageReason(optimization, "load_render");

  const clipIds = useMemo(() => {
    const ids = packages.map((p) => String(p.clip_id));
    if (ids.length > 0) return ids;
    return parseQuality(quality).map((c) => c.clipId);
  }, [packages, quality]);

  const [selectedClipId, setSelectedClipId] = useState<string | null>(null);
  const selected = selectedClipId && clipIds.includes(selectedClipId) ? selectedClipId : clipIds[0];

  if (!terminal) {
    return (
      <Card>
        <p className="text-sm text-muted">Optimizing… results appear as each stage completes.</p>
      </Card>
    );
  }

  if (clipIds.length === 0) {
    return (
      <EmptyState
        icon={<SlidersIcon className="h-6 w-6" />}
        title="No optimized Shorts were produced"
        description={
          loadReason ??
          "The Optimization Engine had no rendered Shorts (or edit timelines) to operate on. Once the Rendering Engine produces an MP4, its optimized package will appear here."
        }
      />
    );
  }

  return (
    <div className="space-y-6">
      {loadReason && (
        <div className="flex items-start gap-3 rounded-xl border border-amber-500/20 bg-amber-500/[0.06] px-4 py-3">
          <AlertIcon className="mt-0.5 h-5 w-5 shrink-0 text-amber-300" />
          <p className="text-sm leading-relaxed text-amber-200/90">{loadReason}</p>
        </div>
      )}

      {clipIds.length > 1 && (
        <div className="flex flex-wrap gap-2" role="tablist" aria-label="Clips">
          {clipIds.map((cid) => {
            const active = cid === selected;
            return (
              <button
                key={cid}
                type="button"
                role="tab"
                aria-selected={active}
                onClick={() => setSelectedClipId(cid)}
                className={`rounded-lg border px-3 py-1.5 text-sm transition-colors ${
                  active
                    ? "border-accent bg-accent/5 text-white"
                    : "border-white/10 bg-white/[0.02] text-muted hover:border-white/20"
                }`}
              >
                {cid}
              </button>
            );
          })}
        </div>
      )}

      {selected && (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          {quality && <QualityDashboard clipId={selected} report={quality} />}
          {music && <MusicPanel clipId={selected} music={music} />}
          {captions && <CaptionPanel clipId={selected} data={captions} />}
          <AudioReport optimization={optimization} />
          {thumbnails && <ThumbnailPanel clipId={selected} data={thumbnails} />}
          {variants && <VariantPanel clipId={selected} data={variants} />}
          {platform && (
            <div className="lg:col-span-2">
              <PlatformPanel data={platform} />
            </div>
          )}
          {packages.length > 0 && (
            <div className="lg:col-span-2">
              <DownloadCenter
                projectId={optimization.project_id}
                clipId={selected}
                packages={packages}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
