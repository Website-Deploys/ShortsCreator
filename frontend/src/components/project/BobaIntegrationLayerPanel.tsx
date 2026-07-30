"use client";

import { useState } from "react";
import type { ReactNode } from "react";

import {
  useBobaIntegrationLayer,
  useExportBobaIntegrationLayer,
  useResetBobaIntegrationLayer,
} from "@/lib/queries";

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function asText(value: unknown, fallback = "Not available"): string {
  return typeof value === "string" && value ? value : fallback;
}

function asStrings(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

function words(value: unknown): string {
  return asText(value).replace(/_/g, " ");
}

function shortDigest(value: unknown): string {
  const digest = asText(value, "");
  return digest ? `${digest.slice(0, 12)}…${digest.slice(-8)}` : "Not available";
}

function yesNo(value: unknown): string {
  return typeof value === "boolean" ? (value ? "Yes" : "No") : "Not available";
}

function statusTone(value: unknown): string {
  const status = asText(value, "").toLowerCase();
  if (
    ["ready", "succeeded", "compatible", "healthy", "available"].includes(status)
  ) {
    return "border-emerald-300/30 bg-emerald-300/[0.06] text-emerald-100";
  }
  if (
    status.includes("blocked") ||
    status.includes("failed") ||
    status.includes("incompatible") ||
    status.includes("prohibited")
  ) {
    return "border-rose-300/30 bg-rose-300/[0.06] text-rose-100";
  }
  if (
    status.includes("future") ||
    status.includes("degraded") ||
    status.includes("warning")
  ) {
    return "border-amber-300/30 bg-amber-300/[0.06] text-amber-100";
  }
  return "border-white/10 bg-white/[0.03] text-muted";
}

function downloadJson(filename: string, payload: unknown) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function Section({
  title,
  children,
  open = false,
}: {
  title: string;
  children: ReactNode;
  open?: boolean;
}) {
  return (
    <details className="rounded-xl border border-white/10 bg-black/10 p-3" open={open}>
      <summary className="cursor-pointer text-xs font-semibold tracking-[0.16em] text-white">
        {title}
      </summary>
      <div className="mt-3 space-y-2 text-xs text-muted">{children}</div>
    </details>
  );
}

function StatusBadge({ value }: { value: unknown }) {
  return (
    <span className={`rounded-full border px-2 py-1 text-[10px] ${statusTone(value)}`}>
      {words(value)}
    </span>
  );
}

function KeyValue({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-white/5 py-1 last:border-0">
      <span>{label}</span>
      <span className="max-w-[65%] break-words text-right text-white">
        {asText(value)}
      </span>
    </div>
  );
}

export function BobaIntegrationLayerPanel({ projectId }: { projectId: string }) {
  const layerQuery = useBobaIntegrationLayer(projectId);
  const exportLayer = useExportBobaIntegrationLayer(projectId);
  const resetLayer = useResetBobaIntegrationLayer(projectId);
  const [notice, setNotice] = useState("");
  const layer = layerQuery.data;

  if (layerQuery.isLoading) {
    return (
      <section className="rounded-2xl border border-white/10 bg-panel/70 p-5 text-sm text-muted">
        Loading BOBA Integration Layer…
      </section>
    );
  }
  if (layerQuery.error) {
    return (
      <section className="rounded-2xl border border-rose-300/30 bg-rose-300/[0.05] p-5">
        <h3 className="font-semibold text-white">BOBA Integration Layer</h3>
        <p className="mt-2 text-sm text-rose-100">{layerQuery.error.message}</p>
      </section>
    );
  }
  if (!layer) {
    return null;
  }

  const transaction = layer.integration_transactions.at(-1);
  const request = layer.integration_requests
    .map(asRecord)
    .find((item) => item.request_id === transaction?.request_id);
  const envelope = layer.request_envelopes
    .map(asRecord)
    .find((item) => item.envelope_id === request?.envelope_id);
  const response = layer.integration_responses
    .map(asRecord)
    .find((item) => item.response_id === transaction?.response_id);
  const compatibility = layer.compatibility_checks
    .map(asRecord)
    .find((item) =>
      transaction?.compatibility_check_ids.includes(asText(item.compatibility_check_id, "")),
    );
  const dependency = layer.dependency_checks
    .map(asRecord)
    .find((item) =>
      transaction?.dependency_check_ids.includes(asText(item.dependency_check_id, "")),
    );
  const approval = asRecord(envelope?.approval_binding);
  const safety = asRecord(envelope?.safety_binding);
  const modulesByStatus = layer.module_descriptors.reduce<Record<string, number>>(
    (counts, item) => {
      counts[item.implementation_status] = (counts[item.implementation_status] ?? 0) + 1;
      return counts;
    },
    {},
  );
  const operationsByClass = layer.operation_descriptors.reduce<Record<string, number>>(
    (counts, item) => {
      counts[item.operation_class] = (counts[item.operation_class] ?? 0) + 1;
      return counts;
    },
    {},
  );
  const recentEvents = layer.integration_events.slice(-5).map(asRecord);
  const recentFailures = layer.integration_failures.slice(-5).map(asRecord);
  const recentHandoffs = layer.integration_handoffs.slice(-5).map(asRecord);
  const idempotency = layer.idempotency_records
    .map(asRecord)
    .find((item) => item.idempotency_record_id === transaction?.idempotency_record_id);

  return (
    <section className="rounded-2xl border border-sky-300/20 bg-panel/70 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-[11px] font-semibold tracking-[0.18em] text-sky-200">
            BOBA INTEGRATION LAYER V1
          </p>
          <h3 className="mt-1 text-lg font-semibold text-white">
            Typed module interoperability
          </h3>
          <p className="mt-2 max-w-3xl text-xs text-muted">
            BOBA Integration Layer connects registered modules through typed,
            validated requests. It does not decide which repair to use and does not
            approve actions.
          </p>
          <p className="mt-1 max-w-3xl text-xs text-muted">
            Execution requests still require Autopilot coordination, exact module
            approval, a current Safety Gate allowance and target-module
            revalidation. Unknown modules and operations cannot be invoked.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            className="rounded-lg border border-white/10 px-3 py-2 text-xs text-white hover:bg-white/5"
            disabled={exportLayer.isPending}
            onClick={() =>
              exportLayer.mutate(undefined, {
                onSuccess: (payload) => {
                  downloadJson(`boba-integration-${projectId}.json`, payload);
                  setNotice("Sanitized Integration Layer export downloaded.");
                },
                onError: (error) => setNotice(error.message),
              })
            }
            type="button"
          >
            Export
          </button>
          <button
            className="rounded-lg border border-rose-300/20 px-3 py-2 text-xs text-rose-100 hover:bg-rose-300/[0.06]"
            disabled={resetLayer.isPending}
            onClick={() => {
              if (!window.confirm("Reset active Integration Layer metadata only?")) return;
              resetLayer.mutate(undefined, {
                onSuccess: () =>
                  setNotice(
                    "Active integration metadata reset; immutable history and upstream artifacts remain.",
                  ),
                onError: (error) => setNotice(error.message),
              });
            }}
            type="button"
          >
            Reset metadata
          </button>
        </div>
      </div>

      {notice && <p className="mt-3 text-xs text-sky-100">{notice}</p>}

      <div className="mt-4 grid gap-3 lg:grid-cols-2">
        <Section title="MODULE REGISTRY" open>
          <KeyValue label="Registry version" value={layer.registry_snapshot.registry_version} />
          <KeyValue label="Registry digest" value={shortDigest(layer.registry_snapshot.registry_sha256)} />
          <KeyValue label="Registered modules" value={layer.module_descriptors.length} />
          <KeyValue label="Available" value={modulesByStatus.available ?? 0} />
          <KeyValue label="Degraded" value={modulesByStatus.degraded ?? 0} />
          <KeyValue label="Unavailable" value={modulesByStatus.unavailable ?? 0} />
          <KeyValue label="Future" value={modulesByStatus.future ?? 0} />
          <p>Unknown modules cannot be invoked.</p>
        </Section>

        <Section title="OPERATION REGISTRY" open>
          <KeyValue label="Registered operations" value={layer.operation_descriptors.length} />
          {Object.entries(operationsByClass).map(([operationClass, count]) => (
            <KeyValue
              key={operationClass}
              label={words(operationClass)}
              value={count}
            />
          ))}
          <p>Operation handlers are fixed by source code, not request payloads.</p>
        </Section>

        <Section title="COMPATIBILITY">
          <StatusBadge value={compatibility?.compatibility_status ?? "Not available"} />
          <KeyValue label="Schema" value={compatibility?.schema_id} />
          <KeyValue label="Producer version" value={compatibility?.producer_schema_version} />
          <KeyValue label="Migration required" value={yesNo(compatibility?.migration_required)} />
          <p>{asText(compatibility?.failure_reason, "No compatibility warning recorded.")}</p>
        </Section>

        <Section title="DEPENDENCIES">
          <StatusBadge value={dependency?.dependency_status ?? "Not available"} />
          <KeyValue label="Missing artifacts" value={asStrings(dependency?.missing_artifact_ids).join(", ") || "None"} />
          <KeyValue label="Stale artifacts" value={asStrings(dependency?.stale_artifact_ids).join(", ") || "None"} />
          <KeyValue label="Unavailable modules" value={asStrings(dependency?.unavailable_module_ids).join(", ") || "None"} />
          <p>{asText(dependency?.failure_reason, "No dependency warning recorded.")}</p>
        </Section>

        <Section title="REQUEST">
          <KeyValue label="Request ID" value={request?.request_id} />
          <KeyValue label="Requesting module" value={request?.requesting_module_id} />
          <KeyValue label="Target module" value={request?.target_module_id} />
          <KeyValue label="Target operation" value={request?.target_operation_id} />
          <KeyValue label="Project" value={request?.project_id} />
          <KeyValue label="Run" value={request?.run_id} />
          <KeyValue label="Request digest" value={shortDigest(request?.request_digest)} />
        </Section>

        <Section title="APPROVAL AND SAFETY">
          <KeyValue label="Approval required" value={yesNo(Boolean(approval.approval_binding_id))} />
          <KeyValue label="Approval match" value={approval.current_match_status} />
          <KeyValue label="Approval valid in transaction" value={yesNo(transaction?.approval_binding_valid)} />
          <KeyValue label="Safety decision" value={safety.decision} />
          <KeyValue label="Safety valid in transaction" value={yesNo(transaction?.safety_binding_valid)} />
          <p>Integration Layer transports these bindings; it does not create or change them.</p>
        </Section>

        <Section title="TRANSACTION" open>
          <StatusBadge value={transaction?.state ?? "Not available"} />
          <KeyValue label="Transaction ID" value={transaction?.transaction_id} />
          <KeyValue label="Operation class" value={words(transaction?.operation_class)} />
          <KeyValue label="Idempotency record" value={idempotency?.idempotency_record_id} />
          <KeyValue label="Idempotent reuse" value={yesNo(idempotency?.completed && response?.idempotency_reused)} />
          <KeyValue label="Target started" value={yesNo(transaction?.target_invocation_started)} />
          <KeyValue label="Target completed" value={yesNo(transaction?.target_invocation_completed)} />
          <KeyValue label="Target revalidated" value={yesNo(transaction?.target_independent_revalidation_confirmed)} />
          {recentEvents.map((event) => (
            <p key={asText(event.event_id)} className="rounded-lg bg-white/[0.03] p-2">
              {asText(event.easy_message)}
            </p>
          ))}
        </Section>

        <Section title="RESULT">
          <StatusBadge value={response?.status ?? "Not available"} />
          <KeyValue label="Response ID" value={response?.response_id} />
          <KeyValue label="Result digest" value={shortDigest(response?.result_digest)} />
          <KeyValue label="Side effects reported" value={transaction?.side_effects_reported.join(", ") || "None"} />
          <p>
            {response
              ? "This is the bounded result reported by the target module."
              : "No routed result is available. A validated request is not the same as an executed request."}
          </p>
        </Section>

        <Section title="INTEGRATION FAILURES">
          {recentFailures.length ? (
            recentFailures.map((failure) => (
              <div key={asText(failure.failure_id)} className="rounded-lg border border-rose-300/20 p-2">
                <StatusBadge value={failure.failure_class} />
                <p className="mt-2 text-white">{asText(failure.title)}</p>
                <p>{asText(failure.bounded_summary)}</p>
                <p>Source: {words(failure.source_layer)}</p>
              </div>
            ))
          ) : (
            <p>No Integration Layer failure is recorded.</p>
          )}
        </Section>

        <Section title="WHAT HAPPENS NEXT">
          {recentHandoffs.length ? (
            recentHandoffs.map((handoff) => (
              <div key={asText(handoff.handoff_id)} className="rounded-lg bg-white/[0.03] p-2">
                <p className="text-white">Target: {words(handoff.target_module_id)}</p>
                <p>{asText(handoff.reason)}</p>
                <p>Human review: {yesNo(handoff.human_review_required)}</p>
              </div>
            ))
          ) : (
            <p>No follow-up handoff is currently recorded.</p>
          )}
          <p>
            The layer never resumes workflows, restores checkpoints, installs
            software, publishes content, or pushes, merges, or deploys code.
          </p>
        </Section>
      </div>
    </section>
  );
}
