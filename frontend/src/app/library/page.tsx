"use client";

/**
 * The Project Management & Asset Library.
 *
 * A read-only production dashboard over everything Olympus has produced, with
 * six views: Dashboard (global stats + search), Assets, Clips, Exports, Activity,
 * and Storage. Everything shown comes from real backend aggregation - no
 * fabricated numbers. The only mutating actions are the explicit cleanup/archive
 * controls (clearly labelled), exactly as the product requires.
 */
import { useState } from "react";
import Link from "next/link";

import { AppShell } from "@/components/AppShell";
import {
  ActivityIcon,
  ArchiveIcon,
  FilmIcon,
  LayersIcon,
  SearchIcon,
  TrashIcon,
} from "@/components/icons";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import {
  activityTone,
  assetKindLabel,
  clockTime,
  formatBytes,
  formatDuration,
  formatMs,
  formatScore,
  humanize,
  namespaceLabel,
  statusTone,
} from "@/lib/library";
import {
  useArchiveProject,
  useLibraryActivity,
  useLibraryAssets,
  useLibraryClips,
  useLibraryCleanup,
  useLibraryDashboard,
  useLibraryExports,
  useLibrarySearch,
  useLibraryStorage,
  useRestoreProject,
} from "@/lib/queries";
import type { LibraryAsset } from "@/lib/types";

type View = "dashboard" | "assets" | "clips" | "exports" | "activity" | "storage";

const VIEWS: { id: View; label: string }[] = [
  { id: "dashboard", label: "Dashboard" },
  { id: "assets", label: "Assets" },
  { id: "clips", label: "Clips" },
  { id: "exports", label: "Exports" },
  { id: "activity", label: "Activity" },
  { id: "storage", label: "Storage" },
];

export default function LibraryPage() {
  const [view, setView] = useState<View>("dashboard");
  return (
    <AppShell>
      <div className="mx-auto max-w-6xl px-6 py-10">
        <div className="mb-6">
          <h1 className="text-2xl font-semibold tracking-tight">Asset Library</h1>
          <p className="mt-1 text-sm text-muted">
            Everything Olympus has produced — aggregated read-only from real engine output.
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

        {view === "dashboard" && <DashboardView />}
        {view === "assets" && <AssetsView />}
        {view === "clips" && <ClipsView />}
        {view === "exports" && <ExportsView />}
        {view === "activity" && <ActivityView />}
        {view === "storage" && <StorageView />}
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

/* ------------------------------ Dashboard --------------------------------- */

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <Card>
      <p className="text-2xl font-semibold tracking-tight text-white">{value}</p>
      <p className="mt-1 text-xs uppercase tracking-wide text-muted">{label}</p>
    </Card>
  );
}

