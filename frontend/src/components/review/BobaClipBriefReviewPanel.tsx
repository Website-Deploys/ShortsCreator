"use client";

/**
 * BOBA Clip Brief Panel V1.
 *
 * A specialized read-only mode of the BOBA Review UI, rendered beside the
 * Candidate Review Panel rather than replacing either of them. It is a clip brief
 * projection, an evidence workspace, a comparison surface and a safe canonical
 * action router. It never generates, regenerates or rewrites a brief, never
 * invents a field the owner schema does not define, never computes a quality or
 * virality score, never chooses a winning brief, and never approves, rejects or
 * optimistically changes brief state.
 */

import { Component, type ReactNode, useEffect, useMemo, useState } from "react";

import {
  BobaClipBriefActionBar,
  BobaClipBriefActionDialog,
} from "@/components/review/BobaClipBriefActionDialog";
import { BobaClipBriefAnnotations } from "@/components/review/BobaClipBriefAnnotations";
import { BobaClipBriefQueue } from "@/components/review/BobaClipBriefCard";
import { BobaClipBriefComparisonView } from "@/components/review/BobaClipBriefComparison";
import {
  BobaClipBriefConflicts,
  BobaClipBriefEvidence,
  BobaClipBriefSourceCards,
} from "@/components/review/BobaClipBriefEvidence";
import {
  BobaClipBriefOverview,
  BobaClipBriefSection,
} from "@/components/review/BobaClipBriefFields";
import { BobaClipBriefPreview } from "@/components/review/BobaClipBriefPreview";
import {
  canCompare,
  removeAnnotation,
  toggleComparison,
  upsertAnnotation,
  type ClipBriefActionDescriptor,
  type ClipBriefActionReceipt,
  type ClipBriefAnnotation,
  type ClipBriefComparison,
  type ClipBriefCompleteness,
  type ClipBriefConflict,
  type ClipBriefEvidenceLink,
  type ClipBriefFieldProjection,
  type ClipBriefQueueItem,
  type ClipBriefReference,
  type ClipBriefReviewFilter,
  type ClipBriefReviewSort,
  type ClipBriefSectionProjection,
  type ClipBriefSnapshot,
  type ClipBriefSourceCard,
} from "@/lib/clipBriefReview";
import {
  useBobaClipBriefQueue,
  useBobaClipBriefRegistry,
  useCompareBobaClipBriefs,
  useCreateBobaClipBriefAction,
  useCreateBobaClipBriefReviewSession,
  useCreateBobaClipBriefSnapshot,
  useRefreshBobaClipBriefSnapshot,
  useSubmitBobaClipBriefAction,
  useUpdateBobaClipBriefReviewSession,
  useValidateBobaClipBriefAction,
} from "@/lib/queries";
import { classifyReviewError } from "@/lib/reviewUi";

type PanelTab = "briefs" | "brief" | "preview" | "evidence" | "compare" | "notes";

const TABS: { id: PanelTab; label: string }[] = [
  { id: "briefs", label: "Briefs" },
  { id: "brief", label: "Brief" },
  { id: "preview", label: "Preview" },
  { id: "evidence", label: "Evidence" },
  { id: "compare", label: "Compare" },
  { id: "notes", label: "Notes" },
];

/** Contains unexpected render failures without leaking internals. */
export class BobaClipBriefReviewErrorBoundary extends Component<
  { children: ReactNode },
  { failed: boolean }
> {
  constructor(props: { children: ReactNode }) {
    super(props);
    this.state = { failed: false };
  }

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (this.state.failed) {
      return (
        <div
          role="alert"
          className="rounded-lg border border-rose-300/30 bg-rose-300/[0.06] p-4 text-sm text-rose-100"
        >
          <p className="font-medium">The clip brief panel could not be displayed.</p>
          <p className="mt-1 text-xs text-rose-100/80">
            No clip brief state changed. Reload the page to try again.
          </p>
        </div>
      );
    }
    return this.props.children;
  }
}

