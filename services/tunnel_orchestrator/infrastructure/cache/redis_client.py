"""Redis client and Redlock-based distributed lock implementation."""

from __future__ import annotations

import asyncio
import contextlib
import secrets
import time
from typing import AsyncIterator

import redis.asyncio as redis_asyncio
from redis.asyncio import Redis

from shared.config import get_settings
from shared.errors import LockAcquisitionFailed
from shared.logging import get_logger
from services.tunnel_orchestrator.application.ports import LockManager

log = get_logger(__name__)

# Lua script for atomic compare-and-delete (release lock only if we own it).
_RELEASE_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""


class RedisClient:
    """Process-wide Redis connection holder."""

    def __init__(self, url: str | None = None) -> None:
        settings = get_settings().redis
        self._url = url or settings.url.get_secret_value()
        self._client: Redis | None = None

    async def connect(self) -> Redis:
        if self._client is None:
            self._client = redis_asyncio.from_url(
                self._url,
                encoding="utf-8",
                decode_responses=True,
                health_check_interval=15,
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            finally:
                self._client = None

    @property
    def client(self) -> Redis:
        if self._client is None:
            raise RuntimeError("RedisClient not connected. Call connect() first.")
        return self._client


class RedisLockManager(LockManager):
    """Single-node Redis lock with token + Lua release.

    For multi-node Redis use Redlock (the same primitive but distributed).
    The interface is identical so callers don't change.
    """

    def __init__(self, client: RedisClient) -> None:
        self._client = client
        self._default_ttl = get_settings().redis.lock_ttl_seconds

    @contextlib.asynccontextmanager
    async def lock(  # type: ignore[override]
        self,
        key: str,
        *,
        ttl_seconds: int | None = None,
        wait_seconds: float = 0.0,
    ) -> AsyncIterator[None]:
        token = secrets.token_hex(16)
        ttl = ttl_seconds or self._default_ttl
        deadline = time.monotonic() + wait_seconds
        backoff = 0.05
        client = self._client.client

        while True:
            ok = await client.set(name=f"lock:{key}", value=token, ex=ttl, nx=True)
            if ok:
                break
            if time.monotonic() >= deadline:
                raise LockAcquisitionFailed(
                    f"Could not acquire lock {key!r} within {wait_seconds:.1f}s",
                    context={"key": key, "ttl_seconds": ttl},
                )
            await asyncio.sleep(min(backoff, 1.0))
            backoff = min(backoff * 1.5, 1.0)

        try:
            yield
        finally:
            try:
                await client.eval(_RELEASE_LUA, 1, f"lock:{key}", token)
            except Exception:  # noqa: BLE001
                log.warning("redis.lock.release_failed", key=key)
