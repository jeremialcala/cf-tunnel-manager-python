"""JWT validator (RS256 / HS256) with JWKS-fetch caching.

Lightweight on purpose: real deployments will use OIDC + refresh; this
module verifies the shape and trust of the bearer token coming over
the wire and exposes the resulting principal.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import jwt as pyjwt
from jwt import PyJWKClient

from shared.config import get_settings
from shared.errors import AppError


class AuthError(AppError):
    code = "AUTH_ERROR"
    http_status = 401


@dataclass(frozen=True, slots=True)
class JWTPrincipal:
    sub: str
    tenant_id: UUID
    permissions: frozenset[str]
    email: str | None = None
    raw: dict[str, Any] | None = None


class JWTValidator:
    def __init__(
        self,
        *,
        jwks_url: str | None = None,
        public_key_path: Path | None = None,
        secret: str | None = None,
        algorithm: str | None = None,
    ) -> None:
        cfg = get_settings().jwt
        self._algorithm = algorithm or cfg.algorithm
        self._issuer = cfg.issuer
        self._audience = cfg.audience
        self._leeway = cfg.leeway_seconds
        self._jwks_url = jwks_url
        self._jwks_client: PyJWKClient | None = (
            PyJWKClient(jwks_url, cache_keys=True) if jwks_url else None
        )
        self._public_key: bytes | None = None
        self._secret: str | None = secret or (
            cfg.secret.get_secret_value() if cfg.secret else None
        )
        if public_key_path or cfg.public_key_path:
            path = public_key_path or cfg.public_key_path
            assert path is not None
            self._public_key = Path(path).read_bytes()

    async def validate(self, token: str) -> JWTPrincipal:
        try:
            key = await self._resolve_key(token)
            payload = pyjwt.decode(
                token,
                key=key,
                algorithms=[self._algorithm],
                audience=self._audience,
                issuer=self._issuer,
                leeway=self._leeway,
                options={"require": ["exp", "iat", "sub"]},
            )
        except pyjwt.PyJWTError as e:
            raise AuthError(f"invalid token: {e}", cause=e) from e

        try:
            tenant_id = UUID(str(payload["tenant_id"]))
        except KeyError as e:
            raise AuthError("token missing tenant_id claim") from e
        except ValueError as e:
            raise AuthError("token tenant_id claim is not a UUID") from e

        return JWTPrincipal(
            sub=str(payload["sub"]),
            tenant_id=tenant_id,
            permissions=frozenset(payload.get("permissions") or []),
            email=payload.get("email"),
            raw=payload,
        )

    async def _resolve_key(self, token: str) -> Any:
        if self._jwks_client:
            return self._jwks_client.get_signing_key_from_jwt(token).key
        if self._public_key:
            return self._public_key
        if self._secret:
            return self._secret
        raise AuthError("no key configured for JWT validation")
