"""The Olympus exception hierarchy.

A single, typed hierarchy used across every layer. Application and domain code
raise these; the HTTP layer (``handlers.py``) translates them into consistent,
structured API error responses. This keeps error semantics in one place and
decouples the domain from the transport (HTTP).

Design rules:
- Every error carries a stable machine-readable ``code`` and a human-readable
  ``message`` (honesty over opaque failure).
- Errors may carry structured ``details`` for actionable client feedback.
- The base class maps to an HTTP status, but domain code never imports HTTP -
  it simply raises the semantically correct error.
"""

from __future__ import annotations

from typing import Any


class OlympusError(Exception):
    """Base class for all expected, handled application errors.

    Unexpected errors (bugs) are *not* subclasses of this - they surface as
    500s and are logged with full stack traces. ``OlympusError`` is for
    conditions we anticipate and translate into clean responses.
    """

    # Sensible defaults; subclasses override.
    code: str = "internal_error"
    http_status: int = 500
    message: str = "An unexpected error occurred."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.details = details or {}
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to the canonical API error shape."""

        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return payload


class ValidationError(OlympusError):
    """Input failed validation (client error)."""

    code = "validation_error"
    http_status = 422
    message = "The request was invalid."


class UnauthorizedError(OlympusError):
    """Caller is not authenticated or not authorised for the resource."""

    code = "unauthorized"
    http_status = 401
    message = "Authentication is required or has failed."


class ForbiddenError(OlympusError):
    """Caller is authenticated but lacks permission for the resource."""

    code = "forbidden"
    http_status = 403
    message = "You do not have permission to perform this action."


class NotFoundError(OlympusError):
    """The requested resource does not exist (or is not visible to the caller)."""

    code = "not_found"
    http_status = 404
    message = "The requested resource was not found."


class ConflictError(OlympusError):
    """The request conflicts with the current state of the resource."""

    code = "conflict"
    http_status = 409
    message = "The request conflicts with the current resource state."


class RateLimitedError(OlympusError):
    """The caller has exceeded a rate limit."""

    code = "rate_limited"
    http_status = 429
    message = "Too many requests. Please slow down."


class StorageError(OlympusError):
    """A storage backend operation failed."""

    code = "storage_error"
    http_status = 502
    message = "A storage operation failed."


class ExternalServiceError(OlympusError):
    """A dependency (AI provider, queue, etc.) failed or was unavailable."""

    code = "external_service_error"
    http_status = 502
    message = "An upstream service failed."


class ConfigurationError(OlympusError):
    """The application is misconfigured. Raised loudly at startup."""

    code = "configuration_error"
    http_status = 500
    message = "The service is misconfigured."
