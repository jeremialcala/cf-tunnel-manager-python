"""Integration: outbox row is written transactionally with the aggregate."""

from __future__ import annotations

import pytest

from services.tunnel_orchestrator.domain.aggregates import Tunnel
from services.tunnel_orchestrator.domain.value_objects import (
    Hostname,
    IngressRuleSet,
    TenantIdVO,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.mark.asyncio
async def test_outbox_inserted_with_aggregate_save():
    """Spins up a real PostgreSQL via testcontainers and asserts that
    creating a Tunnel produces matching outbox_events rows."""
    pytest.importorskip("testcontainers.postgres")
    from sqlalchemy import select, text
    from testcontainers.postgres import PostgresContainer

    from services.tunnel_orchestrator.infrastructure.persistence import (
        Database, PgTunnelRepository,
    )
    from services.tunnel_orchestrator.infrastructure.persistence.models import (
        Base, OutboxRow,
    )

    with PostgresContainer("postgres:16-alpine") as pg:
        dsn = pg.get_connection_url().replace("psycopg2", "asyncpg")
        db = Database(dsn=dsn, echo=False)

        async with db.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        # Need a Tenant row first (FK)
        from services.tunnel_orchestrator.infrastructure.persistence import PgTenantRepository
        from services.tunnel_orchestrator.domain.aggregates import Tenant
        async with db.session_factory() as session:
            tenant = Tenant.new(
                name="acme", slug="acme",
                cf_account_id="acc", cf_token_vault_path="path",
                cf_zone_ids=["zone-1"],
            )
            tenant.activate()
            await PgTenantRepository(session).add(tenant)
            await session.commit()

        # Now create a tunnel
        async with db.session_factory() as session:
            await session.begin()
            tunnel = Tunnel.request(
                tenant_id=tenant.id,
                hostname=Hostname.parse("api.example.com"),
                ingress=IngressRuleSet.single("api.example.com", "http://svc:8000"),
                cf_zone_id="zone-1",
                cluster="default",
                namespace="ns",
            )
            await PgTunnelRepository(session).add(tunnel)
            await session.commit()

        async with db.session_factory() as session:
            rows = (await session.execute(select(OutboxRow))).scalars().all()
        assert len(rows) >= 1
        assert any(r.topic == "tunnel.create.request" for r in rows)

        await db.dispose()
