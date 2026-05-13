"""Structured logging via ``structlog``.

Every log line is emitted as JSON in production with the following
**always-present** fields injected by :pyfunc:`configure_logging`:

* ``timestamp``        — ISO-8601 UTC
* ``level``            — uppercase
* ``logger``           — module name
* ``service.name``     — from ``OTEL_SERVICE_NAME``
* ``service.env``      — from ``APP_ENV``
* ``correlation_id``   — from contextvar (set by middleware / consumer)
* ``tenant_id``        — from contextvar (when applicable)
* ``trace_id`` / ``span_id`` — pulled from the active OTel span if any

Sensitive fields whose name matches the ``_SENSITIVE_KEYS`` regex are
redacted before serialisation.
"""

from __future__ import annotations

import logging
import re
import sys
from typing import Any

import structlog
from structlog.contextvars import merge_contextvars
from structlog.processors import (
    CallsiteParameter,
    CallsiteParameterAdder,
    JSONRenderer,
    StackInfoRenderer,
    TimeStamper,
    UnicodeDecoder,
    add_log_level,
    format_exc_info,
)

from shared.config import get_settings

_SENSITIVE_KEYS = re.compile(
    r"(?i)(token|secret|password|api[_-]?key|authorization|cookie|set[_-]?cookie)"
)
_REDACTED = "***REDACTED***"


def _redact(_logger: Any, _name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    for k in list(event_dict.keys()):
        if _SENSITIVE_KEYS.search(k):
            event_dict[k] = _REDACTED
    return event_dict


def _add_otel_context(_logger: Any, _name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        ctx = span.get_span_context() if span else None
        if ctx and ctx.is_valid:
            event_dict["trace_id"] = format(ctx.trace_id, "032x")
            event_dict["span_id"] = format(ctx.span_id, "016x")
    except Exception:  # pragma: no cover  — OTel optional at log time
        pass
    return event_dict


def _add_service_context(_logger: Any, _name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    event_dict.setdefault("service.name", settings.observability.service_name)
    event_dict.setdefault("service.env", settings.env.value)
    return event_dict


def configure_logging() -> None:
    """Idempotent global logging configuration.

    Should be invoked **once** in the process lifespan (api, worker, scheduler).
    """
    settings = get_settings()
    level_name = settings.log_level
    level = logging.getLevelName(level_name) if isinstance(level_name, str) else logging.INFO

    timestamper = TimeStamper(fmt="iso", utc=True, key="timestamp")

    shared_processors = [
        merge_contextvars,
        add_log_level,
        timestamper,
        _add_service_context,
        _add_otel_context,
        StackInfoRenderer(),
        format_exc_info,
        CallsiteParameterAdder(parameters={CallsiteParameter.MODULE, CallsiteParameter.LINENO}),
        UnicodeDecoder(),
        _redact,
    ]

    if settings.log_format.value == "json":
        renderer = JSONRenderer(serializer=_json_serializer)
        processors = [*shared_processors, renderer]
    else:
        processors = [*shared_processors, structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    # Bridge stdlib logging → structlog so dependencies (sqlalchemy, aiokafka,
    # uvicorn) all flow through the same pipeline.
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level, force=True)
    for noisy in ("aiokafka", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(max(level, logging.INFO))


def _json_serializer(payload: Any, **_: Any) -> str:
    import orjson

    return orjson.dumps(payload, default=str).decode()


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a structured logger bound to ``name``.

    Lazy-initialises logging if the caller forgot to invoke
    :pyfunc:`configure_logging` (useful in scripts and tests).
    """
    if not structlog.is_configured():
        configure_logging()
    return structlog.get_logger(name) if name else structlog.get_logger()
