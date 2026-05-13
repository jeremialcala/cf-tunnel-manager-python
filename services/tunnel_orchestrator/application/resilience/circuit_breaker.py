"""Per-dependency async circuit breakers.

Built on ``purgatory`` (lightweight async breaker). Used to fail fast
when an upstream is degraded — protects the saga global timeout from
being burned in tight retry loops.
"""

from __future__ import annotations

from typing import Awaitable, Callable, TypeVar

from purgatory import AsyncCircuitBreakerFactory

T = TypeVar("T")


class CircuitBreakerRegistry:
    def __init__(
        self,
        *,
        default_threshold: int = 5,
        default_ttl_seconds: float = 60.0,
    ) -> None:
        self._factory = AsyncCircuitBreakerFactory(
            default_threshold=default_threshold,
            default_ttl=default_ttl_seconds,
        )

    async def execute(
        self,
        name: str,
        fn: Callable[[], Awaitable[T]],
        *,
        threshold: int | None = None,
        ttl_seconds: float | None = None,
    ) -> T:
        breaker = await self._factory.get_breaker(
            name, threshold=threshold, ttl=ttl_seconds
        )
        async with breaker:
            return await fn()

    async def reset(self, name: str) -> None:
        breaker = await self._factory.get_breaker(name)
        await breaker.reset()
