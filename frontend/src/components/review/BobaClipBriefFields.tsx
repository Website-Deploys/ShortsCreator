"use client";

/**
 * Field, section and completeness rendering for one exact clip brief.
 *
 * Values are shown exactly as the owner persisted them. Nothing is rewritten,
 * summarised into the value itself, filled in when missing, or graded. Plain
 * language sits beside the value, never in place of it.
 */

import {
  COMPLETENESS_NOTICE,
  completenessLabel,
  fieldDisplayValue,
  fieldStateGlyph,
  fieldStateLabel,
  isSectionExpanded,
  missingFieldSummary,
  requiredBadge,
  revisionNotice,
  sectionSummary,
  unsupportedSchemaNotice,
  type ClipBriefCompleteness,
  type ClipBriefFieldProjection,
  type ClipBriefReference,
  type ClipBriefSectionProjection,
} from "@/lib/clipBriefReview";

export function BobaClipBriefField({
  field,
  showTechnicalDetails,
}: {
  field: ClipBriefFieldProjection;
  showTechnicalDetails: boolean;
}) {
  return (
    <div
      className="rounded border border-white/10 bg-white/[0.02] p-3"
      data-field-path={field.field_path}
      data-state={fieldStateGlyph(field)}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-sm font-medium text-white">{field.field_display_name}</p>
        <span className="text-[11px] text-white/45">{requiredBadge(field)}</span>
      </div>

      <pre className="mt-2 whitespace-pre-wrap break-words text-xs text-white/80">
        {fieldDisplayValue(field)}
      </pre>

      <p className="mt-2 text-[11px] text-white/50">{field.bounded_explanation}</p>
      <p className="mt-0.5 text-[11px] text-white/40">{fieldStateLabel(field)}</p>

      {field.advisory ? (
        <p className="mt-1 text-[11px] text-sky-200/80">
          Advisory guidance from the owning module. It is not a decision.
        </p>
      ) : null}
      {field.truncated_for_display ? (
        <p className="mt-1 text-[11px] text-white/40">
          Shortened for display only. The stored value is unchanged.
        </p>
      ) : null}
      {showTechnicalDetails ? (
        <dl className="mt-2 grid grid-cols-2 gap-x-3 text-[11px] text-white/40">
          <div>
            <dt className="inline">Path: </dt>
            <dd className="inline">{field.field_path}</dd>
          </div>
          <div>
            <dt className="inline">Value type: </dt>
            <dd className="inline">{field.value_type}</dd>
          </div>
        </dl>
      ) : null}
      {field.limitations.length > 0 ? (
        <ul className="mt-1 space-y-0.5 text-[11px] text-white/40">
          {field.limitations.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export function BobaClipBriefSection({
  section,
  fields,
  activeSectionId,
  showEmptyOptionalFields,
  showTechnicalDetails,
  onToggle,
}: {
  section: ClipBriefSectionProjection;
  fields: ClipBriefFieldProjection[];
  activeSectionId: string | null;
  showEmptyOptionalFields: boolean;
  showTechnicalDetails: boolean;
  onToggle: (sectionId: string) => void;
}) {
  const expanded = isSectionExpanded(section, activeSectionId);
  const members = fields.filter((field) =>
    section.field_projection_ids.includes(field.field_projection_id),
  );
  const visible = members.filter(
    (field) =>
      showEmptyOptionalFields || field.required_by_owner_schema || field.present,
  );

  return (
    <section className="rounded-lg border border-white/10 bg-white/[0.02]">
      <button
        type="button"
        onClick={() => onToggle(section.section_id)}
        aria-expanded={expanded}
        className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left"
      >
        <span className="text-sm font-medium text-white">{section.title}</span>
        <span className="text-[11px] text-white/45">{sectionSummary(section)}</span>
      </button>

      {expanded ? (
        <div className="space-y-2 border-t border-white/10 p-3">
          {section.unavailable ? (
            <p className="text-xs text-white/50">{section.bounded_unavailable_message}</p>
          ) : null}
          {section.empty && !section.unavailable ? (
            <p className="text-xs text-white/50">{section.bounded_empty_message}</p>
          ) : null}
          {visible.map((field) => (
            <BobaClipBriefField
              key={field.field_projection_id}
              field={field}
              showTechnicalDetails={showTechnicalDetails}
            />
          ))}
          {visible.length < members.length ? (
            <p className="text-[11px] text-white/40">
              {members.length - visible.length} empty optional field(s) hidden. They are
              missing, not filled in.
            </p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

export function BobaClipBriefCompletenessReadout({
  completeness,
}: {
  completeness: ClipBriefCompleteness | null;
}) {
  if (!completeness) {
    return (
      <p className="text-sm text-white/60">
        No completeness record is available for this brief.
      </p>
    );
  }
  return (
    <div className="rounded-lg border border-white/10 bg-white/[0.02] p-3 text-sm">
      <p className="font-medium text-white">
        {completenessLabel(completeness.completeness_status)}
      </p>
      <p className="mt-1 text-xs text-white/60">
        {completeness.present_required_field_count} of{" "}
        {completeness.required_field_count} required owner-schema fields present ·{" "}
        {completeness.present_optional_field_count} of{" "}
        {completeness.optional_field_count} optional fields present
      </p>
      <p className="mt-1 text-xs text-white/60">{missingFieldSummary(completeness)}</p>
      {completeness.blocking_reasons.length > 0 ? (
        <ul className="mt-2 space-y-0.5 text-xs text-amber-200/80">
          {completeness.blocking_reasons.map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      ) : null}
      <p className="mt-2 text-[11px] text-white/45">{COMPLETENESS_NOTICE}</p>
    </div>
  );
}

export function BobaClipBriefOverview({
  reference,
  completeness,
}: {
  reference: ClipBriefReference | null;
  completeness: ClipBriefCompleteness | null;
}) {
  if (!reference) {
    return <p className="text-sm text-white/60">Select a clip brief to review it.</p>;
  }
  return (
    <div className="space-y-2">
      <div className="rounded-lg border border-white/10 bg-white/[0.02] p-3 text-xs text-white/60">
        <p className="text-sm font-medium text-white">Brief {reference.brief_id}</p>
        <p className="mt-1">
          Candidate {reference.candidate_id} · ranked clip {reference.clip_id} · lifecycle
          bucket {reference.lifecycle_bucket}
        </p>
        <p className="mt-1">{revisionNotice(reference)}</p>
        {unsupportedSchemaNotice(reference) ? (
          <p className="mt-1 text-amber-200/90">{unsupportedSchemaNotice(reference)}</p>
        ) : null}
        {reference.warnings.length > 0 ? (
          <ul className="mt-1 space-y-0.5 text-amber-200/80">
            {reference.warnings.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        ) : null}
        {reference.limitations.length > 0 ? (
          <ul className="mt-1 space-y-0.5 text-white/40">
            {reference.limitations.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        ) : null}
      </div>
      <BobaClipBriefCompletenessReadout completeness={completeness} />
    </div>
  );
}
