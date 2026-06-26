"""Time helpers.

All timestamps in Olympus are timezone-aware UTC. Centralising ``utc_now``
avoids the classic bug of mixing naive and aware datetimes and makes it trivial
to freeze time in tests.
"""

from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> datetime:
    """Return the current time as a timezone-aware UTC ``datetime``."""

    return datetime.now(UTC)
