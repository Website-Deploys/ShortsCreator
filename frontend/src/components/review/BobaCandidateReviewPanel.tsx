"use client";

/**
 * BOBA Candidate Review Panel V1.
 *
 * A specialized mode of the BOBA Review UI. It is a read-only candidate
 * projection, a comparison workspace and a safe canonical action router. It never
 * discovers candidates, reranks them, recomputes a source-owned score, builds a
 * hidden composite, selects a winner, or optimistically changes candidate status.
 */

import { Component, type ReactNode, useEffect, useMemo, useState } from "react";

import {
  BobaCandidateActionBar,
  BobaCandidateActionDialog,
} from "@/components/review/BobaCandidateActionDialog";
import { BobaCandidateQueue } from "@/components/review/BobaCandidateCard";
import {
  BobaCandidateComparison,
  BobaCandidateEvidence,
  BobaCandidateScoreBreakdown,
  BobaCandidateTranscript,
} from "@/components/review/BobaCandidateEvidence";
import { BobaCandidatePreview } from "@/components/review/BobaCandidatePreview";
import {
  LOCAL_SHORTLIST_NOTICE,
  canCompare,
  receiptChangedAuthority,
  toggleComparison,
  toggleLocalShortlist,
  type CandidateActionDescriptor,
  type CandidateActionReceipt,
  type CandidateOverlapRecord,
  type CandidateQueueItem,
  type CandidateReviewFilter,
  type CandidateReviewSort,
  type CandidateScoreCard,
  type CandidateSnapshot,
} from "@/lib/candidateReview";
import { classifyReviewError } from "@/lib/reviewUi";
import {
  useBobaCandidateQueue,
  useBobaCandidateRegistry,
  useBobaCandidateTranscript,
  useCreateBobaCandidateAction,
  useCreateBobaCandidateReviewSession,
  useCreateBobaCandidateSnapshot,
  useRefreshBobaCandidateSnapshot,
  useSubmitBobaCandidateAction,
  useValidateBobaCandidateAction,
} from "@/lib/queries";

type PanelTab = "candidates" | "preview" | "details" | "compare" | "evidence";

const TABS: { id: PanelTab; label: string }[] = [
  { id: "candidates", label: "Candidates" },
  { id: "preview", label: "Preview" },
  { id: "details", label: "Details" },
  { id: "compare", label: "Compare" },
  { id: "evidence", label: "Evidence" },
];

/** Contains unexpected render failures without leaking internals. */
export class BobaCandidateReviewErrorBoundary extends Component<
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
          <p className="font-medium">The candidate review panel could not be displayed.</p>
          <p className="mt-1 text-xs text-rose-100/80">
            No candidate state changed. Reload the page to try again.
          </p>
        </div>
      );
    }
    return this.props.children;
  }
}

