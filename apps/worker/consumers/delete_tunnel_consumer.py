from __future__ import annotations

from typing import Any

from apps.composition import Container
from platform.events.envelope import EventEnvelope
from platform.events.payloads import TunnelDeleteRequestPayload
from services.tunnel_orchestrator.application.commands import DeleteTunnelCommand
from shared.errors import ValidationError
from shared.logging import get_logger

log = get_logger(__name__)


def handler_factory(c: Container):  # noqa: ANN201
    handler = c.delete_handler

    async def handle(envelope: EventEnvelope[Any]) -> None:
        if not isinstance(envelope.payload, TunnelDeleteRequestPayload):
            raise ValidationError(f"Unexpected payload type: {type(envelope.payload)}")
        p = envelope.payload
        cmd = DeleteTunnelCommand(
            tenant_id=p.tenant_id,
            tunnel_id=p.tunnel_id,
            requested_by=p.requested_by,
            correlation_id=str(envelope.correlation_id),
            idempotency_key=str(envelope.idempotency_key) if envelope.idempotency_key else None,
        )
        outcome = await handler.handle(cmd)
        log.info(
            "consumer.delete.handled",
            tunnel_id=str(outcome.tunnel_id), status=outcome.status,
        )

    return handle
