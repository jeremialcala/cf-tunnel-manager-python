"""Cloudflare adapter built on the official ``cloudflare`` Python SDK v5 (async).

Maps :class:`CloudflareProvider` calls onto the SDK and translates the
SDK's exceptions into our typed
:class:`shared.errors.CloudflareAPIError` hierarchy. Per-tenant rate
limiting and circuit breaking are applied here so every saga step
benefits without each having to remember.

Notes
-----

* We always set ``config_src='cloudflare'`` (remote-managed). Setting
  is enforced by :class:`shared.config.CloudflareSettings`.
* All calls are wrapped in a :class:`AsyncRetry` with the policy
  derived from app settings — the breaker fails fast under sustained
  upstream errors.
* The SDK exposes resources at ``client.zero_trust.tunnels.cloudflared``
  in v5; we centralise that here so saga steps remain decoupled from
  the SDK shape.
"""

from __future__ import annotations

import time
from typing import Any

from cloudflare import AsyncCloudflare
from cloudflare import APIStatusError, RateLimitError

from shared.errors import (
    CloudflareAPIError,
    CloudflareRateLimited,
    CloudflareUnauthorized,
)
from shared.logging import get_logger
from shared.observability import metrics
from services.tunnel_orchestrator.application.ports import CloudflareProvider
from services.tunnel_orchestrator.application.ports.cloudflare_provider import (
    CloudflareTunnel,
)
from services.tunnel_orchestrator.application.resilience import (
    AsyncRetry,
    CircuitBreakerRegistry,
    RetryPolicy,
)
from services.tunnel_orchestrator.application.resilience.rate_limiter import (
    RateLimiterRegistry,
)
from services.tunnel_orchestrator.domain.value_objects import (
    DnsRecord,
    Hostname,
    IngressRuleSet,
)

log = get_logger(__name__)


