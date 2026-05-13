from __future__ import annotations

from apps.composition import Container
from shared.logging import get_logger
from services.tunnel_orchestrator.infrastructure.persistence import PgIdempotencyStore

log = get_logger(__name__)


async def run(c: Container) -> None:
    store = PgIdempotencyStore(c.db)
    n = await store.purge_expired(batch_size=10_000)
    log.info("scheduler.idempotency.purged", rows=n)
