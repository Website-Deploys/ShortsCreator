"use client";

import { useMemo, useState, type ReactNode } from "react";

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

function path(projectId: string, suffix = ""): string {
  return "/boba/projects/" + projectId + "/final-decision-bus" + suffix;
}

async function requestJson(route: string, init?: RequestInit): Promise<JsonRecord> {
  const response = await fetch(API_V1 + route, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    if (response.status === 404) return {};
    throw new Error("Final Decision Bus request failed (" + response.status + ").");
  }
  return (await response.json()) as JsonRecord;
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <details className="rounded-xl border border-white/10 bg-black/10 p-3" open={title === "PROPOSED ACTION"}>
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
      <span className="max-w-[65%] break-words text-right text-white">{text(value)}</span>
    </div>
  );
}

function Button({
  children,
  disabled,
  onClick,
}: {
  children: ReactNode;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      className="rounded-lg border border-white/15 bg-white/[0.06] px-3 py-2 text-xs font-semibold text-white transition hover:bg-white/[0.12] disabled:cursor-not-allowed disabled:opacity-50"
      disabled={disabled}
      onClick={onClick}
      type="button"
    >
      {children}
    </button>
  );
}

function SourceLine({
  label,
  sourceId,
  bindings,
}: {
  label: string;
  sourceId: string;
  bindings: JsonRecord[];
}) {
  const matching = bindings.filter((binding) => binding.decision_source_id === sourceId);
  const latest = matching.at(-1);
  return (
    <Line
      label={label}
      value={
        latest
          ? text(latest.observed_decision, text(latest.observed_status))
          : "Not available"
      }
    />
  );
}

