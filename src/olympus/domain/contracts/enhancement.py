"""Enhancement model contracts (ports) for audio/visual/thumbnail AI.

Professional polish - voice isolation, noise/hum removal, EQ, de-essing,
limiting, denoising, sharpening, colour correction, thumbnail scoring - requires
real signal-processing or ML models running over the *rendered* media. Those
models are heavy, swappable, and environment-dependent, so the Optimization
Engine talks to them only through these ports. A capable deployment plugs in
concrete adapters; an environment without them honestly reports they are
unavailable, and the engine records ``UNKNOWN``/``UNAVAILABLE`` instead of
fabricating an enhancement.

This module deliberately ships **no fabricated implementations**. It defines the
ports and a :class:`EnhancementCapabilities` descriptor that states, per
capability, whether a model is present and - when it is not - exactly why. The
default capabilities (built in ``olympus.optimization.enhancement``) report
everything as unavailable in this environment, which is the truth.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class Capability:
    """Availability of a single enhancement capability, honestly reported."""

    name: str
    available: bool
    reason: str | None = None
    model: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "available": self.available,
            "reason": self.reason,
            "model": self.model,
        }


class AudioEnhancer(abc.ABC):
    """Port for audio enhancement over a rendered clip's audio track."""

    name: str = ""

    @abc.abstractmethod
    def analyze(self, storage_key: str) -> dict[str, Any]:
        """Measure loudness/peaks/noise floor from real audio (never estimated)."""

    @abc.abstractmethod
    def enhance(self, storage_key: str, operations: list[str]) -> dict[str, Any]:
        """Apply the requested operations and return the produced artifact."""


class VisualEnhancer(abc.ABC):
    """Port for visual enhancement over a rendered clip's frames."""

    name: str = ""

    @abc.abstractmethod
    def enhance(self, storage_key: str, operations: list[str]) -> dict[str, Any]:
        """Apply visual operations (sharpen/denoise/colour) and return the result."""


class ThumbnailScorer(abc.ABC):
    """Port for scoring candidate thumbnail frames (faces/expression/composition)."""

    name: str = ""

    @abc.abstractmethod
    def score(self, storage_key: str, timestamp: float) -> dict[str, Any]:
        """Score a single candidate frame from real pixels (never invented)."""


class EnhancementCapabilities:
    """A registry describing which enhancement capabilities are available.

    The engine queries this before attempting any model-backed work. Each
    capability is a named :class:`Capability`; when unavailable it carries the
    precise reason, which the engine surfaces verbatim in its honest
    ``UNAVAILABLE``/``UNKNOWN`` output.
    """

    def __init__(
        self,
        capabilities: dict[str, Capability],
        *,
        audio: AudioEnhancer | None = None,
        visual: VisualEnhancer | None = None,
        thumbnail: ThumbnailScorer | None = None,
    ) -> None:
        self._caps = dict(capabilities)
        self.audio = audio
        self.visual = visual
        self.thumbnail = thumbnail

    def capability(self, name: str) -> Capability:
        return self._caps.get(
            name, Capability(name=name, available=False, reason="capability not registered")
        )

    def is_available(self, name: str) -> bool:
        return self.capability(name).available

    def to_dict(self) -> dict[str, Any]:
        return {name: cap.to_dict() for name, cap in self._caps.items()}
