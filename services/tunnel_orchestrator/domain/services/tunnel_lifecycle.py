"""Domain service: pure business rules around tunnel lifecycle.

A *domain service* lives at the seam where invariants span multiple
aggregates or where logic does not belong inside a single aggregate.
This module is **stateless** and has no I/O dependencies.
"""

from __future__ import annotations

from services.tunnel_orchestrator.domain.aggregates import Tenant, Tunnel, TunnelStatus
from services.tunnel_orchestrator.domain.value_objects import Hostname, IngressRuleSet


class TunnelLifecycleService:
    """Business policy enforced *before* the application layer mutates state."""

    @staticmethod
    def authorize_creation(
        tenant: Tenant, hostname: Hostname, cf_zone_id: str, current_count: int
    ) -> None:
        """Raise if the tenant cannot create another tunnel with this config."""
        from shared.errors import (
            CrossTenantAccessDenied,
            TenantNotFound,
            ValidationError,
        )

        if tenant is None:
            raise TenantNotFound("Tenant not found")
        if tenant.status.value != "ACTIVE":
            raise ValidationError(f"Tenant is {tenant.status.value}")
        if not tenant.authorises_zone(cf_zone_id):
            raise CrossTenantAccessDenied(
                f"Tenant {tenant.id} not authorised on zone {cf_zone_id}"
            )
        if current_count >= tenant.quota_max_tunnels:
            raise ValidationError(
                f"Tunnel quota exceeded ({current_count}/{tenant.quota_max_tunnels})"
            )

    @staticmethod
    def is_safe_to_delete(tunnel: Tunnel) -> bool:
        """A tunnel is deletable when not currently being mutated."""
        return tunnel.status in (
            TunnelStatus.READY,
            TunnelStatus.FAILED,
            TunnelStatus.REQUESTED,
        )

    @staticmethod
    def normalise_ingress_for_hostname(
        hostname: Hostname, ingress: IngressRuleSet
    ) -> IngressRuleSet:
        """If the caller did not pin the rule to the hostname, do it for them.

        This is the single place where we decide that a 'simple' user
        intent (just give me a hostname → service) becomes a fully
        qualified rule set.
        """
        rules = list(ingress.rules)
        first = rules[0]
        if first.hostname is None and not first.is_catch_all:
            from services.tunnel_orchestrator.domain.value_objects.ingress_rule import (
                IngressRule,
            )

            rules[0] = IngressRule(
                service=first.service,
                hostname=str(hostname),
                path=first.path,
                origin_request=first.origin_request,
            )
        return IngressRuleSet(tuple(rules))