export function BobaFinalDecisionBusPanel({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const key = ["boba-final-decision-bus", projectId] as const;
  const [actionPolicyId, setActionPolicyId] = useState("");
  const [requestId, setRequestId] = useState("");
  const [decisionId, setDecisionId] = useState("");
  const [envelopeId, setEnvelopeId] = useState("");
  const [invalidationReason, setInvalidationReason] = useState("");
  const [sourceSelectorsText, setSourceSelectorsText] = useState("[]");
  const [lastResult, setLastResult] = useState<JsonRecord>({});

  const busQuery = useQuery({
    queryKey: key,
    queryFn: () => requestJson(path(projectId)),
    enabled: Boolean(projectId),
  });
  const registryQuery = useQuery({
    queryKey: [...key, "registries"],
    queryFn: () => requestJson(path(projectId, "/registries")),
    enabled: Boolean(projectId),
  });
  const sourcesQuery = useQuery({
    queryKey: [...key, "sources"],
    queryFn: () => requestJson(path(projectId, "/sources")),
    enabled: Boolean(projectId),
  });
  const actionsQuery = useQuery({
    queryKey: [...key, "actions"],
    queryFn: () => requestJson(path(projectId, "/actions")),
    enabled: Boolean(projectId),
  });
  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: key }),
      queryClient.invalidateQueries({ queryKey: [...key, "registries"] }),
      queryClient.invalidateQueries({ queryKey: [...key, "sources"] }),
      queryClient.invalidateQueries({ queryKey: [...key, "actions"] }),
    ]);

  const createRequest = useMutation({
    mutationFn: ({ policy, selectors }: { policy: JsonRecord; selectors: JsonRecord[] }) =>
      requestJson(path(projectId, "/requests"), {
        method: "POST",
        body: JSON.stringify({
          source_id: "frontend",
          requested_by_module: "final_decision_bus_panel",
          action_policy_id: text(policy.action_policy_id, ""),
          target_module_id: text(policy.target_module_id, ""),
          target_operation_id: text(policy.target_operation_id, ""),
          source_selectors: selectors,
        }),
      }),
    onSuccess: async (payload) => {
      setRequestId(text(payload.final_decision_request_id, ""));
      setLastResult(payload);
      await refresh();
    },
  });
  const validateRequest = useMutation({
    mutationFn: () => requestJson(path(projectId, "/requests/" + requestId + "/validate"), { method: "POST" }),
    onSuccess: async (payload) => {
      setLastResult(payload);
      await refresh();
    },
  });
  const collectSources = useMutation({
    mutationFn: () =>
      requestJson(path(projectId, "/requests/" + requestId + "/collect-source-decisions"), {
        method: "POST",
      }),
    onSuccess: async (payload) => {
      setLastResult(payload);
      await refresh();
    },
  });
  const bindEvidence = useMutation({
    mutationFn: () =>
      requestJson(path(projectId, "/requests/" + requestId + "/bind-evidence"), {
        method: "POST",
      }),
    onSuccess: async (payload) => {
      setLastResult(payload);
      await refresh();
    },
  });
  const evaluatePolicy = useMutation({
    mutationFn: () =>
      requestJson(path(projectId, "/requests/" + requestId + "/evaluate"), {
        method: "POST",
      }),
    onSuccess: async (payload) => {
      setLastResult(payload);
      await refresh();
    },
  });
  const finalizeDecision = useMutation({
    mutationFn: () =>
      requestJson(path(projectId, "/requests/" + requestId + "/finalize"), {
        method: "POST",
      }),
    onSuccess: async (payload) => {
      setDecisionId(text(payload.final_decision_id, ""));
      setLastResult(payload);
      await refresh();
    },
  });
  const buildEnvelope = useMutation({
    mutationFn: () =>
      requestJson(path(projectId, "/decisions/" + decisionId + "/dispatch-envelope"), {
        method: "POST",
      }),
    onSuccess: async (payload) => {
      setEnvelopeId(text(payload.dispatch_envelope_id, ""));
      setLastResult(payload);
      await refresh();
    },
  });
  const invalidateDecision = useMutation({
    mutationFn: () =>
      requestJson(path(projectId, "/decisions/" + decisionId + "/invalidate"), {
        method: "POST",
        body: JSON.stringify({
          reason: invalidationReason,
          invalidated_by_module: "final_decision_bus_panel",
        }),
      }),
    onSuccess: async (payload) => {
      setLastResult(payload);
      await refresh();
    },
  });
  const exportBus = useMutation({
    mutationFn: () => requestJson(path(projectId, "/export")),
    onSuccess: (payload) => {
      const url = URL.createObjectURL(
        new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" }),
      );
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "boba-final-decision-bus-" + projectId + ".json";
      anchor.click();
      URL.revokeObjectURL(url);
    },
  });
  const resetBus = useMutation({
    mutationFn: () => requestJson(path(projectId), { method: "DELETE" }),
    onSuccess: async (payload) => {
      setRequestId("");
      setDecisionId("");
      setEnvelopeId("");
      setLastResult(payload);
      await refresh();
    },
  });

  const bus = busQuery.data ?? {};
  const registry = registryQuery.data ?? {};
  const policies = useMemo(
    () =>
      list(actionsQuery.data?.action_policies ?? registry.action_policies)
        .map(record)
        .filter((policy) => policy.availability === "available"),
    [actionsQuery.data, registry.action_policies],
  );
  const selectedPolicy =
    policies.find((policy) => policy.action_policy_id === actionPolicyId) ?? policies[0] ?? {};
  const sourceSelectorResult = useMemo(() => {
    try {
      const parsed: unknown = JSON.parse(sourceSelectorsText);
      if (
        !Array.isArray(parsed) ||
        parsed.some(
          (item) =>
            !record(item).decision_source_id || !record(item).producer_record_id,
        )
      ) {
        return {
          selectors: [] as JsonRecord[],
          error: "Use an array of exact decision_source_id and producer_record_id objects.",
        };
      }
      return { selectors: parsed.map(record), error: "" };
    } catch {
      return { selectors: [] as JsonRecord[], error: "Source selectors must be valid JSON." };
    }
  }, [sourceSelectorsText]);
  const sourceDescriptors = list(sourcesQuery.data?.decision_sources ?? registry.decision_sources)
    .map(record);
  const sourceBindings = list(bus.source_bindings).map(record);
  const evidenceBindings = list(bus.evidence_bindings).map(record);
  const conflicts = list(bus.conflicts).map(record);
  const evaluations = list(bus.policy_evaluations).map(record);
  const decisions = list(bus.final_decisions).map(record);
  const envelopes = list(bus.dispatch_envelopes).map(record);
  const latestEvaluation = evaluations.at(-1) ?? {};
  const latestDecision = decisions.at(-1) ?? {};
  const latestEnvelope = envelopes.at(-1) ?? {};
  const missingEvidence = evidenceBindings.filter((binding) => binding.satisfied !== true);
  const disposition = text(
    latestDecision.disposition ?? latestEvaluation.disposition,
    "Not evaluated",
  );
  const busy =
    createRequest.isPending ||
    validateRequest.isPending ||
    collectSources.isPending ||
    bindEvidence.isPending ||
    evaluatePolicy.isPending ||
    finalizeDecision.isPending ||
    buildEnvelope.isPending ||
    invalidateDecision.isPending ||
    resetBus.isPending;

  if (busQuery.isLoading || registryQuery.isLoading) {
    return (
      <section className="rounded-2xl border border-white/10 bg-panel/70 p-5 text-sm text-muted">
        Loading BOBA Final Decision Bus...
      </section>
    );
  }

  if (busQuery.error || registryQuery.error) {
    return (
      <section className="rounded-2xl border border-rose-300/30 bg-rose-300/[0.05] p-5">
        <h3 className="font-semibold text-white">BOBA Final Decision Bus</h3>
        <p className="mt-2 text-sm text-rose-100">
          {(busQuery.error ?? registryQuery.error)?.message}
        </p>
      </section>
    );
  }

  return (
    <section className="space-y-4 rounded-2xl border border-white/10 bg-panel/70 p-5">
      <div>
        <p className="text-xs font-semibold tracking-[0.16em] text-primary">BOBA V1</p>
        <h3 className="mt-1 text-lg font-semibold text-white">Final Decision Bus</h3>
        <p className="mt-2 text-sm text-muted">
          Final Decision Bus combines current authoritative decisions for one exact internal action.
        </p>
        <p className="mt-1 text-sm text-muted">
          It cannot override Rights, Safety, approval, validation, quality, artifact or workflow decisions.
        </p>
        <p className="mt-1 text-sm text-muted">
          A ready decision permits creation of a single-use internal dispatch envelope. It does not execute the action.
        </p>
        <p className="mt-1 text-sm text-muted">
          Any meaningful state change invalidates the decision.
        </p>
      </div>

      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        <Button onClick={() => void sourcesQuery.refetch()}>Inspect decision sources</Button>
        <Button onClick={() => void actionsQuery.refetch()}>Inspect action policies</Button>
        <Button
          disabled={!selectedPolicy.action_policy_id || Boolean(sourceSelectorResult.error) || busy}
          onClick={() => createRequest.mutate({ policy: selectedPolicy, selectors: sourceSelectorResult.selectors })}
        >
          Create exact request
        </Button>
        <Button disabled={!requestId || busy} onClick={() => validateRequest.mutate()}>
          Validate request
        </Button>
        <Button disabled={!requestId || busy} onClick={() => collectSources.mutate()}>
          Collect source decisions
        </Button>
        <Button disabled={!requestId || busy} onClick={() => bindEvidence.mutate()}>
          Bind evidence
        </Button>
        <Button disabled={!requestId || busy} onClick={() => evaluatePolicy.mutate()}>
          Evaluate policy
        </Button>
        <Button disabled={!requestId || busy} onClick={() => finalizeDecision.mutate()}>
          Finalize decision
        </Button>
        <Button disabled={!decisionId || busy} onClick={() => buildEnvelope.mutate()}>
          Build dispatch envelope
        </Button>
        <Button disabled={busy} onClick={() => exportBus.mutate()}>
          Export
        </Button>
        <Button disabled={busy} onClick={() => resetBus.mutate()}>
          Reset active metadata
        </Button>
      </div>

      <label className="block text-xs text-muted">
        Action policy
        <select
          className="mt-1 w-full rounded-lg border border-white/15 bg-black/20 px-3 py-2 text-sm text-white"
          onChange={(event) => setActionPolicyId(event.target.value)}
          value={actionPolicyId || text(selectedPolicy.action_policy_id, "")}
        >
          {policies.map((policy) => (
            <option key={text(policy.action_policy_id)} value={text(policy.action_policy_id)}>
              {text(policy.display_name, text(policy.action_policy_id))}
            </option>
          ))}
        </select>
      </label>
      <label className="block text-xs text-muted">
        Exact source selectors JSON
        <textarea
          className="mt-1 min-h-24 w-full rounded-lg border border-white/15 bg-black/20 px-3 py-2 font-mono text-xs text-white"
          onChange={(event) => setSourceSelectorsText(event.target.value)}
          value={sourceSelectorsText}
        />
      </label>
      <p className="text-xs text-amber-100">
        Enter only exact owner-record IDs and optional canonical digests. This panel never selects evidence automatically.
        {sourceSelectorResult.error ? " " + sourceSelectorResult.error : ""}
      </p>

      <Section title="PROPOSED ACTION">
        <Line label="Policy" value={selectedPolicy.action_policy_id} />
        <Line label="Target module" value={selectedPolicy.target_module_id} />
        <Line label="Target operation" value={selectedPolicy.target_operation_id} />
        <Line label="Request" value={requestId || "Not created"} />
      </Section>
      <Section title="AUTHORITATIVE SOURCES">
        <Line label="Registered source count" value={sourceDescriptors.length} />
        <Line label="Bound source count" value={sourceBindings.length} />
        {sourceDescriptors.slice(0, 12).map((source) => (
          <Line
            key={text(source.decision_source_id)}
            label={text(source.decision_source_id)}
            value={source.availability}
          />
        ))}
      </Section>
      <Section title="RIGHTS">
        <SourceLine label="Rights + Permission Gate" sourceId="rights_permission_gate" bindings={sourceBindings} />
      </Section>
      <Section title="SAFETY">
        <SourceLine label="Safety Gate" sourceId="safety_gate" bindings={sourceBindings} />
      </Section>
      <Section title="APPROVAL">
        <SourceLine label="Target approval" sourceId="target_approval" bindings={sourceBindings} />
      </Section>
      <Section title="WORKFLOW">
        <SourceLine label="Workflow Controller" sourceId="workflow_controller" bindings={sourceBindings} />
      </Section>
      <Section title="ARTIFACTS">
        <SourceLine label="Artifact Inspector" sourceId="artifact_inspector" bindings={sourceBindings} />
      </Section>
      <Section title="TECHNICAL VALIDATION">
        <SourceLine label="Validator Runner" sourceId="validator_runner" bindings={sourceBindings} />
      </Section>
      <Section title="OUTPUT QUALITY">
        <SourceLine label="Output Quality Reviewer" sourceId="output_quality_reviewer" bindings={sourceBindings} />
      </Section>
      <Section title="RECOVERY STATE">
        <SourceLine label="Repair Planner" sourceId="repair_planner" bindings={sourceBindings} />
        <SourceLine label="Code Surgeon" sourceId="code_surgeon" bindings={sourceBindings} />
        <SourceLine label="Tool Recovery" sourceId="tool_recovery_brain" bindings={sourceBindings} />
      </Section>
      <Section title="MISSING EVIDENCE">
        <Line label="Unsatisfied requirements" value={missingEvidence.length} />
        {missingEvidence.slice(0, 8).map((item) => (
          <p className="rounded border border-amber-200/20 p-2 text-amber-100" key={text(item.evidence_binding_id)}>
            {text(item.bounded_reason)}
          </p>
        ))}
      </Section>
      <Section title="CONFLICTS">
        <Line label="Unresolved conflicts" value={conflicts.filter((item) => item.unresolved !== false).length} />
        {conflicts.slice(-8).map((item) => (
          <p className="rounded border border-rose-300/20 p-2 text-rose-100" key={text(item.conflict_id)}>
            {text(item.bounded_summary)}
          </p>
        ))}
      </Section>
      <Section title="FINAL DISPOSITION">
        <Line label="Disposition" value={disposition} />
        <Line label="Ready for dispatch" value={latestDecision.ready_for_dispatch} />
        <Line label="Decision ID" value={decisionId || latestDecision.final_decision_id} />
      </Section>
      <Section title="DISPATCH ENVELOPE">
        <Line label="Envelope ID" value={envelopeId || latestEnvelope.dispatch_envelope_id} />
        <Line label="Single use" value={latestEnvelope.single_use} />
        <Line label="Consumed" value={latestEnvelope.consumed} />
        <Line label="Execution" value="Never performed by this panel" />
      </Section>
      <Section title="WHAT HAPPENS NEXT">
        <p>
          Resolve missing or stale source-owner evidence, then evaluate again. A ready envelope is only
          routing metadata; Integration Layer and the exact target independently revalidate it.
        </p>
        <label className="block pt-2">
          <span className="text-xs text-muted">Invalidation reason</span>
          <input
            className="mt-1 w-full rounded-lg border border-white/15 bg-black/20 px-3 py-2 text-sm text-white"
            onChange={(event) => setInvalidationReason(event.target.value)}
            placeholder="Explain the meaningful state change"
            value={invalidationReason}
          />
        </label>
        <div className="pt-2">
          <Button
            disabled={!decisionId || !invalidationReason.trim() || busy}
            onClick={() => invalidateDecision.mutate()}
          >
            Invalidate decision
          </Button>
        </div>
      </Section>

      {(createRequest.error ||
        validateRequest.error ||
        collectSources.error ||
        bindEvidence.error ||
        evaluatePolicy.error ||
        finalizeDecision.error ||
        buildEnvelope.error ||
        invalidateDecision.error ||
        resetBus.error) && (
        <p className="rounded-lg border border-rose-300/30 bg-rose-300/[0.05] p-3 text-sm text-rose-100">
          {String(
            createRequest.error?.message ??
              validateRequest.error?.message ??
              collectSources.error?.message ??
              bindEvidence.error?.message ??
              evaluatePolicy.error?.message ??
              finalizeDecision.error?.message ??
              buildEnvelope.error?.message ??
              invalidateDecision.error?.message ??
              resetBus.error?.message ??
              "Final Decision Bus request failed.",
          )}
        </p>
      )}
      {Object.keys(lastResult).length > 0 && (
        <p className="text-xs text-muted">
          Last metadata response recorded. No command, workflow transition, validator, repair, or target action ran.
        </p>
      )}
    </section>
  );
}