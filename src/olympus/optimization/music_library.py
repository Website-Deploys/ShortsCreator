"""Copyright-free music: a local royalty-free provider + future-provider stubs.

This module supplies the *default* music provider registry the Optimization
Engine uses. It deliberately contains only legally-safe options:

- :class:`LocalRoyaltyFreeMusicProvider` - a small, curated catalogue of
  royalty-free cues (CC0 / public-domain-style licensing) described by their
  musical character (mood, energy, BPM, genre). It recommends by matching the
  engine's brief to that character with a transparent, inspectable score. It
  never downloads or streams anything; a real deployment would point each entry's
  ``storage_key`` at an actually-licensed asset.
- Future providers (Epidemic Sound, Artlist, Soundstripe, AI-generated music) are
  represented as honest, *unavailable* stubs: they implement the same contract,
  declare ``available = False`` with a reason, and return nothing until a real
  integration (with real credentials/licensing) is wired in. This proves the
  abstraction without faking a catalogue the platform cannot legally offer.

The matching is a deterministic heuristic, not a black-box "AI" claim - its
scores are explained and its confidence kept modest accordingly.
"""

from __future__ import annotations

from olympus.domain.contracts.music import (
    MusicProvider,
    MusicProviderRegistry,
    MusicProviderStatus,
    MusicQuery,
    MusicRecommendation,
    MusicTrack,
)

#: Curated royalty-free catalogue. Each entry describes musical character only;
#: ``storage_key`` is where a deployment would place the actually-licensed file.
_LOCAL_CATALOGUE: tuple[MusicTrack, ...] = (
    MusicTrack(
        id="rf_uplift_pulse",
        title="Uplift Pulse",
        provider="local_royalty_free",
        license="CC0",
        source="Olympus local royalty-free library",
        artist="Olympus Library",
        bpm=120,
        genre="electronic",
        energy=0.8,
        mood=("uplifting", "energetic", "motivational"),
        duration=180.0,
        storage_key=None,
    ),
    MusicTrack(
        id="rf_focus_drive",
        title="Focus Drive",
        provider="local_royalty_free",
        license="CC0",
        source="Olympus local royalty-free library",
        artist="Olympus Library",
        bpm=100,
        genre="lo-fi",
        energy=0.45,
        mood=("focused", "calm", "thoughtful"),
        duration=180.0,
        storage_key=None,
    ),
    MusicTrack(
        id="rf_cinematic_rise",
        title="Cinematic Rise",
        provider="local_royalty_free",
        license="CC0",
        source="Olympus local royalty-free library",
        artist="Olympus Library",
        bpm=90,
        genre="cinematic",
        energy=0.6,
        mood=("inspiring", "dramatic", "emotional"),
        duration=180.0,
        storage_key=None,
    ),
    MusicTrack(
        id="rf_street_bounce",
        title="Street Bounce",
        provider="local_royalty_free",
        license="CC0",
        source="Olympus local royalty-free library",
        artist="Olympus Library",
        bpm=140,
        genre="hip-hop",
        energy=0.85,
        mood=("confident", "energetic", "bold"),
        duration=180.0,
        storage_key=None,
    ),
    MusicTrack(
        id="rf_gentle_morning",
        title="Gentle Morning",
        provider="local_royalty_free",
        license="CC0",
        source="Olympus local royalty-free library",
        artist="Olympus Library",
        bpm=80,
        genre="acoustic",
        energy=0.3,
        mood=("calm", "warm", "reflective"),
        duration=180.0,
        storage_key=None,
    ),
    MusicTrack(
        id="rf_tension_build",
        title="Tension Build",
        provider="local_royalty_free",
        license="CC0",
        source="Olympus local royalty-free library",
        artist="Olympus Library",
        bpm=110,
        genre="cinematic",
        energy=0.7,
        mood=("suspenseful", "dramatic", "intense"),
        duration=180.0,
        storage_key=None,
    ),
)


