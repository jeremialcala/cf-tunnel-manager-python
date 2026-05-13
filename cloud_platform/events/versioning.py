"""Event-type → payload model registry and parser.

Lets the worker route an opaque envelope to the right strongly-typed
model based on ``event_type``. Adding a new event = adding a row to
:pyattr:`EVENT_TYPE_TO_PAYLOAD`.
"""

from __future__ import annotations

from typing import Any, Mapping, Type

from pydantic import BaseModel

from platform.events.envelope import EventEnvelope
from platform.events.payloads import (
    TunnelCreateFailurePayload,
    TunnelCreateRequestPayload,
    TunnelCreateSuccessPayload,
    TunnelDeleteFailurePayload,
    TunnelDeleteRequestPayload,
    TunnelDeleteSuccessPayload,
    TunnelDlqPayload,
    TunnelReconcileRequestPayload,
    TunnelUpdateRequestPayload,
    TunnelValidationFailurePayload,
    TunnelValidationRequestPayload,
    TunnelValidationSuccessPayload,
)
from shared.errors import ValidationError


EVENT_TYPE_TO_PAYLOAD: Mapping[str, Type[BaseModel]] = {
    "tunnel.create.request.v1":     TunnelCreateRequestPayload,
    "tunnel.create.success.v1":     TunnelCreateSuccessPayload,
    "tunnel.create.failure.v1":     TunnelCreateFailurePayload,
    "tunnel.delete.request.v1":     TunnelDeleteRequestPayload,
    "tunnel.delete.success.v1":     TunnelDeleteSuccessPayload,
    "tunnel.delete.failure.v1":     TunnelDeleteFailurePayload,
    "tunnel.update.request.v1":     TunnelUpdateRequestPayload,
    "tunnel.validation.request.v1": TunnelValidationRequestPayload,
    "tunnel.validation.success.v1": TunnelValidationSuccessPayload,
    "tunnel.validation.failure.v1": TunnelValidationFailurePayload,
    "tunnel.reconcile.request.v1":  TunnelReconcileRequestPayload,
    "tunnel.dlq.v1":                TunnelDlqPayload,
}


def parse_event(raw: Mapping[str, Any]) -> EventEnvelope[BaseModel]:
    """Parse a deserialised dict into a typed :class:`EventEnvelope`."""
    event_type = raw.get("event_type")
    if not event_type:
        raise ValidationError("envelope missing 'event_type'")
    payload_model = EVENT_TYPE_TO_PAYLOAD.get(event_type)
    if payload_model is None:
        raise ValidationError(f"Unknown event_type {event_type!r}")
    payload = payload_model.model_validate(raw["payload"])
    raw_no_payload = {k: v for k, v in raw.items() if k != "payload"}
    return EventEnvelope[payload_model].model_validate({**raw_no_payload, "payload": payload})  # type: ignore[valid-type]
