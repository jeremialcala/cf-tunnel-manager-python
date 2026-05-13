"""Per-tenant API rate limiter (token bucket via aiolimiter).

Chosen over Redis-based limiting for the API layer because we want
fail-open semantics if Redis is unavailable. For shared multi-pod
quotas use a Redis adapter.
"""

from __future__ import annotations

from aiolimiter import AsyncLimiter
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, max_rate: int = 60, time_window_seconds: float = 60.0):  # noqa: ANN001
        super().__init__(app)
        self._max_rate = max_rate
        self._window = time_window_seconds
        self._limiters: dict[str, AsyncLimiter] = {}

    async def dispatch(self, request: Request, call_next):  # noqa: ANN001
        # Identify the bucket: prefer authenticated tenant; fallback to client IP.
        principal = getattr(request.state, "principal", None)
        bucket = str(principal.tenant_id) if principal else (request.client.host if request.client else "unknown")
        limiter = self._limiters.get(bucket)
        if limiter is None:
            limiter = AsyncLimiter(self._max_rate, self._window)
            self._limiters[bucket] = limiter
        if not limiter.has_capacity():
            return JSONResponse(
                status_code=429,
                content={"code": "RATE_LIMITED", "message": "API rate limit exceeded"},
                headers={"Retry-After": "1"},
            )
        async with limiter:
            response: Response = await call_next(request)
        return response
