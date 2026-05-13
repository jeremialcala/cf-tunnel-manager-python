from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from services.tunnel_orchestrator.application.sagas.base import (
    SagaInstanceStore,
    SagaStatus,
    StepResult,
)
from services.tunnel_orchestrator.infrastructure.persistence.database import Database
from services.tunnel_orchestrator.infrastructure.persistence.models import (
    SagaInstanceRow,
    SagaStepRow,
)


class PgSagaInstanceStore(SagaInstanceStore):
    """Persists saga + step state across restarts.

    Each method opens its own short transaction so it's safe to call
    from inside the orchestrator without entangling the saga's outer
    UnitOfWork (which already covers domain mutations).
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    async def begin(
        self,
        *,
        saga_id: UUID,
        type: str,
        tenant_id: UUID,
        context: dict[str, Any],
    ) -> None:
        async with self._db.session_factory() as session:
            session.add(
                SagaInstanceRow(
                    id=saga_id,
                    type=type,
                    tenant_id=tenant_id,
                    correlation_id=str(context.get("correlation_id") or ""),
                    status=SagaStatus.PENDING.value,
                    context=context,
                )
            )
            await session.commit()

    async def transition(self, saga_id: UUID, status: SagaStatus) -> None:
        async with self._db.session_factory() as session:
            await session.execute(
                update(SagaInstanceRow)
                .where(SagaInstanceRow.id == saga_id)
                .values(status=status.value)
            )
            await session.commit()

    async def record_step(self, saga_id: UUID, step: StepResult) -> None:
        async with self._db.session_factory() as session:
            session.add(
                SagaStepRow(
                    id=uuid4(),
                    saga_id=saga_id,
                    name=step.name,
                    status=step.status.value,
                    attempts=step.attempts,
                    output=_jsonable(step.output),
                    error=step.error,
                    duration_seconds=step.duration_seconds,
                )
            )
            await session.commit()


def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool, list, dict)):
        return value
    return str(value)
