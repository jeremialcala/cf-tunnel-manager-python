"""Reconciliation: re-validates a tenant's tunnels and emits drift events.

Driven by ``tunnel.reconcile.request`` produced by the scheduler.
Implementation is intentionally minimal: it re-runs validation per
tunnel; richer drift detection (Cloudflare-side mutation) is a
follow-up.
"""

from __future__ import annotations

from typing import Any

from apps.composition import Container
from cloud_platform.events.envelope import EventEnvelope
from cloud_platform.events.payloads import TunnelReconcileRequestPayload
from services.tunnel_orchestrator.application.commands import ValidateTunnelCommand
from services.tunnel_orchestrator.domain.value_objects import TenantIdVO, TunnelIdVO
from services.tunnel_orchestrator.infrastructure.persistence import PgTunnelRepository
from shared.errors import ValidationError
from shared.logging import get_logger

log = get_logger(__name__)


def handler_factory(c: Container):  # noqa: ANN201
    validate_handler = c.validate_handler

    async def handle(envelope: EventEnvelope[Any]) -> None:
        if not isinstance(envelope.payload, TunnelReconcileRequestPayload):
            raise ValidationError(f"Unexpected payload type: {type(envelope.payload)}")
        p = envelope.payload

        ids: list[TunnelIdVO] = []
        if p.tunnel_id:
            ids = [TunnelIdVO(p.tunnel_id)]
        else:
            async with c.db.session_factory() as session:
                tunnels = await PgTunnelRepository(session).list_by_tenant(
                    TenantIdVO(p.tenant_id), limit=500
                )
                ids = [t.id for t in tunnels]

        for tid in ids:
            await validate_handler.handle(
                ValidateTunnelCommand(
                    tenant_id=p.tenant_id,
                    tunnel_id=tid.value,
                    correlation_id=str(envelope.correlation_id),
                )
            )

        log.info("consumer.reconcile.handled", tenant_id=str(p.tenant_id), count=len(ids))

    return handle
