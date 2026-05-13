"""Seed a default tenant for local development."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.tunnel_orchestrator.domain.aggregates import Tenant
from services.tunnel_orchestrator.infrastructure.persistence import (
    Database,
    PgTenantRepository,
)


async def _main() -> None:
    db = Database()
    async with db.session_factory() as session:
        repo = PgTenantRepository(session)
        existing = await repo.get_by_slug("acme")
        if existing:
            print(f"Tenant 'acme' already exists ({existing.id})")
            return
        tenant = Tenant.new(
            name="Acme Corp",
            slug="acme",
            cf_account_id=os.environ.get("CLOUDFLARE_DEFAULT_ACCOUNT_ID", "00000000000000000000000000000000"),
            cf_token_vault_path="secret/tenants/acme/cf_token",
            cf_zone_ids=os.environ.get("SEED_ZONE_IDS", "").split(",") if os.environ.get("SEED_ZONE_IDS") else [],
            k8s_namespace="tunnels-acme",
        )
        tenant.activate()
        await repo.add(tenant)
        await session.commit()
        print(f"Seeded tenant 'acme' with id={tenant.id}")
    await db.dispose()


if __name__ == "__main__":
    asyncio.run(_main())
