"""Versioned contracts for canonical Editing Engine timeline coordinates."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


def _seconds(value: object, *, default: float = 0.0) -> float:
    if not isinstance(value, int | float):
        return default
    parsed = float(value)
    return parsed if math.isfinite(parsed) else default


@dataclass(frozen=True, slots=True)
class ClipSourceWindowV1:
    """One authoritative source-time window shared by every clip track."""

    project_id: str | None
    clip_id: str
    requested_start_seconds: float
    requested_end_seconds: float
    repaired_start_seconds: float
    repaired_end_seconds: float
    duration_seconds: float
    preroll_seconds: float
    postroll_seconds: float
    boundary_repair_applied: bool
    start_reason: str
    end_reason: str
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        requested_start = max(0.0, _seconds(self.requested_start_seconds))
        requested_end = max(requested_start, _seconds(self.requested_end_seconds))
        repaired_start = max(0.0, _seconds(self.repaired_start_seconds))
        repaired_end = max(repaired_start, _seconds(self.repaired_end_seconds))
        duration = repaired_end - repaired_start
        object.__setattr__(self, "requested_start_seconds", round(requested_start, 3))
        object.__setattr__(self, "requested_end_seconds", round(requested_end, 3))
        object.__setattr__(self, "repaired_start_seconds", round(repaired_start, 3))
        object.__setattr__(self, "repaired_end_seconds", round(repaired_end, 3))
        object.__setattr__(self, "duration_seconds", round(duration, 3))
        object.__setattr__(
            self,
            "preroll_seconds",
            round(max(0.0, _seconds(self.preroll_seconds)), 3),
        )
        object.__setattr__(
            self,
            "postroll_seconds",
            round(max(0.0, _seconds(self.postroll_seconds)), 3),
        )
        object.__setattr__(
            self,
            "warnings",
            tuple(dict.fromkeys(str(item) for item in self.warnings)),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation for stage artifacts and manifests."""

        return {
            "contract_version": "1",
            "project_id": self.project_id,
            "clip_id": self.clip_id,
            "requested_start_seconds": self.requested_start_seconds,
            "requested_end_seconds": self.requested_end_seconds,
            "repaired_start_seconds": self.repaired_start_seconds,
            "repaired_end_seconds": self.repaired_end_seconds,
            "duration_seconds": self.duration_seconds,
            "preroll_seconds": self.preroll_seconds,
            "postroll_seconds": self.postroll_seconds,
            "boundary_repair_applied": self.boundary_repair_applied,
            "start_reason": self.start_reason,
            "end_reason": self.end_reason,
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ClipSourceWindowV1:
        """Load persisted V1 data while tolerating missing optional values."""

        repaired_start = _seconds(value.get("repaired_start_seconds"))
        repaired_end = _seconds(value.get("repaired_end_seconds"), default=repaired_start)
        return cls(
            project_id=str(value["project_id"]) if value.get("project_id") is not None else None,
            clip_id=str(value.get("clip_id") or ""),
            requested_start_seconds=_seconds(value.get("requested_start_seconds")),
            requested_end_seconds=_seconds(value.get("requested_end_seconds")),
            repaired_start_seconds=repaired_start,
            repaired_end_seconds=repaired_end,
            duration_seconds=_seconds(
                value.get("duration_seconds"),
                default=repaired_end - repaired_start,
            ),
            preroll_seconds=_seconds(value.get("preroll_seconds")),
            postroll_seconds=_seconds(value.get("postroll_seconds")),
            boundary_repair_applied=value.get("boundary_repair_applied") is True,
            start_reason=str(value.get("start_reason") or "legacy or unspecified boundary"),
            end_reason=str(value.get("end_reason") or "legacy or unspecified boundary"),
            warnings=tuple(str(item) for item in value.get("warnings", []) if item),
        )
