"""Storage-backed workflow repository.

Persists a project's complete workflow (jobs + execution history) as a single
JSON document at ``workflow/{project_id}/workflow.json``. Persisting the whole
graph on every transition is what makes the Workflow Engine crash-recoverable:
on restart the service reloads non-terminal workflows, requeues orphaned RUNNING
jobs, and resumes - finished jobs are never re-run and cancelled jobs stay
cancelled.

A database-backed implementation can replace this behind the same contract.
"""

from __future__ import annotations

import asyncio
import json

from olympus.domain.contracts.storage import StoragePort
from olympus.domain.contracts.workflow import WorkflowRepository
from olympus.domain.entities.workflow import (
    WORKFLOW_TERMINAL,
    JobStatus,
    Workflow,
    WorkflowStatus,
)
from olympus.jobs.contracts import workflow_to_durable_job
from olympus.jobs.store import LocalDurableJobStore
from olympus.platform.errors import StorageError
from olympus.platform.logging import get_logger

log = get_logger(__name__)

_PREFIX = "workflow/"
_SUFFIX = "/workflow.json"


def _key(project_id: str) -> str:
    return f"{_PREFIX}{project_id}{_SUFFIX}"


class StorageWorkflowRepository(WorkflowRepository):
    """Persist workflows as JSON documents in object storage."""

    def __init__(
        self,
        storage: StoragePort,
        *,
        durable_store: LocalDurableJobStore | None = None,
    ) -> None:
        self._storage = storage
        self._durable_store = durable_store

    async def load(self, project_id: str) -> Workflow | None:
        key = _key(project_id)
        if not await self._storage.exists(key):
            return None
        try:
            raw = json.loads(await self._storage.get(key))
        except (json.JSONDecodeError, ValueError) as exc:
            raise StorageError(
                "Stored workflow is corrupt.", details={"project_id": project_id}
            ) from exc
        return Workflow.from_dict(raw)

    async def save(self, workflow: Workflow) -> None:
        data = json.dumps(workflow.to_dict()).encode("utf-8")
        await self._storage.put(_key(workflow.project_id), data, content_type="application/json")
        if self._durable_store is not None:
            payload = workflow_to_durable_job(
                workflow,
                max_logs_tail_chars=self._durable_store.max_logs_tail_chars,
            )
            await asyncio.to_thread(self._durable_store.upsert, payload)

    async def list_active_project_ids(self) -> list[str]:
        out: list[str] = []
        for key in await self._storage.list_keys(_PREFIX):
            if not key.endswith(_SUFFIX):
                continue
            project_id = key[len(_PREFIX) : -len(_SUFFIX)]
            workflow = await self.load(project_id)
            interrupted = workflow is not None and any(
                job.status in {JobStatus.RUNNING, JobStatus.CANCEL_REQUESTED, JobStatus.STALE}
                for job in workflow.jobs
            )
            if workflow is not None and (
                workflow.status not in WORKFLOW_TERMINAL or interrupted
            ):
                out.append(project_id)
        return out

    async def list_all(self) -> list[Workflow]:
        workflows: list[Workflow] = []
        for key in await self._storage.list_keys(_PREFIX):
            if not key.endswith(_SUFFIX):
                continue
            project_id = key[len(_PREFIX) : -len(_SUFFIX)]
            workflow = await self.load(project_id)
            if workflow is not None:
                workflows.append(workflow)
        workflows.sort(key=lambda item: item.created_at, reverse=True)
        return workflows

    async def load_by_job_id(self, job_id: str) -> Workflow | None:
        for workflow in await self.list_all():
            if workflow.workflow_id == job_id:
                return workflow
        return None

    async def delete(self, project_id: str) -> None:
        key = _key(project_id)
        workflow = await self.load(project_id)
        if await self._storage.exists(key):
            await self._storage.delete(key)
        if self._durable_store is not None and workflow is not None:
            await asyncio.to_thread(self._durable_store.delete, workflow.workflow_id)

    @staticmethod
    def is_terminal(status: WorkflowStatus) -> bool:
        return status in WORKFLOW_TERMINAL
