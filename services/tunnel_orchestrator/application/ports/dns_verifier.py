from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from services.tunnel_orchestrator.domain.value_objects import Hostname


@dataclass(frozen=True, slots=True)
class DnsResult:
    hostname: str
    resolved: bool
    answers: tuple[str, ...]
    elapsed_seconds: float
    nameservers_used: tuple[str, ...]


class DnsVerifier(ABC):
    @abstractmethod
    async def verify(
        self,
        hostname: Hostname,
        *,
        timeout_seconds: float | None = None,
        interval_seconds: float | None = None,
        expected_targets: tuple[str, ...] | None = None,
    ) -> DnsResult:
        """Resolve ``hostname`` polling external resolvers until success or timeout."""
