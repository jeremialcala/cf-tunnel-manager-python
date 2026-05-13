"""Tenant aggregate.

A *Tenant* is the unit of isolation: each owns a Cloudflare account and
a Kubernetes namespace. The aggregate stores **references** to secrets
(Vault paths) rather than the secrets themselves — secret material is
loaded only by infrastructure adapters at the moment of use.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Self

from shared.types import utcnow
from services.tunnel_orchestrator.domain.value_objects.tenant_id import TenantIdVO


class TenantStatus(str, Enum):
    PROVISIONING = "PROVISIONING"
    ACTIVE       = "ACTIVE"
    SUSPENDED    = "SUSPENDED"
    ARCHIVED     = "ARCHIVED"


@dataclass(slots=True)
class Tenant:
    """Aggregate root."""

    id: TenantIdVO
    name: str
    slug: str                                   # K8s-safe lowercase, used in namespace
    cf_account_id: str
    cf_token_vault_path: str                    # e.g. "secret/tenants/{id}/cf_token"
    k8s_namespace: str
    k8s_cluster: str = "default"
    cf_zone_ids: list[str] = field(default_factory=list)   # zones this tenant may program
    quota_max_tunnels: int = 200
    status: TenantStatus = TenantStatus.PROVISIONING
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)

    # ------------------------------------------------------ behaviours

    def activate(self) -> None:
        if self.status not in (TenantStatus.PROVISIONING, TenantStatus.SUSPENDED):
            raise ValueError(f"Cannot activate tenant in status {self.status}")
        self.status = TenantStatus.ACTIVE
        self.updated_at = utcnow()

    def suspend(self) -> None:
        if self.status is TenantStatus.ARCHIVED:
            raise ValueError("Cannot suspend archived tenant")
        self.status = TenantStatus.SUSPENDED
        self.updated_at = utcnow()

    def archive(self) -> None:
        self.status = TenantStatus.ARCHIVED
        self.updated_at = utcnow()

    def authorises_zone(self, cf_zone_id: str) -> bool:
        return cf_zone_id in self.cf_zone_ids

    @classmethod
    def new(
        cls,
        *,
        name: str,
        slug: str,
        cf_account_id: str,
        cf_token_vault_path: str,
        k8s_namespace: str | None = None,
        k8s_cluster: str = "default",
        cf_zone_ids: list[str] | None = None,
    ) -> Self:
        return cls(
            id=TenantIdVO.new(),
            name=name,
            slug=slug,
            cf_account_id=cf_account_id,
            cf_token_vault_path=cf_token_vault_path,
            k8s_namespace=k8s_namespace or f"tunnels-{slug}",
            k8s_cluster=k8s_cluster,
            cf_zone_ids=cf_zone_ids or [],
        )
