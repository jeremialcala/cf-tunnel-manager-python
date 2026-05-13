from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from services.tunnel_orchestrator.domain.value_objects import Hostname


@dataclass(frozen=True, slots=True)
class HttpResult:
    url: str
    ok: bool
    status_code: int | None
    elapsed_ms: float
    final_url: str | None = None


class HttpVerifier(ABC):
    @abstractmethod
    async def probe(
        self,
        hostname: Hostname,
        *,
        timeout_seconds: float | None = None,
        interval_seconds: float | None = None,
        expected_codes: set[int] | None = None,
        path: str = "/",
    ) -> HttpResult: ...
