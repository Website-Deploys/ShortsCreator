"use client";

/**
 * The Production Monitoring & Analytics admin dashboard.
 *
 * A strictly read-only operational view over Olympus's real, persisted execution
 * state, with eight views: Overview (health + alerts + usage), Engines, Queue,
 * Storage, Failures, Cost, Audit, and Alerts. Every figure comes from real
 * backend measurement - values that cannot be measured are shown as "Unknown"
 * (never fabricated). Nothing on this page modifies an engine or the workflow.
 */
import { useState } from "react";

import { AppShell } from "@/components/AppShell";
import {
  ActivityIcon,
  AlertIcon,
  ServerIcon,
} from "@/components/icons";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import {
  clockTime,
  engineLabel,
  formatBytes,
  formatMs,
  formatNumber,
  formatRate,
  formatScore,
  formatUsd,
  healthDot,
  healthTone,
  humanize,
  severityBadge,
} from "@/lib/monitoring";
import {
  useMonitoringAlerts,
  useMonitoringAudit,
  useMonitoringCost,
  useMonitoringEngines,
  useMonitoringFailures,
  useMonitoringHealth,
  useMonitoringQueue,
  useMonitoringStorage,
  useMonitoringUsage,
} from "@/lib/queries";
import type { EngineMetricsItem, SystemMetrics } from "@/lib/types";

type View = "overview" | "engines" | "queue" | "storage" | "failures" | "cost" | "audit" | "alerts";

const VIEWS: { id: View; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "engines", label: "Engines" },
  { id: "queue", label: "Queue" },
  { id: "storage", label: "Storage" },
  { id: "failures", label: "Failures" },
  { id: "cost", label: "Cost" },
  { id: "audit", label: "Audit" },
  { id: "alerts", label: "Alerts" },
];

