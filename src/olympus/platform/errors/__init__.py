"""Error-handling framework: a typed exception hierarchy and HTTP handlers."""

from olympus.platform.errors.exceptions import (
    ConfigurationError,
    ConflictError,
    ExternalServiceError,
    ForbiddenError,
    NotFoundError,
    OlympusError,
    RateLimitedError,
    StorageError,
    UnauthorizedError,
    ValidationError,
)
from olympus.platform.errors.handlers import register_exception_handlers

__all__ = [
    "ConfigurationError",
    "ConflictError",
    "ExternalServiceError",
    "ForbiddenError",
    "NotFoundError",
    "OlympusError",
    "RateLimitedError",
    "StorageError",
    "UnauthorizedError",
    "ValidationError",
    "register_exception_handlers",
]
