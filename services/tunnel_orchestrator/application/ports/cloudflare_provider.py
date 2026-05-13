"""Port: Cloudflare provider.

Application layer talks to Cloudflare exclusively through these
interfaces. Adapters implement them in
:pymod:`services.tunnel_orchestrator.infrastructure.cloudflare`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from services.tunnel_orchestrator.domain.value_objects import (
    DnsRecord,
    Hostname,
    IngressRuleSet,
    TenantIdVO,
)


@dataclass(frozen=True, slots=True)
class CloudflareTunnel:
    """DTO returned by the provider — keeps adapter types out of the app."""

    cf_tunnel_id: str
    name: str
    config_src: str           # always 'cloudflare' for this platform


class CloudflareProvider(ABC):
    """Per-tenant adapter (instantiated by the registry below)."""

    @abstractmethod
    async def create_tunnel(self, name: str) -> CloudflareTunnel: ...

    @abstractmethod
    async def find_tunnel_by_name(self, name: str) -> CloudflareTunnel | None: ...

    @abstractmethod
    async def get_tunnel_token(self, cf_tunnel_id: str) -> str:
        """Return the *remote-managed* token used by ``cloudflared``."""

    @abstractmethod
    async def put_ingress_configuration(
        self, cf_tunnel_id: str, rules: IngressRuleSet
    ) -> None: ...

    @abstractmethod
    async def reset_ingress_configuration(self, cf_tunnel_id: str) -> None:
        """Replace ingress with the catch-all-only minimum (compensation)."""

    @abstractmethod
    async def delete_tunnel(self, cf_tunnel_id: str) -> None: ...

    # ----- DNS -----

    @abstractmethod
    async def upsert_dns_record(
        self, zone_id: str, record: DnsRecord
    ) -> str:
        """Returns the Cloudflare record id (used for compensation)."""

    @abstractmethod
    async def delete_dns_record(self, zone_id: str, record_id: str) -> None: ...

    @abstractmethod
    async def find_dns_record_id(
        self, zone_id: str, hostname: Hostname
    ) -> str | None: ...


class CloudflareProviderRegistry(ABC):
    """Resolves the right per-tenant provider (each with its own token).

    Implementations cache providers per ``tenant_id`` with a short TTL.
    """

    @abstractmethod
    async def get(self, tenant_id: TenantIdVO) -> CloudflareProvider: ...

    @abstractmethod
    async def invalidate(self, tenant_id: TenantIdVO) -> None: ...
