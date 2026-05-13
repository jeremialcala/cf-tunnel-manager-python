from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any
from uuid import UUID


class AuditLogger(ABC):
    @abstractmethod
    async def record(
        self,
        *,
        actor: str,
        tenant_id: UUID,
        action: str,
        resource: str,
        outcome: str,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        correlation_id: str | None = None,
        ts: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None: ...
