"""Generic Kafka message envelope.

Every Kafka payload conforms to this envelope. The business payload is
nested under :pyattr:`EventEnvelope.payload`. The envelope itself
carries cross-cutting concerns (trace context, correlation id,
idempotency key, schema id…) so consumers can route, filter and audit
without parsing the body.

The envelope is **transport** concern — domain events stay free of any
of these fields.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from shared.types import (
    CorrelationId,
    EventId,
    IdempotencyKey,
    new_correlation_id,
    new_event_id,
    utcnow,
)

PayloadT = TypeVar("PayloadT", bound=BaseModel)


class TraceContext(BaseModel):
    """W3C trace context fields propagated through Kafka headers."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    traceparent: str | None = None
    tracestate: str | None = None
    baggage: str | None = None


class EventEnvelope(BaseModel, Generic[PayloadT]):
    """Strongly-typed envelope wrapping any business payload."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    schema_id: int | None = None                       # Confluent SR id (set by producer)
    event_id: EventId = Field(default_factory=new_event_id)
    event_type: str
    event_version: int = 1
    occurred_at: datetime = Field(default_factory=utcnow)
    producer: str
    correlation_id: CorrelationId = Field(default_factory=new_correlation_id)
    causation_id: str | None = None
    tenant_id: UUID
    idempotency_key: IdempotencyKey | None = None
    trace_context: TraceContext = Field(default_factory=TraceContext)
    payload: PayloadT


def build_envelope(
    *,
    payload: PayloadT,
    event_type: str,
    tenant_id: UUID,
    producer: str,
    event_version: int = 1,
    correlation_id: CorrelationId | str | None = None,
    causation_id: str | None = None,
    idempotency_key: str | None = None,
    trace_context: TraceContext | None = None,
) -> EventEnvelope[PayloadT]:
    """Helper that fills sensible defaults and forwards correlation."""
    return EventEnvelope[PayloadT](
        event_type=event_type,
        event_version=event_version,
        producer=producer,
        tenant_id=tenant_id,
        correlation_id=CorrelationId(str(correlation_id)) if correlation_id else new_correlation_id(),
        causation_id=causation_id,
        idempotency_key=IdempotencyKey(idempotency_key) if idempotency_key else None,
        trace_context=trace_context or TraceContext(),
        payload=payload,
    )


def envelope_to_dict(env: EventEnvelope[Any]) -> dict[str, Any]:
    """Serialise to a JSON-compatible dict (camel/snake stable)."""
    return env.model_dump(mode="json")
