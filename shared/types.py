"""Common type aliases and primitive helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, NewType, TypeAlias
from uuid import UUID

from pydantic import AfterValidator, StringConstraints
from ulid import ULID

# ----- ID newtypes (compile-time discrimination, runtime = str) -----

TenantId    = NewType("TenantId", UUID)
TunnelId    = NewType("TunnelId", UUID)
SagaId      = NewType("SagaId", UUID)
EventId     = NewType("EventId", str)        # ULIDs serialise as strings
CorrelationId = NewType("CorrelationId", str)
CausationId   = NewType("CausationId", str)
IdempotencyKey = NewType("IdempotencyKey", str)


# ----- timestamps -----

UtcDatetime: TypeAlias = Annotated[
    datetime,
    AfterValidator(lambda dt: dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)),
]


def utcnow() -> datetime:
    """Timezone-aware UTC ``now`` — the only blessed clock helper."""
    return datetime.now(UTC)


def new_event_id() -> EventId:
    """Monotonic, lexicographically-sortable identifier for events."""
    return EventId(str(ULID()))


def new_correlation_id() -> CorrelationId:
    return CorrelationId(str(ULID()))


# ----- string constraints used by domain primitives -----

NonEmptyStr = Annotated[str, StringConstraints(min_length=1, max_length=512, strip_whitespace=True)]
Slug = Annotated[
    str,
    StringConstraints(min_length=1, max_length=63, pattern=r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$"),
]
HostnameStr = Annotated[
    str,
    StringConstraints(
        min_length=3,
        max_length=253,
        pattern=r"^(?=.{1,253}$)(?:(?!-)[A-Za-z0-9-]{1,63}(?<!-)\.)+[A-Za-z]{2,63}$",
    ),
]
