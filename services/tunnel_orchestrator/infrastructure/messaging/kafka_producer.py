"""Idempotent / transactional Kafka producer + outbox publisher.

The :class:`AioKafkaPublisher` is what application code calls. Internal
implementation:

* one shared :class:`AIOKafkaProducer` per process (idempotent, acks=all);
* :meth:`publish` writes to the outbox table — the relay loop drains it.

For the outbox relay we expose :meth:`send_raw` (already serialised
payload + headers) so it can publish without re-validating.
"""

from __future__ import annotations

import asyncio
import base64
import socket
from typing import Any

import orjson
from aiokafka import AIOKafkaProducer

from cloud_platform.events.envelope import EventEnvelope
from cloud_platform.events.headers import headers_from_envelope
from cloud_platform.events.payloads import TunnelDlqPayload
from cloud_platform.events.topics import Topic
from shared.config import get_settings
from shared.errors import MessagingError
from shared.logging import get_logger
from shared.types import utcnow
from services.tunnel_orchestrator.application.ports import EventPublisher
from services.tunnel_orchestrator.infrastructure.persistence.database import Database
from services.tunnel_orchestrator.infrastructure.persistence.outbox import PgOutboxStore

log = get_logger(__name__)


class KafkaProducerFactory:
    """Owns the ``AIOKafkaProducer`` lifecycle."""

    def __init__(self) -> None:
        self._producer: AIOKafkaProducer | None = None

    async def start(self) -> AIOKafkaProducer:
        if self._producer is not None:
            return self._producer

        cfg = get_settings().kafka
        kwargs: dict[str, Any] = dict(
            bootstrap_servers=cfg.bootstrap_servers,
            client_id=f"{cfg.client_id}-{socket.gethostname()}",
            enable_idempotence=cfg.enable_idempotence,
            acks=cfg.acks,
            compression_type=cfg.compression_type,
            request_timeout_ms=30_000,
            linger_ms=20,
            max_request_size=2_097_152,
        )
        if cfg.security_protocol.value != "PLAINTEXT":
            kwargs["security_protocol"] = cfg.security_protocol.value
            if cfg.sasl_mechanism:
                kwargs["sasl_mechanism"] = cfg.sasl_mechanism
                kwargs["sasl_plain_username"] = cfg.sasl_username
                kwargs["sasl_plain_password"] = (
                    cfg.sasl_password.get_secret_value() if cfg.sasl_password else None
                )
        self._producer = AIOKafkaProducer(**kwargs)
        await self._producer.start()
        log.info("kafka.producer.started", bootstrap=cfg.bootstrap_servers)
        return self._producer

    async def stop(self) -> None:
        if self._producer is not None:
            try:
                await self._producer.flush()
            finally:
                await self._producer.stop()
                self._producer = None

    def producer(self) -> AIOKafkaProducer:
        if self._producer is None:
            raise RuntimeError("KafkaProducerFactory not started")
        return self._producer


class AioKafkaPublisher(EventPublisher):
    """Publishes via the **transactional outbox**.

    Domain code never hits Kafka directly — keeps the dual-write
    problem at bay.
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    async def publish(
        self,
        topic: Topic,
        envelope: EventEnvelope[Any],
        *,
        key: str | bytes | None = None,
    ) -> None:
        key_bytes = key.encode() if isinstance(key, str) else key
        async with self._db.session_factory() as session:
            store = PgOutboxStore(session)
            await store.append(topic=topic, envelope=envelope, key=key_bytes)
            await session.commit()

    async def publish_to_dlq(
        self,
        original_topic: str,
        original_partition: int,
        original_offset: int,
        original_event_type: str,
        original_payload: bytes,
        original_headers: dict[str, str],
        reason: str,
        stack: str | None = None,
        attempts: int = 1,
    ) -> None:
        from cloud_platform.events.envelope import build_envelope
        from uuid import UUID

        tenant_str = original_headers.get("tenant_id")
        try:
            tenant_uuid = UUID(tenant_str) if tenant_str else UUID(int=0)
        except ValueError:
            tenant_uuid = UUID(int=0)

        payload = TunnelDlqPayload(
            original_topic=original_topic,
            original_partition=original_partition,
            original_offset=original_offset,
            original_event_type=original_event_type or "unknown",
            original_payload_b64=base64.b64encode(original_payload).decode(),
            original_headers=original_headers,
            dlq_reason=reason,
            dlq_stack=stack,
            first_seen_at=utcnow(),
            attempts=attempts,
        )
        env = build_envelope(
            payload=payload,
            event_type="tunnel.dlq.v1",
            tenant_id=tenant_uuid,
            producer="tunnel-orchestrator/dlq",
            correlation_id=original_headers.get("correlation_id"),
            causation_id=original_headers.get("event_id"),
        )
        await self.publish(Topic.DLQ, env, key=tenant_str)


# ---------- relay sender (used by OutboxRelay.run) ----------


class DirectKafkaSender:
    """Adapter that lets ``OutboxRelay`` push raw outbox rows into Kafka."""

    def __init__(self, factory: KafkaProducerFactory) -> None:
        self._factory = factory

    async def __call__(
        self, topic: str, key: bytes | None, payload: bytes, headers: dict[str, str]
    ) -> None:
        producer = self._factory.producer()
        try:
            await producer.send_and_wait(
                topic=topic,
                key=key,
                value=payload,
                headers=[(k, v.encode()) for k, v in (headers or {}).items()],
            )
        except Exception as e:  # noqa: BLE001
            raise MessagingError(f"Kafka send failed for topic {topic}", cause=e) from e


# Used by callers to keep the import surface small
__all__ = ["AioKafkaPublisher", "KafkaProducerFactory", "DirectKafkaSender", "orjson"]
