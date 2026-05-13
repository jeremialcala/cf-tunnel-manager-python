"""Local end-to-end smoke test.

Steps:
  1. Seed tenant if missing.
  2. Publish a `tunnel.create.request` event directly to Kafka.
  3. Poll Postgres until the corresponding tunnel reaches READY (or FAILED).

Requires a real Cloudflare account; otherwise run unit tests instead.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from platform.events.envelope import build_envelope
from platform.events.payloads import TunnelCreateRequestPayload
from platform.events.topics import Topic
from services.tunnel_orchestrator.infrastructure.messaging import KafkaProducerFactory
from services.tunnel_orchestrator.infrastructure.messaging.kafka_producer import (
    DirectKafkaSender,
)
from services.tunnel_orchestrator.infrastructure.persistence import (
    Database,
    PgTenantRepository,
)
from services.tunnel_orchestrator.infrastructure.persistence.models import TunnelRow

POLL_TIMEOUT_SECONDS = 600
POLL_INTERVAL_SECONDS = 2


async def _main() -> None:
    if not os.environ.get("CLOUDFLARE_API_TOKEN"):
        print("CLOUDFLARE_API_TOKEN required for smoke test", file=sys.stderr)
        sys.exit(2)

    db = Database()
    async with db.session_factory() as session:
        tenant = await PgTenantRepository(session).get_by_slug("acme")
        if tenant is None:
            print("Tenant 'acme' not found; run scripts/seed_db.py first.", file=sys.stderr)
            sys.exit(2)

    hostname = os.environ.get("SMOKE_HOSTNAME") or f"smoke-{uuid4().hex[:6]}.example.com"
    cf_zone_id = os.environ["SMOKE_CF_ZONE_ID"]
    target = os.environ.get("SMOKE_TARGET_SERVICE", "http://httpbin.svc.cluster.local:8080")

    payload = TunnelCreateRequestPayload(
        tenant_id=tenant.id.value,
        hostname=hostname,
        cf_zone_id=cf_zone_id,
        ingress=[{"service": target}],
        requested_by="smoke-test",
    )
    env = build_envelope(
        payload=payload,
        event_type="tunnel.create.request.v1",
        tenant_id=tenant.id.value,
        producer="smoke-test",
        idempotency_key=f"smoke:{hostname}",
    )

    factory = KafkaProducerFactory()
    await factory.start()
    sender = DirectKafkaSender(factory)
    import orjson
    await sender(
        str(Topic.CREATE_REQUEST),
        str(tenant.id.value).encode(),
        orjson.dumps(env.model_dump(mode="json")),
        {"event_type": env.event_type, "tenant_id": str(tenant.id.value)},
    )
    print(f"Published create request for {hostname}")

    deadline = time.time() + POLL_TIMEOUT_SECONDS
    while time.time() < deadline:
        async with db.session_factory() as session:
            stmt = select(TunnelRow).where(
                TunnelRow.tenant_id == tenant.id.value,
                TunnelRow.hostname == hostname,
            )
            row = (await session.execute(stmt)).scalar_one_or_none()
        if row and row.status in {"READY", "FAILED", "DELETED"}:
            print(f"Tunnel {row.id} reached status={row.status} ({row.last_error})")
            sys.exit(0 if row.status == "READY" else 1)
        await asyncio.sleep(POLL_INTERVAL_SECONDS)

    print("Smoke test timed out", file=sys.stderr)
    await factory.stop()
    await db.dispose()
    sys.exit(1)


if __name__ == "__main__":
    asyncio.run(_main())
