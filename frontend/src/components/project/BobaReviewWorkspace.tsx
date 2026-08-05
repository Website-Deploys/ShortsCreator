"use client";

/**
 * BOBA Review UI V1 - unified human review workspace.
 *
 * This is a presentation and canonical action-routing layer. It never creates or
 * changes Rights, Safety, approval, validation, quality, workflow, artifact or
 * Final Decision Bus state. Authoritative state is displayed as changed only
 * after the owning module returns a canonical record and receipt.
 */

import { Component, type ReactNode, useEffect, useMemo, useRef, useState } from "react";

import { BobaReviewActionBar, BobaReviewActionDialog, type ReviewActionDescriptor } from "@/components/project/BobaReviewActionDialog";
import {
  BobaReviewEventStream,
  BobaReviewEvidenceDrawer,
  BobaReviewTimeline,
} from "@/components/project/BobaReviewEvidenceDrawer";
import { BobaReviewPreview } from "@/components/project/BobaReviewPreview";
import { BobaReviewQueue } from "@/components/project/BobaReviewQueue";
import { BobaReviewStatusMatrix } from "@/components/project/BobaReviewStatusMatrix";
import {
  buildStatusMatrix,
  classifyReviewError,
  mergeCanonicalEvents,
  receiptChangedAuthority,
  type QueueFilter,
  type ReviewActionReceipt,
  type ReviewEvent,
  type ReviewQueueItem,
  type ReviewSnapshot,
  type ReviewSourceCard,
} from "@/lib/reviewUi";
import {
  useBobaReviewEvents,
  useBobaReviewQueue,
  useBobaReviewUi,
  useCreateBobaReviewAction,
  useCreateBobaReviewSession,
  useCreateBobaReviewSnapshot,
  useRefreshBobaReviewSnapshot,
  useSubmitBobaReviewAction,
  useValidateBobaReviewAction,
} from "@/lib/queries";

type WorkspaceTab = "queue" | "review" | "evidence" | "events";

const TABS: { id: WorkspaceTab; label: string }[] = [
  { id: "queue", label: "Queue" },
  { id: "review", label: "Review" },
  { id: "evidence", label: "Evidence" },
  { id: "events", label: "Events" },
];

/** Contains unexpected render failures without leaking internals. */
export class BobaReviewErrorBoundary extends Component<
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
        <div role="alert" className="rounded-lg border border-rose-300/30 bg-rose-300/[0.06] p-4 text-sm text-rose-100">
          <p className="font-medium">The review workspace could not be displayed.</p>
          <p className="mt-1 text-xs text-rose-100/80">
            No authoritative state changed. Reload the page to try again.
          </p>
        </div>
      );
    }
    return this.props.children;
  }
}

export function BobaReviewHeader({
  projectId,
  summary,
  reviewerContextId,
  connected,
}: {
  projectId: string;
  summary: Record<string, unknown> | undefined;
  reviewerContextId: string;
  connected: boolean;
}) {
  const count = (key: string) => Number(summary?.[key] ?? 0);
  return (
    <header className="space-y-2">
      <h2 className="text-base font-semibold text-white/95">BOBA REVIEW WORKSPACE</h2>
      <p className="text-xs text-white/60">
        A unified view of the canonical review work for project{" "}
        <span className="font-mono text-white/80">{projectId}</span>. This workspace presents
        decisions owned by other modules and routes confirmed human actions back to them.
      </p>
      <dl className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-5">
        {[
          ["Critical", "critical_attention_count"],
          ["Blocked", "blocked_count"],
          ["Human review", "human_review_required_count"],
          ["Awaiting evidence", "awaiting_evidence_count"],
          ["Total", "total_queue_item_count"],
        ].map(([label, key]) => (
          <div key={key} className="rounded-md border border-white/10 bg-white/[0.02] p-2">
            <dt className="text-white/50">{label}</dt>
            <dd className="text-sm text-white/90">{count(key)}</dd>
          </div>
        ))}
      </dl>
      <p className="text-[11px] text-white/45">
        Reviewer context: <span className="font-mono">{reviewerContextId}</span> ·{" "}
        {connected ? "live canonical events connected" : "live canonical events disconnected"}
      </p>
    </header>
  );
}

