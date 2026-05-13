"""DNS verifier built on ``dnspython`` (async resolver)."""

from __future__ import annotations

import asyncio
import time

import dns.asyncresolver
import dns.exception

from shared.config import get_settings
from shared.logging import get_logger
from shared.observability import metrics
from services.tunnel_orchestrator.application.ports import DnsVerifier
from services.tunnel_orchestrator.application.ports.dns_verifier import DnsResult
from services.tunnel_orchestrator.domain.value_objects import Hostname

log = get_logger(__name__)


class DnsPyVerifier(DnsVerifier):
    def __init__(self) -> None:
        cfg = get_settings().verification
        self._timeout = cfg.dns_timeout_seconds
        self._interval = cfg.dns_interval_seconds
        self._nameservers = cfg.nameservers

    async def verify(
        self,
        hostname: Hostname,
        *,
        timeout_seconds: float | None = None,
        interval_seconds: float | None = None,
        expected_targets: tuple[str, ...] | None = None,
    ) -> DnsResult:
        timeout = timeout_seconds or self._timeout
        interval = interval_seconds or self._interval
        deadline = time.monotonic() + timeout

        resolver = dns.asyncresolver.Resolver()
        resolver.nameservers = list(self._nameservers)
        resolver.lifetime = max(2.0, interval)
        resolver.timeout = max(2.0, interval)

        attempt = 0
        started = time.monotonic()
        while time.monotonic() < deadline:
            attempt += 1
            try:
                answers = await resolver.resolve(str(hostname), "CNAME")
                resolved = tuple(str(a.target).rstrip(".") for a in answers)
                if expected_targets and not any(
                    t.rstrip(".") in resolved for t in expected_targets
                ):
                    log.debug(
                        "dns.target_mismatch",
                        hostname=str(hostname),
                        got=resolved,
                        expected=expected_targets,
                    )
                else:
                    elapsed = time.monotonic() - started
                    metrics.dns_verification_seconds.labels("ok").observe(elapsed)
                    return DnsResult(
                        hostname=str(hostname),
                        resolved=True,
                        answers=resolved,
                        elapsed_seconds=elapsed,
                        nameservers_used=tuple(self._nameservers),
                    )
            except (dns.exception.DNSException, asyncio.TimeoutError) as e:
                log.debug("dns.attempt_failed", hostname=str(hostname), attempt=attempt, error=str(e))

            await asyncio.sleep(interval)

        elapsed = time.monotonic() - started
        metrics.dns_verification_seconds.labels("timeout").observe(elapsed)
        return DnsResult(
            hostname=str(hostname),
            resolved=False,
            answers=(),
            elapsed_seconds=elapsed,
            nameservers_used=tuple(self._nameservers),
        )
