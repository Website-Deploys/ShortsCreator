"""Seed safe pattern-level BOBA global memory without live crawling."""

from __future__ import annotations

from olympus.boba.constitution import get_boba_constitution
from olympus.boba.memory_contracts import BobaGlobalMemoryV1, BobaMemoryRecordV1
from olympus.boba.store import BobaMemoryStore


def build_global_memory() -> tuple[BobaGlobalMemoryV1, list[BobaMemoryRecordV1]]:
    constitution = get_boba_constitution()
    global_memory = BobaGlobalMemoryV1(
        principles=list(constitution["principles"]),
        platform_patterns=[
            "Prefer clear, truthful, platform-appropriate packaging.",
            "Treat trend fit as supporting evidence, never as guaranteed performance.",
        ],
        hook_patterns=[
            "Start near the first meaningful word when context and sync remain intact.",
            "Prefer a clear curiosity gap, tension, or emotionally specific promise "
            "without deception.",
        ],
        editing_patterns=[
            "Preserve setup, turning point, payoff, and a readable ending tail.",
            "Use motion and effects to clarify story beats rather than decorate every caption.",
        ],
        caption_patterns=[
            "Protect readability, safe margins, and speech alignment.",
            "Emphasize only a few meaning-bearing words.",
        ],
        music_patterns=[
            "Keep speech first and report music as mixed only when it is present "
            "in rendered audio.",
            "Prefer subtle, rights-safe, non-noise-like assets.",
        ],
        motion_patterns=[
            "Use face-driven framing only when detections are reliable and rendering "
            "applies the plan.",
            "Fall back to stable safe framing instead of random switching.",
        ],
        metadata_patterns=[
            "Avoid generic titles, unsupported claims, copied phrasing, and spam hashtags.",
            "Explain uncertainty and manual-review requirements.",
        ],
        safety_principles=list(constitution["forbidden_behaviors"]),
        known_limitations=[
            "No cloud sync.",
            "No hidden or passive learning.",
            "No analytics learning yet.",
            "No autonomous web crawling.",
            "No vector database.",
            "No guarantee of improved performance.",
            "No copyrighted content storage.",
        ],
        source_attribution=[
            "BOBA Core Brain V1 constitution",
            "Olympus V2 pattern-level safety and editing guidance",
        ],
        confidence=0.75,
        warnings=["Global Memory V1 is seeded and local; it is not live trend research."],
    )
    category_values = {
        "hook": (global_memory.hook_patterns, ["ranking", "editorial_policy"]),
        "editing": (global_memory.editing_patterns, ["editorial_policy"]),
        "captions": (global_memory.caption_patterns, ["captions"]),
        "music": (global_memory.music_patterns, ["music"]),
        "motion": (global_memory.motion_patterns, ["motion"]),
        "metadata": (global_memory.metadata_patterns, ["upload_metadata"]),
        "safety": (global_memory.safety_principles, ["safety"]),
    }
    records = [
        BobaMemoryRecordV1(
            memory_id=f"global_pattern_{category}",
            scope="global",
            record_type="learned_pattern",
            source="seeded_global_memory_v1",
            confidence=0.75,
            importance=0.8,
            tags=["global_pattern", category],
            summary=" ".join(values[:2]),
            evidence=["Seeded from local BOBA/Olympus principles; no live crawling used."],
            applies_to=targets,
        )
        for category, (values, targets) in category_values.items()
    ]
    return global_memory, records


def build_and_save_global_memory(store: BobaMemoryStore) -> BobaGlobalMemoryV1:
    global_memory, records = build_global_memory()
    for record in records:
        store.save_record(record)
    return store.save_global_memory(global_memory)
