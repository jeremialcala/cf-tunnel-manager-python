"""Generic Kafka consumer runner with bounded concurrency, OTel
context propagation, idempotent commit and DLQ-on-poison.

Usage::

    runner = KafkaConsumerRunner(
        topics=[Topic.CREATE_REQUEST],
        group_id="workers",
        handler=create_tunnel_consumer.handle,
        publisher=publisher,
    )
    await runner.run()
"""

from __future__ import annotations

import asyncio
import socket
import traceback
from typing import Any, Awaitable, Callable, Iterable, Sequence

import orjson
from aiokafka import AIOKafkaConsumer, ConsumerRecord, TopicPartition
from opentelemetry import trace
from opentelemetry.propagate import extract

from platform.events.envelope import EventEnvelope
from platform.events.headers import headers_to_dict
from platform.events.versioning import parse_event
from shared.config import get_settings
from shared.errors import AppError
from shared.logging import get_logger
from shared.observability import bind_correlation, clear_context, metrics
from services.tunnel_orchestrator.application.ports import EventPublisher

log = get_logger(__name__)
tracer = trace.get_tracer("tunnel_orchestrator.consumer")


MessageHandler = Callable[[EventEnvelope[Any]], Awaitable[None]]


class KafkaConsumerRunner:
    def __init__(
        self,
        *,
        topics: Sequence[str],
        group_id: str,
        handler: MessageHandler,
        publisher: EventPublisher,
        concurrency: int | None = None,
    ) -> None:
        cfg = get_settings().kafka
        self._topics = list(topics)
        self._group = group_id
        self._handler = handler
        self._publisher = publisher
        self._concurrency = concurrency or cfg.worker_concurrency
        self._consumer: AIOKafkaConsumer | None = None
        self._stop = asyncio.Event()
        self._sem = asyncio.Semaphore(self._concurrency)

    async def start(self) -> None:
        cfg = get_settings().kafka
        kwargs: dict[str, Any] = dict(
            bootstrap_servers=cfg.bootstrap_servers,
            client_id=f"{cfg.client_id}-{socket.gethostname()}",
            group_id=self._group,
            enable_auto_commit=False,
            isolation_level="read_committed",
            session_timeout_ms=cfg.session_timeout_ms,
            heartbeat_interval_ms=3_000,
            max_poll_records=cfg.max_poll_records,
            auto_offset_reset="earliest",
        )
        if cfg.security_protocol.value != "PLAINTEXT":
            kwargs["security_protocol"] = cfg.security_protocol.value
            if cfg.sasl_mechanism:
                kwargs["sasl_mechanism"] = cfg.sasl_mechanism
                kwargs["sasl_plain_username"] = cfg.sasl_username
                kwargs["sasl_plain_password"] = (
                    cfg.sasl_password.get_secret_value() if cfg.sasl_password else None
                )
        self._consumer = AIOKafkaConsumer(*self._topics, **kwargs)
        await self._consumer.start()
        log.info("kafka.consumer.started", topics=self._topics, group=self._group)

    async def stop(self) -> None:
        self._stop.set()
        if self._consumer is not None:
            try:
                await self._consumer.stop()
            finally:
                self._consumer = None

    async def run(self) -> None:
        if self._consumer is None:
            await self._start_with_retry()

        assert self._consumer is not None
        try:
            while not self._stop.is_set():
                records = await self._consumer.getmany(timeout_ms=1000)
                if not records:
                    continue
                await self._process_batch(records)
        finally:
            await self.stop()

    async def _start_with_retry(self, *, attempts: int = 5, backoff: float = 1.0) -> None:
        last_err: Exception | None = None
        for n in range(1, attempts + 1):
            try:
                await self.start()
                return
            except Exception as e:  # noqa: BLE001
                last_err = e
                log.warning("kafka.consumer.start_failed", attempt=n, error=str(e))
                await asyncio.sleep(backoff * n)
        raise RuntimeError(f"Could not start consumer after {attempts} attempts") from last_err

    # ----------------------------------------------------- batch

    async def _process_batch(
        self, batch: dict[TopicPartition, list[ConsumerRecord]]
    ) -> None:
        tasks = []
        for tp, records in batch.items():
            for record in records:
                tasks.append(self._process_one(tp, record))
        # Bounded concurrency via semaphore inside _process_one.
        await asyncio.gather(*tasks, return_exceptions=False)

        # Commit offsets only after all sagas finished. The combination
        # of `read_committed` isolation + outbox writes guarantees we
        # don't double-emit.
        offsets = {
            tp: records[-1].offset + 1 for tp, records in batch.items() if records
        }
        if offsets and self._consumer is not None:
            await self._consumer.commit(offsets)

    async def _process_one(self, tp: TopicPartition, record: ConsumerRecord) -> None:
        async with self._sem:
            metrics.kafka_consumer_lag.labels(tp.topic, str(tp.partition)).set(0)
            headers = headers_to_dict(record.headers or [])
            otel_ctx = extract(headers)
            with tracer.start_as_current_span(
                f"consume.{tp.topic}",
                context=otel_ctx,
                attributes={
                    "messaging.system": "kafka",
                    "messaging.destination.name": tp.topic,
                    "messaging.kafka.message.offset": record.offset,
                    "messaging.kafka.partition": tp.partition,
                },
            ):
                bind_correlation(headers.get("correlation_id"))
                try:
                    raw = orjson.loads(record.value or b"{}")
                    envelope = parse_event(raw)
                    await self._handler(envelope)
                    metrics.kafka_messages_consumed_total.labels(tp.topic, "ok").inc()
                except AppError as e:
                    metrics.kafka_messages_consumed_total.labels(tp.topic, "domain_error").inc()
                    log.error(
                        "consumer.handler.error",
                        topic=tp.topic, offset=record.offset,
                        code=e.code, error=e.message,
                    )
                    if not getattr(e, "retryable", False):
                        await self._send_to_dlq(tp, record, e, headers)
                except Exception as e:  # noqa: BLE001
                    metrics.kafka_messages_consumed_total.labels(tp.topic, "fatal").inc()
                    log.error(
                        "consumer.handler.fatal",
                        topic=tp.topic, offset=record.offset,
                        error=str(e), stack=traceback.format_exc(),
                    )
                    await self._send_to_dlq(tp, record, e, headers)
                finally:
                    clear_context()

    async def _send_to_dlq(
        self,
        tp: TopicPartition,
        record: ConsumerRecord,
        error: Exception,
        headers: dict[str, str],
    ) -> None:
        try:
            await self._publisher.publish_to_dlq(
                original_topic=tp.topic,
                original_partition=tp.partition,
                original_offset=record.offset,
                original_event_type=headers.get("event_type", "unknown"),
                original_payload=record.value or b"",
                original_headers=headers,
                reason=type(error).__name__,
                stack=traceback.format_exc(),
            )
        except Exception as dlq_err:  # noqa: BLE001
            log.critical("consumer.dlq.publish_failed", error=str(dlq_err))


__all__ = ["KafkaConsumerRunner", "MessageHandler", "TopicPartition", "Iterable"]
