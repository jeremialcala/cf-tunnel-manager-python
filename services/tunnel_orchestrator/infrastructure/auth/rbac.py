"""RBAC: simple permission strings + dependency factory."""

from __future__ import annotations

from enum import StrEnum
from typing import Callable

from services.tunnel_orchestrator.infrastructure.auth.jwt import JWTPrincipal


class Permission(StrEnum):
    TUNNEL_CREATE = "tunnel:create"
    TUNNEL_DELETE = "tunnel:delete"
    TUNNEL_UPDATE = "tunnel:update"
    TUNNEL_READ   = "tunnel:read"
    TUNNEL_VALIDATE = "tunnel:validate"
    TENANT_ADMIN  = "tenant:admin"
    PLATFORM_ADMIN = "platform:admin"


class RBACPolicy:
    """Default policy: ``platform:admin`` is a super-permission."""

    SUPER = Permission.PLATFORM_ADMIN.value

    @classmethod
    def has(cls, principal: JWTPrincipal, perm: Permission | str) -> bool:
        if cls.SUPER in principal.permissions:
            return True
        return str(perm) in principal.permissions


def require_permission(
    perm: Permission,
) -> Callable[[JWTPrincipal], JWTPrincipal]:
    """FastAPI dependency factory.

    Returns a callable that raises an :class:`AuthError` if the
    principal lacks the permission, otherwise echoes the principal
    back.
    """
    def _check(principal: JWTPrincipal) -> JWTPrincipal:
        from services.tunnel_orchestrator.infrastructure.auth.jwt import AuthError
        if not RBACPolicy.has(principal, perm):
            raise AuthError(
                f"missing permission {perm.value!r}",
                context={"required": perm.value, "have": list(principal.permissions)},
            )
        return principal
    _check.__name__ = f"require_{perm.value.replace(':', '_')}"
    return _check
