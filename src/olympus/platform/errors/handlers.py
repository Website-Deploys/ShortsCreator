"""FastAPI exception handlers.

Translates the Olympus exception hierarchy (and unexpected errors) into the
single, consistent API error envelope::

    {
      "error": {
        "code": "not_found",
        "message": "The requested resource was not found.",
        "details": { ... }          # optional
      },
      "request_id": "..."           # for support / correlation
    }

Expected errors (:class:`OlympusError`) are returned with their mapped status
and logged at ``warning``. Unexpected errors are returned as a generic 500
(never leaking internals) and logged at ``error`` with a full stack trace -
failing loudly in the logs while staying safe to the client.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from olympus.platform.errors.exceptions import OlympusError
from olympus.platform.logging import get_logger

log = get_logger(__name__)


def _envelope(request: Request, code: str, message: str, details: Any = None) -> dict[str, Any]:
    body: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details:
        # Coerce dynamic detail payloads (which may contain non-JSON-serializable
        # objects - e.g. pydantic v2 validation ``ctx`` carrying a ValueError) into
        # plain JSON-safe structures. Without this the error handler itself raises
        # a TypeError while rendering its own response, turning a clean 4xx into an
        # unhandled 500.
        body["error"]["details"] = jsonable_encoder(details)
    request_id = getattr(request.state, "request_id", None)
    if request_id:
        body["request_id"] = request_id
    return body


async def _handle_olympus_error(request: Request, exc: OlympusError) -> JSONResponse:
    log.warning("handled_error", code=exc.code, message=exc.message, details=exc.details)
    return JSONResponse(
        status_code=exc.http_status,
        content=_envelope(request, exc.code, exc.message, exc.details or None),
    )


async def _handle_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    log.warning("request_validation_error", errors=exc.errors())
    return JSONResponse(
        status_code=422,
        content=_envelope(
            request,
            "validation_error",
            "The request was invalid.",
            details={"errors": exc.errors()},
        ),
    )


async def _handle_http_exception(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=_envelope(request, "http_error", str(exc.detail)),
    )


async def _handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    # A genuine bug: log everything, reveal nothing.
    log.error("unhandled_exception", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content=_envelope(
            request, "internal_error", "An unexpected error occurred."
        ),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Attach all exception handlers to the FastAPI application."""

    app.add_exception_handler(OlympusError, _handle_olympus_error)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _handle_validation_error)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _handle_unexpected_error)
