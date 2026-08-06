"use client";

/**
 * Side-by-side clip brief comparison.
 *
 * Comparison shows differences only. No brief is scored, preferred or chosen,
 * completeness is not treated as a quality comparison, and a field missing from
 * one brief stays visibly missing rather than being filled from another.
 */

import {
  NO_WINNER_NOTICE,
  comparisonDifferences,
  comparisonMissingFields,
  type ClipBriefComparison,
} from "@/lib/clipBriefReview";

function renderValue(value: unknown, present: boolean): string {
  if (!present) return "— missing —";
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2);
}

export function BobaClipBriefComparisonView({
  comparison,
  differencesOnly,
  onDifferencesOnlyChange,
}: {
  comparison: ClipBriefComparison | null;
  differencesOnly: boolean;
  onDifferencesOnlyChange: (value: boolean) => void;
}) {
  if (!comparison) {
    return (
      <p className="text-sm text-white/60">
        Select at least two clip briefs to compare them.
      </p>
    );
  }
  const rows = differencesOnly
    ? comparisonDifferences(comparison)
    : comparison.field_comparisons;
  const missing = comparisonMissingFields(comparison);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-white/60">
          Comparing {comparison.brief_ids.join(", ")} ·{" "}
          {comparison.same_candidate
            ? "same candidate identity"
            : "different candidate identities"}
        </p>
        <label className="flex items-center gap-1.5 text-xs text-white/50">
          <input
            type="checkbox"
            checked={differencesOnly}
            onChange={(event) => onDifferencesOnlyChange(event.target.checked)}
            aria-label="Show differing fields only"
          />
          Differences only
        </label>
      </div>

      <p className="text-[11px] text-white/45">{NO_WINNER_NOTICE}</p>
      {missing.length > 0 ? (
        <p className="text-[11px] text-amber-200/80">
          {missing.length} field(s) are missing from at least one brief and are shown as
          missing.
        </p>
      ) : null}

      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-left text-xs">
          <thead>
            <tr className="text-white/45">
              <th scope="col" className="py-1 pr-3 font-normal">
                Field
              </th>
              {comparison.brief_ids.map((briefId) => (
                <th key={briefId} scope="col" className="py-1 pr-3 font-normal">
                  {briefId}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.field_path} className="border-t border-white/10 align-top">
                <th scope="row" className="py-2 pr-3 font-normal text-white/70">
                  {row.field_display_name}
                  {row.required_by_owner_schema ? (
                    <span className="ml-1 text-[10px] text-white/40">required</span>
                  ) : null}
                </th>
                {row.values.map((value) => (
                  <td
                    key={`${row.field_path}:${value.brief_id}`}
                    className="py-2 pr-3 text-white/70"
                    data-present={value.present}
                  >
                    <pre className="whitespace-pre-wrap break-words">
                      {renderValue(value.original_value, value.present)}
                    </pre>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {comparison.limitations.length > 0 ? (
        <ul className="space-y-0.5 text-[11px] text-white/40">
          {comparison.limitations.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
