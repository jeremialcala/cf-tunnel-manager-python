"""Saga primitives.

Provides:

* :class:`SagaStep` — a forward action and its compensation.
* :class:`SagaContext` — typed shared state passed between steps.
* :class:`SagaOrchestrator` — runs steps with timeouts, span instrumentation,
  and reverse-order compensation on failure.

The orchestrator is **storage-agnostic**: persistence of saga state is
delegated to ``SagaInstanceStore`` (port — implemented by the PG
adapter). This keeps the orchestrator pure and unit-testable without
any infrastructure.
"""

from __future__ import annotations

import asyncio
import time
import traceback
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Generic, Sequence, TypeVar
from uuid import UUID, uuid4

from opentelemetry import trace

from shared.errors import (
    AppError,
    SagaCompensationFailed,
    SagaError,
    SagaStepFailed,
    SagaTimeout,
)
from shared.logging import get_logger
from shared.observability import metrics
from shared.types import utcnow

log = get_logger(__name__)
tracer = trace.get_tracer("tunnel_orchestrator.saga")

C = TypeVar("C")


# ----------------------------------------------------------------- enums


class SagaStatus(str, Enum):
    PENDING       = "PENDING"
    IN_PROGRESS   = "IN_PROGRESS"
    COMPENSATING  = "COMPENSATING"
    SUCCEEDED     = "SUCCEEDED"
    FAILED        = "FAILED"
    COMPENSATION_FAILED = "COMPENSATION_FAILED"


class StepStatus(str, Enum):
    PENDING     = "PENDING"
    RUNNING     = "RUNNING"
    SUCCEEDED   = "SUCCEEDED"
    FAILED      = "FAILED"
    COMPENSATED = "COMPENSATED"
    SKIPPED     = "SKIPPED"


# --------------------------------------------------------------- DTOs


@dataclass
class SagaContext(Generic[C]):
    """Per-saga mutable scratch-pad. Generic so each saga types its own.

    The orchestrator never reads from ``data`` — it only forwards it
    between steps. Steps may read/write freely.
    """

    saga_id: UUID
    correlation_id: str
    tenant_id: UUID
    started_at: float
    data: C
    step_outputs: dict[str, Any] = field(default_factory=dict)


@dataclass
class StepResult:
    name: str
    status: StepStatus
    output: Any = None
    error: str | None = None
    attempts: int = 1
    duration_seconds: float = 0.0


@dataclass
class SagaResult:
    saga_id: UUID
    status: SagaStatus
    steps: list[StepResult]
    duration_seconds: float
    failed_step: str | None = None
    error: AppError | None = None


# --------------------------------------------------------- Step protocol


class SagaStep(ABC, Generic[C]):
    """A single forward + compensating action.

    Subclass and implement :meth:`execute` (always required) and
    :meth:`compensate` (only if the step has side effects). Steps that
    only read are perfectly fine with the default no-op compensation.
    """

    name: str
    timeout_seconds: float | None = None  # if None, uses orchestrator default

    @abstractmethod
    async def execute(self, ctx: SagaContext[C]) -> Any:
        """Run the forward action. Return value stored in ``ctx.step_outputs[self.name]``."""

    async def compensate(self, ctx: SagaContext[C]) -> None:  # pragma: no cover  — default no-op
        """Default: no-op. Override for steps that mutate external state."""
        return None

    # Hook for steps that want to be skipped under certain conditions
    async def should_skip(self, ctx: SagaContext[C]) -> bool:  # pragma: no cover
        return False


# Persistence port — concrete in infrastructure


class SagaInstanceStore(ABC):
    @abstractmethod
    async def begin(self, *, saga_id: UUID, type: str, tenant_id: UUID, context: dict[str, Any]) -> None: ...

    @abstractmethod
    async def transition(self, saga_id: UUID, status: SagaStatus) -> None: ...

    @abstractmethod
    async def record_step(self, saga_id: UUID, step: StepResult) -> None: ...


# ------------------------------------------------------ orchestrator


