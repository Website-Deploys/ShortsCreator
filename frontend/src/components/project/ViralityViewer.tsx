"use client";

/**
 * The Virality Viewer — a read-only window into how viral every part of the
 * video is, and why.
 *
 * It leads with an honest overall score: the number is always shown next to its
 * confidence and an explicit "based on N of M categories" note, so a high score
 * built on thin evidence can never masquerade as certainty. Below it: per-category
 * score cards with expandable evidence + limitations, strengths/weaknesses/risks/
 * missed opportunities (each evidence-referenced), recommendations, a per-platform
 * comparison, and audience segments. Unavailable signals are shown honestly with
 * a re-run action — never fabricated.
 */
import { useState } from "react";

import {
  AlertIcon,
  ChevronDownIcon,
  MinusCircleIcon,
  RefreshIcon,
  ShareIcon,
  SparklesIcon,
  TargetIcon,
  TrendingUpIcon,
} from "@/components/icons";
import { Card } from "@/components/ui/Card";
import { useRerunViralityStage } from "@/lib/queries";
import {
  confidenceBand,
  CATEGORY_DEFS,
  formatPercent,
  formatTimestamp,
  humanize,
  parseAudience,
  parsePlatforms,
  parseScoreCards,
  parseSummary,
  scoreBand,
  type ScoreCard as ScoreCardModel,
} from "@/lib/virality";
import type { Virality } from "@/lib/types";

function Section({
  icon,
  title,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  children: React.ReactNode;
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

function EvidenceItem({ item }: { item: Record<string, unknown> }) {
  const ts = typeof item.timestamp === "number" ? formatTimestamp(item.timestamp) : null;
  const excerpt = typeof item.excerpt === "string" ? item.excerpt : "";
  const detail = typeof item.detail === "string" ? item.detail : "";
  const type = typeof item.type === "string" ? item.type : "";
  return (
    <li className="flex gap-2 text-xs leading-relaxed text-white/70">
      {ts && <span className="shrink-0 tabular-nums text-muted">{ts}</span>}
      <span>
        {type && <span className="mr-1 text-muted">{humanize(type)}:</span>}
        {excerpt ? `“${excerpt}”` : detail || "—"}
      </span>
    </li>
  );
}

function ScoreCard({ card, projectId }: { card: ScoreCardModel; projectId: string }) {
  const [open, setOpen] = useState(false);
  const rerun = useRerunViralityStage(projectId);

  if (card.status !== "completed" || card.score == null) {
    const failed = card.status === "failed";
    return (
      <div className="rounded-xl border border-white/10 bg-white/[0.02] p-4">
        <div className="flex items-center justify-between gap-2">
          <span className="text-sm font-medium text-muted">{card.label}</span>
          {(card.status === "unavailable" || failed) && (
            <button
              type="button"
              onClick={() => rerun.mutate(card.stage)}
              disabled={rerun.isPending}
              title="Re-run this stage"
              aria-label={`Re-run ${card.label}`}
              className="text-muted transition-colors hover:text-white disabled:opacity-50"
            >
              <RefreshIcon className={`h-3.5 w-3.5 ${rerun.isPending ? "animate-spin" : ""}`} />
            </button>
          )}
        </div>
        <div className="mt-2 flex items-start gap-2">
          {failed ? (
            <AlertIcon className="mt-0.5 h-4 w-4 shrink-0 text-red-300" />
          ) : (
            <MinusCircleIcon className="mt-0.5 h-4 w-4 shrink-0 text-muted" />
          )}
          <p className="text-[11px] leading-relaxed text-muted">{card.reason || "Not available."}</p>
        </div>
      </div>
    );
  }

  const band = scoreBand(card.score);
  const conf = confidenceBand(card.confidence ?? 0);
  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.02] p-4">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-sm font-medium text-white">{card.label}</span>
        <span className={`text-lg font-semibold tabular-nums ${band.className}`}>
          {formatPercent(card.score)}
        </span>
      </div>
      <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-white/5">
        <div
          className="h-full rounded-full bg-accent"
          style={{ width: formatPercent(card.score) }}
        />
      </div>
      <div className="mt-2 flex items-center justify-between">
        <span className={`rounded px-1.5 py-0.5 text-[10px] ${conf.className}`}>
          {conf.label} conf · {formatPercent(card.confidence)}
        </span>
        {(card.evidence.length > 0 || card.limitations) && (
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            className="flex items-center gap-1 text-[11px] text-muted transition-colors hover:text-white"
          >
            Evidence
            <ChevronDownIcon className={`h-3 w-3 transition-transform ${open ? "rotate-180" : ""}`} />
          </button>
        )}
      </div>
      {open && (
        <div className="mt-2 border-t border-white/5 pt-2">
          {card.evidence.length > 0 ? (
            <ul className="space-y-1">
              {card.evidence.map((item, i) => (
                <EvidenceItem key={i} item={item} />
              ))}
            </ul>
          ) : (
            <p className="text-[11px] text-muted">No itemized evidence.</p>
          )}
          {card.limitations && (
            <p className="mt-2 text-[11px] italic leading-relaxed text-muted">{card.limitations}</p>
          )}
        </div>
      )}
    </div>
  );
}

