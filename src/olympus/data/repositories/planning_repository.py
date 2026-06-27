"""Storage-backed clip-planning repository.

Persists a project's editing plans through the storage abstraction, mirroring the
other engines' repository layout so all four behave identically with respect to
durability and rerunnability:

- An **index** at ``planning/{project_id}/index.json`` (overall status +
  per-stage summaries, no heavy data).
- One **stage artifact** per stage at
  ``planning/{project_id}/stages/{stage}.json`` holding that stage's full result
  (its candidates, scores, blueprints, and reasoning).

Loading reassembles the complete :class:`ClipPlanningAnalysis` from the index
plus each stage artifact. A database-backed implementation can later replace this
behind the same :class:`PlanningRepository` contract.
"""

from __future__ import annotations

import json
from datetime import datetime

from olympus.domain.contracts.planning import PlanningRepository
from olympus.domain.contracts.storage import StoragePort
from olympus.domain.entities.planning import (
    ClipPlanningAnalysis,
    PlanningStageResult,
    PlanningStatus,
)
from olympus.platform.errors import StorageError
from olympus.platform.logging import get_logger

log = get_logger(__name__)


def _base(project_id: str) -> str:
    return f"planning/{project_id}"


def _index_key(project_id: str) -> str:
    return f"{_base(project_id)}/index.json"


def _stage_key(project_id: str, stage: str) -> str:
    return f"{_base(project_id)}/stages/{stage}.json"


class StoragePlanningRepository(PlanningRepository):
    """Persist clip-planning analyses as JSON documents in object storage."""

    def __init__(self, storage: StoragePort) -> None:
        self._storage = storage

    async def load(self, project_id: str) -> ClipPlanningAnalysis | None:
        index_key = _index_key(project_id)
        if not await self._storage.exists(index_key):
            return None
        try:
            raw = json.loads(await self._storage.get(index_key))
        except (json.JSONDecodeError, ValueError) as exc:
            raise StorageError(
                "Stored planning index is corrupt.", details={"project_id": project_id}
            ) from exc

        stages: list[PlanningStageResult] = []
        for summary in raw.get("stages", []):
            stage_name = summary["stage"]
            full = await self._load_stage(project_id, stage_name)
            stages.append(full if full is not None else PlanningStageResult.from_dict(summary))

        return ClipPlanningAnalysis(
            project_id=raw["project_id"],
            pipeline_version=str(raw.get("pipeline_version", "1")),
            status=PlanningStatus(raw.get("status", "pending")),
            created_at=datetime.fromisoformat(raw["created_at"]),
            updated_at=datetime.fromisoformat(raw["updated_at"]),
            stages=stages,
        )

    async def _load_stage(self, project_id: str, stage: str) -> PlanningStageResult | None:
        key = _stage_key(project_id, stage)
        if not await self._storage.exists(key):
            return None
        try:
            return PlanningStageResult.from_dict(json.loads(await self._storage.get(key)))
        except (json.JSONDecodeError, KeyError, ValueError):
            log.warning("skipping_corrupt_planning_stage", project_id=project_id, stage=stage)
            return None

    async def save_index(self, analysis: ClipPlanningAnalysis) -> None:
        data = json.dumps(analysis.index()).encode("utf-8")
        await self._storage.put(
            _index_key(analysis.project_id), data, content_type="application/json"
        )

    async def save_stage(self, project_id: str, result: PlanningStageResult) -> None:
        data = json.dumps(result.to_dict()).encode("utf-8")
        await self._storage.put(
            _stage_key(project_id, result.stage), data, content_type="application/json"
        )

    async def delete(self, project_id: str) -> None:
        for key in await self._storage.list_keys(f"{_base(project_id)}/"):
            await self._storage.delete(key)
