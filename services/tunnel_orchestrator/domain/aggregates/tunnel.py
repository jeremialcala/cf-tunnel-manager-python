"""Tunnel aggregate root.

The :class:`Tunnel` aggregate guards the lifecycle invariants of one
Cloudflare Tunnel + the resources backing it (DNS record, Kubernetes
secret, Kubernetes deployment).

State machine
-------------

::

    REQUESTED ──► PROVISIONING ──► READY ──► VALIDATING ──► READY
                       │             │
                       ├─► FAILED ◄──┘
                       │
                       └─► COMPENSATING ──► DELETED
                                            │
                                            └─► FAILED   (compensation failure)

The aggregate exposes :pymeth:`mark_*` methods that perform the
state transitions and append the corresponding domain events to its
outgoing ``_pending_events`` buffer. Persistence repositories drain that
buffer when committing the unit of work.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Self
from uuid import UUID

from shared.errors import InvalidIngressRule
from shared.types import utcnow
from services.tunnel_orchestrator.domain.events.base import DomainEvent
from services.tunnel_orchestrator.domain.events.tunnel_events import (
    TunnelCreated,
    TunnelCreationFailed,
    TunnelCreationRequested,
    TunnelDeleted,
    TunnelValidated,
    TunnelValidationFailed,
)
from services.tunnel_orchestrator.domain.value_objects.dns_record import DnsRecord
from services.tunnel_orchestrator.domain.value_objects.hostname import Hostname
from services.tunnel_orchestrator.domain.value_objects.ingress_rule import IngressRuleSet
from services.tunnel_orchestrator.domain.value_objects.tenant_id import TenantIdVO
from services.tunnel_orchestrator.domain.value_objects.tunnel_id import TunnelIdVO


class TunnelStatus(str, Enum):
    REQUESTED = "REQUESTED"
    PROVISIONING = "PROVISIONING"
    READY = "READY"
    VALIDATING = "VALIDATING"
    COMPENSATING = "COMPENSATING"
    DELETED = "DELETED"
    FAILED = "FAILED"


@dataclass(slots=True)
class Tunnel:
    id: TunnelIdVO
    tenant_id: TenantIdVO
    hostname: Hostname
    ingress: IngressRuleSet
    cf_zone_id: str
    cluster: str
    namespace: str
    status: TunnelStatus = TunnelStatus.REQUESTED
    cf_tunnel_id: str | None = None
    cf_dns_record_id: str | None = None
    deployment_name: str | None = None
    secret_name: str | None = None
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
    last_error: str | None = None
    version: int = 1                                # optimistic concurrency token
    _pending_events: list[DomainEvent] = field(default_factory=list, repr=False)

    # ----------------------------------------------------- factories

    @classmethod
    def request(
        cls,
        *,
        tenant_id: TenantIdVO,
        hostname: Hostname,
        ingress: IngressRuleSet,
        cf_zone_id: str,
        cluster: str,
        namespace: str,
        requested_by: str | None = None,
    ) -> Self:
        if not ingress.rules:
            raise InvalidIngressRule("at least one rule required")
        t = cls(
            id=TunnelIdVO.new(),
            tenant_id=tenant_id,
            hostname=hostname,
            ingress=ingress,
            cf_zone_id=cf_zone_id,
            cluster=cluster,
            namespace=namespace,
        )
        t._pending_events.append(
            TunnelCreationRequested(
                aggregate_id=t.id.value,
                tenant_id=t.tenant_id.value,
                hostname=str(hostname),
                target_service=ingress.rules[0].service,
                cluster=cluster,
                requested_by=requested_by,
            )
        )
        return t

    # ----------------------------------------------------- transitions

    def begin_provisioning(self) -> None:
        self._require(TunnelStatus.REQUESTED)
        self.status = TunnelStatus.PROVISIONING
        self._touch()

    def attach_cloudflare_tunnel(self, cf_tunnel_id: str) -> None:
        self._require(TunnelStatus.PROVISIONING)
        self.cf_tunnel_id = cf_tunnel_id
        self._touch()

    def attach_dns_record(self, record_id: str) -> None:
        self._require(TunnelStatus.PROVISIONING)
        self.cf_dns_record_id = record_id
        self._touch()

    def attach_kubernetes_resources(self, *, deployment: str, secret: str) -> None:
        self._require(TunnelStatus.PROVISIONING)
        self.deployment_name = deployment
        self.secret_name = secret
        self._touch()

    def mark_ready(self) -> None:
        self._require(TunnelStatus.PROVISIONING, TunnelStatus.VALIDATING)
        self.status = TunnelStatus.READY
        self.last_error = None
        self._touch()
        self._pending_events.append(
            TunnelCreated(
                aggregate_id=self.id.value,
                tenant_id=self.tenant_id.value,
                cf_tunnel_id=self._cf_tunnel_id_or_raise(),
                hostname=str(self.hostname),
                cluster=self.cluster,
                namespace=self.namespace,
                deployment_name=self.deployment_name or "",
            )
        )

    def begin_validation(self) -> None:
        self._require(TunnelStatus.READY)
        self.status = TunnelStatus.VALIDATING
        self._touch()

    def mark_validation_ok(self, latency_ms: float | None = None) -> None:
        self._require(TunnelStatus.VALIDATING)
        self.status = TunnelStatus.READY
        self._touch()
        self._pending_events.append(
            TunnelValidated(
                aggregate_id=self.id.value,
                tenant_id=self.tenant_id.value,
                cf_tunnel_id=self._cf_tunnel_id_or_raise(),
                hostname=str(self.hostname),
                dns_ok=True,
                http_ok=True,
                latency_ms=latency_ms,
            )
        )

    def mark_validation_failed(self, reason: str) -> None:
        self._require(TunnelStatus.VALIDATING)
        self.status = TunnelStatus.FAILED
        self.last_error = reason
        self._touch()
        self._pending_events.append(
            TunnelValidationFailed(
                aggregate_id=self.id.value,
                tenant_id=self.tenant_id.value,
                cf_tunnel_id=self._cf_tunnel_id_or_raise(),
                hostname=str(self.hostname),
                reason=reason,
            )
        )

    def begin_compensation(self) -> None:
        self.status = TunnelStatus.COMPENSATING
        self._touch()

    def mark_failed(self, *, step: str, code: str, message: str, compensations: list[str]) -> None:
        self.status = TunnelStatus.FAILED
        self.last_error = f"{code}: {message}"
        self._touch()
        self._pending_events.append(
            TunnelCreationFailed(
                aggregate_id=self.id.value,
                tenant_id=self.tenant_id.value,
                hostname=str(self.hostname),
                failed_step=step,
                error_code=code,
                error_message=message,
                compensations_run=compensations,
            )
        )

    def mark_deleted(self) -> None:
        self.status = TunnelStatus.DELETED
        self._touch()
        self._pending_events.append(
            TunnelDeleted(
                aggregate_id=self.id.value,
                tenant_id=self.tenant_id.value,
                cf_tunnel_id=self._cf_tunnel_id_or_raise(),
                hostname=str(self.hostname),
            )
        )

    # ------------------------------------------------ unit-of-work helpers

    def pull_pending_events(self) -> list[DomainEvent]:
        events, self._pending_events = self._pending_events, []
        return events

    # --------------------------------------------------------- internals

    def _require(self, *allowed: TunnelStatus) -> None:
        if self.status not in allowed:
            raise ValueError(
                f"Invalid transition: tunnel {self.id} is {self.status}, expected one of {allowed}"
            )

    def _touch(self) -> None:
        self.updated_at = utcnow()
        self.version += 1

    def _cf_tunnel_id_or_raise(self) -> str:
        if not self.cf_tunnel_id:
            raise RuntimeError("cf_tunnel_id is not yet attached to this Tunnel")
        return self.cf_tunnel_id


# Convenience for repository hydration: rebuild from a row without
# replaying transitions (does not append events).
def hydrate_tunnel(
    *,
    id: UUID,
    tenant_id: UUID,
    hostname: str,
    ingress: IngressRuleSet,
    cf_zone_id: str,
    cluster: str,
    namespace: str,
    status: str,
    cf_tunnel_id: str | None,
    cf_dns_record_id: str | None,
    deployment_name: str | None,
    secret_name: str | None,
    created_at: datetime,
    updated_at: datetime,
    last_error: str | None,
    version: int,
) -> Tunnel:
    return Tunnel(
        id=TunnelIdVO(id),
        tenant_id=TenantIdVO(tenant_id),
        hostname=Hostname(hostname),
        ingress=ingress,
        cf_zone_id=cf_zone_id,
        cluster=cluster,
        namespace=namespace,
        status=TunnelStatus(status),
        cf_tunnel_id=cf_tunnel_id,
        cf_dns_record_id=cf_dns_record_id,
        deployment_name=deployment_name,
        secret_name=secret_name,
        created_at=created_at,
        updated_at=updated_at,
        last_error=last_error,
        version=version,
    )
