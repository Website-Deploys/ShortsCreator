"""The Monitoring service - the operational analytics boundary.

Aggregates the platform's real, persisted execution state into the monitoring
views: system health, engine performance, workflow analytics, queue, storage
(with captured trends), failures, usage, cost estimation, audit, alerts, and the
combined admin snapshot.

It is strictly observational: it loads each engine/workflow/library output
through its existing repository (read-only) and reads the live worker/queue state
from the running workflow service. It never modifies any of them, and never
fabricates a metric - unmeasurable values are UNKNOWN.
"""

from __future__ import annotations

from typing import Any, Protocol

from olympus.domain.contracts.analysis import AnalysisRepository
from olympus.domain.contracts.editing import EditingRepository
from olympus.domain.contracts.library import ActivityRepository
from olympus.domain.contracts.monitoring import AuditRepository, MetricsSnapshotRepository
from olympus.domain.contracts.optimization import OptimizationRepository
from olympus.domain.contracts.planning import PlanningRepository
from olympus.domain.contracts.projects import ProjectRepository
from olympus.domain.contracts.render_pipeline import RenderRunRepository
from olympus.domain.contracts.rendering import RenderManifestRepository
from olympus.domain.contracts.storage import StoragePort
from olympus.domain.contracts.story import StoryRepository
from olympus.domain.contracts.virality import ViralityRepository
from olympus.domain.contracts.workflow import WorkflowRepository
from olympus.domain.entities.monitoring import (
    AdminSnapshot,
    AuditAction,
    AuditEntry,
    CostEstimate,
    EngineHealth,
    EngineMetrics,
    FailureSummary,
    HealthStatus,
    QueueSnapshot,
    StorageAnalytics,
    StoragePoint,
    SystemMetrics,
    UsageStats,
    WorkflowAnalytics,
)
from olympus.domain.entities.workflow import JobStatus, Workflow
from olympus.monitoring import (
    alerts as alerts_mod,
)
from olympus.monitoring import (
    audit as audit_mod,
)
from olympus.monitoring import (
    cost as cost_mod,
)
from olympus.monitoring import (
    failures as failures_mod,
)
from olympus.monitoring import (
    metrics as metrics_mod,
)
from olympus.monitoring import (
    storage_analytics as storage_mod,
)
from olympus.monitoring import (
    system as system_mod,
)
from olympus.monitoring import (
    workflow_analytics as wf_mod,
)
from olympus.monitoring.metrics import stage_duration_ms
from olympus.platform.logging import get_logger
from olympus.utils import new_id, utc_now

log = get_logger(__name__)


class _LoadableAnalysisRepo(Protocol):
    """Structural type for the per-engine analysis repositories the monitor reads.

    Every engine repository exposes ``async load(project_id) -> <analysis> | None``;
    this captures exactly that capability so the monitor can hold them uniformly
    without depending on a common concrete base (their only shared ABC ancestor
    does not declare ``load``).
    """

    async def load(self, project_id: str) -> Any | None: ...

# Engine -> the repository attribute that loads its per-project analysis.
ENGINES: tuple[str, ...] = (
    "cognitive",
    "story",
    "virality",
    "planning",
    "editing",
    "rendering",
    "optimization",
)
_STUCK_AFTER_SECONDS = 300.0


