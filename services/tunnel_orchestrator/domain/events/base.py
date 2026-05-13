"""Base class for domain events.

Domain events are **immutable** facts. They live in the domain layer
and have **no transport concerns** — wrapping them in a Kafka envelope
is the application/infrastructure layer's job.
"""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from shared.types import EventId, new_event_id, utcnow


class DomainEvent(BaseModel):
    """All domain events inherit this base.

    Subclasses set :pyattr:`event_type` and :pyattr:`event_version` as
    class-level constants to keep the schema explicit.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)

    event_id: EventId = Field(default_factory=new_event_id)
    occurred_at: datetime = Field(default_factory=utcnow)
    aggregate_id: UUID
    tenant_id: UUID

    event_type: ClassVar[str] = "domain.event"
    event_version: ClassVar[int] = 1

    def envelope_metadata(self) -> dict[str, str]:
        """Return values that should populate the outer Kafka envelope."""
        return {
            "event_id": str(self.event_id),
            "event_type": self.event_type,
            "event_version": str(self.event_version),
            "occurred_at": self.occurred_at.isoformat(),
            "tenant_id": str(self.tenant_id),
            "aggregate_id": str(self.aggregate_id),
        }