def _score(track: MusicTrack, query: MusicQuery) -> tuple[float, list[dict[str, str]]]:
    """Deterministic, explainable match score in [0, 1] with its evidence."""

    evidence: list[dict[str, str]] = []
    parts: list[float] = []

    # Mood overlap (the strongest signal).
    if query.mood:
        overlap = set(query.mood) & set(track.mood)
        mood_score = len(overlap) / max(1, len(set(query.mood)))
        parts.append(mood_score)
        if overlap:
            evidence.append(
                {"type": "mood", "detail": f"shared mood: {', '.join(sorted(overlap))}"}
            )

    # Energy proximity.
    if query.energy is not None and track.energy is not None:
        energy_score = 1.0 - min(1.0, abs(query.energy - track.energy))
        parts.append(energy_score)
        evidence.append(
            {
                "type": "energy",
                "detail": f"track energy {track.energy} vs target {round(query.energy, 2)}",
            }
        )

    # Tempo proximity (within ~40 BPM counts).
    if query.target_bpm is not None and track.bpm is not None:
        bpm_score = max(0.0, 1.0 - abs(query.target_bpm - track.bpm) / 40.0)
        parts.append(bpm_score)
        evidence.append(
            {"type": "bpm", "detail": f"track {track.bpm} BPM vs target {query.target_bpm}"}
        )

    # Genre preference.
    if query.genres and track.genre:
        genre_score = 1.0 if track.genre in query.genres else 0.0
        parts.append(genre_score)
        if genre_score:
            evidence.append({"type": "genre", "detail": f"matches preferred genre {track.genre}"})

    score = round(sum(parts) / len(parts), 3) if parts else 0.0
    return score, evidence


class LocalRoyaltyFreeMusicProvider(MusicProvider):
    """Recommends from the curated, license-safe local catalogue."""

    name = "local_royalty_free"

    def __init__(self, catalogue: tuple[MusicTrack, ...] = _LOCAL_CATALOGUE) -> None:
        self._catalogue = catalogue

    def status(self) -> MusicProviderStatus:
        if not self._catalogue:
            return MusicProviderStatus(available=False, reason="local catalogue is empty")
        return MusicProviderStatus(available=True)

    def recommend(self, query: MusicQuery, *, limit: int = 5) -> list[MusicRecommendation]:
        scored: list[MusicRecommendation] = []
        for track in self._catalogue:
            score, evidence = _score(track, query)
            reason = (
                "heuristic match of the clip's mood/energy/tempo brief to this "
                "royalty-free cue's musical character (not an audio-model analysis)"
            )
            scored.append(
                MusicRecommendation(track=track, score=score, reason=reason, evidence=evidence)
            )
        scored.sort(key=lambda r: r.score or 0.0, reverse=True)
        return scored[:limit]


class _UnavailableProvider(MusicProvider):
    """A future, not-yet-integrated licensed provider (honestly unavailable)."""

    def __init__(self, name: str, reason: str) -> None:
        self.name = name
        self._reason = reason

    def status(self) -> MusicProviderStatus:
        return MusicProviderStatus(available=False, reason=self._reason)

    def recommend(self, query: MusicQuery, *, limit: int = 5) -> list[MusicRecommendation]:
        return []


def build_default_music_registry() -> MusicProviderRegistry:
    """The default registry: the local library plus honest future-provider stubs."""

    return MusicProviderRegistry(
        [
            LocalRoyaltyFreeMusicProvider(),
            _UnavailableProvider(
                "epidemic_sound",
                "Epidemic Sound integration is not configured (no API credentials/licence).",
            ),
            _UnavailableProvider(
                "artlist",
                "Artlist integration is not configured (no API credentials/licence).",
            ),
            _UnavailableProvider(
                "soundstripe",
                "Soundstripe integration is not configured (no API credentials/licence).",
            ),
            _UnavailableProvider(
                "ai_generated",
                "AI music generation is not configured (no generation model available).",
            ),
        ]
    )
