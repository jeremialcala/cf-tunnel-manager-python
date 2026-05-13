"""PostgreSQL repository for the Tunnel aggregate."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.tunnel_orchestrator.domain.aggregates import Tunnel, TunnelStatus
from services.tunnel_orchestrator.domain.aggregates.tunnel import hydrate_tunnel
from services.tunnel_orchestrator.domain.repositories import TunnelRepository
from services.tunnel_orchestrator.domain.value_objects import (
    Hostname,
    IngressOriginConfig,
    IngressRule,
    IngressRuleSet,
    TenantIdVO,
    TunnelIdVO,
)
from services.tunnel_orchestrator.infrastructure.persistence.models import TunnelRow
from services.tunnel_orchestrator.infrastructure.persistence.outbox import PgOutboxStore


class PgTunnelRepository(TunnelRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, tunnel_id: TunnelIdVO) -> Tunnel | None:
        row = await self._session.get(TunnelRow, tunnel_id.value)
        return _to_aggregate(row) if row else None

    async def find_by_hostname(
        self, tenant_id: TenantIdVO, hostname: Hostname
    ) -> Tunnel | None:
        stmt = select(TunnelRow).where(
            TunnelRow.tenant_id == tenant_id.value,
            TunnelRow.hostname == str(hostname),
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_aggregate(row) if row else None

    async def list_by_tenant(
        self, tenant_id: TenantIdVO, *, limit: int = 100, cursor: UUID | None = None
    ) -> list[Tunnel]:
        stmt = select(TunnelRow).where(TunnelRow.tenant_id == tenant_id.value)
        if cursor:
            stmt = stmt.where(TunnelRow.id > cursor)
        stmt = stmt.order_by(TunnelRow.id.asc()).limit(limit)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_to_aggregate(r) for r in rows]

    async def add(self, tunnel: Tunnel) -> None:
        self._session.add(_to_row(tunnel))
        await self._dispatch_pending(tunnel)
        await self._session.flush()

    async def save(self, tunnel: Tunnel) -> None:
        existing = await self._session.get(TunnelRow, tunnel.id.value)
        if existing is None:
            self._session.add(_to_row(tunnel))
        else:
            _apply(existing, tunnel)
        await self._dispatch_pending(tunnel)
        await self._session.flush()

    async def delete(self, tunnel_id: TunnelIdVO) -> None:
        row = await self._session.get(TunnelRow, tunnel_id.value)
        if row is not None:
            await self._session.delete(row)
            await self._session.flush()

    # ------------------------------------------------------------ helpers

    async def _dispatch_pending(self, tunnel: Tunnel) -> None:
        events = tunnel.pull_pending_events()
        if not events:
            return
        outbox = PgOutboxStore(self._session)
        for evt in events:
            await outbox.append_domain_event(evt)


# ----------------------------------------------- mapping helpers


def _to_row(t: Tunnel) -> TunnelRow:
    return TunnelRow(
        id=t.id.value,
        tenant_id=t.tenant_id.value,
        hostname=str(t.hostname),
        cf_zone_id=t.cf_zone_id,
        cluster=t.cluster,
        namespace=t.namespace,
        status=t.status.value,
        cf_tunnel_id=t.cf_tunnel_id,
        cf_dns_record_id=t.cf_dns_record_id,
        deployment_name=t.deployment_name,
        secret_name=t.secret_name,
        ingress={"rules": [r.to_dict() for r in t.ingress.rules]},
        last_error=t.last_error,
        version=t.version,
    )


def _apply(row: TunnelRow, t: Tunnel) -> None:
    row.status = t.status.value
    row.cf_tunnel_id = t.cf_tunnel_id
    row.cf_dns_record_id = t.cf_dns_record_id
    row.deployment_name = t.deployment_name
    row.secret_name = t.secret_name
    row.ingress = {"rules": [r.to_dict() for r in t.ingress.rules]}
    row.last_error = t.last_error
    row.version = t.version


def _to_aggregate(row: TunnelRow) -> Tunnel:
    rules = []
    for raw in row.ingress.get("rules", []):
        rules.append(
            IngressRule(
                service=raw["service"],
                hostname=raw.get("hostname"),
                path=raw.get("path"),
                origin_request=(
                    IngressOriginConfig(**raw["originRequest"])
                    if raw.get("originRequest") else None
                ),
            )
        )
    if not rules:
        rules = [IngressRule(service="http_status:404")]
    return hydrate_tunnel(
        id=row.id,
        tenant_id=row.tenant_id,
        hostname=row.hostname,
        ingress=IngressRuleSet(tuple(rules)),
        cf_zone_id=row.cf_zone_id,
        cluster=row.cluster,
        namespace=row.namespace,
        status=row.status,
        cf_tunnel_id=row.cf_tunnel_id,
        cf_dns_record_id=row.cf_dns_record_id,
        deployment_name=row.deployment_name,
        secret_name=row.secret_name,
        created_at=row.created_at,
        updated_at=row.updated_at,
        last_error=row.last_error,
        version=row.version,
    )


# Re-export for type checkers
__all__ = ["PgTunnelRepository"]


# Reference TunnelStatus to keep the import (used by callers via the aggregate type)
_ = TunnelStatus
