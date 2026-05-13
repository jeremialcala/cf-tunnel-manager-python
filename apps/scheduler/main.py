"""Scheduler — leader-elected periodic jobs.

Singleton-style: leader election uses a Redis lock with TTL renewal.
Only the leader emits events; followers stand by and take over if the
leader's heartbeat lapses.

Jobs:

* ``validate_all`` — every 15 min emits a ``tunnel.validation.request``
  for each ``READY`` tunnel.
* ``reconcile_drift`` — every hour emits ``tunnel.reconcile.request``
  per tenant (worker drains).
* ``purge_idempotency`` — daily, removes expired keys.
"""

from __future__ import annotations

import asyncio
import signal
import socket
from contextlib import suppress

from apps.composition import Container, build_container, shutdown_container
from apps.scheduler.jobs import purge_idempotency, reconcile_drift, validate_all
from shared.logging import get_logger

log = get_logger(__name__)

LEADER_KEY = "scheduler:leader"
LEADER_TTL_SECONDS = 30
LEADER_RENEWAL_INTERVAL = 10


async def _is_leader(c: Container, identity: str) -> bool:
    """Try to acquire/renew the leader lock. True if we are leader after this call."""
    redis = c.redis.client
    # SETNX with TTL acts as election; subsequent renewals use compare-and-swap.
    ok = await redis.set(LEADER_KEY, identity, ex=LEADER_TTL_SECONDS, nx=True)
    if ok:
        return True
    current = await redis.get(LEADER_KEY)
    if current == identity:
        await redis.expire(LEADER_KEY, LEADER_TTL_SECONDS)
        return True
    return False


async def _scheduler_loop(c: Container) -> None:
    identity = f"{socket.gethostname()}-{id(c)}"
    log.info("scheduler.identity", identity=identity)

    last_validate = 0.0
    last_reconcile = 0.0
    last_purge = 0.0

    while True:
        leader = await _is_leader(c, identity)
        if not leader:
            await asyncio.sleep(LEADER_RENEWAL_INTERVAL)
            continue

        loop = asyncio.get_running_loop()
        now = loop.time()

        if now - last_validate > 15 * 60:
            with suppress(Exception):
                await validate_all.run(c)
            last_validate = now

        if now - last_reconcile > 60 * 60:
            with suppress(Exception):
                await reconcile_drift.run(c)
            last_reconcile = now

        if now - last_purge > 24 * 3600:
            with suppress(Exception):
                await purge_idempotency.run(c)
            last_purge = now

        await asyncio.sleep(LEADER_RENEWAL_INTERVAL)


async def _run() -> None:
    container = await build_container()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    main_task = asyncio.create_task(_scheduler_loop(container), name="scheduler")
    await stop.wait()
    main_task.cancel()
    with suppress(asyncio.CancelledError):
        await main_task
    await shutdown_container(container)


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