export function BobaCandidateReviewPanel({ projectId }: { projectId: string }) {
  const reviewerContextId = "local_reviewer";
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [filter, setFilter] = useState<CandidateReviewFilter>("all_current");
  const [sort, setSort] = useState<CandidateReviewSort>("review_priority");
  const [search, setSearch] = useState("");
  const [selectedCandidateId, setSelectedCandidateId] = useState<string | null>(null);
  const [comparisonIds, setComparisonIds] = useState<string[]>([]);
  const [shortlistIds, setShortlistIds] = useState<string[]>([]);
  const [snapshot, setSnapshot] = useState<CandidateSnapshot | null>(null);
  const [scoreCards, setScoreCards] = useState<CandidateScoreCard[]>([]);
  const [sourceCards, setSourceCards] = useState<Record<string, unknown>[]>([]);
  const [overlaps, setOverlaps] = useState<CandidateOverlapRecord[]>([]);
  const [confirmations, setConfirmations] = useState<Record<string, string>>({});
  const [contextSeconds, setContextSeconds] = useState(15);
  const [tab, setTab] = useState<PanelTab>("candidates");
  const [pending, setPending] = useState<CandidateActionDescriptor | null>(null);
  const [receipt, setReceipt] = useState<CandidateActionReceipt | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [banner, setBanner] = useState<string | null>(null);

  const registry = useBobaCandidateRegistry(projectId);
  const queue = useBobaCandidateQueue(projectId, { filter, sort });
  const transcript = useBobaCandidateTranscript(projectId, selectedCandidateId, contextSeconds);
  const createSession = useCreateBobaCandidateReviewSession(projectId);
  const createSnapshot = useCreateBobaCandidateSnapshot(projectId);
  const refreshSnapshot = useRefreshBobaCandidateSnapshot(projectId);
  const createAction = useCreateBobaCandidateAction(projectId);
  const validateAction = useValidateBobaCandidateAction(projectId);
  const submitAction = useSubmitBobaCandidateAction(projectId);

  const items: CandidateQueueItem[] = queue.data?.items ?? [];
  const descriptors = useMemo<CandidateActionDescriptor[]>(
    () => registry.data?.actions ?? [],
    [registry.data],
  );

  useEffect(() => {
    if (sessionId || createSession.isPending) return;
    createSession.mutate(
      { reviewer_context_id: reviewerContextId },
      { onSuccess: (session) => setSessionId(session.candidate_review_session_id) },
    );
  }, [sessionId, createSession]);

  const overlapsByCandidate = useMemo(() => {
    const grouped: Record<string, CandidateOverlapRecord[]> = {};
    for (const record of overlaps) {
      for (const id of [record.candidate_a_id, record.candidate_b_id]) {
        grouped[id] = [...(grouped[id] ?? []), record];
      }
    }
    return grouped;
  }, [overlaps]);

  const selectedItem = items.find((item) => item.candidate_id === selectedCandidateId) ?? null;
  const comparisonItems = comparisonIds
    .map((id) => items.find((item) => item.candidate_id === id))
    .filter((item): item is CandidateQueueItem => Boolean(item));
  const validationStatus = String(
    sourceCards.find((card) => card.source_module_id === "validator_runner")
      ?.original_status ?? "unavailable",
  );

  const selectCandidate = (candidateId: string) => {
    setSelectedCandidateId(candidateId);
    setReceipt(null);
    setActionMessage(null);
    setTab("preview");
    if (!sessionId) return;
    createSnapshot.mutate(
      { candidateId, sessionId },
      {
        onSuccess: (payload) => {
          setSnapshot(payload.snapshot);
          setScoreCards(payload.score_cards);
          setSourceCards(payload.source_cards);
          setOverlaps(payload.overlap_records);
          setConfirmations(payload.action_confirmations ?? {});
          setBanner(null);
        },
        onError: (error) => setBanner(classifyReviewError(error).guidance),
      },
    );
  };

  /**
   * Refresh canonical state, then create, validate and submit. No optimistic
   * candidate-status update happens anywhere in this flow.
   */
  const confirmAction = (decisionValue: string | null, reason: string) => {
    if (!pending || !snapshot || !sessionId) return;
    refreshSnapshot.mutate(snapshot.candidate_snapshot_id, {
      onError: (error) => setActionMessage(classifyReviewError(error).guidance),
      onSuccess: (refreshed) => {
        setSnapshot(refreshed.snapshot);
        setScoreCards(refreshed.score_cards);
        setSourceCards(refreshed.source_cards);
        setOverlaps(refreshed.overlap_records);
        setConfirmations(refreshed.action_confirmations ?? {});
        if (refreshed.snapshot.snapshot_digest !== snapshot.snapshot_digest) {
          setActionMessage(
            "Canonical candidate state changed while this review was open. Review the refreshed record, then confirm again.",
          );
          return;
        }
        const token = (refreshed.action_confirmations ?? {})[pending.action_descriptor_id];
        if (!token) {
          setActionMessage(classifyReviewError({ code: "action_unavailable" }).guidance);
          return;
        }
        createAction.mutate(
          {
            candidate_review_session_id: sessionId,
            candidate_snapshot_id: refreshed.snapshot.candidate_snapshot_id,
            action_descriptor_id: pending.action_descriptor_id,
            decision_value: decisionValue,
            reason,
            confirmation_context_digest: token,
            idempotency_key: `candidate-${refreshed.snapshot.candidate_snapshot_id}-${pending.action_descriptor_id}`,
            confirmed: true,
          },
          {
            onError: (error) => setActionMessage(classifyReviewError(error).guidance),
            onSuccess: (created) => {
              const requestId = String(
                (created as { candidate_action_request_id?: string })
                  .candidate_action_request_id ?? "",
              );
              if (!requestId) {
                setActionMessage(
                  classifyReviewError({ code: "malformed_canonical_response" }).guidance,
                );
                return;
              }
              validateAction.mutate(requestId, {
                onError: (error) => setActionMessage(classifyReviewError(error).guidance),
                onSuccess: (validation) => {
                  if (!validation.valid) {
                    setActionMessage(classifyReviewError({ code: validation.code }).guidance);
                    return;
                  }
                  submitAction.mutate(requestId, {
                    onError: (error) => setActionMessage(classifyReviewError(error).guidance),
                    onSuccess: (owned) => {
                      setReceipt(owned);
                      setActionMessage(
                        receiptChangedAuthority(owned)
                          ? null
                          : "Recorded by the owning module. No authoritative candidate state changed.",
                      );
                      void queue.refetch();
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

  const busy =
    createAction.isPending ||
    validateAction.isPending ||
    submitAction.isPending ||
    refreshSnapshot.isPending;

  const queuePanel = (
    <BobaCandidateQueue
      items={items}
      filter={filter}
      sort={sort}
      search={search}
      selectedCandidateId={selectedCandidateId}
      comparisonIds={comparisonIds}
      shortlistIds={shortlistIds}
      overlapsByCandidate={overlapsByCandidate}
      onFilterChange={setFilter}
      onSortChange={setSort}
      onSearchChange={setSearch}
      onSelect={selectCandidate}
      onToggleCompare={(id) => setComparisonIds((current) => toggleComparison(current, id))}
      onToggleShortlist={(id) =>
        setShortlistIds((current) => toggleLocalShortlist(current, id))
      }
      loading={queue.isLoading}
      error={queue.isError ? classifyReviewError(queue.error).guidance : null}
    />
  );

  const previewPanel = (
    <BobaCandidatePreview
      projectId={projectId}
      startSeconds={selectedItem?.start_seconds ?? null}
      endSeconds={selectedItem?.end_seconds ?? null}
      durationSeconds={selectedItem?.duration_seconds ?? null}
      contextSeconds={contextSeconds}
      historical={Boolean(selectedItem?.historical)}
      validationStatus={validationStatus}
    />
  );

  const detailsPanel = (
    <div className="space-y-4">
      {selectedItem === null ? (
        <p className="rounded-lg border border-white/10 bg-white/[0.02] p-4 text-xs text-white/60">
          Select a candidate from the queue to see its source-owned evidence.
        </p>
      ) : (
        <>
          <BobaCandidateScoreBreakdown cards={scoreCards} />
          <BobaCandidateTranscript
            snippets={transcript.data?.candidate_transcript_snippets ?? []}
            segmentIds={transcript.data?.transcript_segment_ids ?? []}
            candidateStart={selectedItem.start_seconds}
            candidateEnd={selectedItem.end_seconds}
            contextStart={transcript.data?.context_start_seconds ?? selectedItem.start_seconds}
            contextEnd={transcript.data?.context_end_seconds ?? selectedItem.end_seconds}
            contextSeconds={contextSeconds}
            onContextChange={setContextSeconds}
            sourceModuleId={transcript.data?.source_module_id ?? "clip_discovery"}
          />
        </>
      )}
    </div>
  );

  const comparePanel = (
    <BobaCandidateComparison
      items={comparisonItems}
      overlaps={overlaps.filter(
        (record) =>
          comparisonIds.includes(record.candidate_a_id) &&
          comparisonIds.includes(record.candidate_b_id),
      )}
      onClear={() => setComparisonIds([])}
    />
  );

  const evidencePanel = <BobaCandidateEvidence sourceCards={sourceCards} />;

  return (
    <BobaCandidateReviewErrorBoundary>
      <div className="space-y-4 rounded-xl border border-white/10 bg-white/[0.01] p-4">
        <header className="space-y-1">
          <h2 className="text-base font-semibold text-white/95">BOBA CANDIDATE REVIEW</h2>
          <p className="text-xs text-white/60">
            Candidate clips discovered for project{" "}
            <span className="font-mono text-white/80">{projectId}</span>. This panel presents
            what Candidate Clip Discovery, Clip Ranking and Editorial Decision decided. It
            does not discover, rerank or select candidates.
          </p>
          <p className="text-[11px] text-white/45">
            {queue.data?.total ?? 0} candidates · {shortlistIds.length} in the session
            shortlist ({LOCAL_SHORTLIST_NOTICE})
          </p>
          {comparisonIds.length > 0 && !canCompare(comparisonIds) && (
            <p className="text-[11px] text-amber-100">
              Select at least two candidates to compare.
            </p>
          )}
        </header>

        {banner && (
          <p
            role="alert"
            className="rounded-md border border-amber-300/30 bg-amber-300/[0.06] p-2 text-xs text-amber-100"
          >
            {banner}
          </p>
        )}
        {registry.isError && (
          <p
            role="alert"
            className="rounded-md border border-rose-300/30 bg-rose-300/[0.06] p-2 text-xs text-rose-100"
          >
            {classifyReviewError(registry.error).guidance}
          </p>
        )}

        <div role="tablist" aria-label="Candidate review sections" className="flex gap-1 xl:hidden">
          {TABS.map((entry, index) => (
            <button
              key={entry.id}
              type="button"
              role="tab"
              id={`candidate-tab-${entry.id}`}
              aria-selected={tab === entry.id}
              aria-controls={`candidate-panel-${entry.id}`}
              tabIndex={tab === entry.id ? 0 : -1}
              onClick={() => setTab(entry.id)}
              onKeyDown={(event) => {
                if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
                  event.preventDefault();
                  const delta = event.key === "ArrowRight" ? 1 : -1;
                  setTab(TABS[(index + delta + TABS.length) % TABS.length].id);
                }
              }}
              className={`min-h-[44px] flex-1 rounded-md border px-1 text-[11px] focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-300 ${
                tab === entry.id
                  ? "border-sky-300/40 bg-sky-300/[0.10] text-sky-100"
                  : "border-white/10 bg-white/[0.02] text-white/70"
              }`}
            >
              {entry.label}
            </button>
          ))}
        </div>

        <div className="xl:hidden">
          <div
            role="tabpanel"
            id={`candidate-panel-${tab}`}
            aria-labelledby={`candidate-tab-${tab}`}
          >
            {tab === "candidates" && queuePanel}
            {tab === "preview" && previewPanel}
            {tab === "details" && detailsPanel}
            {tab === "compare" && comparePanel}
            {tab === "evidence" && evidencePanel}
          </div>
        </div>

        <div className="hidden gap-4 xl:grid xl:grid-cols-[20rem_minmax(0,1fr)_20rem]">
          <div className="space-y-4">{queuePanel}</div>
          <main aria-label="Candidate review detail" className="space-y-4">
            {previewPanel}
            {detailsPanel}
            {comparePanel}
          </main>
          <aside aria-label="Candidate source evidence" className="space-y-4">
            {evidencePanel}
          </aside>
        </div>

        <BobaCandidateActionBar
          descriptors={descriptors}
          snapshot={snapshot}
          confirmations={confirmations}
          candidateId={selectedCandidateId}
          busy={busy}
          onRequest={(descriptor) => {
            setPending(descriptor);
            setReceipt(null);
            setActionMessage(null);
          }}
        />

        <BobaCandidateActionDialog
          descriptor={pending}
          snapshot={snapshot}
          candidateId={selectedCandidateId}
          receipt={receipt}
          validationMessage={actionMessage}
          busy={busy}
          onCancel={() => setPending(null)}
          onConfirm={confirmAction}
        />
      </div>
    </BobaCandidateReviewErrorBoundary>
  );
}
