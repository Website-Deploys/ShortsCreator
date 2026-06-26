"""HTTP middleware.

:class:`RequestContextMiddleware` assigns every request a correlation id
(accepting an inbound ``X-Request-ID`` if present, else generating one), binds
it to the logging context so every log line within the request carries it,
echoes it back in the response header, and logs a structured access line with
latency. This gives end-to-end traceability for free (the architecture's
inspectability requirement).
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from olympus.platform.logging import bind_context, clear_context, get_logger
from olympus.utils import new_id

log = get_logger(__name__)

_REQUEST_ID_HEADER = "X-Request-ID"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Attach a correlation id and emit a structured access log per request."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get(_REQUEST_ID_HEADER) or new_id("req")
        request.state.request_id = request_id
        bind_context(request_id=request_id)

        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
            log.info(
                "http_request",
                method=request.method,
                path=request.url.path,
                duration_ms=elapsed_ms,
            )
            clear_context()

        response.headers[_REQUEST_ID_HEADER] = request_id
        return response
