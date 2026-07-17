"""Storage-backed render-run repository.

Persists a project's render-run state (the pipeline's progress) through the
storage abstraction, mirroring the other engines' repository layout:

- An **index** at ``render/{project_id}/run/index.json`` (overall status,
  per-stage summaries, and the published manifest once available).
- One **stage artifact** per stage at
  ``render/{project_id}/run/stages/{stage}.json`` holding that stage's full
  result (including its logs and built render plan).

The rendered MP4s themselves live under ``render/{project_id}/clips/``. The old
root manifest remains a compatibility copy, while the run index is now the
canonical checkpoint handoff. A database-backed implementation can later replace
this behind the same contract.
"""

from __future__ import annotations

import json
from datetime import datetime

from olympus.domain.contracts.render_pipeline import RenderRunRepository
from olympus.domain.contracts.storage import StoragePort
from olympus.domain.entities.render_pipeline import (
    RenderRun,
    RenderRunStatus,
    RenderStageResult,
)
from olympus.platform.errors import StorageError
from olympus.platform.logging import get_logger

log = get_logger(__name__)


def _base(project_id: str) -> str:
    return f"render/{project_id}/run"


def _index_key(project_id: str) -> str:
    return f"{_base(project_id)}/index.json"


def _stage_key(project_id: str, stage: str) -> str:
    return f"{_base(project_id)}/stages/{stage}.json"


class StorageRenderRunRepository(RenderRunRepository):
    """Persist render runs as JSON documents in object storage."""

    def __init__(self, storage: StoragePort) -> None:
        self._storage = storage

    async def load(self, project_id: str) -> RenderRun | None:
        index_key = _index_key(project_id)
        if not await self._storage.exists(index_key):
            return None
        try:
            raw = json.loads(await self._storage.get(index_key))
        except (json.JSONDecodeError, ValueError) as exc:
            raise StorageError(
                "Stored render-run index is corrupt.", details={"project_id": project_id}
            ) from exc

        stages: list[RenderStageResult] = []
        for summary in raw.get("stages", []):
            full = await self._load_stage(project_id, summary["stage"])
            stages.append(full if full is not None else RenderStageResult.from_dict(summary))

        return RenderRun(
            project_id=raw["project_id"],
            pipeline_version=str(raw.get("pipeline_version", "1")),
            status=RenderRunStatus(raw.get("status", "pending")),
            created_at=datetime.fromisoformat(raw["created_at"]),
            updated_at=datetime.fromisoformat(raw["updated_at"]),
            stages=stages,
        )

    async def _load_stage(self, project_id: str, stage: str) -> RenderStageResult | None:
        key = _stage_key(project_id, stage)
        if not await self._storage.exists(key):
            return None
        try:
            return RenderStageResult.from_dict(json.loads(await self._storage.get(key)))
        except (json.JSONDecodeError, KeyError, ValueError):
            log.warning("skipping_corrupt_render_stage", project_id=project_id, stage=stage)
            return None

    async def save_index(self, run: RenderRun) -> None:
        data = json.dumps(run.index()).encode("utf-8")
        await self._storage.put(_index_key(run.project_id), data, content_type="application/json")

    async def save_stage(self, project_id: str, result: RenderStageResult) -> None:
        data = json.dumps(result.to_dict()).encode("utf-8")
        await self._storage.put(
            _stage_key(project_id, result.stage), data, content_type="application/json"
        )

    async def delete(self, project_id: str) -> None:
        for key in await self._storage.list_keys(f"{_base(project_id)}/"):
            await self._storage.delete(key)
