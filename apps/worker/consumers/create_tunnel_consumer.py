"""Adapter consumer: maps Kafka envelope → application command."""

from __future__ import annotations

from typing import Any

from apps.composition import Container
from cloud_platform.events.envelope import EventEnvelope
from cloud_platform.events.payloads import TunnelCreateRequestPayload
from services.tunnel_orchestrator.application.commands import (
    CreateTunnelCommand,
)
from services.tunnel_orchestrator.application.commands.create_tunnel import (
    IngressRuleInput,
)
from shared.errors import ValidationError
from shared.logging import get_logger

log = get_logger(__name__)


def handler_factory(c: Container):  # noqa: ANN201
    handler = c.create_handler

    async def handle(envelope: EventEnvelope[Any]) -> None:
        if not isinstance(envelope.payload, TunnelCreateRequestPayload):
            raise ValidationError(f"Unexpected payload type: {type(envelope.payload)}")
        p = envelope.payload
        cmd = CreateTunnelCommand(
            tenant_id=p.tenant_id,
            hostname=p.hostname,
            cf_zone_id=p.cf_zone_id,
            cluster=p.cluster,
            ingress=tuple(
                IngressRuleInput(
                    service=r.service,
                    hostname=r.hostname,
                    path=r.path,
                    origin_request=r.origin_request,
                )
                for r in p.ingress
            ),
            requested_by=p.requested_by,
            correlation_id=str(envelope.correlation_id),
            idempotency_key=str(envelope.idempotency_key) if envelope.idempotency_key else None,
        )
        outcome = await handler.handle(cmd)
        log.info(
            "consumer.create.handled",
            tunnel_id=str(outcome.tunnel_id),
            status=outcome.status,
            failed_step=outcome.failed_step,
        )

    return handle
