from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4


@dataclass(frozen=True, slots=True)
class TunnelIdVO:
    """Internal tunnel identifier (UUID v4).

    Distinct from the upstream Cloudflare tunnel id (``cf_tunnel_id``)
    which is allocated by Cloudflare and stored separately on the
    aggregate.
    """

    value: UUID

    @classmethod
    def new(cls) -> "TunnelIdVO":
        return cls(uuid4())

    @classmethod
    def parse(cls, raw: str | UUID) -> "TunnelIdVO":
        return cls(raw if isinstance(raw, UUID) else UUID(str(raw)))

    def __str__(self) -> str:  # pragma: no cover
        return str(self.value)
