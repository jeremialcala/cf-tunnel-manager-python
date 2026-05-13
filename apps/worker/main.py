"""Worker process entrypoint.

Spins up:

* the Kafka consumer for ``tunnel.create.request``,
  ``tunnel.delete.request``, ``tunnel.validation.request``,
  ``tunnel.reconcile.request``;
* the **outbox relay** loop (drains PG outbox to Kafka);
* an HTTP healthz endpoint on ``PROMETHEUS_METRICS_PORT`` for K8s
  probes and Prometheus scraping.

Graceful shutdown:

1. Receive ``SIGTERM``.
2. Stop consumer (no new fetches).
3. Drain in-flight sagas (timeout = ``SAGA_GLOBAL_TIMEOUT_SECONDS``).
4. Stop outbox relay.
5. Flush producer, close DB / Redis / K8s clients.
"""

from __future__ import annotations

import asyncio
import signal
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

from apps.composition import Container, build_container, shutdown_container
from apps.worker.consumers import (
    create_tunnel_consumer,
    delete_tunnel_consumer,
    reconcile_consumer,
    validation_consumer,
)
from cloud_platform.events.topics import Topic
from shared.config import get_settings
from shared.logging import get_logger
from shared.observability import metrics
from services.tunnel_orchestrator.infrastructure.messaging import KafkaConsumerRunner

log = get_logger(__name__)


# ----------------------- tiny healthz on the metrics port -----------------------


class _Healthz(BaseHTTPRequestHandler):
    def log_message(self, *args, **_):  # noqa: ANN001 — silence noisy default
        pass

    def do_GET(self) -> None:                                # noqa: N802
        if self.path == "/healthz" or self.path == "/health/live":
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"alive"}')
            return
        if self.path.startswith("/metrics"):
            body, ct = metrics.render()
            self.send_response(200)
            self.send_header("content-type", ct)
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()


def _start_healthz(port: int) -> None:
    Thread(target=HTTPServer(("0.0.0.0", port), _Healthz).serve_forever, daemon=True).start()


# ------------------------------------ runner ----------------------------------


async def _run() -> None:
    container = await build_container()
    settings = get_settings()
    _start_healthz(settings.observability.metrics_port)

    # Build the consumer runners (one per topic group).
    handlers = {
        Topic.CREATE_REQUEST: create_tunnel_consumer.handler_factory(container),
        Topic.DELETE_REQUEST: delete_tunnel_consumer.handler_factory(container),
        Topic.VALIDATION_REQUEST: validation_consumer.handler_factory(container),
        Topic.RECONCILE_REQUEST: reconcile_consumer.handler_factory(container),
    }
    runners: list[KafkaConsumerRunner] = []
    for topic, handler in handlers.items():
        runners.append(
            KafkaConsumerRunner(
                topics=[str(topic)],
                group_id=f"{settings.kafka.consumer_group}-{topic.value.replace('.', '-')}",
                handler=handler,
                publisher=container.publisher,
            )
        )

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _signal_handler(signum: int) -> None:
        log.info("worker.signal", signal=signum)
        stop_event.set()
        for r in runners:
            asyncio.create_task(r.stop())
        asyncio.create_task(container.outbox_relay.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler, int(sig))

    log.info("worker.start", topics=list(handlers.keys()))

    relay_task = asyncio.create_task(container.outbox_relay.run(), name="outbox-relay")
    consumer_tasks = [
        asyncio.create_task(r.run(), name=f"consumer-{i}") for i, r in enumerate(runners)
    ]

    await stop_event.wait()

    # Drain in-flight work
    drain_deadline = settings.resilience.saga_global_timeout_seconds
    log.info("worker.drain.start", timeout_seconds=drain_deadline)
    for task in [*consumer_tasks, relay_task]:
        with suppress(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=drain_deadline)

    await shutdown_container(container)
    log.info("worker.shutdown.complete")


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
