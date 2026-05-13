"""``/v1/tunnels`` — CRUD + validate."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Path, Query, status
from pydantic import BaseModel, ConfigDict, Field

from apps.api.dependencies import (
    create_tunnel_handler,
    current_principal,
    delete_tunnel_handler,
    get_query,
    list_query,
    require_create_dep,
    require_delete_dep,
    require_read_dep,
    require_validate_dep,
    validate_tunnel_handler,
)
from services.tunnel_orchestrator.application.commands import (
    CreateTunnelCommand,
    CreateTunnelHandler,
    DeleteTunnelCommand,
    DeleteTunnelHandler,
    ValidateTunnelCommand,
    ValidateTunnelHandler,
)
from services.tunnel_orchestrator.application.commands.create_tunnel import (
    IngressRuleInput,
)
from services.tunnel_orchestrator.application.queries import (
    GetTunnelHandler,
    ListTunnelsHandler,
    TunnelView,
)
from services.tunnel_orchestrator.infrastructure.auth import JWTPrincipal
from shared.observability import current_correlation_id

router = APIRouter()


# ---------- request DTOs ----------


class IngressRuleDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")
    service: str = Field(min_length=1, examples=["http://my-svc.svc.cluster.local:8080"])
    hostname: str | None = None
    path: str | None = None
    origin_request: dict[str, str | bool] | None = None


class CreateTunnelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hostname: str = Field(min_length=3, examples=["api.svc.example.com"])
    cf_zone_id: str = Field(min_length=1)
    cluster: str = "default"
    ingress: list[IngressRuleDTO] = Field(min_length=1)


class CreateTunnelResponse(BaseModel):
    tunnel_id: UUID
    cf_tunnel_id: str | None
    status: str
    failed_step: str | None = None
    correlation_id: str | None = None


class DeleteTunnelResponse(BaseModel):
    tunnel_id: UUID
    status: str
    failed_step: str | None = None


class ValidateTunnelResponse(BaseModel):
    tunnel_id: UUID
    dns_ok: bool
    http_ok: bool
    latency_ms: float | None = None


# ---------- routes ----------


@router.post(
    "",
    response_model=CreateTunnelResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Provision a Cloudflare Tunnel",
)
async def create_tunnel(
    body: CreateTunnelRequest,
    principal: Annotated[JWTPrincipal, Depends(current_principal)],
    handler: Annotated[CreateTunnelHandler, Depends(create_tunnel_handler)],
    _perm = Depends(require_create_dep),                 # noqa: B008
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> CreateTunnelResponse:
    cmd = CreateTunnelCommand(
        tenant_id=principal.tenant_id,
        hostname=body.hostname,
        cf_zone_id=body.cf_zone_id,
        cluster=body.cluster,
        ingress=tuple(IngressRuleInput(**r.model_dump()) for r in body.ingress),
        requested_by=principal.sub,
        correlation_id=current_correlation_id(),
        idempotency_key=idempotency_key,
    )
    out = await handler.handle(cmd)
    return CreateTunnelResponse(
        tunnel_id=out.tunnel_id,
        cf_tunnel_id=out.cf_tunnel_id,
        status=out.status,
        failed_step=out.failed_step,
        correlation_id=out.correlation_id,
    )


@router.delete(
    "/{tunnel_id}",
    response_model=DeleteTunnelResponse,
    summary="Delete a Cloudflare Tunnel",
)
async def delete_tunnel(
    tunnel_id: Annotated[UUID, Path()],
    principal: Annotated[JWTPrincipal, Depends(current_principal)],
    handler: Annotated[DeleteTunnelHandler, Depends(delete_tunnel_handler)],
    _perm = Depends(require_delete_dep),                 # noqa: B008
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> DeleteTunnelResponse:
    cmd = DeleteTunnelCommand(
        tenant_id=principal.tenant_id,
        tunnel_id=tunnel_id,
        requested_by=principal.sub,
        correlation_id=current_correlation_id(),
        idempotency_key=idempotency_key,
    )
    out = await handler.handle(cmd)
    return DeleteTunnelResponse(
        tunnel_id=out.tunnel_id, status=out.status, failed_step=out.failed_step
    )


@router.get("/{tunnel_id}", response_model=TunnelView)
async def get_tunnel(
    tunnel_id: Annotated[UUID, Path()],
    principal: Annotated[JWTPrincipal, Depends(current_principal)],
    handler: Annotated[GetTunnelHandler, Depends(get_query)],
    _perm = Depends(require_read_dep),                   # noqa: B008
) -> TunnelView:
    from services.tunnel_orchestrator.application.queries import GetTunnelQuery

    return await handler.handle(GetTunnelQuery(principal.tenant_id, tunnel_id))


@router.get("", response_model=list[TunnelView])
async def list_tunnels(
    principal: Annotated[JWTPrincipal, Depends(current_principal)],
    handler: Annotated[ListTunnelsHandler, Depends(list_query)],
    _perm = Depends(require_read_dep),                   # noqa: B008
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    cursor: UUID | None = None,
) -> list[TunnelView]:
    from services.tunnel_orchestrator.application.queries import ListTunnelsQuery

    return await handler.handle(ListTunnelsQuery(principal.tenant_id, limit, cursor))


@router.post(
    "/{tunnel_id}/validate",
    response_model=ValidateTunnelResponse,
    summary="Re-run DNS + HTTP validation",
)
async def validate_tunnel(
    tunnel_id: Annotated[UUID, Path()],
    principal: Annotated[JWTPrincipal, Depends(current_principal)],
    handler: Annotated[ValidateTunnelHandler, Depends(validate_tunnel_handler)],
    background: BackgroundTasks,
    _perm = Depends(require_validate_dep),               # noqa: B008
) -> ValidateTunnelResponse:
    cmd = ValidateTunnelCommand(
        tenant_id=principal.tenant_id,
        tunnel_id=tunnel_id,
        correlation_id=current_correlation_id(),
    )
    out = await handler.handle(cmd)
    return ValidateTunnelResponse(
        tunnel_id=out.tunnel_id,
        dns_ok=out.dns_ok,
        http_ok=out.http_ok,
        latency_ms=out.latency_ms,
    )
