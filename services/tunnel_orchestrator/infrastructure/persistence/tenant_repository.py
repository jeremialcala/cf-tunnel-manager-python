from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.tunnel_orchestrator.domain.aggregates import Tenant, TenantStatus
from services.tunnel_orchestrator.domain.repositories import TenantRepository
from services.tunnel_orchestrator.domain.value_objects import TenantIdVO
from services.tunnel_orchestrator.infrastructure.persistence.models import TenantRow


class PgTenantRepository(TenantRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, tenant_id: TenantIdVO) -> Tenant | None:
        row = await self._session.get(TenantRow, tenant_id.value)
        return _to_agg(row) if row else None

    async def get_by_slug(self, slug: str) -> Tenant | None:
        stmt = select(TenantRow).where(TenantRow.slug == slug)
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_agg(row) if row else None

    async def list_active(self) -> list[Tenant]:
        stmt = select(TenantRow).where(TenantRow.status == "ACTIVE")
        return [_to_agg(r) for r in (await self._session.execute(stmt)).scalars().all()]

    async def add(self, tenant: Tenant) -> None:
        self._session.add(_to_row(tenant))
        await self._session.flush()

    async def save(self, tenant: Tenant) -> None:
        existing = await self._session.get(TenantRow, tenant.id.value)
        if existing is None:
            self._session.add(_to_row(tenant))
        else:
            _apply(existing, tenant)
        await self._session.flush()


def _to_row(t: Tenant) -> TenantRow:
    return TenantRow(
        id=t.id.value,
        name=t.name,
        slug=t.slug,
        cf_account_id=t.cf_account_id,
        cf_token_vault_path=t.cf_token_vault_path,
        k8s_namespace=t.k8s_namespace,
        k8s_cluster=t.k8s_cluster,
        cf_zone_ids=list(t.cf_zone_ids),
        quota_max_tunnels=t.quota_max_tunnels,
        status=t.status.value,
    )


def _apply(row: TenantRow, t: Tenant) -> None:
    row.name = t.name
    row.k8s_namespace = t.k8s_namespace
    row.k8s_cluster = t.k8s_cluster
    row.cf_zone_ids = list(t.cf_zone_ids)
    row.quota_max_tunnels = t.quota_max_tunnels
    row.status = t.status.value


def _to_agg(row: TenantRow) -> Tenant:
    return Tenant(
        id=TenantIdVO(row.id),
        name=row.name,
        slug=row.slug,
        cf_account_id=row.cf_account_id,
        cf_token_vault_path=row.cf_token_vault_path,
        k8s_namespace=row.k8s_namespace,
        k8s_cluster=row.k8s_cluster,
        cf_zone_ids=list(row.cf_zone_ids or []),
        quota_max_tunnels=row.quota_max_tunnels,
        status=TenantStatus(row.status),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
