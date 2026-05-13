"""Read-side queries — they return DTOs and never mutate state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from shared.errors import TunnelNotFound
from services.tunnel_orchestrator.domain.aggregates import Tunnel
from services.tunnel_orchestrator.domain.repositories import TunnelRepository
from services.tunnel_orchestrator.domain.value_objects import TenantIdVO, TunnelIdVO


class TunnelView(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    tenant_id: UUID
    hostname: str
    status: str
    cf_tunnel_id: str | None
    cluster: str
    namespace: str
    deployment_name: str | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_aggregate(cls, t: Tunnel) -> "TunnelView":
        return cls(
            id=t.id.value,
            tenant_id=t.tenant_id.value,
            hostname=str(t.hostname),
            status=t.status.value,
            cf_tunnel_id=t.cf_tunnel_id,
            cluster=t.cluster,
            namespace=t.namespace,
            deployment_name=t.deployment_name,
            last_error=t.last_error,
            created_at=t.created_at,
            updated_at=t.updated_at,
        )


@dataclass(frozen=True, slots=True)
class GetTunnelQuery:
    tenant_id: UUID
    tunnel_id: UUID


class GetTunnelHandler:
    def __init__(self, tunnels: TunnelRepository) -> None:
        self._tunnels = tunnels

    async def handle(self, q: GetTunnelQuery) -> TunnelView:
        t = await self._tunnels.get(TunnelIdVO(q.tunnel_id))
        if t is None or t.tenant_id != TenantIdVO(q.tenant_id):
            raise TunnelNotFound(f"Tunnel {q.tunnel_id} not found")
        return TunnelView.from_aggregate(t)


@dataclass(frozen=True, slots=True)
class ListTunnelsQuery:
    tenant_id: UUID
    limit: int = 100
    cursor: UUID | None = None


class ListTunnelsHandler:
    def __init__(self, tunnels: TunnelRepository) -> None:
        self._tunnels = tunnels

    async def handle(self, q: ListTunnelsQuery) -> list[TunnelView]:
        items = await self._tunnels.list_by_tenant(
            TenantIdVO(q.tenant_id), limit=q.limit, cursor=q.cursor
        )
        return [TunnelView.from_aggregate(t) for t in items]
