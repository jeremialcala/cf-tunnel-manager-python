"""Per-tenant Cloudflare provider registry with TTL cache + token loader."""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

from cloudflare import AsyncCloudflare

from shared.logging import get_logger
from services.tunnel_orchestrator.application.ports import (
    CloudflareProvider,
    CloudflareProviderRegistry,
)
from services.tunnel_orchestrator.application.resilience import (
    CircuitBreakerRegistry,
    RetryPolicy,
)
from services.tunnel_orchestrator.application.resilience.rate_limiter import (
    CLOUDFLARE_DEFAULT_LIMIT,
    CLOUDFLARE_WINDOW_SECONDS,
    RateLimiterRegistry,
)
from services.tunnel_orchestrator.application.resilience.retry import AsyncRetry
from services.tunnel_orchestrator.domain.repositories import TenantRepository
from services.tunnel_orchestrator.domain.value_objects import TenantIdVO
from services.tunnel_orchestrator.infrastructure.cloudflare.provider import (
    CloudflareProviderImpl,
)

log = get_logger(__name__)


@dataclass(slots=True, frozen=True)
class _TenantCfBundle:
    account_id: str
    api_token: str


class TenantTokenLoader(ABC):
    """Strategy for fetching the per-tenant Cloudflare token.

    Implementations: env-based loader (single tenant dev), DB+secret-store
    loader (production), Vault loader (CSI driver), …
    """

    @abstractmethod
    async def load(self, tenant_id: TenantIdVO) -> _TenantCfBundle: ...


class DbBackedTokenLoader(TenantTokenLoader):
    """Looks up the tenant in PG, then resolves the token from the secret store.

    Pluggable: the ``secret_resolver`` is an async callable that maps a
    Vault path to a token string.
    """

    def __init__(
        self,
        tenants: TenantRepository,
        secret_resolver,            # noqa: ANN001
    ) -> None:
        self._tenants = tenants
        self._resolver = secret_resolver

    async def load(self, tenant_id: TenantIdVO) -> _TenantCfBundle:
        tenant = await self._tenants.get(tenant_id)
        if tenant is None:
            raise LookupError(f"Tenant {tenant_id} not found")
        token = await self._resolver(tenant.cf_token_vault_path)
        return _TenantCfBundle(account_id=tenant.cf_account_id, api_token=token)


class CloudflareProviderRegistryImpl(CloudflareProviderRegistry):
    """Lazy, TTL-cached per-tenant provider registry."""

    def __init__(
        self,
        *,
        loader: TenantTokenLoader,
        ttl_seconds: float = 300.0,
        retry_policy: RetryPolicy | None = None,
        breaker: CircuitBreakerRegistry | None = None,
        rate_limiter: RateLimiterRegistry | None = None,
    ) -> None:
        self._loader = loader
        self._ttl = ttl_seconds
        self._lock = asyncio.Lock()
        self._cache: dict[str, tuple[float, CloudflareProviderImpl, AsyncCloudflare]] = {}
        self._retry_policy = retry_policy or RetryPolicy()
        self._breaker = breaker or CircuitBreakerRegistry()
        self._rate = rate_limiter or RateLimiterRegistry(
            max_rate=CLOUDFLARE_DEFAULT_LIMIT,
            time_period_seconds=CLOUDFLARE_WINDOW_SECONDS,
        )

    async def get(self, tenant_id: TenantIdVO) -> CloudflareProvider:
        key = str(tenant_id)
        now = time.monotonic()
        cached = self._cache.get(key)
        if cached and (now - cached[0] < self._ttl):
            return cached[1]

        async with self._lock:
            cached = self._cache.get(key)
            if cached and (now - cached[0] < self._ttl):
                return cached[1]
            bundle = await self._loader.load(tenant_id)
            client = AsyncCloudflare(api_token=bundle.api_token)
            provider = CloudflareProviderImpl(
                client=client,
                account_id=bundle.account_id,
                tenant_id=key,
                rate_limiter=self._rate,
                breaker=self._breaker,
                retry=AsyncRetry(self._retry_policy),
            )
            self._cache[key] = (now, provider, client)
            return provider

    async def invalidate(self, tenant_id: TenantIdVO) -> None:
        key = str(tenant_id)
        async with self._lock:
            entry = self._cache.pop(key, None)
        if entry:
            try:
                await entry[2].close()
            except Exception:  # noqa: BLE001
                log.warning("cloudflare.client.close_failed", tenant_id=key)
