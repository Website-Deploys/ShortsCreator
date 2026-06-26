"""Application configuration package.

Exposes :func:`get_settings`, the single, cached entry point for reading
configuration anywhere in the application.
"""

from olympus.platform.config.settings import Settings, get_settings

__all__ = ["Settings", "get_settings"]
