"""Storage-backed story repository.

Persists a project's narrative understanding through the storage abstraction,
mirroring the Cognitive Engine's repository layout so the two engines behave
identically with respect to durability and rerunnability:

- An **index** at ``story/{project_id}/index.json`` (overall status + per-stage
  summaries, no heavy data).
- One **stage artifact** per stage at ``story/{project_id}/stages/{stage}.json``
  holding that stage's full result (its structured conclusions + evidence).

Loading reassembles the complete :class:`StoryAnalysis` from the index plus each
stage artifact. A database-backed implementation can later replace this behind
the same :class:`StoryRepository` contract.
"""

from __future__ import annotations

import json
from datetime import datetime

from olympus.domain.contracts.storage import StoragePort
from olympus.domain.contracts.story import StoryRepository
from olympus.domain.entities.story import StoryAnalysis, StoryStageResult, StoryStatus
from olympus.platform.errors import StorageError
from olympus.platform.logging import get_logger

log = get_logger(__name__)


def _base(project_id: str) -> str:
    return f"story/{project_id}"


def _index_key(project_id: str) -> str:
    return f"{_base(project_id)}/index.json"


def _stage_key(project_id: str, stage: str) -> str:
    return f"{_base(project_id)}/stages/{stage}.json"


class StorageStoryRepository(StoryRepository):
    """Persist story analyses as JSON documents in object storage."""

    def __init__(self, storage: StoragePort) -> None:
        self._storage = storage

    async def load(self, project_id: str) -> StoryAnalysis | None:
        index_key = _index_key(project_id)
        if not await self._storage.exists(index_key):
            return None
        try:
            raw = json.loads(await self._storage.get(index_key))
        except (json.JSONDecodeError, ValueError) as exc:
            raise StorageError(
                "Stored story index is corrupt.", details={"project_id": project_id}
            ) from exc

        stages: list[StoryStageResult] = []
        for summary in raw.get("stages", []):
            stage_name = summary["stage"]
            full = await self._load_stage(project_id, stage_name)
            stages.append(full if full is not None else StoryStageResult.from_dict(summary))

        return StoryAnalysis(
            project_id=raw["project_id"],
            pipeline_version=str(raw.get("pipeline_version", "1")),
            status=StoryStatus(raw.get("status", "pending")),
            created_at=datetime.fromisoformat(raw["created_at"]),
            updated_at=datetime.fromisoformat(raw["updated_at"]),
            stages=stages,
        )

    async def _load_stage(self, project_id: str, stage: str) -> StoryStageResult | None:
        key = _stage_key(project_id, stage)
        if not await self._storage.exists(key):
            return None
        try:
            return StoryStageResult.from_dict(json.loads(await self._storage.get(key)))
        except (json.JSONDecodeError, KeyError, ValueError):
            log.warning("skipping_corrupt_story_stage", project_id=project_id, stage=stage)
            return None

    async def save_index(self, analysis: StoryAnalysis) -> None:
        data = json.dumps(analysis.index()).encode("utf-8")
        await self._storage.put(
            _index_key(analysis.project_id), data, content_type="application/json"
        )

    async def save_stage(self, project_id: str, result: StoryStageResult) -> None:
        data = json.dumps(result.to_dict()).encode("utf-8")
        await self._storage.put(
            _stage_key(project_id, result.stage), data, content_type="application/json"
        )

    async def delete(self, project_id: str) -> None:
        for key in await self._storage.list_keys(f"{_base(project_id)}/"):
            await self._storage.delete(key)