class SagaOrchestrator(Generic[C]):
    """Run a fixed sequence of :class:`SagaStep` against a context.

    Failure semantics:

    * a step exception → mark step ``FAILED``, transition saga to
      ``COMPENSATING``, run compensations of *previously succeeded*
      steps in **reverse order**, transition to ``FAILED``.
    * compensation exception → continue with remaining compensations,
      but transition saga to ``COMPENSATION_FAILED`` at the end so a
      human can intervene.
    * total elapsed > ``global_timeout_seconds`` → :class:`SagaTimeout`,
      treated like a step failure.
    """

    def __init__(
        self,
        *,
        saga_type: str,
        steps: Sequence[SagaStep[C]],
        store: SagaInstanceStore,
        step_timeout_seconds: float = 120.0,
        global_timeout_seconds: float = 600.0,
    ) -> None:
        if not steps:
            raise ValueError("Saga must have at least one step")
        self.saga_type = saga_type
        self.steps = list(steps)
        self.store = store
        self.step_timeout_seconds = step_timeout_seconds
        self.global_timeout_seconds = global_timeout_seconds

    async def run(self, ctx: SagaContext[C]) -> SagaResult:
        metrics.saga_started_total.labels(self.saga_type, str(ctx.tenant_id)).inc()
        metrics.saga_in_flight.labels(self.saga_type).inc()

        await self.store.begin(
            saga_id=ctx.saga_id,
            type=self.saga_type,
            tenant_id=ctx.tenant_id,
            context={"correlation_id": ctx.correlation_id},
        )
        await self.store.transition(ctx.saga_id, SagaStatus.IN_PROGRESS)

        executed: list[SagaStep[C]] = []
        results: list[StepResult] = []

        try:
            with tracer.start_as_current_span(
                f"saga.{self.saga_type}.run",
                attributes={
                    "saga.id": str(ctx.saga_id),
                    "saga.type": self.saga_type,
                    "tenant.id": str(ctx.tenant_id),
                },
            ):
                async with asyncio.timeout(self.global_timeout_seconds):
                    for step in self.steps:
                        result = await self._run_step(step, ctx)
                        results.append(result)
                        if result.status is StepStatus.SKIPPED:
                            continue
                        if result.status is StepStatus.FAILED:
                            raise SagaStepFailed(
                                step.name,
                                message=result.error or "step failed",
                            )
                        executed.append(step)

            await self.store.transition(ctx.saga_id, SagaStatus.SUCCEEDED)
            metrics.saga_completed_total.labels(self.saga_type, "succeeded", str(ctx.tenant_id)).inc()
            return SagaResult(
                saga_id=ctx.saga_id,
                status=SagaStatus.SUCCEEDED,
                steps=results,
                duration_seconds=time.monotonic() - ctx.started_at,
            )

        except (SagaStepFailed, SagaTimeout, asyncio.TimeoutError) as exc:
            failed_step = (
                exc.step_name if isinstance(exc, SagaStepFailed)
                else (executed[-1].name if executed else "<global-timeout>")
            )
            log.error(
                "saga.failed",
                saga_id=str(ctx.saga_id),
                saga_type=self.saga_type,
                failed_step=failed_step,
                error=str(exc),
            )
            await self.store.transition(ctx.saga_id, SagaStatus.COMPENSATING)
            comp_status = await self._compensate(executed, ctx, results)
            metrics.saga_completed_total.labels(
                self.saga_type, "failed", str(ctx.tenant_id)
            ).inc()
            return SagaResult(
                saga_id=ctx.saga_id,
                status=comp_status,
                steps=results,
                duration_seconds=time.monotonic() - ctx.started_at,
                failed_step=failed_step,
                error=exc if isinstance(exc, AppError) else SagaError(str(exc)),
            )
        finally:
            metrics.saga_in_flight.labels(self.saga_type).dec()

    # ----------------------------------------------------------- step

    async def _run_step(self, step: SagaStep[C], ctx: SagaContext[C]) -> StepResult:
        if await step.should_skip(ctx):
            return StepResult(name=step.name, status=StepStatus.SKIPPED)

        timeout = step.timeout_seconds or self.step_timeout_seconds
        started = time.monotonic()
        with tracer.start_as_current_span(
            f"saga.{self.saga_type}.{step.name}",
            attributes={
                "saga.id": str(ctx.saga_id),
                "saga.step": step.name,
                "saga.step_timeout_seconds": timeout,
            },
        ) as span:
            try:
                async with asyncio.timeout(timeout):
                    output = await step.execute(ctx)
                ctx.step_outputs[step.name] = output
                duration = time.monotonic() - started
                metrics.saga_step_duration_seconds.labels(
                    self.saga_type, step.name, "succeeded"
                ).observe(duration)
                result = StepResult(
                    name=step.name,
                    status=StepStatus.SUCCEEDED,
                    output=_summarise_output(output),
                    duration_seconds=duration,
                )
                await self.store.record_step(ctx.saga_id, result)
                return result
            except Exception as exc:  # noqa: BLE001  — orchestrator must catch any
                duration = time.monotonic() - started
                metrics.saga_step_duration_seconds.labels(
                    self.saga_type, step.name, "failed"
                ).observe(duration)
                span.record_exception(exc)
                span.set_status(trace.Status(trace.StatusCode.ERROR, str(exc)))
                result = StepResult(
                    name=step.name,
                    status=StepStatus.FAILED,
                    error=f"{type(exc).__name__}: {exc}",
                    duration_seconds=duration,
                )
                await self.store.record_step(ctx.saga_id, result)
                return result

    # ------------------------------------------------- compensation

    async def _compensate(
        self,
        executed: list[SagaStep[C]],
        ctx: SagaContext[C],
        results: list[StepResult],
    ) -> SagaStatus:
        any_compensation_failed = False
        for step in reversed(executed):
            try:
                with tracer.start_as_current_span(
                    f"saga.{self.saga_type}.{step.name}.compensate"
                ):
                    await step.compensate(ctx)
                metrics.saga_compensations_total.labels(
                    self.saga_type, step.name, "succeeded"
                ).inc()
                # mark in-place
                for r in results:
                    if r.name == step.name and r.status is StepStatus.SUCCEEDED:
                        r.status = StepStatus.COMPENSATED
            except Exception as exc:  # noqa: BLE001
                any_compensation_failed = True
                metrics.saga_compensations_total.labels(
                    self.saga_type, step.name, "failed"
                ).inc()
                log.error(
                    "saga.compensation.failed",
                    saga_id=str(ctx.saga_id),
                    step=step.name,
                    error=str(exc),
                    stack=traceback.format_exc(),
                )

        final = SagaStatus.COMPENSATION_FAILED if any_compensation_failed else SagaStatus.FAILED
        await self.store.transition(ctx.saga_id, final)
        if any_compensation_failed:
            # Surface a *fatal* error for ops alerting; the orchestrator
            # still returns a SagaResult so the caller can persist it.
            raise SagaCompensationFailed(
                "One or more compensating actions failed — manual intervention required",
                context={"saga_id": str(ctx.saga_id)},
            )
        return final


# --------------------------------------------------------- helpers


def _summarise_output(value: Any) -> Any:
    """Trim large/sensitive structures before persisting to DB."""
    if isinstance(value, (str, bytes)):
        return value[:512] if hasattr(value, "__getitem__") else str(value)[:512]
    if isinstance(value, dict):
        return {k: _summarise_output(v) for k, v in value.items() if "token" not in k.lower()}
    return value


def new_saga_id() -> UUID:
    return uuid4()


# Re-exports for ergonomic ``from .base import *`` usage in steps.
__all__ = [
    "SagaContext",
    "SagaInstanceStore",
    "SagaOrchestrator",
    "SagaResult",
    "SagaStatus",
    "SagaStep",
    "StepResult",
    "StepStatus",
    "new_saga_id",
]


# Re-export Callable for typing convenience in step modules.
StepFactory = Callable[..., SagaStep[Any]]
