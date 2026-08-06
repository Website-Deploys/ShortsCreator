"use client";

/**
 * Evidence, conflict and source-card surfaces.
 *
 * Evidence is linked only through identities the owning modules persisted.
 * Missing evidence is shown as missing and is never treated as a pass, and a
 * conflict is reported unresolved rather than being decided here.
 */

import {
  conflictResolutionLabel,
  conflictSummary,
  describeSourceCard,
  formatSourceWindow,
  type ClipBriefConflict,
  type ClipBriefEvidenceLink,
  type ClipBriefSourceCard,
} from "@/lib/clipBriefReview";

export function BobaClipBriefEvidence({
  links,
  missingCount,
}: {
  links: ClipBriefEvidenceLink[];
  missingCount: number;
}) {
  if (links.length === 0) {
    return (
      <p className="text-sm text-white/60">
        No canonical evidence link exists for this brief yet.
      </p>
    );
  }
  return (
    <div className="space-y-2">
      <p className="text-xs text-white/60">
        {missingCount === 0
          ? "Every linked canonical source record is present."
          : `${missingCount} linked source record(s) missing. Missing evidence is never a pass.`}
      </p>
      <ul className="space-y-2">
        {links.map((link) => (
          <li
            key={link.evidence_link_id}
            className="rounded border border-white/10 bg-white/[0.02] p-3 text-xs"
            data-missing={link.missing}
          >
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <p className="text-sm text-white">{link.evidence_type}</p>
              <span className="text-[11px] text-white/45">
                {link.advisory ? "advisory" : "authoritative"} · {link.source_module_id}
              </span>
            </div>
            <p className="mt-1 text-white/70">{link.bounded_summary}</p>
            <p className="mt-1 text-white/45">
              Field {link.brief_field_path} ·{" "}
              {link.exact_identity_match
                ? "exact identity match"
                : "no exact identity match"}{" "}
              · {link.digest_match ? "digest recorded" : "no digest"}
            </p>
            {link.source_start_seconds !== null && link.source_end_seconds !== null ? (
              <p className="mt-1 text-white/45">
                Source window{" "}
                {formatSourceWindow(link.source_start_seconds, link.source_end_seconds)}
              </p>
            ) : null}
            {link.transcript_segment_ids.length > 0 ? (
              <p className="mt-1 text-white/45">
                Owner transcript segments: {link.transcript_segment_ids.join(", ")}
              </p>
            ) : null}
            {link.limitations.length > 0 ? (
              <ul className="mt-1 space-y-0.5 text-white/40">
                {link.limitations.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function BobaClipBriefConflicts({
  conflicts,
}: {
  conflicts: ClipBriefConflict[];
}) {
  return (
    <div className="space-y-2">
      <p className="text-xs text-white/60">{conflictSummary(conflicts)}</p>
      {conflicts.length > 0 ? (
        <ul className="space-y-2">
          {conflicts.map((conflict) => (
            <li
              key={conflict.conflict_record_id}
              className="rounded border border-amber-300/30 bg-amber-300/[0.05] p-3 text-xs"
              data-blocking={conflict.blocks_review_action}
            >
              <p className="text-sm text-white">{conflict.conflict_type}</p>
              <p className="mt-1 text-white/70">{conflict.bounded_summary}</p>
              <p className="mt-1 text-white/50">
                Brief value: {conflict.value_a || "not recorded"} · Source value:{" "}
                {conflict.value_b || "not recorded"}
              </p>
              <p className="mt-1 text-white/50">
                Fields: {conflict.brief_field_paths.join(", ") || "not recorded"}
              </p>
              <p className="mt-1 text-white/50">{conflictResolutionLabel(conflict)}</p>
              {conflict.blocks_review_action ? (
                <p className="mt-1 text-amber-100">
                  This conflict blocks the review action for this brief.
                </p>
              ) : null}
              {conflict.limitations.length > 0 ? (
                <ul className="mt-1 space-y-0.5 text-white/40">
                  {conflict.limitations.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export function BobaClipBriefSourceCards({ cards }: { cards: ClipBriefSourceCard[] }) {
  if (cards.length === 0) {
    return <p className="text-sm text-white/60">No source card is available.</p>;
  }
  return (
    <ul className="space-y-2">
      {cards.map((card) => (
        <li
          key={card.source_card_id}
          className="rounded border border-white/10 bg-white/[0.02] p-3 text-xs"
          data-available={card.current}
        >
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <p className="text-sm text-white">{card.title}</p>
            <span className="text-[11px] text-white/45">{card.authority_domain}</span>
          </div>
          <p className="mt-1 text-white/70">{describeSourceCard(card)}</p>
          {card.bounded_summary ? (
            <p className="mt-1 text-white/60">{card.bounded_summary}</p>
          ) : null}
          {card.blocking ? (
            <p className="mt-1 text-rose-200/90">
              This owning module reports a blocking state. Only that module can clear it.
            </p>
          ) : null}
          {card.limitations.length > 0 ? (
            <ul className="mt-1 space-y-0.5 text-white/40">
              {card.limitations.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          ) : null}
        </li>
      ))}
    </ul>
  );
}
