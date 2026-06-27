"""Project Management & Asset Library - the production management layer.

A fully-additive, read-only aggregation over everything the eight Olympus engines
have produced: an asset library (source videos, clips, renders, exports), a clip
library, an export library, global search, dashboard statistics, and a per-project
storage inspector. It adds a small amount of library-owned state of its own -
captured version snapshots, an activity feed, and favorites/tags/archive metadata
- under a dedicated ``library/`` storage namespace that no engine touches.

It never modifies an engine or its data and never fabricates a value: every
record reflects real stored state, and anything an engine did not produce is
reported as UNKNOWN. The only writes it performs are its own metadata and the
explicitly-requested cleanup/archive operations.
"""

from olympus.project_management import dashboard, inventory, search, sizes

__all__ = ["dashboard", "inventory", "search", "sizes"]
