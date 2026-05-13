"""OpenTelemetry tracing setup.

Bootstraps an OTLP exporter (gRPC by default) and instruments the
libraries we use heavily. Call :pyfunc:`configure_tracing` once at
process startup; call :pyfunc:`instrument_app` after the FastAPI ``app``
is created to enable HTTP server instrumentation.
"""

from __future__ import annotations

from typing import Any

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import (
    ALWAYS_OFF,
    ALWAYS_ON,
    ParentBased,
    TraceIdRatioBased,
)

from shared.config import get_settings

_TRACER: trace.Tracer | None = None
_INITIALISED = False


def _build_sampler(name: str, arg: float) -> Any:
    name = name.lower()
    if name in {"always_on", "alwayson"}:
        return ALWAYS_ON
    if name in {"always_off", "alwaysoff"}:
        return ALWAYS_OFF
    if name == "traceidratio":
        return TraceIdRatioBased(arg)
    return ParentBased(root=TraceIdRatioBased(arg))


def configure_tracing() -> trace.Tracer:
    """Idempotent setup of the global ``TracerProvider``."""
    global _TRACER, _INITIALISED
    if _INITIALISED:
        assert _TRACER is not None
        return _TRACER

    settings = get_settings()
    resource_attrs = {SERVICE_NAME: settings.observability.service_name}
    for kv in settings.observability.resource_attributes.split(","):
        if "=" in kv:
            k, v = kv.split("=", 1)
            resource_attrs[k.strip()] = v.strip()
    resource_attrs["deployment.environment"] = settings.env.value

    provider = TracerProvider(
        resource=Resource.create(resource_attrs),
        sampler=_build_sampler(
            settings.observability.traces_sampler,
            settings.observability.traces_sampler_arg,
        ),
    )
    exporter = OTLPSpanExporter(endpoint=settings.observability.otlp_endpoint, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    _TRACER = trace.get_tracer(settings.observability.service_name)
    _INITIALISED = True
    return _TRACER


def get_tracer() -> trace.Tracer:
    return _TRACER or configure_tracing()


def instrument_app(app: Any) -> None:
    """Wire OTel auto-instrumentation onto a FastAPI app + common clients."""
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.instrumentation.redis import RedisInstrumentor

    configure_tracing()
    FastAPIInstrumentor.instrument_app(app, excluded_urls="/health/.*,/metrics")
    HTTPXClientInstrumentor().instrument()
    RedisInstrumentor().instrument()

    try:  # SQLAlchemy is optional in worker
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        SQLAlchemyInstrumentor().instrument()
    except Exception:  # pragma: no cover
        pass
