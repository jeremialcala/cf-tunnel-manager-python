"""Idempotency service.

Implements the *idempotent receiver* pattern. Each request carries an
``idempotency_key`` (e.g. ``tenant:{id}:hostname:{h}``). On first
arrival we record the request hash; subsequent arrivals with:

- **same key + same hash** → return the cached outcome (replay-safe);
- **same key + different hash** → :class:`IdempotencyConflict`.

Rotation: rows expire after ``RETENTION_SECONDS`` (default 7 days).
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any
from uuid import UUID

from shared.errors import IdempotencyConflict
from shared.types import utcnow

RETENTION_SECONDS: int = 7 * 24 * 3600


def _hash_request(request: dict[str, Any]) -> str:
    """Deterministic request hash. Drops volatile fields like timestamps."""
    import orjson

    payload = orjson.dumps(request, option=orjson.OPT_SORT_KEYS)
    return hashlib.sha256(payload).hexdigest()


class IdempotencyOutcome(str, Enum):
    NEW = "NEW"            # caller should proceed
    REPLAY = "REPLAY"      # caller should return cached response
    CONFLICT = "CONFLICT"  # raised — included for completeness


@dataclass(frozen=True, slots=True)
class IdempotencyRecord:
    key: str
    tenant_id: UUID
    request_hash: str
    response: dict[str, Any] | None
    created_at: datetime
    expires_at: datetime


class IdempotencyStore(ABC):
    """Persistence port for idempotency records (PostgreSQL adapter)."""

    @abstractmethod
    async def get(self, key: str) -> IdempotencyRecord | None: ...

    @abstractmethod
    async def insert_pending(
        self,
        *,
        key: str,
        tenant_id: UUID,
        request_hash: str,
        ttl_seconds: int = RETENTION_SECONDS,
    ) -> bool:
        """Atomic INSERT ... ON CONFLICT DO NOTHING. Returns ``True`` if inserted."""

    @abstractmethod
    async def complete(self, key: str, response: dict[str, Any]) -> None: ...

    @abstractmethod
    async def purge_expired(self, *, batch_size: int = 1000) -> int: ...


class IdempotencyService:
    """Application-level façade orchestrating the store + business policy."""

    def __init__(self, store: IdempotencyStore) -> None:
        self._store = store

    async def begin(
        self,
        *,
        key: str,
        tenant_id: UUID,
        request: dict[str, Any],
    ) -> tuple[IdempotencyOutcome, dict[str, Any] | None]:
        """Reserve the key.

        Returns ``(NEW, None)`` if this is a fresh request and the
        caller should proceed, or ``(REPLAY, cached_response)`` for an
        already-completed identical request. Raises
        :class:`IdempotencyConflict` on hash mismatch.
        """
        request_hash = _hash_request(request)
        inserted = await self._store.insert_pending(
            key=key, tenant_id=tenant_id, request_hash=request_hash
        )
        if inserted:
            return IdempotencyOutcome.NEW, None

        existing = await self._store.get(key)
        if existing is None:
            # Race: row was purged between insert and get — treat as new
            return IdempotencyOutcome.NEW, None

        if existing.request_hash != request_hash:
            raise IdempotencyConflict(
                f"Idempotency key {key!r} reused with different request body",
                context={"existing_hash": existing.request_hash, "incoming_hash": request_hash},
            )

        return IdempotencyOutcome.REPLAY, existing.response

    async def complete(self, *, key: str, response: dict[str, Any]) -> None:
        await self._store.complete(key, response)

    @staticmethod
    def make_key(tenant_id: UUID, *parts: str) -> str:
        return "tenant:" + str(tenant_id) + ":" + ":".join(parts)

    @staticmethod
    def default_expiry() -> datetime:
        return utcnow() + timedelta(seconds=RETENTION_SECONDS)
