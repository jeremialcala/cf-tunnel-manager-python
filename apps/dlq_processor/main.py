"""DLQ processor.

Default policy is **manual triage**: each ``tunnel.dlq`` message is
logged + counted; replay is a deliberate operator action via the
``tunnel-dlq`` CLI (see ``scripts/dlq_replay.py``).

If env ``DLQ_AUTO_REPLAY=true`` is set, the processor will re-publish
the original payload to its origin topic — useful for transient
upstream outages.
"""

from __future__ import annotations

import asyncio
import base64
import os
import signal
from contextlib import suppress
from typing import Any

from apps.composition import Container, build_container, shutdown_container
from platform.events.envelope import EventEnvelope
from platform.events.payloads import TunnelDlqPayload
from platform.events.topics import Topic
from shared.errors import ValidationError
from shared.logging import get_logger
from shared.observability import metrics
from services.tunnel_orchestrator.infrastructure.messaging import KafkaConsumerRunner

log = get_logger(__name__)


def handler_factory(c: Container, *, auto_replay: bool):  # noqa: ANN201
    sender = c.kafka

    async def handle(envelope: EventEnvelope[Any]) -> None:
        if not isinstance(envelope.payload, TunnelDlqPayload):
            raise ValidationError(f"Unexpected DLQ payload: {type(envelope.payload)}")
        p = envelope.payload
        log.warning(
            "dlq.received",
            origin_topic=p.original_topic,
            origin_offset=p.original_offset,
            reason=p.dlq_reason,
            event_type=p.original_event_type,
            attempts=p.attempts,
        )
        metrics.kafka_messages_consumed_total.labels(str(Topic.DLQ), "received").inc()

        if auto_replay and p.attempts < 3:
            payload = base64.b64decode(p.original_payload_b64)
            producer = sender.producer()
            await producer.send_and_wait(
                topic=p.original_topic,
                key=p.original_headers.get("tenant_id", "").encode() or None,
                value=payload,
                headers=[(k, v.encode()) for k, v in p.original_headers.items()],
            )
            log.info("dlq.auto_replayed", origin_topic=p.original_topic)

    return handle


async def _run() -> None:
    container = await build_container()
    auto = os.getenv("DLQ_AUTO_REPLAY", "false").lower() == "true"
    runner = KafkaConsumerRunner(
        topics=[str(Topic.DLQ)],
        group_id="tunnel-orchestrator-dlq",
        handler=handler_factory(container, auto_replay=auto),
        publisher=container.publisher,
        concurrency=4,
    )
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    task = asyncio.create_task(runner.run(), name="dlq")
    await stop.wait()
    await runner.stop()
    with suppress(asyncio.CancelledError):
        await task
    await shutdown_container(container)


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