function DashboardView() {
  const { data, isLoading } = useLibraryDashboard();
  const [q, setQ] = useState("");
  const search = useLibrarySearch(q);

  return (
    <div className="space-y-8">
      {isLoading || !data ? (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-20 rounded-xl" />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatCard label="Projects" value={String(data.total_projects)} />
          <StatCard label="Videos processed" value={String(data.videos_processed)} />
          <StatCard label="Minutes analyzed" value={data.minutes_analyzed.toFixed(1)} />
          <StatCard label="Clips generated" value={String(data.clips_generated)} />
          <StatCard label="Renders completed" value={String(data.renders_completed)} />
          <StatCard label="Exports" value={String(data.exports)} />
          <StatCard label="Avg viral score" value={formatScore(data.average_viral_score)} />
          <StatCard label="Storage used" value={formatBytes(data.storage_bytes)} />
        </div>
      )}

      <div>
        <div className="relative mb-3">
          <SearchIcon className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search projects, clips, videos, exports…"
            className="w-full rounded-lg border border-white/10 bg-white/[0.02] py-2.5 pl-9 pr-3 text-sm text-white outline-none transition-colors focus:border-accent"
          />
        </div>
        {q.trim() && (
          <Card>
            {search.isLoading ? (
              <LoadingRows />
            ) : search.data && search.data.hits.length > 0 ? (
              <ul className="divide-y divide-white/5">
                {search.data.hits.map((hit) => (
                  <li key={`${hit.kind}-${hit.id}`} className="flex items-center justify-between gap-3 py-2">
                    <Link
                      href={`/projects/${hit.project_id}`}
                      className="min-w-0 transition-colors hover:text-white"
                    >
                      <p className="truncate text-sm text-white">{hit.title}</p>
                      <p className="truncate text-xs text-muted">{hit.subtitle}</p>
                    </Link>
                    <span className="shrink-0 rounded bg-white/5 px-2 py-0.5 text-[11px] text-muted">
                      {hit.kind}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="py-3 text-sm text-muted">No matches.</p>
            )}
          </Card>
        )}
      </div>
    </div>
  );
}

/* ------------------------------ Assets ------------------------------------ */

const ASSET_KINDS = ["", "source_video", "clip", "render", "export"];

function AssetsView() {
  const [kind, setKind] = useState("");
  const [showArchived, setShowArchived] = useState(false);
  const params: Record<string, string | boolean | undefined> = { kind: kind || undefined };
  if (showArchived) params.archived = true;
  const { data, isLoading } = useLibraryAssets(params);
  const archive = useArchiveProject();
  const restore = useRestoreProject();

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {ASSET_KINDS.map((k) => (
          <button
            key={k || "all"}
            type="button"
            onClick={() => setKind(k)}
            className={`rounded-lg border px-2.5 py-1 text-xs transition-colors ${
              kind === k ? "border-accent text-white" : "border-white/10 text-muted hover:text-white"
            }`}
          >
            {k ? assetKindLabel(k) : "All"}
          </button>
        ))}
        <label className="ml-auto flex items-center gap-2 text-xs text-muted">
          <input
            type="checkbox"
            checked={showArchived}
            onChange={(e) => setShowArchived(e.target.checked)}
          />
          Archived
        </label>
      </div>

      {isLoading ? (
        <LoadingRows />
      ) : !data || data.assets.length === 0 ? (
        <EmptyState
          icon={<LayersIcon className="h-6 w-6" />}
          title="No assets"
          description="Assets appear here as projects upload videos and the engines produce clips, renders, and exports."
        />
      ) : (
        <Card>
          <ul className="divide-y divide-white/5">
            {data.assets.map((asset) => (
              <AssetRow
                key={asset.id}
                asset={asset}
                onArchive={() => archive.mutate(asset.project_id)}
                onRestore={() => restore.mutate(asset.project_id)}
              />
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

function AssetRow({
  asset,
  onArchive,
  onRestore,
}: {
  asset: LibraryAsset;
  onArchive: () => void;
  onRestore: () => void;
}) {
  return (
    <li className="flex items-center justify-between gap-3 py-2.5">
      <Link href={`/projects/${asset.project_id}`} className="min-w-0 transition-colors hover:text-white">
        <p className="truncate text-sm text-white">{asset.name}</p>
        <p className="truncate text-xs text-muted">
          {assetKindLabel(asset.kind)} · {asset.project_name}
          {asset.tags.length > 0 && ` · ${asset.tags.map((t) => `#${t}`).join(" ")}`}
        </p>
      </Link>
      <div className="flex shrink-0 items-center gap-3">
        <span className="text-xs tabular-nums text-muted">{formatBytes(asset.size_bytes)}</span>
        {asset.kind === "source_video" &&
          (asset.archived ? (
            <button
              type="button"
              onClick={onRestore}
              className="text-xs text-muted hover:text-white"
              title="Restore project"
            >
              Restore
            </button>
          ) : (
            <button
              type="button"
              onClick={onArchive}
              className="text-muted transition-colors hover:text-amber-300"
              title="Archive project"
              aria-label="Archive project"
            >
              <ArchiveIcon className="h-4 w-4" />
            </button>
          ))}
      </div>
    </li>
  );
}

/* ------------------------------ Clips ------------------------------------- */

function ClipsView() {
  const { data, isLoading } = useLibraryClips();
  if (isLoading) return <LoadingRows />;
  if (!data || data.clips.length === 0) {
    return (
      <EmptyState
        icon={<FilmIcon className="h-6 w-6" />}
        title="No clips yet"
        description="Clips appear here once the Editing Engine assembles timelines from a project."
      />
    );
  }
  return (
    <Card>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="text-xs uppercase tracking-wide text-muted">
            <tr>
              <th className="pb-2 pr-4 font-medium">Clip</th>
              <th className="pb-2 pr-4 font-medium">Duration</th>
              <th className="pb-2 pr-4 font-medium">Viral score</th>
              <th className="pb-2 pr-4 font-medium">Platform</th>
              <th className="pb-2 pr-4 font-medium">Status</th>
              <th className="pb-2 font-medium">Render</th>
            </tr>
          </thead>
          <tbody className="text-white/90">
            {data.clips.map((clip) => (
              <tr key={`${clip.project_id}-${clip.clip_id}`} className="border-t border-white/5">
                <td className="py-2 pr-4">
                  <Link href={`/projects/${clip.project_id}`} className="hover:text-white">
                    {clip.title}
                  </Link>
                  <div className="text-[11px] text-muted">{clip.project_name}</div>
                </td>
                <td className="py-2 pr-4 tabular-nums">{formatDuration(clip.duration)}</td>
                <td className="py-2 pr-4">{formatScore(clip.viral_score)}</td>
                <td className="py-2 pr-4">{clip.platform ? humanize(clip.platform) : "—"}</td>
                <td className={`py-2 pr-4 ${statusTone(clip.status)}`}>{humanize(clip.status)}</td>
                <td className="py-2 tabular-nums text-muted">{clip.render_version ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

/* ------------------------------ Exports ----------------------------------- */

function ExportsView() {
  const { data, isLoading } = useLibraryExports();
  if (isLoading) return <LoadingRows />;
  if (!data || data.exports.length === 0) {
    return (
      <EmptyState
        icon={<FilmIcon className="h-6 w-6" />}
        title="No exports yet"
        description="Exports appear here once the Rendering Engine produces MP4s for a project."
      />
    );
  }
  return (
    <Card>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="text-xs uppercase tracking-wide text-muted">
            <tr>
              <th className="pb-2 pr-4 font-medium">Clip</th>
              <th className="pb-2 pr-4 font-medium">Resolution</th>
              <th className="pb-2 pr-4 font-medium">Codec</th>
              <th className="pb-2 pr-4 font-medium">Bitrate</th>
              <th className="pb-2 pr-4 font-medium">Size</th>
              <th className="pb-2 pr-4 font-medium">Render time</th>
              <th className="pb-2 font-medium">Download</th>
            </tr>
          </thead>
          <tbody className="text-white/90">
            {data.exports.map((e) => (
              <tr key={e.id} className="border-t border-white/5">
                <td className="py-2 pr-4">
                  <Link href={`/projects/${e.project_id}`} className="hover:text-white">
                    {e.clip_id}
                  </Link>
                  <div className="text-[11px] text-muted">{e.project_name}</div>
                </td>
                <td className="py-2 pr-4 tabular-nums">{e.resolution ?? "—"}</td>
                <td className="py-2 pr-4">{e.codec ?? "—"}</td>
                <td className="py-2 pr-4 tabular-nums">
                  {e.bitrate_kbps ? `${e.bitrate_kbps} kbps` : "—"}
                </td>
                <td className="py-2 pr-4 tabular-nums">{formatBytes(e.file_size)}</td>
                <td className="py-2 pr-4 tabular-nums">{formatMs(e.render_time_ms)}</td>
                <td className={`py-2 ${statusTone(e.download_status)}`}>{e.download_status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

/* ------------------------------ Activity ---------------------------------- */

function ActivityView() {
  const { data, isLoading } = useLibraryActivity();
  if (isLoading) return <LoadingRows />;
  if (!data || data.events.length === 0) {
    return (
      <EmptyState
        icon={<ActivityIcon className="h-6 w-6" />}
        title="No activity yet"
        description="Every action — project created, workflow finished, render completed, project archived — appears here."
      />
    );
  }
  return (
    <Card>
      <ul className="space-y-2.5">
        {data.events.map((event) => (
          <li key={event.id} className="flex items-start gap-3">
            <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${activityTone(event.type)}`} />
            <div className="min-w-0 flex-1">
              <p className="text-sm text-white">{event.message}</p>
              <p className="text-[11px] text-muted">
                {humanize(event.type)} · {clockTime(event.ts)}
              </p>
            </div>
          </li>
        ))}
      </ul>
    </Card>
  );
}

/* ------------------------------ Storage ----------------------------------- */

function StorageView() {
  const { data, isLoading } = useLibraryStorage();
  const cleanup = useLibraryCleanup();
  const [busy, setBusy] = useState<string | null>(null);

  const runCleanup = (operation: string) => {
    setBusy(operation);
    cleanup.mutate({ operation }, { onSettled: () => setBusy(null) });
  };

  if (isLoading) return <LoadingRows />;
  if (!data || data.breakdowns.length === 0) {
    return (
      <EmptyState
        icon={<LayersIcon className="h-6 w-6" />}
        title="No storage used"
        description="Per-project storage consumption appears here as Olympus produces output."
      />
    );
  }

  return (
    <div className="space-y-6">
      <Card>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-sm font-medium text-white">Cleanup tools</p>
            <p className="text-xs text-muted">
              Free space safely — rendered outputs are only removed when explicitly unused or failed.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              variant="secondary"
              onClick={() => runCleanup("temp-files")}
              disabled={busy !== null}
            >
              <TrashIcon className="mr-1.5 h-4 w-4" />
              Temp files
            </Button>
            <Button
              variant="secondary"
              onClick={() => runCleanup("failed-renders")}
              disabled={busy !== null}
            >
              <TrashIcon className="mr-1.5 h-4 w-4" />
              Failed renders
            </Button>
            <Button
              variant="secondary"
              onClick={() => runCleanup("unused-renders")}
              disabled={busy !== null}
            >
              <TrashIcon className="mr-1.5 h-4 w-4" />
              Unused renders
            </Button>
          </div>
        </div>
        {cleanup.data && (
          <p className="mt-3 rounded-lg bg-white/[0.03] px-3 py-2 text-xs text-muted">
            {humanize(cleanup.data.result.operation)}: removed {cleanup.data.result.deleted_count}{" "}
            file(s), freed {formatBytes(cleanup.data.result.freed_bytes)}.
          </p>
        )}
      </Card>

      <div className="mb-1 flex items-center justify-between text-xs text-muted">
        <span>Per-project consumption</span>
        <span>Total: {formatBytes(data.total_bytes)}</span>
      </div>
      <div className="space-y-3">
        {data.breakdowns.map((b) => (
          <Card key={b.project_id}>
            <div className="flex items-center justify-between gap-3">
              <Link
                href={`/projects/${b.project_id}`}
                className="truncate text-sm font-medium text-white hover:text-white"
              >
                {b.project_name}
              </Link>
              <span className="shrink-0 text-sm tabular-nums text-white">{formatBytes(b.total)}</span>
            </div>
            <div className="mt-3 flex flex-wrap gap-1.5">
              {Object.entries(b.namespaces)
                .filter(([, bytes]) => bytes > 0)
                .sort((a, c) => c[1] - a[1])
                .map(([ns, bytes]) => (
                  <span
                    key={ns}
                    className="rounded bg-white/5 px-2 py-0.5 text-[11px] text-muted"
                    title={namespaceLabel(ns)}
                  >
                    {namespaceLabel(ns)}: {formatBytes(bytes)}
                  </span>
                ))}
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}
