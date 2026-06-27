"""Storage-backed analysis repository.

Persists a project's video understanding through the storage abstraction, split
into two kinds of document so work is never lost and stages stay independently
rerunnable:

- An **index** at ``analysis/{project_id}/index.json`` holding the overall status
  and a lightweight per-stage summary (no heavy data).
- One **stage artifact** per stage at ``analysis/{project_id}/stages/{stage}.json``
  holding that stage's full result, including its (potentially large) data.

Loading reassembles the complete :class:`Analysis` by reading the index and
hydrating each stage from its artifact (falling back to the index summary when an
artifact is missing). A database-backed implementation can later replace this
behind the same :class:`AnalysisRepository` contract.
"""

from __future__ import annotations

import json

from olympus.domain.contracts.analysis import AnalysisRepository
from olympus.domain.contracts.storage import StoragePort
from olympus.domain.entities.analysis import (
    Analysis,
    AnalysisStatus,
    StageResult,
)
from olympus.platform.errors import StorageError
from olympus.platform.logging import get_logger

log = get_logger(__name__)


def _base(project_id: str) -> str:
    return f"analysis/{project_id}"


def _index_key(project_id: str) -> str:
    return f"{_base(project_id)}/index.json"


def _stage_key(project_id: str, stage: str) -> str:
    return f"{_base(project_id)}/stages/{stage}.json"


class StorageAnalysisRepository(AnalysisRepository):
    """Persist analyses as JSON documents in object storage."""

    def __init__(self, storage: StoragePort) -> None:
        self._storage = storage

    async def load(self, project_id: str) -> Analysis | None:
        index_key = _index_key(project_id)
        if not await self._storage.exists(index_key):
            return None
        try:
            raw = json.loads(await self._storage.get(index_key))
        except (json.JSONDecodeError, ValueError) as exc:
            raise StorageError(
                "Stored analysis index is corrupt.", details={"project_id": project_id}
            ) from exc

        stages: list[StageResult] = []
        for summary in raw.get("stages", []):
            stage_name = summary["stage"]
            full = await self._load_stage(project_id, stage_name)
            stages.append(full if full is not None else StageResult.from_dict(summary))

        return Analysis(
            project_id=raw["project_id"],
            pipeline_version=str(raw.get("pipeline_version", "1")),
            status=AnalysisStatus(raw.get("status", "pending")),
            created_at=_dt(raw["created_at"]),
            updated_at=_dt(raw["updated_at"]),
            stages=stages,
        )

    async def _load_stage(self, project_id: str, stage: str) -> StageResult | None:
        key = _stage_key(project_id, stage)
        if not await self._storage.exists(key):
            return None
        try:
            return StageResult.from_dict(json.loads(await self._storage.get(key)))
        except (json.JSONDecodeError, KeyError, ValueError):
            log.warning("skipping_corrupt_stage", project_id=project_id, stage=stage)
            return None

    async def save_index(self, analysis: Analysis) -> None:
        data = json.dumps(analysis.index()).encode("utf-8")
        await self._storage.put(
            _index_key(analysis.project_id), data, content_type="application/json"
        )

    async def save_stage(self, project_id: str, result: StageResult) -> None:
        data = json.dumps(result.to_dict()).encode("utf-8")
        await self._storage.put(
            _stage_key(project_id, result.stage), data, content_type="application/json"
        )

    async def delete(self, project_id: str) -> None:
        for key in await self._storage.list_keys(f"{_base(project_id)}/"):
            await self._storage.delete(key)


def _dt(value: str):
    from datetime import datetime

    return datetime.fromisoformat(value)
