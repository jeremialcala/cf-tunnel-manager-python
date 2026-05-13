from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import AbstractAsyncContextManager


class LockManager(ABC):
    """Distributed lock primitive (Redlock-style)."""

    @abstractmethod
    def lock(
        self,
        key: str,
        *,
        ttl_seconds: int | None = None,
        wait_seconds: float = 0.0,
    ) -> AbstractAsyncContextManager[None]:
        """Acquire and auto-release on context exit.

        Raises :class:`shared.errors.LockAcquisitionFailed` if the lock
        cannot be acquired within ``wait_seconds``.
        """
