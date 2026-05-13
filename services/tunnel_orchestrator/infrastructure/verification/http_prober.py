"""End-to-end HTTPS prober via httpx."""

from __future__ import annotations

import asyncio
import time

import httpx

from shared.config import get_settings
from shared.logging import get_logger
from shared.observability import metrics
from services.tunnel_orchestrator.application.ports import HttpVerifier
from services.tunnel_orchestrator.application.ports.http_verifier import HttpResult
from services.tunnel_orchestrator.domain.value_objects import Hostname

log = get_logger(__name__)


class HttpxProber(HttpVerifier):
    def __init__(self) -> None:
        cfg = get_settings().verification
        self._timeout = cfg.http_timeout_seconds
        self._interval = cfg.http_interval_seconds
        self._expected = cfg.expected_status_codes

    async def probe(
        self,
        hostname: Hostname,
        *,
        timeout_seconds: float | None = None,
        interval_seconds: float | None = None,
        expected_codes: set[int] | None = None,
        path: str = "/",
    ) -> HttpResult:
        timeout = timeout_seconds or self._timeout
        interval = interval_seconds or self._interval
        expected = expected_codes or self._expected
        url = f"https://{hostname}{path}"
        deadline = time.monotonic() + timeout
        started = time.monotonic()

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0),
            follow_redirects=False,
            http2=True,
        ) as client:
            attempt = 0
            last_status: int | None = None
            last_url: str | None = None
            while time.monotonic() < deadline:
                attempt += 1
                try:
                    r = await client.get(url, headers={"User-Agent": "tunnel-orchestrator/probe"})
                    last_status = r.status_code
                    last_url = str(r.url)
                    if r.status_code in expected:
                        elapsed_ms = (time.monotonic() - started) * 1000
                        metrics.http_verification_seconds.labels("ok").observe(elapsed_ms / 1000)
                        return HttpResult(
                            url=url,
                            ok=True,
                            status_code=r.status_code,
                            elapsed_ms=elapsed_ms,
                            final_url=str(r.url),
                        )
                except (httpx.HTTPError, asyncio.TimeoutError) as e:
                    log.debug("http.probe.attempt_failed", url=url, attempt=attempt, error=str(e))
                await asyncio.sleep(interval)

        elapsed_ms = (time.monotonic() - started) * 1000
        metrics.http_verification_seconds.labels("timeout").observe(elapsed_ms / 1000)
        return HttpResult(url=url, ok=False, status_code=last_status, elapsed_ms=elapsed_ms, final_url=last_url)
