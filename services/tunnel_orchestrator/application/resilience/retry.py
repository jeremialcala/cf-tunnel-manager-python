"""Async retry primitives.

Two surfaces:

* :func:`retryable` — decorator for ad-hoc reuse;
* :class:`AsyncRetry` — re-usable executor for "run this coro under
  policy P" semantics, useful inside Saga steps where each step pulls
  its own policy from settings.

Both use ``tenacity`` for proven backoff math but expose a domain-typed
exception filter so retries respect our :class:`InfrastructureError`
``retryable`` flag.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, TypeVar

from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from shared.errors import AppError, InfrastructureError, SagaTimeout

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 5
    initial_delay_ms: int = 500
    max_delay_ms: int = 15_000
    jitter: bool = True

    def is_retryable(self, exc: BaseException) -> bool:
        if isinstance(exc, AppError):
            return getattr(exc, "retryable", False)
        # Network-y stdlib exceptions
        return isinstance(exc, (TimeoutError, ConnectionError, OSError))


class AsyncRetry:
    """Run a coroutine under a :class:`RetryPolicy`.

    Designed to be cheap to instantiate per call — no shared state.
    """

    def __init__(self, policy: RetryPolicy) -> None:
        self.policy = policy

    async def run(self, fn: Callable[[], Awaitable[T]]) -> T:
        retrying = AsyncRetrying(
            stop=stop_after_attempt(self.policy.max_attempts),
            wait=wait_exponential_jitter(
                initial=self.policy.initial_delay_ms / 1000,
                max=self.policy.max_delay_ms / 1000,
            ),
            retry=retry_if_exception(self.policy.is_retryable),
            reraise=True,
        )
        try:
            async for attempt in retrying:
                with attempt:
                    return await fn()
        except RetryError as e:  # pragma: no cover  — reraise=True handles this
            raise SagaTimeout("retry attempts exhausted") from e
        raise RuntimeError("unreachable")  # pragma: no cover


def retryable(
    *,
    max_attempts: int = 5,
    initial_delay_ms: int = 500,
    max_delay_ms: int = 15_000,
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Decorator wrapping a coroutine in :class:`AsyncRetry`."""

    policy = RetryPolicy(max_attempts, initial_delay_ms, max_delay_ms)

    def decorator(fn: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        async def wrapper(*args: object, **kwargs: object) -> T:
            return await AsyncRetry(policy).run(lambda: fn(*args, **kwargs))

        wrapper.__wrapped__ = fn  # type: ignore[attr-defined]
        wrapper.__name__ = fn.__name__
        return wrapper

    return decorator


# Re-export for typed callers that want to discriminate domain failures
__all__ = ["AsyncRetry", "RetryPolicy", "retryable", "InfrastructureError"]
