"""Kafka header utilities.

We mirror the most important envelope fields into Kafka headers so:

* consumers can filter / route without deserialising the payload;
* DLQ tooling and observability backends keep the IDs even if the body
  gets re-encoded;
* OpenTelemetry can extract the W3C trace context from headers using
  the standard ``traceparent`` / ``tracestate`` keys.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from cloud_platform.events.envelope import EventEnvelope


HeaderTuple = tuple[str, bytes]


@dataclass(frozen=True, slots=True)
class EventHeaders:
    event_id: str
    event_type: str
    event_version: str
    correlation_id: str
    causation_id: str | None
    tenant_id: str
    idempotency_key: str | None
    producer: str
    traceparent: str | None
    tracestate: str | None
    schema_id: str | None

    def to_list(self) -> list[HeaderTuple]:
        out: list[HeaderTuple] = [
            ("event_id", self.event_id.encode()),
            ("event_type", self.event_type.encode()),
            ("event_version", self.event_version.encode()),
            ("correlation_id", self.correlation_id.encode()),
            ("tenant_id", self.tenant_id.encode()),
            ("producer", self.producer.encode()),
        ]
        if self.causation_id:
            out.append(("causation_id", self.causation_id.encode()))
        if self.idempotency_key:
            out.append(("idempotency_key", self.idempotency_key.encode()))
        if self.traceparent:
            out.append(("traceparent", self.traceparent.encode()))
        if self.tracestate:
            out.append(("tracestate", self.tracestate.encode()))
        if self.schema_id:
            out.append(("schema_id", self.schema_id.encode()))
        return out

    @classmethod
    def from_list(cls, headers: Sequence[HeaderTuple] | None) -> "EventHeaders":
        h = {k: v.decode() for k, v in (headers or [])}
        return cls(
            event_id=h.get("event_id", ""),
            event_type=h.get("event_type", ""),
            event_version=h.get("event_version", "1"),
            correlation_id=h.get("correlation_id", ""),
            causation_id=h.get("causation_id"),
            tenant_id=h.get("tenant_id", ""),
            idempotency_key=h.get("idempotency_key"),
            producer=h.get("producer", "unknown"),
            traceparent=h.get("traceparent"),
            tracestate=h.get("tracestate"),
            schema_id=h.get("schema_id"),
        )


def headers_from_envelope(env: EventEnvelope[object]) -> EventHeaders:
    return EventHeaders(
        event_id=str(env.event_id),
        event_type=env.event_type,
        event_version=str(env.event_version),
        correlation_id=str(env.correlation_id),
        causation_id=env.causation_id,
        tenant_id=str(env.tenant_id),
        idempotency_key=str(env.idempotency_key) if env.idempotency_key else None,
        producer=env.producer,
        traceparent=env.trace_context.traceparent,
        tracestate=env.trace_context.tracestate,
        schema_id=str(env.schema_id) if env.schema_id is not None else None,
    )


def headers_to_dict(headers: Iterable[HeaderTuple] | None) -> dict[str, str]:
    return {k: v.decode() for k, v in (headers or [])}
