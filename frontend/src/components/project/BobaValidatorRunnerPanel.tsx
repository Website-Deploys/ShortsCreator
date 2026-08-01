"use client";

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
    throw new Error(`Validator Runner request failed (${response.status}).`);
  }
  return (await response.json()) as JsonRecord;
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
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

export function BobaValidatorRunnerPanel({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const key = ["boba-validator-runner", projectId] as const;
  const runnerQuery = useQuery({
    queryKey: key,
    queryFn: () => requestJson(`/boba/projects/${projectId}/validator-runner`),
    enabled: Boolean(projectId),
  });
  const registryQuery = useQuery({
    queryKey: [...key, "registry"],
    queryFn: () =>
      requestJson(`/boba/projects/${projectId}/validator-runner/registry`),
    enabled: Boolean(projectId),
  });
  const exportRunner = useMutation({
    mutationFn: () =>
      requestJson(`/boba/projects/${projectId}/validator-runner/export`),
    onSuccess: (payload) => {
      const url = URL.createObjectURL(
        new Blob([JSON.stringify(payload, null, 2)], {
          type: "application/json",
        }),
      );
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `boba-validator-runner-${projectId}.json`;
      anchor.click();
      URL.revokeObjectURL(url);
    },
  });
  const resetRunner = useMutation({
    mutationFn: () =>
      requestJson(`/boba/projects/${projectId}/validator-runner`, {
        method: "DELETE",
      }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: key }),
  });

  if (runnerQuery.isLoading || registryQuery.isLoading) {
    return (
      <section className="rounded-2xl border border-white/10 bg-panel/70 p-5 text-sm text-muted">
        Loading BOBA Validator Runner…
      </section>
    );
  }
  if (runnerQuery.error || registryQuery.error) {
    return (
      <section className="rounded-2xl border border-rose-300/30 bg-rose-300/[0.05] p-5">
        <h3 className="font-semibold text-white">BOBA Validator Runner</h3>
        <p className="mt-2 text-sm text-rose-100">
          {(runnerQuery.error ?? registryQuery.error)?.message}
        </p>
      </section>
    );
  }

  const runner = runnerQuery.data ?? {};
  const registry = registryQuery.data ?? {};
  const snapshot = record(registry.registry_snapshot);
  const validators = list(registry.validators).map(record);
  const plans = list(runner.validation_plans).map(record);
  const runs = list(runner.validation_runs).map(record);
  const checks = list(runner.check_runs).map(record);
  const evidence = list(runner.evidence).map(record);
  const decisions = list(runner.suite_decisions).map(record);
  const plan = plans.at(-1) ?? {};
  const run = runs.at(-1) ?? {};
  const decision = decisions.at(-1) ?? {};
  const policy = list(runner.execution_policies).map(record).at(-1) ?? {};
  const budget = list(runner.resource_budgets).map(record).at(-1) ?? {};

  return (
    <section className="rounded-2xl border border-cyan-300/20 bg-panel/70 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold tracking-[0.18em] text-cyan-100">
            BOBA VALIDATOR RUNNER V1
          </p>
          <p className="mt-2 text-sm text-muted">
            Validator Runner executes only registered local validation checks.
          </p>
        </div>
        <span className="rounded-full border border-white/10 px-3 py-1 text-xs text-white">
          {text(run.run_status, "No active run")}
        </span>
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <Section title="VALIDATOR REGISTRY">
          <Line label="Registry version" value={snapshot.registry_version} />
          <Line label="Registry snapshot" value={snapshot.registry_snapshot_id} />
          <Count label="Registered validators" value={validators} />
          <Count
            label="Unavailable validators"
            value={snapshot.unavailable_validator_ids}
          />
          <p>Validator versions and availability are bound to the snapshot.</p>
        </Section>
        <Section title="VALIDATION PLAN">
          <Line label="Objective" value={plan.validation_objective} />
          <Line label="Plan" value={plan.validation_plan_id} />
          <Line label="Status" value={plan.plan_status} />
          <Line label="Safety Gate" value={plan.safety_decision_id} />
          <Line label="Approval" value={plan.approval_record_id} />
        </Section>
        <Section title="TARGET AND INPUTS">
          <Line label="Target type" value={plan.target_type} />
          <Line label="Target identity" value={plan.target_id} />
          <Line label="Workflow run" value={plan.workflow_run_id} />
          <Line label="Stage instance" value={plan.stage_instance_id} />
          <Count label="Input bindings" value={runner.input_bindings} />
          <Count label="Environment snapshots" value={runner.environment_snapshots} />
        </Section>
        <Section title="REQUIRED CHECKS">
          <Count label="Required checks" value={plan.required_check_ids} />
          <Count label="Completed" value={run.completed_check_run_ids} />
          <Count label="Failed" value={run.failed_check_run_ids} />
          <Count label="Unavailable" value={run.unavailable_check_run_ids} />
          <p>Required unavailable checks make the suite incomplete rather than passed.</p>
        </Section>
        <Section title="OPTIONAL CHECKS">
          <Count label="Optional checks" value={plan.optional_check_ids} />
          <Count label="Skipped" value={run.skipped_check_run_ids} />
          <Count label="Timed out" value={run.timed_out_check_run_ids} />
        </Section>
        <Section title="EXECUTION POLICY">
          <Line label="Policy" value={policy.execution_policy_id} />
          <Line label="Shell allowed" value={String(policy.shell_allowed ?? false)} />
          <Line label="Network allowed" value={String(policy.network_allowed ?? false)} />
          <Line
            label="Package installation"
            value={String(policy.package_installation_allowed ?? false)}
          />
        </Section>
        <Section title="RESOURCE BUDGET">
          <Line label="Maximum checks" value={budget.maximum_check_count} />
          <Line
            label="Total timeout"
            value={budget.maximum_total_duration_seconds}
          />
          <Line
            label="Parallel checks"
            value={budget.maximum_parallel_checks}
          />
        </Section>
        <Section title="LIVE VALIDATION">
          <Line label="Run" value={run.validation_run_id} />
          <Line label="Status" value={run.run_status} />
          <Line label="Active validator" value={run.active_check_run_id} />
          <Count label="Check runs" value={checks} />
        </Section>
        <Section title="RESULTS">
          <Count label="Results" value={runner.results} />
          <Count label="Incidents" value={runner.incidents} />
          <Count label="Recent events" value={runner.events} />
        </Section>
        <Section title="EVIDENCE">
          <Count label="Evidence records" value={evidence} />
          <p>
            Changing the target, validator version, environment or project
            snapshot invalidates saved results.
          </p>
        </Section>
        <Section title="SUITE DECISION">
          <Line label="Decision" value={decision.decision} />
          <Line
            label="Technical validation passed"
            value={String(decision.technical_validation_passed ?? false)}
          />
          <p>
            A passed suite confirms only the exact technical validation plan. It
            does not approve creative quality, workflow continuation, upload or
            publication.
          </p>
        </Section>
        <Section title="WHAT HAPPENS NEXT">
          <Count label="Downstream handoffs" value={runner.handoffs} />
          <Count label="Limitations" value={decision.limitations} />
          <p>
            Passing technical evidence may be reviewed by Output Quality
            Reviewer; Workflow Controller retains transition authority.
          </p>
        </Section>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <button
          className="rounded-lg border border-white/15 px-3 py-2 text-xs text-white"
          onClick={() => void registryQuery.refetch()}
          type="button"
        >
          Inspect validators
        </button>
        {[
          "Create validation plan",
          "Validate plan",
          "Start registered validation",
          "Cancel validation",
          "Retry eligible check",
        ].map((label) => (
          <button
            className="cursor-not-allowed rounded-lg border border-white/10 px-3 py-2 text-xs text-muted"
            disabled
            key={label}
            title="Requires an exact upstream target, plan, Safety, and approval binding."
            type="button"
          >
            {label}
          </button>
        ))}
        <button
          className="rounded-lg border border-white/15 px-3 py-2 text-xs text-white"
          onClick={() => exportRunner.mutate()}
          type="button"
        >
          Export report
        </button>
        <button
          className="rounded-lg border border-rose-300/30 px-3 py-2 text-xs text-rose-100"
          onClick={() => resetRunner.mutate()}
          type="button"
        >
          Reset active metadata
        </button>
      </div>
    </section>
  );
}
