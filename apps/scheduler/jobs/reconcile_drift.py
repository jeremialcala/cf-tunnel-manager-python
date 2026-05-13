from __future__ import annotations

from apps.composition import Container
from cloud_platform.events.envelope import build_envelope
from cloud_platform.events.payloads import TunnelReconcileRequestPayload
from cloud_platform.events.topics import Topic
from shared.logging import get_logger
from services.tunnel_orchestrator.infrastructure.persistence import PgTenantRepository

log = get_logger(__name__)


async def run(c: Container) -> None:
    async with c.db.session_factory() as session:
        tenants = await PgTenantRepository(session).list_active()
    for tenant in tenants:
        env = build_envelope(
            payload=TunnelReconcileRequestPayload(tenant_id=tenant.id.value, scope="tenant"),
            event_type="tunnel.reconcile.request.v1",
            tenant_id=tenant.id.value,
            producer="tunnel-orchestrator/scheduler",
        )
        await c.publisher.publish(Topic.RECONCILE_REQUEST, env, key=str(tenant.id.value))
    log.info("scheduler.reconcile.emitted", tenants=len(tenants))