export default function AdminPage() {
  const [view, setView] = useState<View>("overview");
  return (
    <AppShell>
      <div className="mx-auto max-w-6xl px-6 py-10">
        <div className="mb-6">
          <h1 className="text-2xl font-semibold tracking-tight">Admin & Monitoring</h1>
          <p className="mt-1 text-sm text-muted">
            Operational observability over real execution state — read-only, never fabricated.
          </p>
        </div>

        <div className="mb-8 flex flex-wrap gap-1 border-b border-white/10">
          {VIEWS.map((v) => (
            <button
              key={v.id}
              type="button"
              onClick={() => setView(v.id)}
              className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium transition-colors ${
                view === v.id
                  ? "border-accent text-white"
                  : "border-transparent text-muted hover:text-white"
              }`}
            >
              {v.label}
            </button>
          ))}
        </div>

        {view === "overview" && <OverviewView />}
        {view === "engines" && <EnginesView />}
        {view === "queue" && <QueueView />}
        {view === "storage" && <StorageView />}
        {view === "failures" && <FailuresView />}
        {view === "cost" && <CostView />}
        {view === "audit" && <AuditView />}
        {view === "alerts" && <AlertsView />}
      </div>
    </AppShell>
  );
}

function LoadingRows() {
  return (
    <div className="space-y-2">
      {[0, 1, 2, 3].map((i) => (
        <Skeleton key={i} className="h-12 w-full rounded-lg" />
      ))}
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <Card>
      <p className="text-2xl font-semibold tracking-tight text-white">{value}</p>
      <p className="mt-1 text-xs uppercase tracking-wide text-muted">{label}</p>
    </Card>
  );
}

/* ------------------------------ Overview ---------------------------------- */

function OverviewView() {
  const health = useMonitoringHealth();
  const usage = useMonitoringUsage();
  const alerts = useMonitoringAlerts();

  return (
    <div className="space-y-8">
      <Card>
        <div className="flex items-center gap-3">
          <span className={`h-3 w-3 rounded-full ${healthDot(health.data?.overall)}`} />
          <div>
            <p className="text-sm font-medium text-white">Overall health</p>
            <p className={`text-sm capitalize ${healthTone(health.data?.overall)}`}>
              {health.isLoading ? "Checking…" : (health.data?.overall ?? "Unknown")}
            </p>
          </div>
        </div>
        {health.data && (
          <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
            {health.data.engines.map((e) => (
              <div key={e.engine} className="rounded-lg border border-white/5 bg-white/[0.02] px-3 py-2">
                <div className="flex items-center gap-2">
                  <span className={`h-2 w-2 rounded-full ${healthDot(e.status)}`} />
                  <span className="truncate text-xs text-white">{engineLabel(e.engine)}</span>
                </div>
                <p className="mt-0.5 text-[11px] text-muted">
                  Failure rate: {formatRate(e.failure_rate)}
                </p>
              </div>
            ))}
          </div>
        )}
      </Card>

      {usage.isLoading || !usage.data ? (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-20 rounded-xl" />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatCard label="Projects" value={formatNumber(usage.data.projects)} />
          <StatCard label="Videos processed" value={formatNumber(usage.data.videos_processed)} />
          <StatCard label="Minutes analyzed" value={usage.data.minutes_analyzed.toFixed(1)} />
          <StatCard label="Clips" value={formatNumber(usage.data.clips)} />
          <StatCard label="Renders" value={formatNumber(usage.data.renders)} />
          <StatCard label="Workflows run" value={formatNumber(usage.data.workflows_run)} />
          <StatCard label="Stage executions" value={formatNumber(usage.data.total_stage_executions)} />
          <StatCard label="Busiest engine" value={usage.data.busiest_engine ? engineLabel(usage.data.busiest_engine) : "—"} />
        </div>
      )}

      {health.data?.system && <SystemPanel system={health.data.system} />}

      <div>
        <h2 className="mb-2 text-sm font-medium text-white">Active alerts</h2>
        {alerts.isLoading ? (
          <LoadingRows />
        ) : alerts.data && alerts.data.alerts.length > 0 ? (
          <div className="space-y-2">
            {alerts.data.alerts.slice(0, 5).map((a) => (
              <div key={a.id} className="flex items-center gap-3 rounded-lg border border-white/5 bg-white/[0.02] px-3 py-2">
                <span className={`rounded border px-1.5 py-0.5 text-[10px] uppercase ${severityBadge(a.severity)}`}>
                  {a.severity}
                </span>
                <span className="text-sm text-white/90">{a.message}</span>
              </div>
            ))}
          </div>
        ) : (
          <p className="rounded-lg bg-white/[0.02] px-3 py-3 text-sm text-muted">
            No active alerts — everything within thresholds.
          </p>
        )}
      </div>
    </div>
  );
}

function SystemPanel({ system }: { system: SystemMetrics }) {
  return (
    <Card>
      <p className="mb-3 text-sm font-medium text-white">Host system</p>
      <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
        <Metric label="CPU cores" value={formatNumber(system.cpu_count)} />
        <Metric label="Load (1m)" value={system.load_avg_1m == null ? "Unknown" : system.load_avg_1m.toFixed(2)} />
        <Metric label="Process CPU" value={system.process_cpu_seconds == null ? "Unknown" : `${system.process_cpu_seconds.toFixed(1)}s`} />
        <Metric label="Process RSS" value={formatBytes(system.process_max_rss_bytes)} />
        <Metric label="Disk used" value={formatRate(system.disk_used_pct)} />
        <Metric label="Disk free" value={formatBytes(system.disk_free_bytes)} />
      </div>
      {system.unavailable.length > 0 && (
        <p className="mt-3 text-[11px] text-muted">
          Unavailable in this environment: {system.unavailable.map(humanize).join(", ")} (reported honestly, not estimated).
        </p>
      )}
    </Card>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[11px] uppercase tracking-wide text-muted">{label}</p>
      <p className="tabular-nums text-white">{value}</p>
    </div>
  );
}

/* ------------------------------ Engines ----------------------------------- */

function EnginesView() {
  const { data, isLoading } = useMonitoringEngines();
  if (isLoading) return <LoadingRows />;
  if (!data || data.engines.length === 0) {
    return (
      <EmptyState
        icon={<ServerIcon className="h-6 w-6" />}
        title="No engine metrics yet"
        description="Per-engine performance appears here once the engines have executed stages."
      />
    );
  }
  return (
    <Card>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="text-xs uppercase tracking-wide text-muted">
            <tr>
              <th className="pb-2 pr-4 font-medium">Engine</th>
              <th className="pb-2 pr-4 font-medium">Runs</th>
              <th className="pb-2 pr-4 font-medium">Executions</th>
              <th className="pb-2 pr-4 font-medium">Completed</th>
              <th className="pb-2 pr-4 font-medium">Failed</th>
              <th className="pb-2 pr-4 font-medium">Retries</th>
              <th className="pb-2 pr-4 font-medium">Avg time</th>
              <th className="pb-2 pr-4 font-medium">Confidence</th>
              <th className="pb-2 font-medium">Completion</th>
            </tr>
          </thead>
          <tbody className="text-white/90">
            {data.engines.map((m: EngineMetricsItem) => (
              <tr key={m.engine} className="border-t border-white/5">
                <td className="py-2 pr-4 text-white">{engineLabel(m.engine)}</td>
                <td className="py-2 pr-4 tabular-nums">{m.runs}</td>
                <td className="py-2 pr-4 tabular-nums">{m.stage_executions}</td>
                <td className="py-2 pr-4 tabular-nums text-emerald-300">{m.completed}</td>
                <td className={`py-2 pr-4 tabular-nums ${m.failed > 0 ? "text-rose-300" : ""}`}>
                  {m.failed}
                </td>
                <td className="py-2 pr-4 tabular-nums">{m.retries}</td>
                <td className="py-2 pr-4 tabular-nums">{formatMs(m.avg_execution_ms)}</td>
                <td className="py-2 pr-4 tabular-nums">{formatScore(m.avg_confidence)}</td>
                <td className="py-2 tabular-nums">{formatRate(m.completion_rate)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-[11px] text-muted">
        Unmeasured values show as “—” / “Unknown”. UNAVAILABLE stages are counted separately and never treated as failures.
      </p>
    </Card>
  );
}

/* ------------------------------ Queue ------------------------------------- */

function QueueView() {
  const { data, isLoading } = useMonitoringQueue();
  if (isLoading || !data) return <LoadingRows />;
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard label="Queued" value={formatNumber(data.queued)} />
        <StatCard label="Running" value={formatNumber(data.running)} />
        <StatCard label="Completed" value={formatNumber(data.completed)} />
        <StatCard label="Failed" value={formatNumber(data.failed)} />
        <StatCard label="Dead" value={formatNumber(data.dead)} />
        <StatCard label="Active workflows" value={formatNumber(data.active_workflows)} />
        <StatCard label="Workers" value={formatNumber(data.worker_count)} />
        <StatCard label="Utilization" value={formatRate(data.worker_utilization)} />
      </div>

      <Card>
        <p className="text-sm font-medium text-white">Worker pool</p>
        <p className="mt-1 text-xs text-muted">
          {data.pool_running
            ? `Pool running — ${data.busy_workers} busy, ${data.idle_workers} idle, ${data.offline_workers} offline.`
            : "Worker pool not introspected (no live workflow service attached) — counts derived from persisted jobs."}
        </p>
        <p className="mt-2 text-xs text-muted">
          Avg queue latency: {formatMs(data.avg_queue_latency_ms)}
        </p>
      </Card>

      {(data.stuck_jobs.length > 0 || data.dead_jobs.length > 0) && (
        <Card>
          <p className="mb-2 text-sm font-medium text-white">Attention required</p>
          {data.stuck_jobs.length > 0 && (
            <p className="text-xs text-amber-300">{data.stuck_jobs.length} stuck job(s).</p>
          )}
          {data.dead_jobs.length > 0 && (
            <ul className="mt-1 space-y-1 text-xs text-rose-300">
              {data.dead_jobs.map((j, i) => (
                <li key={i}>
                  {String(j.stage ?? "stage")} — {String(j.error ?? "no error recorded")}
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}
    </div>
  );
}

/* ------------------------------ Storage ----------------------------------- */

function StorageView() {
  const { data, isLoading } = useMonitoringStorage();
  if (isLoading || !data) return <LoadingRows />;
  const namespaces = Object.entries(data.namespaces)
    .filter(([, bytes]) => bytes > 0)
    .sort((a, b) => b[1] - a[1]);
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between text-xs text-muted">
        <span>Storage by namespace</span>
        <span>Total: {formatBytes(data.total_bytes)}</span>
      </div>
      {namespaces.length === 0 ? (
        <EmptyState
          icon={<ServerIcon className="h-6 w-6" />}
          title="No storage used"
          description="Storage usage by namespace appears here as Olympus produces output."
        />
      ) : (
        <Card>
          <ul className="divide-y divide-white/5">
            {namespaces.map(([ns, bytes]) => (
              <li key={ns} className="flex items-center justify-between gap-3 py-2">
                <span className="text-sm capitalize text-white">{ns}</span>
                <span className="text-sm tabular-nums text-muted">{formatBytes(bytes)}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}
      <Card>
        <p className="text-sm font-medium text-white">Trend</p>
        {data.trend.length === 0 ? (
          <p className="mt-1 text-xs text-muted">
            No captured points yet. Trend accumulates from snapshots captured over time.
          </p>
        ) : (
          <ul className="mt-2 space-y-1 text-xs text-muted">
            {data.trend.slice(-8).map((p, i) => (
              <li key={i} className="flex justify-between tabular-nums">
                <span>{clockTime(p.ts)}</span>
                <span>{formatBytes(p.total_bytes)}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

/* ------------------------------ Failures ---------------------------------- */

function FailuresView() {
  const { data, isLoading } = useMonitoringFailures();
  if (isLoading || !data) return <LoadingRows />;
  if (data.total_failures === 0) {
    return (
      <EmptyState
        icon={<AlertIcon className="h-6 w-6" />}
        title="No failures recorded"
        description="Genuine FAILED stages and dead jobs appear here. Honest UNAVAILABLE stages are never counted as failures."
      />
    );
  }
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Card>
          <p className="mb-2 text-xs uppercase tracking-wide text-muted">By engine</p>
          {Object.entries(data.by_engine).map(([k, v]) => (
            <div key={k} className="flex justify-between text-sm text-white/90">
              <span>{engineLabel(k)}</span>
              <span className="tabular-nums">{v}</span>
            </div>
          ))}
        </Card>
        <Card>
          <p className="mb-2 text-xs uppercase tracking-wide text-muted">By exception</p>
          {Object.entries(data.by_exception).map(([k, v]) => (
            <div key={k} className="flex justify-between text-sm text-white/90">
              <span className="truncate pr-2">{k}</span>
              <span className="tabular-nums">{v}</span>
            </div>
          ))}
        </Card>
        <Card>
          <p className="mb-2 text-xs uppercase tracking-wide text-muted">Total</p>
          <p className="text-2xl font-semibold text-rose-300">{data.total_failures}</p>
        </Card>
      </div>
      <Card>
        <p className="mb-2 text-sm font-medium text-white">Recent failures</p>
        <ul className="divide-y divide-white/5">
          {data.recent.map((r, i) => (
            <li key={i} className="py-2">
              <div className="flex justify-between text-sm">
                <span className="text-white">{engineLabel(r.engine)} · {r.stage}</span>
                <span className="text-[11px] text-muted">{clockTime(r.ts)}</span>
              </div>
              <p className="text-[11px] text-rose-300/80">{r.error ?? "No error message recorded"}</p>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}

/* ------------------------------ Cost -------------------------------------- */

function CostView() {
  const { data, isLoading } = useMonitoringCost();
  if (isLoading || !data) return <LoadingRows />;
  return (
    <div className="space-y-4">
      <Card>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs uppercase tracking-wide text-muted">
              <tr>
                <th className="pb-2 pr-4 font-medium">Item</th>
                <th className="pb-2 pr-4 font-medium">Quantity</th>
                <th className="pb-2 pr-4 font-medium">Rate</th>
                <th className="pb-2 font-medium">Estimated</th>
              </tr>
            </thead>
            <tbody className="text-white/90">
              {data.lines.map((line) => (
                <tr key={line.item} className="border-t border-white/5">
                  <td className="py-2 pr-4 capitalize text-white">{humanize(line.item)}</td>
                  <td className="py-2 pr-4 tabular-nums">
                    {line.quantity == null ? "Unknown" : `${line.quantity} ${line.unit}`}
                  </td>
                  <td className="py-2 pr-4 tabular-nums text-muted">{formatUsd(line.rate_usd)}</td>
                  <td className="py-2 tabular-nums">{formatUsd(line.estimated_usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="mt-3 flex items-center justify-between border-t border-white/10 pt-3">
          <span className="text-sm font-medium text-white">Estimated total</span>
          <span className="text-lg font-semibold text-white">{formatUsd(data.total_usd)}</span>
        </div>
      </Card>
      <p className="text-[11px] text-muted">{data.disclaimer}</p>
    </div>
  );
}

/* ------------------------------ Audit ------------------------------------- */

function AuditView() {
  const { data, isLoading } = useMonitoringAudit();
  if (isLoading) return <LoadingRows />;
  if (!data || data.entries.length === 0) {
    return (
      <EmptyState
        icon={<ActivityIcon className="h-6 w-6" />}
        title="No audit entries yet"
        description="Workflow starts/completions, render and optimization executions, and recorded operator actions appear here."
      />
    );
  }
  return (
    <Card>
      <ul className="space-y-2.5">
        {data.entries.map((e) => (
          <li key={e.id} className="flex items-start gap-3">
            <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-accent" />
            <div className="min-w-0 flex-1">
              <p className="text-sm text-white">{e.message}</p>
              <p className="text-[11px] text-muted">
                {humanize(e.action)} · {clockTime(e.ts)} · {e.source}
              </p>
            </div>
          </li>
        ))}
      </ul>
    </Card>
  );
}

/* ------------------------------ Alerts ------------------------------------ */

function AlertsView() {
  const { data, isLoading } = useMonitoringAlerts();
  if (isLoading) return <LoadingRows />;
  if (!data || data.alerts.length === 0) {
    return (
      <EmptyState
        icon={<AlertIcon className="h-6 w-6" />}
        title="No active alerts"
        description="Informational alerts (dead jobs, stuck workers, large storage, disk pressure, repeated failures, low confidence) appear here when measured thresholds are crossed."
      />
    );
  }
  return (
    <div className="space-y-2">
      {data.alerts.map((a) => (
        <Card key={a.id}>
          <div className="flex items-start gap-3">
            <span className={`rounded border px-1.5 py-0.5 text-[10px] uppercase ${severityBadge(a.severity)}`}>
              {a.severity}
            </span>
            <div>
              <p className="text-sm text-white">{a.message}</p>
              <p className="text-[11px] text-muted">{humanize(a.category)}</p>
            </div>
          </div>
        </Card>
      ))}
      <p className="text-[11px] text-muted">
        Alerts are informational only — no notifications are sent.
      </p>
    </div>
  );
}
