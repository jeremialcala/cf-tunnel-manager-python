"""Async-safe correlation / tenant context propagation.

Implemented on top of :pymod:`contextvars` so it survives across
``await`` boundaries and ``asyncio.TaskGroup`` siblings, while *not*
leaking between unrelated tasks (e.g. parallel Saga branches).
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator
from uuid import UUID

import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars

from shared.types import CorrelationId, TenantId, new_correlation_id

_correlation_id: ContextVar[CorrelationId | None] = ContextVar("correlation_id", default=None)
_causation_id:   ContextVar[str | None] = ContextVar("causation_id", default=None)
_tenant_id:      ContextVar[TenantId | None] = ContextVar("tenant_id", default=None)


def current_correlation_id() -> CorrelationId | None:
    return _correlation_id.get()


def current_tenant_id() -> TenantId | None:
    return _tenant_id.get()


def bind_correlation(
    correlation_id: CorrelationId | str | None = None,
    *,
    causation_id: str | None = None,
) -> CorrelationId:
    """Bind correlation id into both contextvars and structlog binding.

    Returns the (possibly newly generated) correlation id.
    """
    cid = CorrelationId(str(correlation_id)) if correlation_id else new_correlation_id()
    _correlation_id.set(cid)
    if causation_id:
        _causation_id.set(causation_id)
    bind_contextvars(correlation_id=cid, causation_id=causation_id or "")
    return cid


def bind_tenant(tenant_id: TenantId | UUID | str) -> TenantId:
    tid = TenantId(tenant_id if isinstance(tenant_id, UUID) else UUID(str(tenant_id)))
    _tenant_id.set(tid)
    bind_contextvars(tenant_id=str(tid))
    return tid


def clear_context() -> None:
    _correlation_id.set(None)
    _causation_id.set(None)
    _tenant_id.set(None)
    clear_contextvars()


@contextmanager
def CorrelationContext(  # noqa: N802 — used as ctx manager, capital looks intentional
    correlation_id: CorrelationId | str | None = None,
    *,
    causation_id: str | None = None,
    tenant_id: TenantId | UUID | str | None = None,
) -> Iterator[CorrelationId]:
    """Scoped binder. Use around a unit of work that should share context.

    Example
    -------

    >>> with CorrelationContext(tenant_id=t.id) as cid:
    ...     log.info("doing.thing", x=1)   # will include correlation_id, tenant_id
    """
    prev_cid = _correlation_id.get()
    prev_caus = _causation_id.get()
    prev_tid = _tenant_id.get()
    cid = bind_correlation(correlation_id, causation_id=causation_id)
    if tenant_id is not None:
        bind_tenant(tenant_id)
    try:
        yield cid
    finally:
        _correlation_id.set(prev_cid)
        _causation_id.set(prev_caus)
        _tenant_id.set(prev_tid)
        # Re-bind for structlog so following logs see the previous state.
        if prev_cid:
            structlog.contextvars.bind_contextvars(correlation_id=prev_cid)
        else:
            structlog.contextvars.unbind_contextvars("correlation_id", "causation_id", "tenant_id")
