"""Storage analytics - measured global usage by namespace.

Reuses the library's size helper (`project_management.sizes`) to measure real
byte usage under each top-level namespace. The trend over time is supplied
separately by the captured snapshot series; this module measures the current
point only.
"""

from __future__ import annotations

from olympus.domain.contracts.storage import StoragePort
from olympus.project_management.sizes import measure_prefix

# Top-level storage namespaces Olympus writes under (some may be empty / 0).
NAMESPACES: tuple[str, ...] = (
    "projects",
    "uploads",
    "analysis",
    "story",
    "virality",
    "planning",
    "editing",
    "render",
    "optimization",
    "workflow",
    "library",
    "monitoring",
    "logs",
    "cache",
)


async def collect_storage(storage: StoragePort) -> tuple[int, dict[str, int]]:
    """Measure current storage usage per namespace; returns (total, by-namespace)."""

    namespaces: dict[str, int] = {}
    for ns in NAMESPACES:
        namespaces[ns] = await measure_prefix(storage, f"{ns}/")
    total = sum(namespaces.values())
    return total, namespaces