export function BobaWorkflowRail({ cards }: { cards: ReviewSourceCard[] }) {
  const rows = buildStatusMatrix(cards);
  return (
    <nav aria-label="Workflow progress by authority domain" className="space-y-1">
      <h3 className="text-sm font-semibold text-white/90">WORKFLOW RAIL</h3>
      <ol className="space-y-1">
        {rows.map((row) => (
          <li
            key={row.key}
            className="flex items-center justify-between gap-2 rounded border border-white/10 bg-white/[0.02] px-2 py-1 text-[11px]"
          >
            <span className="text-white/80">{row.label}</span>
            <span className="text-white/55">
              {row.blocking ? "Blocking" : row.humanActionRequired ? "Human action" : row.originalStatus.replace(/_/g, " ")}
            </span>
          </li>
        ))}
      </ol>
    </nav>
  );
}

export function BobaReviewMobileTabs({
  active,
  onChange,
}: {
  active: WorkspaceTab;
  onChange: (tab: WorkspaceTab) => void;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const move = (index: number, delta: number) => {
    const next = (index + delta + TABS.length) % TABS.length;
    refs.current[next]?.focus();
    onChange(TABS[next].id);
  };
  return (
    <div role="tablist" aria-label="Review workspace sections" className="flex gap-1 lg:hidden">
      {TABS.map((tab, index) => (
        <button
          key={tab.id}
          ref={(node) => {
            refs.current[index] = node;
          }}
          type="button"
          role="tab"
          id={`review-tab-${tab.id}`}
          aria-selected={active === tab.id}
          aria-controls={`review-panel-${tab.id}`}
          tabIndex={active === tab.id ? 0 : -1}
          onClick={() => onChange(tab.id)}
          onKeyDown={(event) => {
            if (event.key === "ArrowRight") {
              event.preventDefault();
              move(index, 1);
            } else if (event.key === "ArrowLeft") {
              event.preventDefault();
              move(index, -1);
            }
          }}
          className={`min-h-[44px] flex-1 rounded-md border px-2 text-xs focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-300 ${
            active === tab.id
              ? "border-sky-300/40 bg-sky-300/[0.10] text-sky-100"
              : "border-white/10 bg-white/[0.02] text-white/70"
          }`}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

export function BobaReviewWorkspace({ projectId }: { projectId: string }) {
  const reviewerContextId = "local_reviewer";
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [filter, setFilter] = useState<QueueFilter>({ category: "all", includeHistorical: false });
  const [selected, setSelected] = useState<ReviewQueueItem | null>(null);
  const [snapshot, setSnapshot] = useState<ReviewSnapshot | null>(null);
  const [cards, setCards] = useState<ReviewSourceCard[]>([]);
  const [events, setEvents] = useState<ReviewEvent[]>([]);
  const [tab, setTab] = useState<WorkspaceTab>("queue");
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const [evidenceModule, setEvidenceModule] = useState<string | null>(null);
  const [pending, setPending] = useState<ReviewActionDescriptor | null>(null);
  const [receipt, setReceipt] = useState<ReviewActionReceipt | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [banner, setBanner] = useState<string | null>(null);
  const [confirmations, setConfirmations] = useState<Record<string, string>>({});

  const ui = useBobaReviewUi(projectId);
  const queue = useBobaReviewQueue(projectId, {
    category: filter.category,
    includeHistorical: filter.includeHistorical,
  });
  const eventQuery = useBobaReviewEvents(projectId);
  const createSession = useCreateBobaReviewSession(projectId);
  const createSnapshot = useCreateBobaReviewSnapshot(projectId);
  const refreshSnapshot = useRefreshBobaReviewSnapshot(projectId);
  const createAction = useCreateBobaReviewAction(projectId);
  const validateAction = useValidateBobaReviewAction(projectId);
  const submitAction = useSubmitBobaReviewAction(projectId);

  const descriptors = useMemo<ReviewActionDescriptor[]>(() => {
    const raw = (ui.data as { action_descriptors?: ReviewActionDescriptor[] } | undefined)
      ?.action_descriptors;
    return Array.isArray(raw) ? raw : [];
  }, [ui.data]);

  const summary = (ui.data as { ui_summary?: Record<string, unknown> } | undefined)?.ui_summary;
  const allCards = useMemo<ReviewSourceCard[]>(() => {
    const raw = (ui.data as { source_cards?: ReviewSourceCard[] } | undefined)?.source_cards;
    return Array.isArray(raw) ? raw : [];
  }, [ui.data]);

  // One review session per mounted workspace. Sessions hold UI state only.
  useEffect(() => {
    if (sessionId || createSession.isPending) return;
    createSession.mutate(
      { reviewer_context_id: reviewerContextId },
      { onSuccess: (session) => setSessionId(session.review_session_id) },
    );
  }, [sessionId, createSession]);

  useEffect(() => {
    const incoming = eventQuery.data?.events;
    if (!incoming) return;
    setEvents((existing) => mergeCanonicalEvents(existing, incoming));
  }, [eventQuery.data]);

  const displayCards = cards.length > 0 ? cards : allCards;
  const validationStatus =
    displayCards.find((card) => card.source_module_id === "validator_runner")?.original_status ??
    "unavailable";

  const selectItem = (item: ReviewQueueItem) => {
    setSelected(item);
    setReceipt(null);
    setActionMessage(null);
    setTab("review");
    if (!sessionId) return;
    createSnapshot.mutate(
      { targetId: item.target_id, sessionId },
      {
        onSuccess: (payload) => {
          setSnapshot(payload.snapshot);
          setCards(payload.source_cards);
          setConfirmations(payload.action_confirmations ?? {});
          setBanner(null);
        },
        onError: (error) => setBanner(classifyReviewError(error).guidance),
      },
    );
  };

  /**
   * Refresh canonical state, then create, validate and submit. No optimistic
   * authority update happens anywhere in this flow.
   */
  const confirmAction = (decisionValue: string | null, reason: string) => {
    if (!pending || !snapshot || !sessionId) return;
    refreshSnapshot.mutate(snapshot.review_snapshot_id, {
      onError: (error) => setActionMessage(classifyReviewError(error).guidance),
      onSuccess: (refreshed) => {
        setSnapshot(refreshed.snapshot);
        setCards(refreshed.source_cards);
        setConfirmations(refreshed.action_confirmations ?? {});
        if (refreshed.snapshot.snapshot_digest !== snapshot.snapshot_digest) {
          setActionMessage(
            "Canonical state changed while this review was open. Review the refreshed record, then confirm again.",
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
            review_session_id: sessionId,
            review_snapshot_id: refreshed.snapshot.review_snapshot_id,
            action_descriptor_id: pending.action_descriptor_id,
            decision_value: decisionValue,
            reason,
            confirmation_context_digest: token,
            idempotency_key: `review-${refreshed.snapshot.review_snapshot_id}-${pending.action_descriptor_id}`,
            confirmed: true,
          },
          {
            onError: (error) => setActionMessage(classifyReviewError(error).guidance),
            onSuccess: (created) => {
              const requestId = String(
                (created as { review_action_request_id?: string }).review_action_request_id ?? "",
              );
              if (!requestId) {
                setActionMessage(classifyReviewError({ code: "malformed_canonical_response" }).guidance);
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
                      if (!receiptChangedAuthority(owned)) {
                        setActionMessage(
                          "The owning module did not report an authoritative change. Nothing was applied.",
                        );
                      } else {
                        setActionMessage(null);
                      }
                      void ui.refetch();
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

  const queueError = queue.isError ? classifyReviewError(queue.error).guidance : null;
  const connected = !eventQuery.isError;

  const queuePanel = (
    <BobaReviewQueue
      items={queue.data?.items ?? []}
      filter={filter}
      sort="priority"
      selectedTargetId={selected?.target_id ?? null}
      onSelect={selectItem}
      onFilterChange={setFilter}
      loading={queue.isLoading}
      error={queueError}
    />
  );

  const reviewPanel = (
    <div className="space-y-4">
      {selected === null ? (
        <p className="rounded-lg border border-white/10 bg-white/[0.02] p-4 text-xs text-white/60">
          Select an item from the review queue to see its canonical record.
        </p>
      ) : (
        <>
          <section aria-labelledby="review-target-heading" className="space-y-1">
            <h3 id="review-target-heading" className="text-sm font-semibold text-white/90">
              {selected.title}
            </h3>
            <p className="text-xs text-white/65">{selected.bounded_summary}</p>
            <p className="text-[11px] text-white/45">
              Target <span className="font-mono">{selected.target_id}</span> ·{" "}
              {selected.target_type.replace(/_/g, " ")} · owned by{" "}
              <span className="font-mono">{selected.source_module_ids.join(", ")}</span>
            </p>
            {snapshot?.stale && (
              <p role="alert" className="text-[11px] text-amber-100">
                This snapshot is stale. Refresh before deciding.
              </p>
            )}
          </section>
          <BobaReviewPreview
            projectId={projectId}
            clipId={null}
            validationStatus={validationStatus}
          />
          <BobaReviewStatusMatrix
            cards={displayCards}
            onOpenEvidence={(sourceModule) => {
              setEvidenceModule(sourceModule);
              setEvidenceOpen(true);
              setTab("evidence");
            }}
          />
        </>
      )}
    </div>
  );

  const evidencePanel = (
    <BobaReviewEvidenceDrawer
      open
      cards={displayCards}
      focusModule={evidenceModule}
      onClose={() => {
        setEvidenceOpen(false);
        setTab("review");
      }}
    />
  );

  const eventsPanel = (
    <div className="space-y-4">
      <BobaReviewEventStream
        events={events}
        connected={connected}
        onReconnect={() => void eventQuery.refetch()}
      />
      <BobaReviewTimeline events={events} />
    </div>
  );

  return (
    <BobaReviewErrorBoundary>
      <div className="space-y-4 rounded-xl border border-white/10 bg-white/[0.01] p-4">
        <BobaReviewHeader
          projectId={projectId}
          summary={summary}
          reviewerContextId={reviewerContextId}
          connected={connected}
        />

        {banner && (
          <p role="alert" className="rounded-md border border-amber-300/30 bg-amber-300/[0.06] p-2 text-xs text-amber-100">
            {banner}
          </p>
        )}
        {ui.isError && (
          <p role="alert" className="rounded-md border border-rose-300/30 bg-rose-300/[0.06] p-2 text-xs text-rose-100">
            {classifyReviewError(ui.error).guidance}
          </p>
        )}

        <BobaReviewMobileTabs active={tab} onChange={setTab} />

        <div className="lg:hidden">
          <div role="tabpanel" id={`review-panel-${tab}`} aria-labelledby={`review-tab-${tab}`}>
            {tab === "queue" && queuePanel}
            {tab === "review" && reviewPanel}
            {tab === "evidence" && evidencePanel}
            {tab === "events" && eventsPanel}
          </div>
        </div>

        <div className="hidden gap-4 lg:grid lg:grid-cols-[18rem_10rem_minmax(0,1fr)]">
          <div className="space-y-4">{queuePanel}</div>
          <BobaWorkflowRail cards={displayCards} />
          <main aria-label="Review detail" className="space-y-4">
            {reviewPanel}
            {evidenceOpen && evidencePanel}
            {eventsPanel}
          </main>
        </div>

        <BobaReviewActionBar
          descriptors={descriptors}
          snapshot={snapshot}
          confirmableActionIds={Object.keys(confirmations)}
          busy={busy}
          onRequest={(descriptor) => {
            setPending(descriptor);
            setReceipt(null);
            setActionMessage(null);
          }}
        />

        <BobaReviewActionDialog
          descriptor={pending}
          snapshot={snapshot}
          receipt={receipt}
          validationMessage={actionMessage}
          busy={busy}
          onCancel={() => setPending(null)}
          onConfirm={confirmAction}
        />
      </div>
    </BobaReviewErrorBoundary>
  );
}