function AssessmentList({
  title,
  items,
  tone,
}: {
  title: string;
  items: { category?: string; evidence: string }[];
  tone: "good" | "bad" | "warn";
}) {
  const dot =
    tone === "good" ? "bg-emerald-400" : tone === "warn" ? "bg-amber-400" : "bg-rose-400";
  return (
    <div>
      <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted">{title}</p>
      {items.length > 0 ? (
        <ul className="space-y-1.5">
          {items.map((item, i) => (
            <li key={i} className="flex items-start gap-2 text-sm text-white/85">
              <span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${dot}`} />
              <span>
                {item.category && (
                  <span className="mr-1 font-medium text-white">{humanize(item.category)}:</span>
                )}
                {item.evidence}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted">None identified.</p>
      )}
    </div>
  );
}

export function ViralityViewer({
  virality,
  durationSeconds,
}: {
  virality: Virality;
  durationSeconds?: number | null;
}) {
  const summary = parseSummary(virality);
  const cards = parseScoreCards(virality);
  const platforms = parsePlatforms(virality);
  const audience = parseAudience(virality);

  return (
    <div className="space-y-6">
      {/* Overall score — honesty-first */}
      <Section icon={<TrendingUpIcon className="h-4 w-4" />} title="Overall virality">
        {summary ? (
          <div>
            <div className="flex flex-wrap items-end gap-x-4 gap-y-2">
              <span className="text-4xl font-semibold tabular-nums text-white">
                {summary.overallScore == null ? "—" : formatPercent(summary.overallScore)}
              </span>
              <div className="mb-1">
                <span
                  className={`rounded px-2 py-0.5 text-xs ${confidenceBand(summary.overallConfidence).className}`}
                >
                  {confidenceBand(summary.overallConfidence).label} confidence ·{" "}
                  {formatPercent(summary.overallConfidence)}
                </span>
                <p className="mt-1 text-[11px] text-muted">
                  Based on {summary.availableCategories.length} of {CATEGORY_DEFS.length} categories
                  {summary.pendingCategories.length > 0 &&
                    ` · ${summary.pendingCategories.length} pending (insufficient evidence)`}
                </p>
              </div>
            </div>
            {summary.overallConfidence < 0.4 && (
              <p className="mt-3 rounded-lg border border-amber-500/20 bg-amber-500/5 px-3 py-2 text-xs leading-relaxed text-amber-200/90">
                This score is based on limited evidence. Most categories are pending because the
                upstream transcript/story signals are unavailable, so treat the number as
                low-confidence, not a verdict.
              </p>
            )}
            {summary.limitations && (
              <p className="mt-3 text-[11px] italic leading-relaxed text-muted">
                {summary.limitations}
              </p>
            )}
          </div>
        ) : (
          <p className="text-sm text-muted">
            The overall assessment becomes available once the pipeline has run.
          </p>
        )}
      </Section>

      {/* Category score cards */}
      <Section icon={<SparklesIcon className="h-4 w-4" />} title="Category scores">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {cards.map((card) => (
            <ScoreCard key={card.stage} card={card} projectId={virality.project_id} />
          ))}
        </div>
      </Section>

      {/* Strengths / weaknesses / risks / missed */}
      {summary && (
        <Section icon={<AlertIcon className="h-4 w-4" />} title="Strengths, weaknesses & risks">
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
            <AssessmentList title="Strengths" items={summary.strengths} tone="good" />
            <AssessmentList title="Weaknesses" items={summary.weaknesses} tone="bad" />
            <AssessmentList title="Risks" items={summary.risks} tone="warn" />
            <AssessmentList
              title="Missed opportunities"
              items={summary.missedOpportunities}
              tone="warn"
            />
          </div>
        </Section>
      )}

      {/* Recommendations */}
      {summary && (
        <Section icon={<SparklesIcon className="h-4 w-4" />} title="Recommendations">
          {summary.recommendations.length > 0 ? (
            <ul className="space-y-3">
              {summary.recommendations.map((rec, i) => (
                <li key={i} className="rounded-lg bg-white/[0.03] p-3">
                  <p className="text-sm font-medium text-white">{rec.title}</p>
                  <p className="mt-1 text-xs leading-relaxed text-white/70">Because {rec.reason}.</p>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted">
              No evidence-backed recommendations yet. Recommendations only appear when the analysis
              genuinely supports them.
            </p>
          )}
        </Section>
      )}

      {/* Platform comparison */}
      <Section icon={<ShareIcon className="h-4 w-4" />} title="Platform fit">
        {platforms.length > 0 ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            {platforms.map((p) => (
              <div key={p.key} className="rounded-xl border border-white/10 bg-white/[0.02] p-4">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="text-sm font-medium text-white">{p.label}</span>
                  <span className={`text-base font-semibold tabular-nums ${scoreBand(p.score).className}`}>
                    {formatPercent(p.score)}
                  </span>
                </div>
                <p className="mt-2 text-[11px] leading-relaxed text-muted">{p.reason}</p>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted">
            Platform fit becomes available once the video duration is known.
          </p>
        )}
      </Section>

      {/* Audience segments */}
      <Section icon={<TargetIcon className="h-4 w-4" />} title="Audience fit">
        {audience.length > 0 ? (
          <ul className="space-y-2">
            {audience.map((seg, i) => (
              <li key={i} className="flex flex-wrap items-center gap-2">
                <span className="text-sm text-white">{seg.segment}</span>
                <span className="text-[11px] text-muted">
                  from: {seg.matchedKeywords.join(", ")}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted">
            Audience segments are inferred from topic keywords, which require a transcript. None are
            available yet.
          </p>
        )}
      </Section>
    </div>
  );
}
