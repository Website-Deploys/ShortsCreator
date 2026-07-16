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
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from olympus.domain.entities.rendering import RenderManifest

if TYPE_CHECKING:
    from olympus.domain.contracts.storage import StoragePort


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


# --------------------------------------------------------------------------- #
# Clip renderer abstraction (the Rendering Engine's replaceable execution port)
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class RendererAvailability:
    """Whether a renderer can execute here, reported honestly with a reason.

    When ``available`` is ``False`` the ``reason`` states exactly why (e.g.
    "FFmpeg binary not found on PATH"), which the engine surfaces verbatim in its
    ``UNAVAILABLE`` stage results rather than fabricating a render.
    """

    available: bool
    renderer: str
    reason: str | None = None
    version: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "renderer": self.renderer,
            "reason": self.reason,
            "version": self.version,
        }


@dataclass(slots=True)
class ClipRenderSpec:
    """A complete instruction to render one clip's timeline to an encoded file.

    The ``timeline`` is the Editing Engine's clip-relative timeline (tracks of
    video/audio/caption/marker events). The renderer executes exactly those
    decisions - it never alters them. Output settings (dimensions, fps, bitrate)
    are execution parameters, not creative choices.
    """

    clip_id: str
    source_key: str
    output_key: str
    timeline: dict[str, Any]
    width: int
    height: int
    fps: int
    video_bitrate_kbps: int
    audio_bitrate_kbps: int
    preview: bool = False


@dataclass(slots=True)
class ClipRenderOutput:
    """The measured result of rendering one clip (never fabricated).

    Every media field is *measured* from the encoded file the renderer produced
    (e.g. via ffprobe); ``logs`` carries renderer output for the render-logs view.
    """

    clip_id: str
    output_key: str
    width: int | None = None
    height: int | None = None
    duration: float | None = None
    fps: float | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    has_audio: bool | None = None
    bitrate_kbps: int | None = None
    audio_sample_rate: int | None = None
    size_bytes: int | None = None
    logs: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class RendererUnavailableError(RuntimeError):
    """Raised by a renderer when it cannot execute (dependency absent).

    Carries the precise human-readable reason so the calling stage can record an
    honest ``UNAVAILABLE`` result instead of failing or fabricating output.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ClipRenderer(abc.ABC):
    """A replaceable engine that encodes one clip's timeline into a real file.

    This is the Rendering Engine's execution port. FFmpeg implements it today;
    GPU, cloud, and distributed renderers can implement the same contract without
    touching any pipeline stage. Implementations must report availability
    honestly and must never write a fabricated/placeholder media file in place of
    a real render.
    """

    #: Stable renderer identifier.
    name: str = ""

    @abc.abstractmethod
    def availability(self) -> RendererAvailability:
        """Whether this renderer can execute in the current environment."""

    @abc.abstractmethod
    async def render_clip(self, spec: ClipRenderSpec, storage: StoragePort) -> ClipRenderOutput:
        """Encode the clip's timeline to ``spec.output_key`` in ``storage``.

        Raises :class:`RendererUnavailableError` when the renderer cannot execute
        (e.g. FFmpeg missing), or :class:`olympus.platform.errors.ExternalServiceError`
        on a genuine execution failure.
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



class RenderManifestStore(RenderManifestRepository):
    """Read/write access to a project's render manifest.

    Extends the read-only :class:`RenderManifestRepository` (which the
    Optimization Engine depends on) with the write side that the Rendering Engine
    - the manifest's official producer - uses to publish the manifest once real
    MP4s exist. Keeping the read contract separate means the Optimization Engine
    never gains a write capability it should not have.
    """

    @abc.abstractmethod
    async def save(self, manifest: RenderManifest) -> None:
        """Durably publish the render manifest (overwrites any prior one)."""

    @abc.abstractmethod
    async def delete(self, project_id: str) -> None:
        """Delete the manifest and rendered outputs for a project (idempotent)."""
