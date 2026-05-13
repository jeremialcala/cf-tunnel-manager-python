"""Transactional outbox: store + relay loop."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Iterable

import orjson
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from platform.events.envelope import EventEnvelope, build_envelope
from platform.events.headers import headers_from_envelope
from platform.events.topics import Topic
from shared.logging import get_logger
from services.tunnel_orchestrator.domain.events.base import DomainEvent
from services.tunnel_orchestrator.infrastructure.persistence.database import Database
from services.tunnel_orchestrator.infrastructure.persistence.models import OutboxRow

log = get_logger(__name__)


# Topic mapping for domain events → kafka topic
_DOMAIN_TO_TOPIC: dict[str, Topic] = {
    "tunnel.create.requested.v1":   Topic.CREATE_REQUEST,
    "tunnel.created.v1":            Topic.CREATE_SUCCESS,
    "tunnel.creation_failed.v1":    Topic.CREATE_FAILURE,
    "tunnel.delete.requested.v1":   Topic.DELETE_REQUEST,
    "tunnel.deleted.v1":            Topic.DELETE_SUCCESS,
    "tunnel.deletion_failed.v1":    Topic.DELETE_FAILURE,
    "tunnel.validated.v1":          Topic.VALIDATION_SUCCESS,
    "tunnel.validation_failed.v1":  Topic.VALIDATION_FAILURE,
    "tunnel.updated.v1":            Topic.UPDATE_SUCCESS,
    "tunnel.drift_detected.v1":     Topic.AUDIT,
}


class PgOutboxStore:
    """Append-only writer used inside saga / repository transactions."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(
        self,
        *,
        topic: Topic,
        envelope: EventEnvelope[object],
        key: bytes | None,
    ) -> None:
        payload = orjson.dumps(envelope.model_dump(mode="json"))
        headers = {h[0]: h[1].decode() for h in headers_from_envelope(envelope).to_list()}
        self._session.add(
            OutboxRow(
                topic=str(topic),
                key=key,
                payload=payload,
                headers=headers,
                status="PENDING",
            )
        )

    async def append_domain_event(self, evt: DomainEvent) -> None:
        topic = _DOMAIN_TO_TOPIC.get(evt.event_type, Topic.AUDIT)
        env = build_envelope(
            payload=evt,
            event_type=evt.event_type,
            tenant_id=evt.tenant_id,
            producer="tunnel-orchestrator/domain",
            event_version=evt.event_version,
        )
        key = str(evt.aggregate_id).encode()
        await self.append(topic=topic, envelope=env, key=key)


class OutboxRelay:
    """Background loop that drains the outbox into Kafka.

    Runs as part of the worker process. Single-flight per process is
    fine: leadership comes implicitly from each worker's partitioning;
    the same row can never be picked up twice because we mark it
    ``IN_FLIGHT`` with a ``SKIP LOCKED`` ``SELECT FOR UPDATE``.
    """

    def __init__(
        self,
        *,
        db: Database,
        publisher_send,                # noqa: ANN001 — Callable[[topic, key, payload, headers], Awaitable[None]]
        batch_size: int = 100,
        poll_interval_seconds: float = 0.5,
    ) -> None:
        self._db = db
        self._send = publisher_send
        self._batch = batch_size
        self._poll = poll_interval_seconds
        self._stop = asyncio.Event()

    async def run(self) -> None:
        log.info("outbox.relay.started")
        while not self._stop.is_set():
            sent = await self._tick()
            if sent == 0:
                await asyncio.wait_for(self._stop.wait(), timeout=self._poll) if False else \
                    await asyncio.sleep(self._poll)
        log.info("outbox.relay.stopped")

    async def stop(self) -> None:
        self._stop.set()

    async def _tick(self) -> int:
        async with self._db.session_factory() as session:
            rows = await self._claim(session)
            if not rows:
                return 0
            for row in rows:
                try:
                    await self._send(
                        row.topic, row.key, row.payload, row.headers
                    )
                    await session.execute(
                        update(OutboxRow)
                        .where(OutboxRow.id == row.id)
                        .values(status="SENT", sent_at=datetime.utcnow())
                    )
                except Exception as exc:  # noqa: BLE001
                    log.error(
                        "outbox.relay.send_failed",
                        outbox_id=str(row.id),
                        topic=row.topic,
                        error=str(exc),
                    )
                    await session.execute(
                        update(OutboxRow)
                        .where(OutboxRow.id == row.id)
                        .values(
                            status="PENDING",
                            attempts=OutboxRow.attempts + 1,
                            last_error=str(exc)[:1024],
                        )
                    )
            await session.commit()
            return len(rows)

    async def _claim(self, session: AsyncSession) -> list[OutboxRow]:
        # SELECT ... FOR UPDATE SKIP LOCKED so multiple relay loops
        # can run concurrently without double-sending.
        stmt = (
            select(OutboxRow)
            .where(OutboxRow.status == "PENDING")
            .order_by(OutboxRow.scheduled_at.asc())
            .limit(self._batch)
            .with_for_update(skip_locked=True)
        )
        rows = (await session.execute(stmt)).scalars().all()
        if not rows:
            return []
        await session.execute(
            update(OutboxRow)
            .where(OutboxRow.id.in_([r.id for r in rows]))
            .values(status="IN_FLIGHT")
        )
        return list(rows)


# Used by callers that don't want to import Iterable explicitly
_ = Iterable
