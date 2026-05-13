"""FastAPI dependencies — typed accessors over the composition container."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request

from apps.composition import Container
from services.tunnel_orchestrator.application.commands import (
    CreateTunnelHandler,
    DeleteTunnelHandler,
    ValidateTunnelHandler,
)
from services.tunnel_orchestrator.application.queries import (
    GetTunnelHandler,
    ListTunnelsHandler,
)
from services.tunnel_orchestrator.infrastructure.auth import (
    JWTPrincipal,
    JWTValidator,
    Permission,
    require_permission,
)


def get_container(request: Request) -> Container:
    return request.app.state.container


def get_jwt_validator(c: Container = Depends(get_container)) -> JWTValidator:
    # Lazy single instance per app; rebuild here to keep stateless.
    if not hasattr(c, "_jwt"):
        c._jwt = JWTValidator()        # type: ignore[attr-defined]
    return c._jwt                      # type: ignore[attr-defined]


async def current_principal(
    authorization: Annotated[str | None, Header()] = None,
    validator: JWTValidator = Depends(get_jwt_validator),
) -> JWTPrincipal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    return await validator.validate(token)


# ---- handler dependencies ----


def create_tunnel_handler(c: Container = Depends(get_container)) -> CreateTunnelHandler:
    return c.create_handler


def delete_tunnel_handler(c: Container = Depends(get_container)) -> DeleteTunnelHandler:
    return c.delete_handler


def validate_tunnel_handler(c: Container = Depends(get_container)) -> ValidateTunnelHandler:
    return c.validate_handler


def get_query(c: Container = Depends(get_container)) -> GetTunnelHandler:
    return c.get_query


def list_query(c: Container = Depends(get_container)) -> ListTunnelsHandler:
    return c.list_query


# ---- permission helpers ----


def require_create() -> Permission:
    return Permission.TUNNEL_CREATE


# Pre-built permission dependencies for ergonomics.
require_create_dep = require_permission(Permission.TUNNEL_CREATE)
require_delete_dep = require_permission(Permission.TUNNEL_DELETE)
require_read_dep = require_permission(Permission.TUNNEL_READ)
require_validate_dep = require_permission(Permission.TUNNEL_VALIDATE)
require_admin_dep = require_permission(Permission.TENANT_ADMIN)
