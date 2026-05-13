"""Use case: validate an existing tunnel (DNS + HTTP probe).

Triggered by:

* the scheduler emitting ``tunnel.validation.request`` periodically;
* operators via the API ``POST /tunnels/{id}/validate``.

Failure does NOT auto-rollback the tunnel — it surfaces a failure
event for alerting and an audit log entry. Reconciliation is a
separate workflow.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from cloud_platform.events.envelope import build_envelope
from cloud_platform.events.payloads import (
    TunnelValidationFailurePayload,
    TunnelValidationSuccessPayload,
)
from cloud_platform.events.topics import Topic
from shared.errors import TunnelNotFound
from shared.types import utcnow
from services.tunnel_orchestrator.application.ports import (
    DnsVerifier,
    EventPublisher,
    HttpVerifier,
)
from services.tunnel_orchestrator.domain.repositories import TunnelRepository
from services.tunnel_orchestrator.domain.value_objects import TenantIdVO, TunnelIdVO


class ValidateTunnelCommand(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    tenant_id: UUID
    tunnel_id: UUID
    correlation_id: str | None = None


@dataclass(frozen=True, slots=True)
class ValidateTunnelOutcome:
    tunnel_id: UUID
    dns_ok: bool
    http_ok: bool
    latency_ms: float | None = None
    duration_seconds: float = 0.0


class ValidateTunnelHandler:
    PRODUCER = "tunnel-orchestrator/validate-handler"

    def __init__(
        self,
        *,
        tunnels: TunnelRepository,
        dns: DnsVerifier,
        http: HttpVerifier,
        publisher: EventPublisher,
    ) -> None:
        self._tunnels = tunnels
        self._dns = dns
        self._http = http
        self._publisher = publisher

    async def handle(self, cmd: ValidateTunnelCommand) -> ValidateTunnelOutcome:
        started = time.monotonic()
        tunnel = await self._tunnels.get(TunnelIdVO(cmd.tunnel_id))
        if tunnel is None or tunnel.tenant_id != TenantIdVO(cmd.tenant_id):
            raise TunnelNotFound(f"Tunnel {cmd.tunnel_id} not found")

        tunnel.begin_validation()
        try:
            dns_result = await self._dns.verify(tunnel.hostname)
            http_result = await self._http.probe(tunnel.hostname)

            if dns_result.resolved and http_result.ok:
                tunnel.mark_validation_ok(latency_ms=http_result.elapsed_ms)
                await self._publisher.publish(
                    Topic.VALIDATION_SUCCESS,
                    build_envelope(
                        payload=TunnelValidationSuccessPayload(
                            tenant_id=tunnel.tenant_id.value,
                            tunnel_id=tunnel.id.value,
                            cf_tunnel_id=tunnel.cf_tunnel_id or "",
                            hostname=str(tunnel.hostname),
                            dns_ok=True,
                            http_ok=True,
                            latency_ms=http_result.elapsed_ms,
                            validated_at=utcnow(),
                        ),
                        event_type="tunnel.validation.success.v1",
                        tenant_id=tunnel.tenant_id.value,
                        producer=self.PRODUCER,
                        correlation_id=cmd.correlation_id,
                    ),
                    key=str(tunnel.id.value),
                )
            else:
                reasons: list[str] = []
                if not dns_result.resolved:
                    reasons.append("dns_unresolved")
                if not http_result.ok:
                    reasons.append(f"http_{http_result.status_code}")
                reason = "+".join(reasons)
                tunnel.mark_validation_failed(reason)
                await self._publisher.publish(
                    Topic.VALIDATION_FAILURE,
                    build_envelope(
                        payload=TunnelValidationFailurePayload(
                            tenant_id=tunnel.tenant_id.value,
                            tunnel_id=tunnel.id.value,
                            cf_tunnel_id=tunnel.cf_tunnel_id or "",
                            hostname=str(tunnel.hostname),
                            reason=reason,
                            failed_at=utcnow(),
                        ),
                        event_type="tunnel.validation.failure.v1",
                        tenant_id=tunnel.tenant_id.value,
                        producer=self.PRODUCER,
                        correlation_id=cmd.correlation_id,
                    ),
                    key=str(tunnel.id.value),
                )

            await self._tunnels.save(tunnel)
            return ValidateTunnelOutcome(
                tunnel_id=tunnel.id.value,
                dns_ok=dns_result.resolved,
                http_ok=http_result.ok,
                latency_ms=http_result.elapsed_ms if http_result.ok else None,
                duration_seconds=time.monotonic() - started,
            )
        except Exception:
            tunnel.mark_validation_failed("internal_error")
            await self._tunnels.save(tunnel)
            raise
