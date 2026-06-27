"""Music provider contracts (ports) for copyright-free background music.

The Optimization Engine recommends background music for a Short, but it must
never scrape a platform or touch copyrighted songs. Instead it talks to *music
providers* behind this abstraction: a local royalty-free library today, and
licensed/AI providers (Epidemic Sound, Artlist, Soundstripe, generated music,
other licensed catalogues) in the future - each implementing the same contract
so they are interchangeable and independently replaceable.

A provider exposes a catalogue it can legally offer and answers a structured
:class:`MusicQuery` (the emotional/energetic/tempo brief the engine derives from
the story, virality, and editing analyses). Providers report their own
availability honestly: a not-yet-integrated provider returns ``available =
False`` with a reason, and the engine records that rather than pretending a
recommendation exists.

Nothing here downloads, streams, mixes, or renders audio. It only *recommends*
tracks, with the license source always attached so attribution/clearance is
explicit downstream.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class MusicTrack:
    """One licensable, copyright-free track a provider can offer.

    ``license`` and ``source`` are mandatory and always preserved on a
    recommendation so downstream clearance/attribution is never ambiguous. Energy
    is a 0..1 intensity; ``bpm``/``genre``/``mood`` describe musical character.
    """

    id: str
    title: str
    provider: str
    license: str
    source: str
    artist: str | None = None
    bpm: int | None = None
    genre: str | None = None
    energy: float | None = None
    mood: tuple[str, ...] = ()
    duration: float | None = None
    storage_key: str | None = None
    attribution_required: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "provider": self.provider,
            "license": self.license,
            "source": self.source,
            "artist": self.artist,
            "bpm": self.bpm,
            "genre": self.genre,
            "energy": self.energy,
            "mood": list(self.mood),
            "duration": self.duration,
            "storage_key": self.storage_key,
            "attribution_required": self.attribution_required,
        }


@dataclass(slots=True)
class MusicQuery:
    """The structured brief the engine derives to request music.

    Every field is optional and may be ``None`` when the upstream signal that
    would set it is unavailable - providers must degrade gracefully rather than
    invent a match.
    """

    mood: tuple[str, ...] = ()
    energy: float | None = None
    target_bpm: int | None = None
    genres: tuple[str, ...] = ()
    min_duration: float | None = None
    platform: str | None = None


@dataclass(slots=True)
class MusicProviderStatus:
    """A provider's honest availability."""

    available: bool
    reason: str | None = None


@dataclass(slots=True)
class MusicRecommendation:
    """A scored, explained track recommendation."""

    track: MusicTrack
    score: float | None
    reason: str
    evidence: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "track": self.track.to_dict(),
            "score": self.score,
            "reason": self.reason,
            "evidence": self.evidence,
        }


class MusicProvider(abc.ABC):
    """A replaceable source of copyright-free music."""

    #: Stable provider identifier.
    name: str = ""

    @abc.abstractmethod
    def status(self) -> MusicProviderStatus:
        """Whether this provider can currently be queried (honest, with reason)."""

    @abc.abstractmethod
    def recommend(self, query: MusicQuery, *, limit: int = 5) -> list[MusicRecommendation]:
        """Return scored recommendations for the brief (empty if unavailable)."""


class MusicProviderRegistry:
    """An ordered set of music providers the engine consults.

    The registry tries available providers in priority order. Future providers
    can be registered without changing any caller; unavailable ones are simply
    skipped (and surfaced honestly in the engine's output).
    """

    def __init__(self, providers: list[MusicProvider] | None = None) -> None:
        self._providers: list[MusicProvider] = list(providers or [])

    def register(self, provider: MusicProvider) -> None:
        self._providers.append(provider)

    @property
    def providers(self) -> list[MusicProvider]:
        return list(self._providers)

    def available(self) -> list[MusicProvider]:
        return [p for p in self._providers if p.status().available]

    def statuses(self) -> list[dict[str, Any]]:
        """Honest availability of every registered provider (for the UI)."""

        out: list[dict[str, Any]] = []
        for provider in self._providers:
            status = provider.status()
            out.append(
                {"provider": provider.name, "available": status.available, "reason": status.reason}
            )
        return out

    def recommend(self, query: MusicQuery, *, limit: int = 5) -> list[MusicRecommendation]:
        """Aggregate recommendations from the first available provider(s)."""

        out: list[MusicRecommendation] = []
        for provider in self.available():
            out.extend(provider.recommend(query, limit=limit))
            if len(out) >= limit:
                break
        out.sort(key=lambda r: (r.score is not None, r.score or 0.0), reverse=True)
        return out[:limit]
