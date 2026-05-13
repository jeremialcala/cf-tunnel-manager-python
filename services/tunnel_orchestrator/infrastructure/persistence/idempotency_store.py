from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from shared.types import utcnow
from services.tunnel_orchestrator.application.idempotency import (
    IdempotencyRecord,
    IdempotencyStore,
)
from services.tunnel_orchestrator.infrastructure.persistence.database import Database
from services.tunnel_orchestrator.infrastructure.persistence.models import IdempotencyRow


class PgIdempotencyStore(IdempotencyStore):
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self, key: str) -> IdempotencyRecord | None:
        async with self._db.session_factory() as session:
            row = (
                await session.execute(
                    select(IdempotencyRow).where(IdempotencyRow.key == key)
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            return IdempotencyRecord(
                key=row.key,
                tenant_id=row.tenant_id,
                request_hash=row.request_hash,
                response=row.response,
                created_at=row.created_at,
                expires_at=row.expires_at,
            )

    async def insert_pending(
        self,
        *,
        key: str,
        tenant_id: UUID,
        request_hash: str,
        ttl_seconds: int = 7 * 24 * 3600,
    ) -> bool:
        expires_at = utcnow() + timedelta(seconds=ttl_seconds)
        stmt = (
            pg_insert(IdempotencyRow)
            .values(
                key=key,
                tenant_id=tenant_id,
                request_hash=request_hash,
                response=None,
                expires_at=expires_at,
            )
            .on_conflict_do_nothing(index_elements=["key"])
            .returning(IdempotencyRow.key)
        )
        async with self._db.session_factory() as session:
            inserted = (await session.execute(stmt)).scalar_one_or_none()
            await session.commit()
            return inserted is not None

    async def complete(self, key: str, response: dict[str, Any]) -> None:
        async with self._db.session_factory() as session:
            await session.execute(
                update(IdempotencyRow)
                .where(IdempotencyRow.key == key)
                .values(response=response)
            )
            await session.commit()

    async def purge_expired(self, *, batch_size: int = 1000) -> int:
        async with self._db.session_factory() as session:
            stmt = (
                delete(IdempotencyRow)
                .where(IdempotencyRow.expires_at < utcnow())
                .returning(IdempotencyRow.key)
            )
            rows = (await session.execute(stmt)).all()
            await session.commit()
            return len(rows)
