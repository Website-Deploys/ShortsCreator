"""Small, dependency-free helpers shared across the codebase.

Anything here must have zero dependencies on other Olympus packages (no config,
no logging, no adapters) so it is safe to import from anywhere.
"""

from olympus.utils.ids import new_id
from olympus.utils.locks import project_write_lock
from olympus.utils.timing import utc_now

__all__ = ["new_id", "project_write_lock", "utc_now"]
