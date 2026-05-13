from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from services.tunnel_orchestrator.application.ports import AuditLogger
from services.tunnel_orchestrator.infrastructure.persistence.database import Database
from services.tunnel_orchestrator.infrastructure.persistence.models import AuditRow


class PgAuditLogger(AuditLogger):
    def __init__(self, db: Database) -> None:
        self._db = db

    async def record(
        self,
        *,
        actor: str,
        tenant_id: UUID,
        action: str,
        resource: str,
        outcome: str,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        correlation_id: str | None = None,
        ts: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        async with self._db.session_factory() as session:
            session.add(
                AuditRow(
                    actor=actor,
                    tenant_id=tenant_id,
                    action=action,
                    resource=resource,
                    outcome=outcome,
                    correlation_id=correlation_id,
                    before=before,
                    after=after,
                    extra_metadata=metadata or {},
                    **({"ts": ts} if ts else {}),
                )
            )
            await session.commit()
