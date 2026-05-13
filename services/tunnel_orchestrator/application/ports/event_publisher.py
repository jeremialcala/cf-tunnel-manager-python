from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from platform.events.envelope import EventEnvelope
from platform.events.topics import Topic


class EventPublisher(ABC):
    """Outgoing event boundary.

    Implementations route events through the **transactional outbox** —
    a write goes to the outbox table inside the saga's DB transaction;
    a relay process drains the outbox into Kafka transactionally.
    """

    @abstractmethod
    async def publish(
        self,
        topic: Topic,
        envelope: EventEnvelope[Any],
        *,
        key: str | bytes | None = None,
    ) -> None: ...

    @abstractmethod
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
    ) -> None: ...
