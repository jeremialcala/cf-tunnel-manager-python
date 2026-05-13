from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4


@dataclass(frozen=True, slots=True)
class TenantIdVO:
    """Value object wrapper around a UUID v4 tenant identifier."""

    value: UUID

    @classmethod
    def new(cls) -> "TenantIdVO":
        return cls(uuid4())

    @classmethod
    def parse(cls, raw: str | UUID) -> "TenantIdVO":
        return cls(raw if isinstance(raw, UUID) else UUID(str(raw)))

    def __str__(self) -> str:  # pragma: no cover
        return str(self.value)
