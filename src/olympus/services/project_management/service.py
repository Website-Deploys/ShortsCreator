"""The Library service - the Project Management application boundary.

Aggregates everything the eight engines have produced into managed views (assets,
clips, exports, search, dashboard, storage), and manages the library's own
additive state (captured versions, activity feed, favorites/tags/archive) plus
the explicitly-requested cleanup/archive operations.

It is strictly read-only over engine data: it loads each engine's output through
its existing repository and never writes back to it. The only writes it performs
are to the library's own ``library/`` namespace and the cleanup operations the
operator explicitly requests. Every figure reflects real stored state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from olympus.domain.contracts.analysis import AnalysisRepository
from olympus.domain.contracts.editing import EditingRepository
from olympus.domain.contracts.library import (
    ActivityRepository,
    LibraryMetaRepository,
    VersionRepository,
)
from olympus.domain.contracts.optimization import OptimizationRepository
from olympus.domain.contracts.planning import PlanningRepository
from olympus.domain.contracts.projects import ProjectRepository
from olympus.domain.contracts.render_pipeline import RenderRunRepository
from olympus.domain.contracts.rendering import RenderManifestRepository
from olympus.domain.contracts.storage import StoragePort
from olympus.domain.contracts.story import StoryRepository
from olympus.domain.contracts.virality import ViralityRepository
from olympus.domain.contracts.workflow import WorkflowRepository
from olympus.domain.entities.analysis import Analysis
from olympus.domain.entities.editing import EditingAnalysis
from olympus.domain.entities.library import (
    ActivityEvent,
    ActivityType,
    AssetKind,
    AssetRecord,
    CleanupResult,
    ClipRecord,
    DashboardStats,
    ExportRecord,
    ProjectLibraryMeta,
    SearchHit,
    StorageBreakdown,
    VersionRecord,
)
from olympus.domain.entities.optimization import OptimizationAnalysis
from olympus.domain.entities.planning import ClipPlanningAnalysis
from olympus.domain.entities.project import Project
from olympus.domain.entities.render_pipeline import RenderRun, RenderRunStatus
from olympus.domain.entities.rendering import RenderManifest
from olympus.domain.entities.story import StoryAnalysis
from olympus.domain.entities.virality import ViralityAnalysis
from olympus.platform.errors import NotFoundError, ValidationError
from olympus.platform.logging import get_logger
from olympus.project_management import inventory, search
from olympus.project_management.dashboard import compute_dashboard
from olympus.project_management.sizes import measure_prefix, size_of
from olympus.utils import new_id, utc_now

log = get_logger(__name__)

_VERSIONED_ENGINES = (
    "cognitive",
    "story",
    "virality",
    "planning",
    "editing",
    "rendering",
    "optimization",
)


@dataclass(slots=True)
class _Bundle:
    """A project's loaded engine outputs (read-only)."""

    project: Project
    meta: ProjectLibraryMeta
    analysis: Analysis | None
    story: StoryAnalysis | None
    virality: ViralityAnalysis | None
    planning: ClipPlanningAnalysis | None
    editing: EditingAnalysis | None
    render_manifest: RenderManifest | None
    render_run: RenderRun | None
    optimization: OptimizationAnalysis | None


