"""Identifier generation.

Olympus uses time-ordered, URL-safe, collision-resistant identifiers for all
entities. We standardise on UUIDv4 hex for the foundation; the helper is
centralised so the scheme can evolve (e.g. to a sortable ULID/UUIDv7) in one
place without touching call sites.
"""

from __future__ import annotations

import uuid


def new_id(prefix: str | None = None) -> str:
    """Return a new unique identifier.

    Args:
        prefix: Optional short prefix (e.g. ``"proj"``, ``"clip"``) to make ids
            self-describing in logs and URLs. The result is ``"{prefix}_{hex}"``.

    Returns:
        A unique, URL-safe identifier string.
    """

    raw = uuid.uuid4().hex
    return f"{prefix}_{raw}" if prefix else raw
