"""Typed contexts for the create / delete tunnel sagas."""

from __future__ import annotations

from dataclasses import dataclass, field

from services.tunnel_orchestrator.domain.aggregates import Tunnel


@dataclass
class CreateTunnelSagaData:
    tunnel: Tunnel
    cf_zone_id: str
    cluster: str
    namespace: str
    image: str
    replicas: int

    # Filled in by steps
    cf_tunnel_id: str | None = None
    cf_dns_record_id: str | None = None
    deployment_name: str | None = None
    secret_name: str | None = None
    remote_token: str | None = None
    compensations_executed: list[str] = field(default_factory=list)


@dataclass
class DeleteTunnelSagaData:
    tunnel: Tunnel
    cf_zone_id: str
