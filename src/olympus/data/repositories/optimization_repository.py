"""Storage-backed optimization repository.

Persists a project's optimization analysis through the storage abstraction,
mirroring the other engines' repository layout so they all behave identically
with respect to durability and rerunnability:

- An **index** at ``optimization/{project_id}/index.json`` (overall status +
  per-stage summaries, no heavy data).
- One **stage artifact** per stage at
  ``optimization/{project_id}/stages/{stage}.json`` holding that stage's full
  result.

Note the publish stage additionally writes real downloadable assets (caption
files, metadata, quality report) under ``optimization/{project_id}/packages/...``
via the storage port directly; those are referenced by ``storage_key`` in the
stage data. Loading reassembles the complete :class:`OptimizationAnalysis` from
the index plus each stage artifact. A database-backed implementation can later
replace this behind the same :class:`OptimizationRepository` contract.
"""

from __future__ import annotations

import json
from datetime import datetime

from olympus.domain.contracts.optimization import OptimizationRepository
from olympus.domain.contracts.storage import StoragePort
from olympus.domain.entities.optimization import (
    OptimizationAnalysis,
    OptimizationStageResult,
    OptimizationStatus,
)
from olympus.platform.errors import StorageError
from olympus.platform.logging import get_logger

log = get_logger(__name__)


def _base(project_id: str) -> str:
    return f"optimization/{project_id}"


def _index_key(project_id: str) -> str:
    return f"{_base(project_id)}/index.json"


def _stage_key(project_id: str, stage: str) -> str:
    return f"{_base(project_id)}/stages/{stage}.json"


class StorageOptimizationRepository(OptimizationRepository):
    """Persist optimization analyses as JSON documents in object storage."""

    def __init__(self, storage: StoragePort) -> None:
        self._storage = storage

    async def load(self, project_id: str) -> OptimizationAnalysis | None:
        index_key = _index_key(project_id)
        if not await self._storage.exists(index_key):
            return None
        try:
            raw = json.loads(await self._storage.get(index_key))
        except (json.JSONDecodeError, ValueError) as exc:
            raise StorageError(
                "Stored optimization index is corrupt.", details={"project_id": project_id}
            ) from exc

        stages: list[OptimizationStageResult] = []
        for summary in raw.get("stages", []):
            stage_name = summary["stage"]
            full = await self._load_stage(project_id, stage_name)
            stages.append(full if full is not None else OptimizationStageResult.from_dict(summary))

        return OptimizationAnalysis(
            project_id=raw["project_id"],
            pipeline_version=str(raw.get("pipeline_version", "1")),
            status=OptimizationStatus(raw.get("status", "pending")),
            created_at=datetime.fromisoformat(raw["created_at"]),
            updated_at=datetime.fromisoformat(raw["updated_at"]),
            stages=stages,
        )

    async def _load_stage(self, project_id: str, stage: str) -> OptimizationStageResult | None:
        key = _stage_key(project_id, stage)
        if not await self._storage.exists(key):
            return None
        try:
            return OptimizationStageResult.from_dict(json.loads(await self._storage.get(key)))
        except (json.JSONDecodeError, KeyError, ValueError):
            log.warning("skipping_corrupt_optimization_stage", project_id=project_id, stage=stage)
            return None

    async def save_index(self, analysis: OptimizationAnalysis) -> None:
        data = json.dumps(analysis.index()).encode("utf-8")
        await self._storage.put(
            _index_key(analysis.project_id), data, content_type="application/json"
        )

    async def save_stage(self, project_id: str, result: OptimizationStageResult) -> None:
        data = json.dumps(result.to_dict()).encode("utf-8")
        await self._storage.put(
            _stage_key(project_id, result.stage), data, content_type="application/json"
        )

    async def delete(self, project_id: str) -> None:
        for key in await self._storage.list_keys(f"{_base(project_id)}/"):
            await self._storage.delete(key)