class MonitoringService:
    """Read-only aggregation of measured operational analytics."""

    def __init__(
        self,
        *,
        storage: StoragePort,
        project_repo: ProjectRepository,
        analysis_repo: AnalysisRepository,
        story_repo: StoryRepository,
        virality_repo: ViralityRepository,
        planning_repo: PlanningRepository,
        editing_repo: EditingRepository,
        render_manifest_repo: RenderManifestRepository,
        render_run_repo: RenderRunRepository,
        optimization_repo: OptimizationRepository,
        workflow_repo: WorkflowRepository,
        activity_repo: ActivityRepository,
        audit_repo: AuditRepository,
        snapshot_repo: MetricsSnapshotRepository,
        workflow_service: Any | None = None,
        disk_path: str = ".",
    ) -> None:
        self._storage = storage
        self._projects = project_repo
        self._workflow_repo = workflow_repo
        self._activity = activity_repo
        self._audit = audit_repo
        self._snapshots = snapshot_repo
        self._workflow_service = workflow_service
        self._disk_path = disk_path
        self._repos: dict[str, _LoadableAnalysisRepo] = {
            "cognitive": analysis_repo,
            "story": story_repo,
            "virality": virality_repo,
            "planning": planning_repo,
            "editing": editing_repo,
            "rendering": render_run_repo,
            "optimization": optimization_repo,
        }
        self._render_manifest = render_manifest_repo
        self._render_run = render_run_repo
        self._optimization = optimization_repo
        self._analysis = analysis_repo
        self._editing = editing_repo

    # -- loading helpers ------------------------------------------------------
    async def _project_ids(self) -> list[str]:
        return [p.id for p in await self._projects.list()]

    async def _load_engine_analyses(self, engine: str, project_ids: list[str]) -> list[Any]:
        repo = self._repos[engine]
        out = []
        for pid in project_ids:
            analysis = await repo.load(pid)
            if analysis is not None:
                out.append(analysis)
        return out

    async def _load_workflows(self) -> list[Workflow]:
        workflows: list[Workflow] = []
        for pid in await self._project_ids():
            wf = await self._workflow_repo.load(pid)
            if wf is not None:
                workflows.append(wf)
        return workflows

    @staticmethod
    def _jobs_by_engine(workflows: list[Workflow]) -> dict[str, list[Any]]:
        out: dict[str, list[Any]] = {}
        for wf in workflows:
            for job in wf.jobs:
                out.setdefault(job.engine, []).append(job)
        return out

    @staticmethod
    def _concurrent_by_engine(workflows: list[Workflow]) -> dict[str, int]:
        out: dict[str, int] = {}
        for wf in workflows:
            for job in wf.jobs:
                if job.status is JobStatus.RUNNING:
                    out[job.engine] = out.get(job.engine, 0) + 1
        return out

    # -- engine metrics -------------------------------------------------------
    async def engine_metrics(self) -> list[EngineMetrics]:
        project_ids = await self._project_ids()
        workflows = await self._load_workflows()
        jobs_by_engine = self._jobs_by_engine(workflows)
        concurrent = self._concurrent_by_engine(workflows)
        out: list[EngineMetrics] = []
        for engine in ENGINES:
            analyses = await self._load_engine_analyses(engine, project_ids)
            out.append(
                metrics_mod.build_engine_metrics(
                    engine,
                    analyses,
                    jobs=jobs_by_engine.get(engine),
                    concurrent=concurrent.get(engine, 0),
                )
            )
        return out

    @staticmethod
    def _engine_health(metrics: list[EngineMetrics]) -> list[EngineHealth]:
        out: list[EngineHealth] = []
        for m in metrics:
            rate = m.failure_rate
            if m.stage_executions == 0:
                status, detail = HealthStatus.HEALTHY, "no executions observed"
            elif rate is None or rate == 0:
                status, detail = HealthStatus.HEALTHY, "no failures observed"
            elif rate < 0.25:
                status, detail = HealthStatus.DEGRADED, f"failure rate {rate}"
            else:
                status, detail = HealthStatus.UNHEALTHY, f"failure rate {rate}"
            out.append(
                EngineHealth(engine=m.engine, status=status, detail=detail, failure_rate=rate)
            )
        return out

    async def engine_health(self) -> list[EngineHealth]:
        return self._engine_health(await self.engine_metrics())

    # -- system / performance -------------------------------------------------
    def system_metrics(self) -> SystemMetrics:
        return system_mod.collect_system_metrics(self._disk_path)

    # -- workflow analytics ---------------------------------------------------
    async def workflow_analytics(self) -> WorkflowAnalytics:
        return wf_mod.build_workflow_analytics(await self._load_workflows())

    # -- queue monitoring -----------------------------------------------------
    async def queue(self) -> QueueSnapshot:
        snapshot = QueueSnapshot()
        workflows = await self._load_workflows()
        now = utc_now()
        latencies: list[float] = []
        for wf in workflows:
            for job in wf.jobs:
                status = job.status.value
                if status == "ready":
                    snapshot.queued += 1
                elif status == "running":
                    snapshot.running += 1
                    if (
                        job.started_at
                        and (now - job.started_at).total_seconds() > _STUCK_AFTER_SECONDS
                    ):
                        snapshot.stuck_jobs.append(
                            {"job_id": job.job_id, "project_id": job.project_id, "stage": job.stage}
                        )
                elif status == "pending" and job.available_at and now < job.available_at:
                    snapshot.delayed += 1
                elif status == "completed":
                    snapshot.completed += 1
                elif status == "failed":
                    snapshot.failed += 1
                elif status == "dead":
                    snapshot.dead += 1
                    snapshot.dead_jobs.append(
                        {
                            "job_id": job.job_id,
                            "project_id": job.project_id,
                            "stage": job.stage,
                            "error": job.error,
                        }
                    )
                elif status == "blocked":
                    snapshot.blocked += 1
                elif status == "cancelled":
                    snapshot.cancelled += 1
                if job.started_at and job.created_at:
                    latencies.append((job.started_at - job.created_at).total_seconds() * 1000.0)
            if wf.status.value == "running":
                snapshot.active_workflows += 1
        if latencies:
            snapshot.avg_queue_latency_ms = round(sum(latencies) / len(latencies), 2)

        # Live worker health from the running workflow service (if available).
        if self._workflow_service is not None:
            try:
                workers = await self._workflow_service.workers()
                snapshot.workers = workers
                snapshot.worker_count = len(workers)
                snapshot.busy_workers = sum(1 for w in workers if w.get("status") == "busy")
                snapshot.idle_workers = sum(1 for w in workers if w.get("status") == "idle")
                snapshot.offline_workers = sum(1 for w in workers if w.get("status") == "offline")
                sched = await self._workflow_service.scheduler_status()
                snapshot.pool_running = bool(sched.get("pool_running"))
            except Exception as exc:  # never let live introspection break monitoring
                log.warning("queue_live_introspection_failed", error=str(exc))
        return snapshot

    # -- storage analytics ----------------------------------------------------
    async def storage_analytics(self, *, capture: bool = True) -> StorageAnalytics:
        total, namespaces = await storage_mod.collect_storage(self._storage)
        if capture:
            await self._snapshots.append(
                StoragePoint(ts=utc_now(), total_bytes=total, namespaces=namespaces)
            )
        trend = await self._snapshots.list()
        return StorageAnalytics(total_bytes=total, namespaces=namespaces, trend=trend)

    # -- failures -------------------------------------------------------------
    async def failures(self) -> FailureSummary:
        project_ids = await self._project_ids()
        engine_analyses: list[tuple[str, str, Any]] = []
        for engine in ENGINES:
            repo = self._repos[engine]
            for pid in project_ids:
                analysis = await repo.load(pid)
                if analysis is not None:
                    engine_analyses.append((engine, pid, analysis))
        jobs = [job for wf in await self._load_workflows() for job in wf.jobs]
        return failures_mod.build_failure_summary(
            engine_analyses=engine_analyses, workflow_jobs=jobs
        )

    # -- usage ----------------------------------------------------------------
    async def usage(self) -> UsageStats:
        projects = await self._projects.list()
        stats = UsageStats(projects=len(projects))
        metrics = await self.engine_metrics()
        stats.total_stage_executions = sum(m.stage_executions for m in metrics)
        busiest = max(metrics, key=lambda m: m.stage_executions, default=None)
        stats.busiest_engine = busiest.engine if busiest and busiest.stage_executions else None
        for project in projects:
            analysis = await self._analysis.load(project.id)
            if analysis is not None:
                stats.videos_processed += 1
                stats.minutes_analyzed += (project.duration_seconds or 0.0) / 60.0
            editing = await self._editing.load(project.id)
            stats.clips += len(self._timelines(editing))
            manifest = await self._render_manifest.load(project.id)
            renders = len(manifest.renders) if manifest else 0
            stats.renders += renders
            stats.exports += renders
        stats.workflows_run = len(await self._load_workflows())
        return stats

    @staticmethod
    def _timelines(editing: Any) -> list[Any]:
        if editing is None:
            return []
        stage = editing.stage("timeline_validation")
        if stage is None or stage.status.value != "completed":
            return []
        tl = stage.data.get("timelines")
        return tl if isinstance(tl, list) else []

    # -- cost -----------------------------------------------------------------
    async def cost(self) -> CostEstimate:
        projects = await self._projects.list()
        transcription_minutes = 0.0
        render_minutes = 0.0
        for project in projects:
            analysis = await self._analysis.load(project.id)
            if analysis is not None:
                transcription_minutes += (project.duration_seconds or 0.0) / 60.0
            run = await self._render_run.load(project.id)
            if run is not None:
                for stage in run.stages:
                    dur = stage_duration_ms(stage)
                    if dur is not None:
                        render_minutes += dur / 60000.0
        total_storage, _ = await storage_mod.collect_storage(self._storage)
        cpu_seconds = self.system_metrics().process_cpu_seconds
        return cost_mod.build_cost_estimate(
            transcription_minutes=round(transcription_minutes, 3),
            render_minutes=round(render_minutes, 3),
            storage_bytes=total_storage,
            cpu_seconds=cpu_seconds,
        )

    # -- audit ----------------------------------------------------------------
    async def audit(self, *, limit: int = 200) -> list[AuditEntry]:
        workflows = await self._load_workflows()
        activity = await self._activity.list(limit=limit * 2)
        project_ids = await self._project_ids()
        render_runs = [(pid, await self._render_run.load(pid)) for pid in project_ids]
        optimizations = [(pid, await self._optimization.load(pid)) for pid in project_ids]
        derived = audit_mod.derive_audit_entries(
            workflows=workflows,
            activity_events=activity,
            render_runs=render_runs,
            optimizations=optimizations,
        )
        recorded = await self._audit.list(limit=limit)
        merged = derived + recorded
        # De-duplicate by id, newest first.
        seen: set[str] = set()
        out: list[AuditEntry] = []
        for entry in sorted(merged, key=lambda e: e.ts, reverse=True):
            if entry.id in seen:
                continue
            seen.add(entry.id)
            out.append(entry)
        return out[:limit]

    async def record_audit(
        self,
        action: AuditAction,
        message: str,
        *,
        project_id: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> AuditEntry:
        entry = AuditEntry(
            id=new_id("audit"),
            ts=utc_now(),
            action=action,
            message=message,
            project_id=project_id,
            source="recorded",
            detail=detail or {},
        )
        await self._audit.append(entry)
        return entry

    # -- alerts ---------------------------------------------------------------
    async def alerts(self) -> list[Any]:
        metrics = await self.engine_metrics()
        queue = await self.queue()
        storage = await self.storage_analytics(capture=False)
        system = self.system_metrics()
        failures = await self.failures()
        return alerts_mod.generate_alerts(
            engine_metrics=metrics, queue=queue, storage=storage, system=system, failures=failures
        )

    # -- health ---------------------------------------------------------------
    def _overall_health(
        self, engine_health: list[EngineHealth], queue: QueueSnapshot, system: SystemMetrics
    ) -> HealthStatus:
        statuses = [e.status for e in engine_health]
        if HealthStatus.UNHEALTHY in statuses or queue.dead > 0:
            return HealthStatus.UNHEALTHY
        disk = system.disk_used_pct
        if (
            HealthStatus.DEGRADED in statuses
            or (disk is not None and disk >= 0.85)
            or queue.stuck_jobs
        ):
            return HealthStatus.DEGRADED
        return HealthStatus.HEALTHY

    async def health(self) -> dict[str, Any]:
        metrics = await self.engine_metrics()
        engine_health = self._engine_health(metrics)
        queue = await self.queue()
        system = self.system_metrics()
        overall = self._overall_health(engine_health, queue, system)
        return {
            "overall": overall.value,
            "engines": [e.to_dict() for e in engine_health],
            "system": system.to_dict(),
            "queue": queue.to_dict(),
        }

    # -- admin (combined) -----------------------------------------------------
    async def admin(self) -> AdminSnapshot:
        metrics = await self.engine_metrics()
        engine_health = self._engine_health(metrics)
        queue = await self.queue()
        system = self.system_metrics()
        usage = await self.usage()
        storage = await self.storage_analytics()
        failures = await self.failures()
        alerts = alerts_mod.generate_alerts(
            engine_metrics=metrics, queue=queue, storage=storage, system=system, failures=failures
        )
        recent_audit = await self.audit(limit=20)
        return AdminSnapshot(
            overall_health=self._overall_health(engine_health, queue, system),
            engine_health=engine_health,
            system=system,
            queue=queue,
            usage=usage,
            storage_total_bytes=storage.total_bytes,
            alerts=alerts,
            recent_failures=failures.recent[:10],
            recent_audit=recent_audit[:20],
        )