class LibraryService:
    """Read-only aggregation + library-owned metadata, versions, and cleanup."""

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
        version_repo: VersionRepository,
        activity_repo: ActivityRepository,
        meta_repo: LibraryMetaRepository,
    ) -> None:
        self._storage = storage
        self._projects = project_repo
        self._analysis = analysis_repo
        self._story = story_repo
        self._virality = virality_repo
        self._planning = planning_repo
        self._editing = editing_repo
        self._render_manifest = render_manifest_repo
        self._render_run = render_run_repo
        self._optimization = optimization_repo
        self._workflow = workflow_repo
        self._versions = version_repo
        self._activity = activity_repo
        self._meta = meta_repo

    def _size_of(self, key: str) -> int | None:
        return size_of(self._storage, key)

    # -- loading --------------------------------------------------------------
    async def _bundle(self, project: Project) -> _Bundle:
        pid = project.id
        return _Bundle(
            project=project,
            meta=await self._meta.get(pid),
            analysis=await self._analysis.load(pid),
            story=await self._story.load(pid),
            virality=await self._virality.load(pid),
            planning=await self._planning.load(pid),
            editing=await self._editing.load(pid),
            render_manifest=await self._render_manifest.load(pid),
            render_run=await self._render_run.load(pid),
            optimization=await self._optimization.load(pid),
        )

    async def _select_projects(
        self, project_id: str | None, *, archived: bool | None
    ) -> list[Project]:
        if project_id is not None:
            project = await self._projects.get(project_id)
            projects = [project] if project else []
        else:
            projects = await self._projects.list()
        if archived is None or archived is False:
            metas = {m.project_id: m for m in await self._meta.list_all()}
            projects = [
                p for p in projects if not metas.get(p.id, ProjectLibraryMeta(p.id)).archived
            ]
        elif archived is True:
            metas = {m.project_id: m for m in await self._meta.list_all()}
            projects = [p for p in projects if metas.get(p.id, ProjectLibraryMeta(p.id)).archived]
        return projects

    # -- asset / clip / export libraries --------------------------------------
    async def assets(
        self,
        *,
        kind: str | None = None,
        project_id: str | None = None,
        query: str | None = None,
        tag: str | None = None,
        favorite: bool | None = None,
        archived: bool | None = None,
    ) -> list[AssetRecord]:
        out: list[AssetRecord] = []
        for project in await self._select_projects(project_id, archived=archived):
            bundle = await self._bundle(project)
            out.extend(
                inventory.build_assets(
                    project,
                    editing=bundle.editing,
                    render_manifest=bundle.render_manifest,
                    optimization=bundle.optimization,
                    render_run=bundle.render_run,
                    meta=bundle.meta,
                    size_of=self._size_of,
                )
            )
        if kind is not None:
            out = [a for a in out if a.kind.value == kind]
        if tag is not None:
            out = [a for a in out if tag in a.tags]
        if favorite is not None:
            out = [a for a in out if a.favorite is favorite]
        if query:
            q = query.lower()
            out = [a for a in out if q in a.name.lower() or q in a.project_name.lower()]
        out.sort(key=lambda a: a.created_at or utc_now(), reverse=True)
        return out

    async def clips(
        self,
        *,
        project_id: str | None = None,
        query: str | None = None,
        platform: str | None = None,
        status: str | None = None,
        archived: bool | None = None,
    ) -> list[ClipRecord]:
        out: list[ClipRecord] = []
        for project in await self._select_projects(project_id, archived=archived):
            bundle = await self._bundle(project)
            out.extend(
                inventory.build_clips(
                    project,
                    editing=bundle.editing,
                    render_manifest=bundle.render_manifest,
                    optimization=bundle.optimization,
                    meta=bundle.meta,
                )
            )
        if platform is not None:
            out = [c for c in out if c.platform == platform]
        if status is not None:
            out = [c for c in out if c.status == status]
        if query:
            q = query.lower()
            out = [c for c in out if q in c.title.lower() or q in c.project_name.lower()]
        out.sort(key=lambda c: c.created_at or utc_now(), reverse=True)
        return out

    async def exports(
        self,
        *,
        project_id: str | None = None,
        platform: str | None = None,
        archived: bool | None = None,
    ) -> list[ExportRecord]:
        out: list[ExportRecord] = []
        for project in await self._select_projects(project_id, archived=archived):
            bundle = await self._bundle(project)
            out.extend(
                inventory.build_exports(
                    project,
                    render_manifest=bundle.render_manifest,
                    render_run=bundle.render_run,
                    optimization=bundle.optimization,
                    size_of=self._size_of,
                )
            )
        if platform is not None:
            out = [e for e in out if e.platform == platform]
        out.sort(key=lambda e: e.created_at or utc_now(), reverse=True)
        return out

    # -- search ---------------------------------------------------------------
    async def search(self, query: str, *, limit: int = 50) -> list[SearchHit]:
        if not query.strip():
            return []
        projects = await self._projects.list()
        clips: list[ClipRecord] = []
        exports: list[ExportRecord] = []
        assets: list[AssetRecord] = []
        for project in projects:
            bundle = await self._bundle(project)
            clips.extend(
                inventory.build_clips(
                    project,
                    editing=bundle.editing,
                    render_manifest=bundle.render_manifest,
                    optimization=bundle.optimization,
                    meta=bundle.meta,
                )
            )
            exports.extend(
                inventory.build_exports(
                    project,
                    render_manifest=bundle.render_manifest,
                    render_run=bundle.render_run,
                    optimization=bundle.optimization,
                    size_of=self._size_of,
                )
            )
            assets.append(
                AssetRecord(
                    id=f"{project.id}:source",
                    project_id=project.id,
                    project_name=project.name,
                    kind=AssetKind.SOURCE_VIDEO,
                    name=project.source_filename,
                    tags=list(bundle.meta.tags),
                )
            )
        return search.search(
            query, projects=projects, clips=clips, exports=exports, assets=assets, limit=limit
        )

    # -- dashboard ------------------------------------------------------------
    async def dashboard(self) -> DashboardStats:
        projects = await self._projects.list()
        metas = {m.project_id: m for m in await self._meta.list_all()}
        clips: list[ClipRecord] = []
        exports: list[ExportRecord] = []
        rendered = 0
        videos_processed = 0
        minutes = 0.0
        storage_bytes = 0
        for project in projects:
            bundle = await self._bundle(project)
            project_clips = inventory.build_clips(
                project,
                editing=bundle.editing,
                render_manifest=bundle.render_manifest,
                optimization=bundle.optimization,
                meta=bundle.meta,
            )
            clips.extend(project_clips)
            exports.extend(
                inventory.build_exports(
                    project,
                    render_manifest=bundle.render_manifest,
                    render_run=bundle.render_run,
                    optimization=bundle.optimization,
                    size_of=self._size_of,
                )
            )
            rendered += len(bundle.render_manifest.renders) if bundle.render_manifest else 0
            if bundle.analysis is not None:
                videos_processed += 1
                minutes += (project.duration_seconds or 0.0) / 60.0
            storage_bytes += (await self._storage_breakdown(project)).total
        archived = sum(1 for m in metas.values() if m.archived)
        return compute_dashboard(
            total_projects=len(projects),
            videos_processed=videos_processed,
            minutes_analyzed=minutes,
            clips=clips,
            exports=exports,
            rendered_clip_count=rendered,
            storage_bytes=storage_bytes,
            archived_projects=archived,
        )

    # -- storage inspector ----------------------------------------------------
    async def _storage_breakdown(self, project: Project) -> StorageBreakdown:
        pid = project.id
        source = self._size_of(project.storage_key)
        namespaces = {
            "uploads": source if source is not None else (project.size_bytes or 0),
            "analysis": await measure_prefix(self._storage, f"analysis/{pid}/"),
            "story": await measure_prefix(self._storage, f"story/{pid}/"),
            "virality": await measure_prefix(self._storage, f"virality/{pid}/"),
            "planning": await measure_prefix(self._storage, f"planning/{pid}/"),
            "editing": await measure_prefix(self._storage, f"editing/{pid}/"),
            "renders": await measure_prefix(self._storage, f"render/{pid}/"),
            "exports": await measure_prefix(self._storage, f"optimization/{pid}/packages/"),
            "optimization": await measure_prefix(
                self._storage,
                f"optimization/{pid}/",
                exclude=(f"optimization/{pid}/packages/",),
            ),
            "logs": await measure_prefix(self._storage, f"workflow/{pid}/"),
        }
        return StorageBreakdown(project_id=pid, project_name=project.name, namespaces=namespaces)

    async def storage(self, project_id: str | None = None) -> list[StorageBreakdown]:
        if project_id is not None:
            project = await self._projects.get(project_id)
            projects = [project] if project else []
        else:
            projects = await self._projects.list()
        out = [await self._storage_breakdown(p) for p in projects]
        out.sort(key=lambda b: b.total, reverse=True)
        return out

    # -- version history ------------------------------------------------------
    async def capture_versions(self, project_id: str) -> list[VersionRecord]:
        project = await self._projects.get(project_id)
        if project is None:
            raise NotFoundError("Project not found.", details={"id": project_id})
        bundle = await self._bundle(project)
        entities = {
            "cognitive": bundle.analysis,
            "story": bundle.story,
            "virality": bundle.virality,
            "planning": bundle.planning,
            "editing": bundle.editing,
            "rendering": bundle.render_run,
            "optimization": bundle.optimization,
        }
        captured: list[VersionRecord] = []
        for engine, entity in entities.items():
            payload = _payload(entity)
            if payload is None:
                continue
            record = await self._versions.capture(
                project_id,
                engine,
                payload,
                status=payload.get("status"),
                summary={"stages": len(payload.get("stages", []))},
            )
            if record is not None:
                captured.append(record)
                await self._record(
                    ActivityType.VERSION_CAPTURED,
                    f"Captured {engine} v{record.version}",
                    project_id=project_id,
                    detail={"engine": engine, "version": record.version},
                )
        return captured

    async def list_version_engines(self, project_id: str) -> list[str]:
        return await self._versions.list_engines(project_id)

    async def list_versions(self, project_id: str, engine: str) -> list[VersionRecord]:
        return await self._versions.list_versions(project_id, engine)

    async def get_version(
        self, project_id: str, engine: str, version: int
    ) -> dict[str, Any] | None:
        return await self._versions.get_payload(project_id, engine, version)

    # -- activity feed --------------------------------------------------------
    async def activity(
        self, project_id: str | None = None, *, limit: int = 100
    ) -> list[ActivityEvent]:
        events: list[ActivityEvent] = list(await self._activity.list(project_id, limit=limit * 2))
        events.extend(await self._derive_activity(project_id))
        events.sort(key=lambda e: e.ts, reverse=True)
        # De-duplicate by (type, project, message, ts) keeping order.
        seen: set[tuple[Any, ...]] = set()
        deduped: list[ActivityEvent] = []
        for e in events:
            key = (e.type.value, e.project_id, e.message, e.ts.isoformat())
            if key in seen:
                continue
            seen.add(key)
            deduped.append(e)
        return deduped[:limit]

    async def _derive_activity(self, project_id: str | None) -> list[ActivityEvent]:
        """Activity derived from real project + workflow state (not stored by us)."""

        derived: list[ActivityEvent] = []
        projects = (
            [p for p in [await self._projects.get(project_id)] if p]
            if project_id is not None
            else await self._projects.list()
        )
        for project in projects:
            derived.append(
                ActivityEvent(
                    id=f"{project.id}:created",
                    ts=project.created_at,
                    type=ActivityType.PROJECT_CREATED,
                    message=f"Project '{project.name}' created",
                    project_id=project.id,
                )
            )
            workflow = await self._workflow.load(project.id)
            if workflow is None:
                continue
            for ev in workflow.history:
                atype = _map_workflow_event(ev.type.value)
                if atype is None:
                    continue
                derived.append(
                    ActivityEvent(
                        id=f"{project.id}:{ev.type.value}:{ev.ts.isoformat()}",
                        ts=ev.ts,
                        type=atype,
                        message=ev.message,
                        project_id=project.id,
                        detail={"stage": ev.stage} if ev.stage else {},
                    )
                )
        return derived

    async def _record(
        self,
        atype: ActivityType,
        message: str,
        *,
        project_id: str | None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        await self._activity.append(
            ActivityEvent(
                id=new_id("act"),
                ts=utc_now(),
                type=atype,
                message=message,
                project_id=project_id,
                detail=detail or {},
            )
        )

    # -- metadata: favorites / tags / archive ---------------------------------
    async def _require_project(self, project_id: str) -> Project:
        project = await self._projects.get(project_id)
        if project is None:
            raise NotFoundError("Project not found.", details={"id": project_id})
        return project

    async def set_project_favorite(self, project_id: str, favorite: bool) -> ProjectLibraryMeta:
        await self._require_project(project_id)
        meta = await self._meta.get(project_id)
        meta.favorite = favorite
        await self._meta.save(meta)
        await self._record(
            ActivityType.ASSET_FAVORITED,
            f"Project {'favorited' if favorite else 'unfavorited'}",
            project_id=project_id,
        )
        return meta

    async def add_project_tag(self, project_id: str, tag: str) -> ProjectLibraryMeta:
        cleaned = tag.strip().lower()
        if not cleaned:
            raise ValidationError("Tag cannot be empty.")
        await self._require_project(project_id)
        meta = await self._meta.get(project_id)
        if cleaned not in meta.tags:
            meta.tags.append(cleaned)
            await self._meta.save(meta)
            await self._record(
                ActivityType.ASSET_TAGGED, f"Tagged project '{cleaned}'", project_id=project_id
            )
        return meta

    async def remove_project_tag(self, project_id: str, tag: str) -> ProjectLibraryMeta:
        await self._require_project(project_id)
        meta = await self._meta.get(project_id)
        if tag in meta.tags:
            meta.tags.remove(tag)
            await self._meta.save(meta)
        return meta

    async def set_asset_favorite(
        self, project_id: str, asset_id: str, favorite: bool
    ) -> ProjectLibraryMeta:
        await self._require_project(project_id)
        meta = await self._meta.get(project_id)
        entry = meta.assets.setdefault(asset_id, {})
        entry["favorite"] = favorite
        await self._meta.save(meta)
        return meta

    async def add_asset_tag(self, project_id: str, asset_id: str, tag: str) -> ProjectLibraryMeta:
        cleaned = tag.strip().lower()
        if not cleaned:
            raise ValidationError("Tag cannot be empty.")
        await self._require_project(project_id)
        meta = await self._meta.get(project_id)
        entry = meta.assets.setdefault(asset_id, {})
        tags = entry.setdefault("tags", [])
        if cleaned not in tags:
            tags.append(cleaned)
            await self._meta.save(meta)
        return meta

    async def archive(self, project_id: str) -> ProjectLibraryMeta:
        await self._require_project(project_id)
        meta = await self._meta.get(project_id)
        meta.archived = True
        await self._meta.save(meta)
        await self._record(ActivityType.PROJECT_ARCHIVED, "Project archived", project_id=project_id)
        return meta

    async def restore(self, project_id: str) -> ProjectLibraryMeta:
        await self._require_project(project_id)
        meta = await self._meta.get(project_id)
        meta.archived = False
        await self._meta.save(meta)
        await self._record(ActivityType.PROJECT_RESTORED, "Project restored", project_id=project_id)
        return meta

    # -- cleanup tools --------------------------------------------------------
    async def _delete_keys(self, keys: list[str]) -> tuple[list[str], int]:
        freed = 0
        deleted: list[str] = []
        for key in keys:
            size = self._size_of(key)
            await self._storage.delete(key)
            deleted.append(key)
            if size is not None:
                freed += size
        return deleted, freed

    async def cleanup_temp_files(self, project_id: str | None = None) -> CleanupResult:
        projects = await self._target_projects(project_id)
        keys: list[str] = []
        for p in projects:
            keys.extend(await self._storage.list_keys(f"render/{p.id}/work/"))
        deleted, freed = await self._delete_keys(keys)
        await self._record(
            ActivityType.CLEANUP_PERFORMED,
            f"Removed {len(deleted)} temporary file(s)",
            project_id=project_id,
            detail={"operation": "temp_files"},
        )
        return CleanupResult(
            operation="temp_files",
            deleted_keys=deleted,
            freed_bytes=freed,
            note="Removed render working/temporary files; rendered outputs were untouched.",
        )

    async def cleanup_failed_renders(self, project_id: str | None = None) -> CleanupResult:
        projects = await self._target_projects(project_id)
        keys: list[str] = []
        for p in projects:
            run = await self._render_run.load(p.id)
            if run is not None and run.status is RenderRunStatus.FAILED:
                keys.extend(await self._storage.list_keys(f"render/{p.id}/clips/"))
                keys.extend(await self._storage.list_keys(f"render/{p.id}/work/"))
        deleted, freed = await self._delete_keys(keys)
        await self._record(
            ActivityType.CLEANUP_PERFORMED,
            f"Removed {len(deleted)} failed-render file(s)",
            project_id=project_id,
            detail={"operation": "failed_renders"},
        )
        return CleanupResult(
            operation="failed_renders",
            deleted_keys=deleted,
            freed_bytes=freed,
            note="Removed clip files from render runs whose status is FAILED.",
        )

    async def cleanup_unused_renders(self, project_id: str | None = None) -> CleanupResult:
        projects = await self._target_projects(project_id)
        keys: list[str] = []
        for p in projects:
            manifest = await self._render_manifest.load(p.id)
            referenced = {r.storage_key for r in manifest.renders} if manifest else set()
            for key in await self._storage.list_keys(f"render/{p.id}/clips/"):
                if key not in referenced:
                    keys.append(key)
        deleted, freed = await self._delete_keys(keys)
        await self._record(
            ActivityType.CLEANUP_PERFORMED,
            f"Removed {len(deleted)} unused-render file(s)",
            project_id=project_id,
            detail={"operation": "unused_renders"},
        )
        return CleanupResult(
            operation="unused_renders",
            deleted_keys=deleted,
            freed_bytes=freed,
            note="Removed clip files no longer referenced by the current render manifest.",
        )

    async def _target_projects(self, project_id: str | None) -> list[Project]:
        if project_id is not None:
            return [await self._require_project(project_id)]
        return await self._projects.list()

    # -- lifecycle ------------------------------------------------------------
    async def delete_library_data(self, project_id: str) -> None:
        """Delete the library's own data for a project (idempotent, additive)."""

        await self._versions.delete(project_id)
        await self._activity.delete(project_id)
        await self._meta.delete(project_id)


def _payload(entity: object) -> dict[str, Any] | None:
    """A stable, serialisable snapshot of an engine output for versioning."""

    if entity is None:
        return None
    index = getattr(entity, "index", None)
    if callable(index):
        result = index()
        return result if isinstance(result, dict) else None
    to_dict = getattr(entity, "to_dict", None)
    if callable(to_dict):
        result = to_dict()
        return result if isinstance(result, dict) else None
    status = getattr(entity, "status", None)
    stages = getattr(entity, "stages", None)
    payload: dict[str, Any] = {}
    if status is not None:
        payload["status"] = getattr(status, "value", str(status))
    if stages is not None:
        payload["stages"] = [s.summary() for s in stages]
    return payload or None


def _map_workflow_event(value: str) -> ActivityType | None:
    mapping = {
        "workflow_started": ActivityType.WORKFLOW_STARTED,
        "workflow_completed": ActivityType.WORKFLOW_COMPLETED,
        "workflow_failed": ActivityType.WORKFLOW_FAILED,
        "workflow_cancelled": ActivityType.WORKFLOW_CANCELLED,
        "stage_finished": ActivityType.STAGE_FINISHED,
    }
    return mapping.get(value)
