"""Correlation ID middleware.

Reads ``X-Correlation-Id`` from the request (creates one if missing),
binds it into the contextvar so logs/spans pick it up, and echoes it
on the response.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from shared.observability import bind_correlation, clear_context

HEADER_NAME = "X-Correlation-Id"


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # noqa: ANN001
        incoming = request.headers.get(HEADER_NAME) or request.headers.get("traceparent")
        cid = bind_correlation(incoming)
        try:
            response: Response = await call_next(request)
        finally:
            clear_context()
        response.headers[HEADER_NAME] = str(cid)
        return response
