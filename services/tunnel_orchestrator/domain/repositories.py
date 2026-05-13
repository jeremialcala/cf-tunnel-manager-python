"""Repository ports.

These are *interfaces* — the domain layer declares what it needs;
infrastructure adapters implement them. Following the Hexagonal pattern
strictly, no SQL/HTTP/Redis types appear here.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from services.tunnel_orchestrator.domain.aggregates import Tenant, Tunnel
from services.tunnel_orchestrator.domain.value_objects import Hostname, TenantIdVO, TunnelIdVO


class TunnelRepository(ABC):
    """Persistence boundary for the :class:`Tunnel` aggregate."""

    @abstractmethod
    async def get(self, tunnel_id: TunnelIdVO) -> Tunnel | None: ...

    @abstractmethod
    async def find_by_hostname(
        self, tenant_id: TenantIdVO, hostname: Hostname
    ) -> Tunnel | None: ...

    @abstractmethod
    async def list_by_tenant(
        self, tenant_id: TenantIdVO, *, limit: int = 100, cursor: UUID | None = None
    ) -> list[Tunnel]: ...

    @abstractmethod
    async def add(self, tunnel: Tunnel) -> None: ...

    @abstractmethod
    async def save(self, tunnel: Tunnel) -> None:
        """Persist mutations and drain ``pending_events`` into the outbox.

        Implementations MUST do both in a single DB transaction to keep
        the transactional outbox guarantee.
        """

    @abstractmethod
    async def delete(self, tunnel_id: TunnelIdVO) -> None: ...


class TenantRepository(ABC):

    @abstractmethod
    async def get(self, tenant_id: TenantIdVO) -> Tenant | None: ...

    @abstractmethod
    async def get_by_slug(self, slug: str) -> Tenant | None: ...

    @abstractmethod
    async def list_active(self) -> list[Tenant]: ...

    @abstractmethod
    async def add(self, tenant: Tenant) -> None: ...

    @abstractmethod
    async def save(self, tenant: Tenant) -> None: ...