class CloudflareProviderImpl(CloudflareProvider):
    """Per-tenant Cloudflare adapter."""

    def __init__(
        self,
        *,
        client: AsyncCloudflare,
        account_id: str,
        tenant_id: str,
        rate_limiter: RateLimiterRegistry,
        breaker: CircuitBreakerRegistry,
        retry: AsyncRetry | None = None,
    ) -> None:
        self._client = client
        self._account_id = account_id
        self._tenant_id = tenant_id
        self._rate = rate_limiter
        self._breaker = breaker
        self._retry = retry or AsyncRetry(RetryPolicy())

    # ----------------------------------------------------- tunnels

    async def create_tunnel(self, name: str) -> CloudflareTunnel:
        async def _call() -> Any:
            return await self._client.zero_trust.tunnels.cloudflared.create(
                account_id=self._account_id,
                name=name,
                config_src="cloudflare",
            )

        result = await self._instrumented("create_tunnel", _call)
        return CloudflareTunnel(
            cf_tunnel_id=str(result.id),
            name=str(result.name),
            config_src="cloudflare",
        )

    async def find_tunnel_by_name(self, name: str) -> CloudflareTunnel | None:
        async def _call() -> Any:
            return await self._client.zero_trust.tunnels.cloudflared.list(
                account_id=self._account_id, name=name, is_deleted=False
            )

        page = await self._instrumented("find_tunnel_by_name", _call)
        for item in page.result or []:
            if item.name == name:
                return CloudflareTunnel(
                    cf_tunnel_id=str(item.id),
                    name=str(item.name),
                    config_src=getattr(item, "config_src", "cloudflare") or "cloudflare",
                )
        return None

    async def get_tunnel_token(self, cf_tunnel_id: str) -> str:
        async def _call() -> Any:
            return await self._client.zero_trust.tunnels.cloudflared.token.get(
                account_id=self._account_id, tunnel_id=cf_tunnel_id
            )

        token = await self._instrumented("get_tunnel_token", _call)
        # SDK returns a string-typed model; normalise.
        return token if isinstance(token, str) else str(token)

    async def put_ingress_configuration(
        self, cf_tunnel_id: str, rules: IngressRuleSet
    ) -> None:
        config_payload: dict[str, Any] = {"ingress": rules.to_payload()}

        async def _call() -> Any:
            return await self._client.zero_trust.tunnels.cloudflared.configurations.update(
                account_id=self._account_id,
                tunnel_id=cf_tunnel_id,
                config=config_payload,
            )

        await self._instrumented("put_ingress_configuration", _call)

    async def reset_ingress_configuration(self, cf_tunnel_id: str) -> None:
        config_payload: dict[str, Any] = {
            "ingress": [{"service": "http_status:404"}],
        }

        async def _call() -> Any:
            return await self._client.zero_trust.tunnels.cloudflared.configurations.update(
                account_id=self._account_id,
                tunnel_id=cf_tunnel_id,
                config=config_payload,
            )

        await self._instrumented("reset_ingress_configuration", _call, swallow_404=True)

    async def delete_tunnel(self, cf_tunnel_id: str) -> None:
        async def _call() -> Any:
            return await self._client.zero_trust.tunnels.cloudflared.delete(
                account_id=self._account_id, tunnel_id=cf_tunnel_id, body={}
            )

        await self._instrumented("delete_tunnel", _call, swallow_404=True)

    # --------------------------------------------------------- DNS

    async def upsert_dns_record(self, zone_id: str, record: DnsRecord) -> str:
        async def _list() -> Any:
            return await self._client.dns.records.list(
                zone_id=zone_id, name=str(record.hostname), type=record.type.value
            )

        existing = await self._instrumented("dns.list", _list)
        record_payload: dict[str, Any] = {
            "type": record.type.value,
            "name": str(record.hostname),
            "content": record.target,
            "proxied": record.proxied,
            "ttl": record.ttl,
            "comment": record.comment,
        }

        for r in (existing.result or []):
            if r.name == str(record.hostname):
                async def _update() -> Any:
                    return await self._client.dns.records.update(
                        dns_record_id=str(r.id),
                        zone_id=zone_id,
                        **record_payload,
                    )
                updated = await self._instrumented("dns.update", _update)
                return str(updated.id)

        async def _create() -> Any:
            return await self._client.dns.records.create(zone_id=zone_id, **record_payload)

        created = await self._instrumented("dns.create", _create)
        return str(created.id)

    async def find_dns_record_id(self, zone_id: str, hostname: Hostname) -> str | None:
        async def _list() -> Any:
            return await self._client.dns.records.list(zone_id=zone_id, name=str(hostname))

        existing = await self._instrumented("dns.find", _list)
        for r in (existing.result or []):
            if r.name == str(hostname):
                return str(r.id)
        return None

    async def delete_dns_record(self, zone_id: str, record_id: str) -> None:
        async def _call() -> Any:
            return await self._client.dns.records.delete(
                dns_record_id=record_id, zone_id=zone_id
            )

        await self._instrumented("dns.delete", _call, swallow_404=True)

    # --------------------------------------------------- internals

    async def _instrumented(
        self,
        op: str,
        fn,                                 # noqa: ANN001 — callable
        *,
        swallow_404: bool = False,
    ) -> Any:
        await self._rate.acquire(self._tenant_id, tenant_label=self._tenant_id)

        async def _execute() -> Any:
            started = time.monotonic()
            try:
                value = await fn()
                metrics.cloudflare_calls_total.labels(op, "ok", self._tenant_id).inc()
                return value
            except RateLimitError as e:
                metrics.cloudflare_calls_total.labels(op, "rate_limited", self._tenant_id).inc()
                retry_after = float(getattr(e.response, "headers", {}).get("retry-after", 5))
                raise CloudflareRateLimited(retry_after, message=str(e), cause=e) from e
            except APIStatusError as e:
                status = getattr(e, "status_code", None) or getattr(e.response, "status_code", 0)
                if status == 401 or status == 403:
                    metrics.cloudflare_calls_total.labels(op, "unauthorized", self._tenant_id).inc()
                    raise CloudflareUnauthorized(message=str(e), cause=e) from e
                if status == 404 and swallow_404:
                    metrics.cloudflare_calls_total.labels(op, "not_found", self._tenant_id).inc()
                    return None
                metrics.cloudflare_calls_total.labels(op, f"api_{status}", self._tenant_id).inc()
                raise CloudflareAPIError(message=str(e), context={"status": status}, cause=e) from e
            finally:
                metrics.cloudflare_call_duration_seconds.labels(op).observe(
                    time.monotonic() - started
                )

        return await self._breaker.execute(
            f"cloudflare:{self._tenant_id}",
            lambda: self._retry.run(_execute),
        )
