"""Rendering contract (port).

Defines the capability "given a complete edit plan and source media, produce a
finished, encoded video". The rendering layer is deterministic execution - it
does *what* the edit plan says, it never *decides* (the decide/do separation
from the architecture). Implemented by the FFmpeg adapter in
``olympus.rendering`` for the MVP; a richer compositor implements the same
contract in V2.

The ``edit_plan`` is intentionally typed as an opaque mapping in the foundation
release; its concrete schema is defined alongside the Editing service in a later
milestone, so this contract remains stable as the plan grows richer.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Any

from olympus.domain.entities.rendering import RenderManifest


@dataclass(slots=True)
class RenderRequest:
    """Inputs required to render a single Short."""

    source_key: str
    output_key: str
    edit_plan: dict[str, Any]


@dataclass(slots=True)
class RenderResult:
    """The outcome of a render."""

    output_key: str
    duration_s: float
    width: int
    height: int


class Renderer(abc.ABC):
    """Abstract rendering backend."""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Stable renderer identifier (for logging and metrics)."""

    @abc.abstractmethod
    async def render(self, request: RenderRequest) -> RenderResult:
        """Execute the edit plan against the source media and produce output.

        Raises :class:`olympus.platform.errors.ExternalServiceError` (or a
        rendering-specific error) on failure.
        """



class RenderManifestRepository(abc.ABC):
    """Read access to a project's render manifest (the Rendering Engine output).

    This is the boundary the Optimization Engine uses to discover the finished
    MP4s it should optimize. It is intentionally read-only here: the Optimization
    Engine never produces or mutates renders, it only consumes what the Rendering
    Engine durably published. A future Rendering Engine writes the manifest; a
    storage-backed adapter reads it behind this contract, and a database-backed
    one can replace it later without touching the Optimization Engine.

    ``load`` returns ``None`` when no manifest exists (the Rendering Engine has
    not run for this project) - the honest signal that there is nothing rendered
    to optimize yet.
    """

    @abc.abstractmethod
    async def load(self, project_id: str) -> RenderManifest | None:
        """Load the project's render manifest, or ``None`` if none exists."""
