"""``/v1/admin`` — tenant onboarding + token rotation operations."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field

from apps.api.dependencies import current_principal, get_container, require_admin_dep
from apps.composition import Container
from services.tunnel_orchestrator.domain.aggregates import Tenant
from services.tunnel_orchestrator.infrastructure.auth import JWTPrincipal
from services.tunnel_orchestrator.infrastructure.persistence import PgTenantRepository

router = APIRouter()


class CreateTenantBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=63, pattern=r"^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?$")
    cf_account_id: str
    cf_token_vault_path: str
    cf_zone_ids: list[str] = Field(default_factory=list)
    k8s_namespace: str | None = None
    k8s_cluster: str = "default"
    quota_max_tunnels: int = Field(default=200, ge=1, le=10_000)


class TenantView(BaseModel):
    id: UUID
    name: str
    slug: str
    status: str
    cf_account_id: str
    k8s_namespace: str
    k8s_cluster: str
    cf_zone_ids: list[str]
    quota_max_tunnels: int


@router.post(
    "/tenants",
    response_model=TenantView,
    status_code=status.HTTP_201_CREATED,
    summary="Onboard a new tenant",
)
async def create_tenant(
    body: CreateTenantBody,
    _principal: Annotated[JWTPrincipal, Depends(current_principal)],
    _admin = Depends(require_admin_dep),                 # noqa: B008
    c: Container = Depends(get_container),
) -> TenantView:
    tenant = Tenant.new(
        name=body.name,
        slug=body.slug,
        cf_account_id=body.cf_account_id,
        cf_token_vault_path=body.cf_token_vault_path,
        k8s_namespace=body.k8s_namespace,
        k8s_cluster=body.k8s_cluster,
        cf_zone_ids=body.cf_zone_ids,
    )
    tenant.activate()
    async with c.db.session_factory() as session:
        await PgTenantRepository(session).add(tenant)
        await session.commit()
    return TenantView(
        id=tenant.id.value,
        name=tenant.name,
        slug=tenant.slug,
        status=tenant.status.value,
        cf_account_id=tenant.cf_account_id,
        k8s_namespace=tenant.k8s_namespace,
        k8s_cluster=tenant.k8s_cluster,
        cf_zone_ids=list(tenant.cf_zone_ids),
        quota_max_tunnels=tenant.quota_max_tunnels,
    )
