"use client";

import type { ReactNode } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { API_V1 } from "@/lib/config";

type JsonRecord = Record<string, unknown>;

function record(value: unknown): JsonRecord {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as JsonRecord)
    : {};
}

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function text(value: unknown, fallback = "Not available"): string {
  return typeof value === "string" && value ? value : fallback;
}

async function requestJson(path: string, init?: RequestInit): Promise<JsonRecord> {
  const response = await fetch(`${API_V1}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    if (response.status === 404) return {};
    throw new Error(`Report Reader request failed (${response.status}).`);
  }
  return (await response.json()) as JsonRecord;
}

function trustedReferencePayload(reference: JsonRecord): JsonRecord {
  return {
    source_descriptor_id: text(reference.source_descriptor_id, ""),
    sanitized_storage_reference: text(reference.sanitized_storage_reference, ""),
    producer_module_id: text(reference.producer_module_id, ""),
    producer_record_id: text(reference.producer_record_id, ""),
    report_type: text(reference.report_type, ""),
    schema_id: text(reference.schema_id, ""),
    schema_version: text(reference.schema_version, "1"),
    expected_digest: text(reference.expected_digest, ""),
    format: text(reference.format, ""),
    workflow_run_id: text(reference.workflow_run_id, ""),
    stage_instance_id: text(reference.stage_instance_id, ""),
    immutable: reference.immutable !== false,
    historical: reference.historical === true,
    required: reference.required !== false,
    rights_relevant: reference.rights_relevant === true,
    safety_relevant: reference.safety_relevant === true,
    quality_relevant: reference.quality_relevant === true,
    workflow_relevant: reference.workflow_relevant === true,
    warnings: list(reference.warnings)
      .filter((item) => typeof item === "string")
      .slice(0, 32),
  };
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <details className="rounded-xl border border-white/10 bg-black/10 p-3">
      <summary className="cursor-pointer text-xs font-semibold tracking-[0.14em] text-white">
        {title}
      </summary>
      <div className="mt-3 space-y-2 text-xs text-muted">{children}</div>
    </details>
  );
}

function Line({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="flex justify-between gap-4 border-b border-white/5 py-1 last:border-0">
      <span>{label}</span>
      <span className="max-w-[65%] break-words text-right text-white">
        {text(value)}
      </span>
    </div>
  );
}

function Count({ label, value }: { label: string; value: unknown }) {
  return <Line label={label} value={list(value).length.toString()} />;
}

function Items({ values, field }: { values: unknown; field: string }) {
  const items = list(values).map(record).slice(0, 12);
  if (!items.length) return <p>Not available.</p>;
  return (
    <div className="space-y-2">
      {items.map((item, index) => (
        <p className="rounded border border-white/10 p-2 text-white" key={`${field}-${index}`}>
          {text(item[field] ?? item.bounded_summary ?? item.technical_message)}
        </p>
      ))}
    </div>
  );
}

export function BobaReportReaderPanel({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const key = ["boba-report-reader", projectId] as const;
  const readerQuery = useQuery({
    queryKey: key,
    queryFn: () => requestJson(`/boba/projects/${projectId}/report-reader`),
    enabled: Boolean(projectId),
  });
  const registryQuery = useQuery({
    queryKey: [...key, "registry"],
    queryFn: () => requestJson(`/boba/projects/${projectId}/report-reader/registry`),
    enabled: Boolean(projectId),
  });
  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: key }),
      queryClient.invalidateQueries({ queryKey: [...key, "registry"] }),
    ]);
  const createReadRequest = useMutation({
    mutationFn: (references: JsonRecord[]) =>
      requestJson(`/boba/projects/${projectId}/report-reader/requests`, {
        method: "POST",
        body: JSON.stringify({
          reading_mode: "current_project_review",
          report_references: references.map(trustedReferencePayload),
        }),
      }),
    onSuccess: refresh,
  });
  const validateReferences = useMutation({
    mutationFn: (requestId: string) =>
      requestJson(
        `/boba/projects/${projectId}/report-reader/requests/${requestId}/validate`,
        { method: "POST" },
      ),
    onSuccess: refresh,
  });
  const readReports = useMutation({
    mutationFn: (requestId: string) =>
      requestJson(
        `/boba/projects/${projectId}/report-reader/requests/${requestId}/read`,
        { method: "POST" },
      ),
    onSuccess: refresh,
  });
  const compareReports = useMutation({
    mutationFn: (runId: string) =>
      requestJson(`/boba/projects/${projectId}/report-reader/compare`, {
        method: "POST",
        body: JSON.stringify({ read_run_id: runId }),
      }),
    onSuccess: refresh,
  });
  const buildBundle = useMutation({
    mutationFn: (runId: string) =>
      requestJson(`/boba/projects/${projectId}/report-reader/bundles`, {
        method: "POST",
        body: JSON.stringify({
          read_run_id: runId,
          purpose: "Read-only report explanation",
        }),
      }),
    onSuccess: refresh,
  });
  const exportReader = useMutation({
    mutationFn: () =>
      requestJson(`/boba/projects/${projectId}/report-reader/export`),
    onSuccess: (payload) => {
      const url = URL.createObjectURL(
        new Blob([JSON.stringify(payload, null, 2)], {
          type: "application/json",
        }),
      );
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `boba-report-reader-${projectId}.json`;
      anchor.click();
      URL.revokeObjectURL(url);
    },
  });
  const resetReader = useMutation({
    mutationFn: () =>
      requestJson(`/boba/projects/${projectId}/report-reader`, {
        method: "DELETE",
      }),
    onSuccess: refresh,
  });

  if (readerQuery.isLoading || registryQuery.isLoading) {
    return (
      <section className="rounded-2xl border border-white/10 bg-panel/70 p-5 text-sm text-muted">
        Loading BOBA Report Reader...
      </section>
    );
  }

  if (readerQuery.error || registryQuery.error) {
    return (
      <section className="rounded-2xl border border-rose-300/30 bg-rose-300/[0.05] p-5">
        <h3 className="font-semibold text-white">BOBA Report Reader</h3>
        <p className="mt-2 text-sm text-rose-100">
          {(readerQuery.error ?? registryQuery.error)?.message}
        </p>
      </section>
    );
  }

  const reader = readerQuery.data ?? {};
  const trustedReferences = list(reader.report_references)
    .map(record)
    .filter(
      (reference) =>
        Boolean(text(reference.source_descriptor_id, "")) &&
        Boolean(text(reference.sanitized_storage_reference, "")),
    );
  const registry = registryQuery.data ?? {};
  const snapshot = record(registry.registry_snapshot);
  const summary = record(reader.reader_summary);
  const latestRequest = list(reader.read_requests).map(record).at(-1) ?? {};
  const latestRun = list(reader.read_runs).map(record).at(-1) ?? {};
  const latestBundle = list(reader.report_bundles).map(record).at(-1) ?? {};
  const latestRequestId = text(latestRequest.read_request_id, "");
  const latestRunId = text(latestRun.read_run_id, "");
  const actionError =
    createReadRequest.error ??
    validateReferences.error ??
    readReports.error ??
    compareReports.error ??
    buildBundle.error ??
    exportReader.error ??
    resetReader.error;

  return (
    <section className="rounded-2xl border border-emerald-300/20 bg-panel/70 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold tracking-[0.18em] text-emerald-100">
            BOBA REPORT READER V1
          </p>
          <p className="mt-2 text-sm text-muted">
            Report Reader explains registered Olympus and BOBA reports without
            changing their decisions.
          </p>
        </div>
        <span className="rounded-full border border-white/10 px-3 py-1 text-xs text-white">
          {text(latestRun.status, "No read run")}
        </span>
      </div>

      <p className="mt-3 text-xs text-muted">
        A technical validation pass is not the same as quality approval or
        workflow permission. Historical reports remain visible but cannot
        prove the current project state.
      </p>

      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <Section title="REPORT SOURCES">
          <Line label="Registry version" value={snapshot.registry_version} />
          <Line label="Registry snapshot" value={snapshot.registry_snapshot_id} />
          <Count label="Available sources" value={registry.sources} />
          <Count label="Exact references" value={reader.report_references} />
        </Section>
        <Section title="REPORT IDENTITY">
          <Line label="Project" value={reader.project_id} />
          <Line label="Reading mode" value={latestRequest.reading_mode} />
          <Line label="Request" value={latestRequest.read_request_id} />
          <Line label="Run" value={latestRun.read_run_id} />
          <Line label="Bundle" value={latestBundle.report_bundle_id} />
        </Section>
        <Section title="SOURCE DECISIONS">
          <Items values={reader.status_interpretations} field="original_decision" />
        </Section>
        <Section title="CONFIRMED FACTS">
          <Items values={reader.findings} field="confirmed_fact" />
        </Section>
        <Section title="SOURCE ASSESSMENTS">
          <Items values={reader.findings} field="source_assessment" />
        </Section>
        <Section title="BOBA INTERPRETATION">
          <Items values={reader.findings} field="reader_interpretation" />
        </Section>
        <Section title="EVIDENCE">
          <Count label="Evidence references" value={reader.evidence_references} />
          <Items values={reader.evidence_references} field="bounded_summary" />
        </Section>
        <Section title="TIMELINE">
          <Count label="Chronology entries" value={reader.chronology_entries} />
          <Items values={reader.chronology_entries} field="bounded_summary" />
        </Section>
        <Section title="CONTRADICTIONS">
          <Count label="Unresolved contradictions" value={reader.contradictions} />
          <Items values={reader.contradictions} field="bounded_summary" />
        </Section>
        <Section title="MISSING INFORMATION">
          <Count label="Open questions" value={reader.open_questions} />
          <Items values={reader.open_questions} field="bounded_question" />
        </Section>
        <Section title="EASY EXPLANATION">
          <p className="text-white">{text(latestBundle.easy_summary)}</p>
          <p>
            Conflicting reports remain unresolved until the responsible source
            module or a human reviewer resolves them.
          </p>
        </Section>
        <Section title="WHAT HAPPENS NEXT">
          <Line label="Safest next action" value={summary.safest_next_action} />
          <Count label="Advisory handoffs" value={reader.handoffs} />
          <Items values={reader.handoffs} field="reason" />
        </Section>
      </div>

      {actionError && (
        <p className="mt-3 text-xs text-rose-100">{actionError.message}</p>
      )}

      <div className="mt-4 flex flex-wrap gap-2">
        <button
          className="rounded-lg border border-white/15 px-3 py-2 text-xs text-white"
          onClick={() => void registryQuery.refetch()}
          type="button"
        >
          Inspect report sources
        </button>
        <button
          className="rounded-lg border border-white/15 px-3 py-2 text-xs text-white disabled:opacity-50"
          disabled={!trustedReferences.length || createReadRequest.isPending}
          onClick={() => createReadRequest.mutate(trustedReferences)}
          title={
            trustedReferences.length
              ? "Create a read-only request from persisted exact report references."
              : "No exact source-generated report references are available yet."
          }
          type="button"
        >
          Create read request
        </button>
        <button
          className="rounded-lg border border-white/15 px-3 py-2 text-xs text-white disabled:opacity-50"
          disabled={!latestRequestId || validateReferences.isPending}
          onClick={() => validateReferences.mutate(latestRequestId)}
          type="button"
        >
          Validate references
        </button>
        <button
          className="rounded-lg border border-white/15 px-3 py-2 text-xs text-white disabled:opacity-50"
          disabled={!latestRequestId || readReports.isPending}
          onClick={() => readReports.mutate(latestRequestId)}
          type="button"
        >
          Read selected reports
        </button>
        <button
          className="rounded-lg border border-white/15 px-3 py-2 text-xs text-white disabled:opacity-50"
          disabled={!latestRunId || compareReports.isPending}
          onClick={() => compareReports.mutate(latestRunId)}
          type="button"
        >
          Compare reports
        </button>
        <button
          className="rounded-lg border border-white/15 px-3 py-2 text-xs text-white disabled:opacity-50"
          disabled={!latestRunId || buildBundle.isPending}
          onClick={() => buildBundle.mutate(latestRunId)}
          type="button"
        >
          Build report bundle
        </button>
        <button
          className="rounded-lg border border-white/15 px-3 py-2 text-xs text-white"
          onClick={() => exportReader.mutate()}
          type="button"
        >
          Export summary
        </button>
        <button
          className="rounded-lg border border-rose-300/30 px-3 py-2 text-xs text-rose-100"
          onClick={() => resetReader.mutate()}
          type="button"
        >
          Reset active metadata
        </button>
      </div>
    </section>
  );
}
