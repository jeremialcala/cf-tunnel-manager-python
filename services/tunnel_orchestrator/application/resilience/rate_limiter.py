"""Per-tenant async token-bucket rate limiter registry.

Cloudflare's documented limit is 1200 requests / 5 minutes per token.
We give each tenant its own ``aiolimiter.AsyncLimiter`` so noisy
neighbours can't starve quiet ones.
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

from aiolimiter import AsyncLimiter

from shared.observability import metrics


class RateLimiterRegistry:
    """Lazy, lock-free per-key registry.

    The dictionary write is safe under asyncio because there is no
    suspension point between ``in`` check and ``setdefault``.
    """

    def __init__(self, *, max_rate: int, time_period_seconds: float) -> None:
        self._max_rate = max_rate
        self._period = time_period_seconds
        self._limiters: dict[str, AsyncLimiter] = {}

    def for_tenant(self, tenant_id: UUID) -> AsyncLimiter:
        return self._get_or_create(str(tenant_id))

    def for_key(self, key: str) -> AsyncLimiter:
        return self._get_or_create(key)

    def _get_or_create(self, key: str) -> AsyncLimiter:
        limiter = self._limiters.get(key)
        if limiter is None:
            limiter = AsyncLimiter(self._max_rate, self._period)
            self._limiters[key] = limiter
        return limiter

    async def acquire(self, key: str, *, tenant_label: str = "") -> None:
        await self._get_or_create(key).acquire()
        # Approximation; aiolimiter doesn't expose remaining.
        if tenant_label:
            metrics.cloudflare_rate_limit_remaining.labels(tenant_id=tenant_label).set(
                self._max_rate
            )


CLOUDFLARE_DEFAULT_LIMIT: Final[int] = 1200
CLOUDFLARE_WINDOW_SECONDS: Final[float] = 300.0
