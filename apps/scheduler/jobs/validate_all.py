"""Emit one ``tunnel.validation.request`` per READY tunnel."""

from __future__ import annotations

from apps.composition import Container
from cloud_platform.events.envelope import build_envelope
from cloud_platform.events.payloads import TunnelValidationRequestPayload
from cloud_platform.events.topics import Topic
from shared.logging import get_logger
from services.tunnel_orchestrator.domain.aggregates import TunnelStatus
from services.tunnel_orchestrator.domain.repositories import TunnelRepository
from services.tunnel_orchestrator.infrastructure.persistence import (
    PgTenantRepository,
    PgTunnelRepository,
)

log = get_logger(__name__)


async def run(c: Container) -> None:
    emitted = 0
    async with c.db.session_factory() as session:
        tenants = await PgTenantRepository(session).list_active()
        for tenant in tenants:
            repo: TunnelRepository = PgTunnelRepository(session)
            tunnels = await repo.list_by_tenant(tenant.id, limit=500)
            for t in tunnels:
                if t.status is not TunnelStatus.READY:
                    continue
                env = build_envelope(
                    payload=TunnelValidationRequestPayload(
                        tenant_id=tenant.id.value, tunnel_id=t.id.value
                    ),
                    event_type="tunnel.validation.request.v1",
                    tenant_id=tenant.id.value,
                    producer="tunnel-orchestrator/scheduler",
                )
                await c.publisher.publish(
                    Topic.VALIDATION_REQUEST, env, key=str(tenant.id.value)
                )
                emitted += 1
    log.info("scheduler.validate_all.emitted", count=emitted)
