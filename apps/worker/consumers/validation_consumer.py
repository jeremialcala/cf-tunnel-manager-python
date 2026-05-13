from __future__ import annotations

from typing import Any

from apps.composition import Container
from platform.events.envelope import EventEnvelope
from platform.events.payloads import TunnelValidationRequestPayload
from services.tunnel_orchestrator.application.commands import ValidateTunnelCommand
from shared.errors import ValidationError
from shared.logging import get_logger

log = get_logger(__name__)


def handler_factory(c: Container):  # noqa: ANN201
    handler = c.validate_handler

    async def handle(envelope: EventEnvelope[Any]) -> None:
        if not isinstance(envelope.payload, TunnelValidationRequestPayload):
            raise ValidationError(f"Unexpected payload type: {type(envelope.payload)}")
        p = envelope.payload
        outcome = await handler.handle(
            ValidateTunnelCommand(
                tenant_id=p.tenant_id,
                tunnel_id=p.tunnel_id,
                correlation_id=str(envelope.correlation_id),
            )
        )
        log.info(
            "consumer.validate.handled",
            tunnel_id=str(outcome.tunnel_id),
            dns_ok=outcome.dns_ok, http_ok=outcome.http_ok,
        )

    return handle
