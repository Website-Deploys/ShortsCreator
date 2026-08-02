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
  if (typeof value === "string" && value) return value;
  if (typeof value === "number" && Number.isFinite(value)) return value.toString();
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return fallback;
}

async function requestJson(path: string, init?: RequestInit): Promise<JsonRecord> {
  const response = await fetch(`${API_V1}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    if (response.status === 404) return {};
    throw new Error(`Artifact Inspector request failed (${response.status}).`);
  }
  return (await response.json()) as JsonRecord;
}

function trustedReferencePayload(reference: JsonRecord): JsonRecord {
  return {
    workflow_run_id: text(reference.workflow_run_id, ""),
    stage_instance_id: text(reference.stage_instance_id, ""),
    clip_id: text(reference.clip_id, ""),
    output_id: text(reference.output_id, ""),
    owner_module_id: text(reference.owner_module_id, ""),
    producer_record_id: text(reference.producer_record_id, ""),
    artifact_type_id: text(reference.artifact_type_id, ""),
    schema_id: text(reference.schema_id, ""),
    schema_version: text(reference.schema_version, "1"),
    expected_digest: text(reference.expected_digest, ""),
    expected_digest_type: "sha256",
    expected_size_bytes:
      typeof reference.expected_size_bytes === "number"
        ? reference.expected_size_bytes
        : null,
    sanitized_storage_reference: text(reference.sanitized_storage_reference, ""),
    storage_kind: text(reference.storage_kind, "unknown"),
    immutable: reference.immutable !== false,
    source_media: reference.source_media === true,
    source_media_read_only: reference.source_media_read_only !== false,
    accepted_output: reference.accepted_output === true,
    generated_output: reference.generated_output === true,
    required: reference.required !== false,
    historical: reference.historical === true,
    rights_status: text(reference.rights_status, "unknown"),
    created_at: text(reference.created_at, ""),
    completed_at: text(reference.completed_at, ""),
    declared_lineage: list(reference.declared_lineage)
      .map(record)
      .slice(0, 32),
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
          {text(item[field] ?? item.bounded_explanation ?? item.bounded_summary)}
        </p>
      ))}
    </div>
  );
}

export function BobaArtifactInspectorPanel({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const key = ["boba-artifact-inspector", projectId] as const;
  const inspectorQuery = useQuery({
    queryKey: key,
    queryFn: () => requestJson(`/boba/projects/${projectId}/artifact-inspector`),
    enabled: Boolean(projectId),
  });
  const registryQuery = useQuery({
    queryKey: [...key, "registry"],
    queryFn: () => requestJson(`/boba/projects/${projectId}/artifact-inspector/registry`),
    enabled: Boolean(projectId),
  });
  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: key }),
      queryClient.invalidateQueries({ queryKey: [...key, "registry"] }),
    ]);
  const createInspectionRequest = useMutation({
    mutationFn: (references: JsonRecord[]) =>
      requestJson(`/boba/projects/${projectId}/artifact-inspector/requests`, {
        method: "POST",
        body: JSON.stringify({
          inspection_mode: "project_inventory",
          artifact_references: references.map(trustedReferencePayload),
        }),
      }),
    onSuccess: refresh,
  });
  const validateReferences = useMutation({
    mutationFn: (requestId: string) =>
      requestJson(
        `/boba/projects/${projectId}/artifact-inspector/requests/${requestId}/validate`,
        { method: "POST" },
      ),
    onSuccess: refresh,
  });
  const inspectArtifacts = useMutation({
    mutationFn: (requestId: string) =>
      requestJson(
        `/boba/projects/${projectId}/artifact-inspector/requests/${requestId}/inspect`,
        { method: "POST" },
      ),
    onSuccess: refresh,
  });
  const buildInventory = useMutation({
    mutationFn: (runId: string) =>
      requestJson(`/boba/projects/${projectId}/artifact-inspector/inventory`, {
        method: "POST",
        body: JSON.stringify({ inspection_run_id: runId }),
      }),
    onSuccess: refresh,
  });
  const inspectLineage = useMutation({
    mutationFn: (runId: string) =>
      requestJson(`/boba/projects/${projectId}/artifact-inspector/lineage`, {
        method: "POST",
        body: JSON.stringify({ inspection_run_id: runId }),
      }),
    onSuccess: refresh,
  });
  const compareArtifacts = useMutation({
    mutationFn: ({ runId, left, right }: { runId: string; left: string; right: string }) =>
      requestJson(`/boba/projects/${projectId}/artifact-inspector/compare`, {
        method: "POST",
        body: JSON.stringify({
          inspection_run_id: runId,
          left_reference_id: left,
          right_reference_id: right,
        }),
      }),
    onSuccess: refresh,
  });
  const exportInspection = useMutation({
    mutationFn: () => requestJson(`/boba/projects/${projectId}/artifact-inspector/export`),
    onSuccess: (payload) => {
      const url = URL.createObjectURL(
        new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" }),
      );
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `boba-artifact-inspector-${projectId}.json`;
      anchor.click();
      URL.revokeObjectURL(url);
    },
  });
  const resetInspector = useMutation({
    mutationFn: () =>
      requestJson(`/boba/projects/${projectId}/artifact-inspector`, { method: "DELETE" }),
    onSuccess: refresh,
  });

  if (inspectorQuery.isLoading || registryQuery.isLoading) {
    return (
      <section className="rounded-2xl border border-white/10 bg-panel/70 p-5 text-sm text-muted">
        Loading BOBA Artifact Inspector...
      </section>
    );
  }

  if (inspectorQuery.error || registryQuery.error) {
    return (
      <section className="rounded-2xl border border-rose-300/30 bg-rose-300/[0.05] p-5">
        <h3 className="font-semibold text-white">BOBA Artifact Inspector</h3>
        <p className="mt-2 text-sm text-rose-100">
          {(inspectorQuery.error ?? registryQuery.error)?.message}
        </p>
      </section>
    );
  }

  const inspector = inspectorQuery.data ?? {};
  const registry = registryQuery.data ?? {};
  const snapshot = record(registry.registry_snapshot);
  const summary = record(inspector.inspector_summary);
  const references = list(inspector.artifact_references)
    .map(record)
    .filter(
      (reference) =>
        Boolean(text(reference.artifact_type_id, "")) &&
        Boolean(text(reference.sanitized_storage_reference, "")),
    );
  const latestRequest = list(inspector.inspection_requests).map(record).at(-1) ?? {};
  const latestRun = list(inspector.inspection_runs).map(record).at(-1) ?? {};
  const latestRequestId = text(latestRequest.inspection_request_id, "");
  const latestRunId = text(latestRun.inspection_run_id, "");
  const referenceIds = list(latestRequest.artifact_reference_ids)
    .filter((item): item is string => typeof item === "string")
    .slice(0, 2);
  const latestReference = references.at(-1) ?? {};
  const latestSnapshot = list(inspector.artifact_snapshots).map(record).at(-1) ?? {};
  const latestIntegrity = list(inspector.integrity_assessments).map(record).at(-1) ?? {};
  const latestFreshness = list(inspector.freshness_assessments).map(record).at(-1) ?? {};
  const latestProtection = list(inspector.protection_assessments).map(record).at(-1) ?? {};
  const latestInventory = list(inspector.inventories).map(record).at(-1) ?? {};
  const actionError =
    createInspectionRequest.error ??
    validateReferences.error ??
    inspectArtifacts.error ??
    buildInventory.error ??
    inspectLineage.error ??
    compareArtifacts.error ??
    exportInspection.error ??
    resetInspector.error;

  return (
    <section className="rounded-2xl border border-cyan-300/20 bg-panel/70 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold tracking-[0.18em] text-cyan-100">
            BOBA ARTIFACT INSPECTOR V1
          </p>
          <p className="mt-2 text-sm text-muted">
            Artifact Inspector checks registered local artifacts without changing them.
          </p>
        </div>
        <span className="rounded-full border border-white/10 px-3 py-1 text-xs text-white">
          {text(latestRun.status, "No inspection run")}
        </span>
      </div>

      <div className="mt-3 space-y-1 text-xs text-muted">
        <p>
          A matching digest confirms byte equality only. It does not confirm media quality or
          workflow permission.
        </p>
        <p>Deep technical checks are sent to Validator Runner.</p>
        <p>Report meaning remains owned by Report Reader and the original producer.</p>
        <p>Accepted outputs and source media remain protected and read-only.</p>
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <Section title="ARTIFACT REGISTRY">
          <Line label="Registry version" value={snapshot.registry_version} />
          <Line label="Registry snapshot" value={snapshot.registry_snapshot_id} />
          <Count label="Available types" value={snapshot.available_artifact_type_ids} />
          <Count label="Future types" value={snapshot.future_artifact_type_ids} />
        </Section>
        <Section title="ARTIFACT IDENTITY">
          <Line label="Project" value={inspector.project_id} />
          <Line label="Owner" value={latestReference.owner_module_id} />
          <Line label="Workflow / stage" value={`${text(latestReference.workflow_run_id, "—")} / ${text(latestReference.stage_instance_id, "—")}`} />
          <Line label="Clip / output" value={`${text(latestReference.clip_id, "—")} / ${text(latestReference.output_id, "—")}`} />
          <Line label="Request" value={latestRequest.inspection_request_id} />
          <Line label="Run" value={latestRun.inspection_run_id} />
          <Count label="Exact references" value={references} />
        </Section>
        <Section title="STORAGE AND FORMAT">
          <Line label="Registered reference" value={latestReference.sanitized_storage_reference} />
          <Line label="Expected kind / size" value={`${text(latestReference.storage_kind)} / ${text(latestReference.expected_size_bytes)}`} />
          <Line label="Observed kind / size" value={`${text(latestSnapshot.observed_storage_kind)} / ${text(latestSnapshot.observed_size_bytes)}`} />
          <Line label="Observed format" value={latestSnapshot.observed_format} />
          <Items values={inspector.artifact_snapshots} field="observed_format" />
        </Section>
        <Section title="INTEGRITY">
          <Line label="Status" value={latestIntegrity.status} />
          <Line label="Persisted / recomputed" value={`${text(latestIntegrity.persisted_digest_status)} / ${text(latestIntegrity.recomputed_digest_status)}`} />
          <Line label="Digest recomputed" value={latestSnapshot.recomputed_digest_used} />
          <Line label="Changed during read" value={latestSnapshot.changed_during_read} />
          <Items values={inspector.integrity_assessments} field="bounded_explanation" />
        </Section>
        <Section title="FRESHNESS">
          <Line label="Current assessment" value={latestFreshness.status} />
          <Items values={inspector.freshness_assessments} field="bounded_explanation" />
        </Section>
        <Section title="PROTECTION">
          <Line label="Source media" value={latestProtection.source_media_status} />
          <Line label="Accepted output" value={latestProtection.accepted_output_status} />
          <Line label="Immutable" value={latestProtection.immutable_status} />
          <Items values={inspector.protection_assessments} field="bounded_explanation" />
        </Section>
        <Section title="INVENTORY">
          <Count label="Inventories" value={inspector.inventories} />
          <Line label="Current inventory" value={summary.current_inventory_id} />
          <Count label="Present" value={latestInventory.present_reference_ids} />
          <Count label="Missing required" value={latestInventory.missing_required_reference_ids} />
          <Count label="Orphan candidates" value={latestInventory.orphan_candidate_reference_ids} />
        </Section>
        <Section title="LINEAGE">
          <Items values={inspector.lineage_edges} field="relationship" />
        </Section>
        <Section title="MISSING OR ORPHANED ARTIFACTS">
          <Items values={inspector.findings} field="confirmed_fact" />
        </Section>
        <Section title="DUPLICATES AND CONFLICTS">
          <Items values={inspector.comparisons} field="bounded_explanation" />
        </Section>
        <Section title="DEEPER VALIDATION REQUIRED">
          <Items values={inspector.handoffs} field="reason" />
        </Section>
        <Section title="WHAT HAPPENS NEXT">
          <Line label="Safest next action" value={summary.safest_next_action} />
          <Count label="Inspection events" value={inspector.events} />
        </Section>
      </div>

      {actionError && <p className="mt-3 text-xs text-rose-100">{actionError.message}</p>}

      <div className="mt-4 flex flex-wrap gap-2">
        <button
          className="rounded-lg border border-white/15 px-3 py-2 text-xs text-white"
          onClick={() => void registryQuery.refetch()}
          type="button"
        >
          Inspect artifact types
        </button>
        <button
          className="rounded-lg border border-white/15 px-3 py-2 text-xs text-white disabled:opacity-50"
          disabled={!references.length || createInspectionRequest.isPending}
          onClick={() => createInspectionRequest.mutate(references)}
          title={
            references.length
              ? "Create a read-only request from persisted exact artifact references."
              : "No persisted exact artifact references are available yet."
          }
          type="button"
        >
          Create inspection request
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
          disabled={!latestRequestId || inspectArtifacts.isPending}
          onClick={() => inspectArtifacts.mutate(latestRequestId)}
          type="button"
        >
          Inspect selected artifacts
        </button>
        <button
          className="rounded-lg border border-white/15 px-3 py-2 text-xs text-white disabled:opacity-50"
          disabled={!latestRunId || buildInventory.isPending}
          onClick={() => buildInventory.mutate(latestRunId)}
          type="button"
        >
          Build project inventory
        </button>
        <button
          className="rounded-lg border border-white/15 px-3 py-2 text-xs text-white disabled:opacity-50"
          disabled={!latestRunId || inspectLineage.isPending}
          onClick={() => inspectLineage.mutate(latestRunId)}
          type="button"
        >
          Inspect lineage
        </button>
        <button
          className="rounded-lg border border-white/15 px-3 py-2 text-xs text-white disabled:opacity-50"
          disabled={!latestRunId || referenceIds.length < 2 || compareArtifacts.isPending}
          onClick={() =>
            compareArtifacts.mutate({
              runId: latestRunId,
              left: referenceIds[0] ?? "",
              right: referenceIds[1] ?? "",
            })
          }
          type="button"
        >
          Compare artifacts
        </button>
        <button
          className="rounded-lg border border-white/15 px-3 py-2 text-xs text-white"
          onClick={() => exportInspection.mutate()}
          type="button"
        >
          Export inspection
        </button>
        <button
          className="rounded-lg border border-rose-300/30 px-3 py-2 text-xs text-rose-100"
          onClick={() => resetInspector.mutate()}
          type="button"
        >
          Reset active metadata
        </button>
      </div>
    </section>
  );
}
