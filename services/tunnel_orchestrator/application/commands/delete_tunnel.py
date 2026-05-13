"""Use case: delete a tunnel.

Same shape as create: idempotency → lock → delete-saga → publish.
Compensation is naturally absent because every delete step is itself a
cleanup; failures surface to the caller and the saga can be re-run.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from platform.events.envelope import build_envelope
from platform.events.payloads import (
    TunnelDeleteFailurePayload,
    TunnelDeleteSuccessPayload,
)
from platform.events.topics import Topic
from shared.config import get_settings
from shared.errors import (
    Conflict,
    LockAcquisitionFailed,
    TunnelNotFound,
    ValidationError,
)
from shared.logging import get_logger
from shared.types import utcnow
from services.tunnel_orchestrator.application.idempotency import (
    IdempotencyOutcome,
    IdempotencyService,
)
from services.tunnel_orchestrator.application.ports import (
    AuditLogger,
    EventPublisher,
    LockManager,
)
from services.tunnel_orchestrator.application.sagas import SagaStatus
from services.tunnel_orchestrator.application.sagas.base import SagaContext, new_saga_id
from services.tunnel_orchestrator.application.sagas.context import DeleteTunnelSagaData
from services.tunnel_orchestrator.application.sagas.delete_tunnel_saga import (
    DeleteTunnelSaga,
    DeleteTunnelSagaDeps,
)
from services.tunnel_orchestrator.domain.repositories import TunnelRepository
from services.tunnel_orchestrator.domain.services import TunnelLifecycleService
from services.tunnel_orchestrator.domain.value_objects import TenantIdVO, TunnelIdVO

log = get_logger(__name__)


class DeleteTunnelCommand(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    tenant_id: UUID
    tunnel_id: UUID
    requested_by: str | None = None
    correlation_id: str | None = None
    idempotency_key: str | None = None


@dataclass(frozen=True, slots=True)
class DeleteTunnelOutcome:
    tunnel_id: UUID
    status: str                    # "DELETED" | "FAILED" | "REPLAY"
    failed_step: str | None = None
    duration_seconds: float = 0.0
    correlation_id: str | None = None


class DeleteTunnelHandler:
    PRODUCER = "tunnel-orchestrator/delete-handler"

    def __init__(
        self,
        *,
        tunnels: TunnelRepository,
        lock_manager: LockManager,
        idempotency: IdempotencyService,
        publisher: EventPublisher,
        saga_deps: DeleteTunnelSagaDeps,
        audit: AuditLogger,
    ) -> None:
        self._tunnels = tunnels
        self._lock = lock_manager
        self._idem = idempotency
        self._publisher = publisher
        self._saga_factory = DeleteTunnelSaga(saga_deps)
        self._audit = audit

    async def handle(self, cmd: DeleteTunnelCommand) -> DeleteTunnelOutcome:
        started = time.monotonic()
        tunnel_vo = TunnelIdVO(cmd.tunnel_id)
        tenant_vo = TenantIdVO(cmd.tenant_id)
        idempotency_key = cmd.idempotency_key or self._idem.make_key(
            cmd.tenant_id, "delete-tunnel", str(cmd.tunnel_id)
        )

        outcome, cached = await self._idem.begin(
            key=idempotency_key,
            tenant_id=cmd.tenant_id,
            request=cmd.model_dump(mode="json"),
        )
        if outcome is IdempotencyOutcome.REPLAY and cached:
            return DeleteTunnelOutcome(
                tunnel_id=cmd.tunnel_id,
                status="REPLAY",
                correlation_id=cached.get("correlation_id"),
            )

        tunnel = await self._tunnels.get(tunnel_vo)
        if tunnel is None or tunnel.tenant_id != tenant_vo:
            raise TunnelNotFound(f"Tunnel {cmd.tunnel_id} not found")
        if not TunnelLifecycleService.is_safe_to_delete(tunnel):
            raise ValidationError(
                f"Tunnel cannot be deleted in status {tunnel.status.value}",
                context={"status": tunnel.status.value},
            )

        ctx = SagaContext[DeleteTunnelSagaData](
            saga_id=new_saga_id(),
            correlation_id=cmd.correlation_id or "",
            tenant_id=cmd.tenant_id,
            started_at=time.monotonic(),
            data=DeleteTunnelSagaData(tunnel=tunnel, cf_zone_id=tunnel.cf_zone_id),
        )

        try:
            async with self._lock.lock(
                f"delete_tunnel:{tenant_vo}:{tunnel.hostname}",
                ttl_seconds=int(get_settings().resilience.saga_global_timeout_seconds),
            ):
                result = await self._saga_factory.build().run(ctx)
        except LockAcquisitionFailed as e:
            raise Conflict("Another saga in progress for this tunnel") from e

        if result.status is SagaStatus.SUCCEEDED:
            tunnel.mark_deleted()
            await self._tunnels.save(tunnel)
            await self._publisher.publish(
                Topic.DELETE_SUCCESS,
                build_envelope(
                    payload=TunnelDeleteSuccessPayload(
                        tenant_id=tunnel.tenant_id.value,
                        tunnel_id=tunnel.id.value,
                        cf_tunnel_id=tunnel.cf_tunnel_id or "unknown",
                        deleted_at=utcnow(),
                    ),
                    event_type="tunnel.delete.success.v1",
                    tenant_id=tunnel.tenant_id.value,
                    producer=self.PRODUCER,
                    correlation_id=ctx.correlation_id,
                ),
                key=str(tunnel.id.value),
            )
            await self._audit.record(
                actor=cmd.requested_by or "system",
                tenant_id=cmd.tenant_id,
                action="tunnel.delete",
                resource=f"tunnel/{tunnel.id.value}",
                outcome="SUCCESS",
                correlation_id=ctx.correlation_id,
            )
            outcome_str, failed_step = "DELETED", None
        else:
            failed_step = result.failed_step
            err = result.error
            await self._publisher.publish(
                Topic.DELETE_FAILURE,
                build_envelope(
                    payload=TunnelDeleteFailurePayload(
                        tenant_id=tunnel.tenant_id.value,
                        tunnel_id=tunnel.id.value,
                        cf_tunnel_id=tunnel.cf_tunnel_id,
                        failed_step=failed_step or "<unknown>",
                        error_code=getattr(err, "code", "DELETE_FAILED"),
                        error_message=getattr(err, "message", str(err)),
                        failed_at=utcnow(),
                    ),
                    event_type="tunnel.delete.failure.v1",
                    tenant_id=tunnel.tenant_id.value,
                    producer=self.PRODUCER,
                    correlation_id=ctx.correlation_id,
                ),
                key=str(tunnel.id.value),
            )
            outcome_str = "FAILED"

        await self._idem.complete(
            key=idempotency_key,
            response={
                "tunnel_id": str(tunnel.id.value),
                "status": outcome_str,
                "correlation_id": ctx.correlation_id,
            },
        )
        return DeleteTunnelOutcome(
            tunnel_id=tunnel.id.value,
            status=outcome_str,
            failed_step=failed_step,
            duration_seconds=time.monotonic() - started,
            correlation_id=ctx.correlation_id,
        )