export function BobaClipBriefReviewPanel({ projectId }: { projectId: string }) {
  const reviewerContextId = "local_reviewer";
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [filter, setFilter] = useState<ClipBriefReviewFilter>("all_current");
  const [sort, setSort] = useState<ClipBriefReviewSort>("review_priority");
  const [selectedBriefId, setSelectedBriefId] = useState<string | null>(null);
  const [comparisonIds, setComparisonIds] = useState<string[]>([]);
  const [comparison, setComparison] = useState<ClipBriefComparison | null>(null);
  const [differencesOnly, setDifferencesOnly] = useState(true);
  const [snapshot, setSnapshot] = useState<ClipBriefSnapshot | null>(null);
  const [reference, setReference] = useState<ClipBriefReference | null>(null);
  const [fields, setFields] = useState<ClipBriefFieldProjection[]>([]);
  const [sections, setSections] = useState<ClipBriefSectionProjection[]>([]);
  const [sourceCards, setSourceCards] = useState<ClipBriefSourceCard[]>([]);
  const [evidenceLinks, setEvidenceLinks] = useState<ClipBriefEvidenceLink[]>([]);
  const [completeness, setCompleteness] = useState<ClipBriefCompleteness | null>(null);
  const [conflicts, setConflicts] = useState<ClipBriefConflict[]>([]);
  const [confirmations, setConfirmations] = useState<Record<string, string>>({});
  const [activeSectionId, setActiveSectionId] = useState<string | null>(null);
  const [showEmptyOptionalFields, setShowEmptyOptionalFields] = useState(false);
  const [showTechnicalDetails, setShowTechnicalDetails] = useState(false);
  const [contextSeconds, setContextSeconds] = useState(0);
  const [annotations, setAnnotations] = useState<ClipBriefAnnotation[]>([]);
  const [tab, setTab] = useState<PanelTab>("briefs");
  const [pending, setPending] = useState<ClipBriefActionDescriptor | null>(null);
  const [receipt, setReceipt] = useState<ClipBriefActionReceipt | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [banner, setBanner] = useState<string | null>(null);

  const registry = useBobaClipBriefRegistry(projectId);
  const queue = useBobaClipBriefQueue(projectId, { filter, sort });
  const createSession = useCreateBobaClipBriefReviewSession(projectId);
  const updateSession = useUpdateBobaClipBriefReviewSession(projectId);
  const createSnapshot = useCreateBobaClipBriefSnapshot(projectId);
  const refreshSnapshot = useRefreshBobaClipBriefSnapshot(projectId);
  const compareBriefs = useCompareBobaClipBriefs(projectId);
  const createAction = useCreateBobaClipBriefAction(projectId);
  const validateAction = useValidateBobaClipBriefAction(projectId);
  const submitAction = useSubmitBobaClipBriefAction(projectId);

  const items: ClipBriefQueueItem[] = queue.data?.items ?? [];
  const descriptors = useMemo<ClipBriefActionDescriptor[]>(
    () => registry.data?.actions ?? [],
    [registry.data],
  );
  const fieldPaths = useMemo(() => fields.map((field) => field.field_path), [fields]);

  useEffect(() => {
    if (sessionId || createSession.isPending) return;
    createSession.mutate(
      { reviewer_context_id: reviewerContextId },
      { onSuccess: (session) => setSessionId(session.clip_brief_review_session_id) },
    );
  }, [sessionId, createSession]);

  const applySnapshot = (payload: {
    snapshot: ClipBriefSnapshot;
    brief_reference: ClipBriefReference;
    field_projections: ClipBriefFieldProjection[];
    section_projections: ClipBriefSectionProjection[];
    source_cards: ClipBriefSourceCard[];
    evidence_links: ClipBriefEvidenceLink[];
    completeness: ClipBriefCompleteness;
    conflict_records: ClipBriefConflict[];
    action_confirmations: Record<string, string>;
  }) => {
    setSnapshot(payload.snapshot);
    setReference(payload.brief_reference);
    setFields(payload.field_projections);
    setSections(payload.section_projections);
    setSourceCards(payload.source_cards);
    setEvidenceLinks(payload.evidence_links);
    setCompleteness(payload.completeness);
    setConflicts(payload.conflict_records);
    setConfirmations(payload.action_confirmations ?? {});
  };

  const selectBrief = (briefId: string) => {
    setSelectedBriefId(briefId);
    setReceipt(null);
    setActionMessage(null);
    setTab("brief");
    if (!sessionId) return;
    createSnapshot.mutate(
      { briefId, sessionId },
      {
        onSuccess: (payload) => {
          applySnapshot(payload);
          setBanner(null);
        },
        onError: (error) => setBanner(classifyReviewError(error).guidance),
      },
    );
  };

  const toggleBriefComparison = (briefId: string) => {
    const next = toggleComparison(comparisonIds, briefId);
    setComparisonIds(next);
    setComparison(null);
    if (sessionId) {
      updateSession.mutate({ sessionId, updates: { comparison_brief_ids: next } });
    }
  };

  const runComparison = () => {
    if (!canCompare(comparisonIds)) return;
    compareBriefs.mutate(comparisonIds, {
      onSuccess: (payload) => {
        setComparison(payload.comparison);
        setTab("compare");
      },
      onError: (error) => setBanner(classifyReviewError(error).guidance),
    });
  };

  /**
   * Re-read canonical state, then create, validate and submit. No brief field,
   * status or completeness value is updated optimistically anywhere in this flow.
   */
  const confirmAction = (decisionValue: string | null, reason: string) => {
    if (!pending || !snapshot || !sessionId) return;
    refreshSnapshot.mutate(snapshot.brief_snapshot_id, {
      onError: (error) => setActionMessage(classifyReviewError(error).guidance),
      onSuccess: (refreshed) => {
        applySnapshot(refreshed);
        if (refreshed.snapshot.snapshot_digest !== snapshot.snapshot_digest) {
          setActionMessage(
            "Canonical clip brief state changed while this review was open. Review the refreshed record, then confirm again.",
          );
          return;
        }
        const token = (refreshed.action_confirmations ?? {})[pending.action_descriptor_id];
        if (!token) {
          setActionMessage(
            "This action is no longer available for this exact clip brief.",
          );
          return;
        }
        createAction.mutate(
          {
            clip_brief_review_session_id: sessionId,
            brief_snapshot_id: refreshed.snapshot.brief_snapshot_id,
            action_descriptor_id: pending.action_descriptor_id,
            decision_value: decisionValue,
            reason,
            confirmation_context_digest: token,
            idempotency_key: `clip_brief_${refreshed.snapshot.brief_snapshot_id}_${pending.action_descriptor_id}`,
            confirmed: true,
          },
          {
            onError: (error) => setActionMessage(classifyReviewError(error).guidance),
            onSuccess: (created) => {
              const requestId = String(created.clip_brief_action_request_id ?? "");
              validateAction.mutate(requestId, {
                onError: (error) =>
                  setActionMessage(classifyReviewError(error).guidance),
                onSuccess: (validation) => {
                  if (!validation.valid) {
                    setActionMessage(validation.message);
                    return;
                  }
                  submitAction.mutate(requestId, {
                    onError: (error) =>
                      setActionMessage(classifyReviewError(error).guidance),
                    onSuccess: (owner) => {
                      setReceipt(owner);
                      setPending(null);
                      setActionMessage(null);
                    },
                  });
                },
              });
            },
          },
        );
      },
    });
  };

  const comparisonReady = canCompare(comparisonIds);

  return (
    <section
      aria-label="BOBA clip brief panel"
      className="rounded-xl border border-white/10 bg-white/[0.02] p-4"
    >
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold text-white">Clip Brief Panel</h2>
          <p className="mt-0.5 text-xs text-white/50">
            A read-only projection of the clip briefs the Clip Brief Generator
            persisted, with their canonical evidence.
          </p>
        </div>
        <div className="flex flex-wrap gap-1">
          {TABS.map((option) => (
            <button
              key={option.id}
              type="button"
              onClick={() => setTab(option.id)}
              aria-pressed={tab === option.id}
              className={`rounded px-2 py-1 text-xs ${
                tab === option.id
                  ? "bg-white/[0.10] text-white"
                  : "text-white/60 hover:text-white"
              }`}
            >
              {option.label}
            </button>
          ))}
        </div>
      </header>

      {banner ? (
        <p role="status" className="mt-3 text-xs text-amber-200/90">
          {banner}
        </p>
      ) : null}
      {queue.isError ? (
        <p role="status" className="mt-3 text-xs text-amber-200/90">
          {classifyReviewError(queue.error).guidance}
        </p>
      ) : null}

      <div className="mt-4 space-y-4">
        {tab === "briefs" ? (
          <BobaClipBriefQueue
            items={items}
            total={queue.data?.total ?? 0}
            filter={filter}
            sort={sort}
            selectedBriefId={selectedBriefId}
            comparisonIds={comparisonIds}
            onFilterChange={setFilter}
            onSortChange={setSort}
            onSelect={selectBrief}
            onToggleComparison={toggleBriefComparison}
          />
        ) : null}

        {tab === "brief" ? (
          <div className="space-y-3">
            <BobaClipBriefOverview reference={reference} completeness={completeness} />
            <div className="flex flex-wrap gap-3 text-xs text-white/60">
              <label className="flex items-center gap-1.5">
                <input
                  type="checkbox"
                  checked={showEmptyOptionalFields}
                  onChange={(event) => setShowEmptyOptionalFields(event.target.checked)}
                />
                Show empty optional fields
              </label>
              <label className="flex items-center gap-1.5">
                <input
                  type="checkbox"
                  checked={showTechnicalDetails}
                  onChange={(event) => setShowTechnicalDetails(event.target.checked)}
                />
                Show technical details
              </label>
            </div>
            <div className="space-y-2">
              {sections.map((section) => (
                <BobaClipBriefSection
                  key={section.section_projection_id}
                  section={section}
                  fields={fields}
                  activeSectionId={activeSectionId}
                  showEmptyOptionalFields={showEmptyOptionalFields}
                  showTechnicalDetails={showTechnicalDetails}
                  onToggle={(sectionId) =>
                    setActiveSectionId(activeSectionId === sectionId ? null : sectionId)
                  }
                />
              ))}
            </div>
            <BobaClipBriefActionBar
              descriptors={descriptors}
              snapshot={snapshot}
              confirmations={confirmations}
              receipt={receipt}
              message={actionMessage}
              onSelect={setPending}
            />
            <BobaClipBriefActionDialog
              descriptor={pending}
              snapshot={snapshot}
              confirmations={confirmations}
              submitting={submitAction.isPending || createAction.isPending}
              onCancel={() => setPending(null)}
              onConfirm={confirmAction}
            />
          </div>
        ) : null}

        {tab === "preview" ? (
          <BobaClipBriefPreview
            projectId={projectId}
            reference={reference}
            contextSeconds={contextSeconds}
            onContextSecondsChange={setContextSeconds}
          />
        ) : null}

        {tab === "evidence" ? (
          <div className="space-y-4">
            <BobaClipBriefEvidence
              links={evidenceLinks}
              missingCount={evidenceLinks.filter((link) => link.missing).length}
            />
            <BobaClipBriefConflicts conflicts={conflicts} />
            <BobaClipBriefSourceCards cards={sourceCards} />
          </div>
        ) : null}

        {tab === "compare" ? (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2 text-xs text-white/60">
              <span>{comparisonIds.length} selected</span>
              <button
                type="button"
                disabled={!comparisonReady || compareBriefs.isPending}
                onClick={runComparison}
                className="rounded border border-white/10 px-3 py-1.5 disabled:opacity-40"
              >
                Compare selected briefs
              </button>
              {!comparisonReady ? (
                <span className="text-white/40">
                  Select between two and four briefs to compare.
                </span>
              ) : null}
            </div>
            <BobaClipBriefComparisonView
              comparison={comparison}
              differencesOnly={differencesOnly}
              onDifferencesOnlyChange={setDifferencesOnly}
            />
          </div>
        ) : null}

        {tab === "notes" ? (
          <BobaClipBriefAnnotations
            annotations={annotations}
            fieldPaths={fieldPaths.length > 0 ? fieldPaths : ["brief_id"]}
            onAdd={(annotation) => {
              const next = upsertAnnotation(annotations, annotation);
              setAnnotations(next);
              if (sessionId) {
                updateSession.mutate({
                  sessionId,
                  updates: { local_annotations: next },
                });
              }
            }}
            onRemove={(annotationId) => {
              const next = removeAnnotation(annotations, annotationId);
              setAnnotations(next);
              if (sessionId) {
                updateSession.mutate({
                  sessionId,
                  updates: { local_annotations: next },
                });
              }
            }}
          />
        ) : null}
      </div>

      <footer className="mt-4 space-y-0.5 border-t border-white/10 pt-3 text-[11px] text-white/40">
        <p>
          This panel does not generate, regenerate or rewrite a clip brief and adds no
          field the owner schema does not define.
        </p>
        <p>
          Completeness means only that required owner-schema fields are present. It is
          not quality, approval, technical validation or render readiness.
        </p>
      </footer>
    </section>
  );
}
