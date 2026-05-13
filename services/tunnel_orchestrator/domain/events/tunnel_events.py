from __future__ import annotations

from typing import ClassVar
from uuid import UUID

from pydantic import Field

from services.tunnel_orchestrator.domain.events.base import DomainEvent


# ----- Lifecycle: Create -----

class TunnelCreationRequested(DomainEvent):
    event_type: ClassVar[str] = "tunnel.create.requested.v1"

    hostname: str
    target_service: str
    cluster: str | None = None
    requested_by: str | None = None


class TunnelCreated(DomainEvent):
    event_type: ClassVar[str] = "tunnel.created.v1"

    cf_tunnel_id: str
    hostname: str
    cluster: str
    namespace: str
    deployment_name: str


class TunnelCreationFailed(DomainEvent):
    event_type: ClassVar[str] = "tunnel.creation_failed.v1"

    hostname: str
    failed_step: str
    error_code: str
    error_message: str
    compensations_run: list[str] = Field(default_factory=list)


# ----- Lifecycle: Delete -----

class TunnelDeletionRequested(DomainEvent):
    event_type: ClassVar[str] = "tunnel.delete.requested.v1"
    cf_tunnel_id: str
    hostname: str
    requested_by: str | None = None


class TunnelDeleted(DomainEvent):
    event_type: ClassVar[str] = "tunnel.deleted.v1"
    cf_tunnel_id: str
    hostname: str


class TunnelDeletionFailed(DomainEvent):
    event_type: ClassVar[str] = "tunnel.deletion_failed.v1"
    cf_tunnel_id: str
    hostname: str
    failed_step: str
    error_code: str
    error_message: str


# ----- Lifecycle: Update -----

class TunnelUpdated(DomainEvent):
    event_type: ClassVar[str] = "tunnel.updated.v1"
    cf_tunnel_id: str
    changes: dict[str, object]


# ----- Validation -----

class TunnelValidated(DomainEvent):
    event_type: ClassVar[str] = "tunnel.validated.v1"
    cf_tunnel_id: str
    hostname: str
    dns_ok: bool
    http_ok: bool
    latency_ms: float | None = None


class TunnelValidationFailed(DomainEvent):
    event_type: ClassVar[str] = "tunnel.validation_failed.v1"
    cf_tunnel_id: str
    hostname: str
    reason: str


# ----- Reconciliation -----

class TunnelDriftDetected(DomainEvent):
    """Emitted when scheduled reconciliation finds the tunnel state in
    Cloudflare or Kubernetes does not match the orchestrator's view."""

    event_type: ClassVar[str] = "tunnel.drift_detected.v1"
    cf_tunnel_id: str
    drift_type: str
    expected: dict[str, object]
    actual: dict[str, object]


__all__ = [
    "TunnelCreated",
    "TunnelCreationFailed",
    "TunnelCreationRequested",
    "TunnelDeleted",
    "TunnelDeletionFailed",
    "TunnelDeletionRequested",
    "TunnelDriftDetected",
    "TunnelUpdated",
    "TunnelValidated",
    "TunnelValidationFailed",
]


# Re-export to satisfy aggregate type hints elsewhere
TunnelCreationRequested.model_rebuild()
