from __future__ import annotations

import pytest

from services.tunnel_orchestrator.domain.aggregates import Tunnel, TunnelStatus
from services.tunnel_orchestrator.domain.value_objects import (
    Hostname,
    IngressRuleSet,
    TenantIdVO,
)

pytestmark = pytest.mark.unit


def _new(hostname: str = "api.example.com") -> Tunnel:
    h = Hostname.parse(hostname)
    ingress = IngressRuleSet.single(str(h), "http://svc:8000")
    return Tunnel.request(
        tenant_id=TenantIdVO.new(),
        hostname=h,
        ingress=ingress,
        cf_zone_id="zone-1",
        cluster="default",
        namespace="ns",
    )


def test_lifecycle_requested_to_ready():
    t = _new()
    assert t.status is TunnelStatus.REQUESTED
    t.begin_provisioning()
    t.attach_cloudflare_tunnel("cf-x")
    t.attach_dns_record("dns-x")
    t.attach_kubernetes_resources(deployment="d", secret="s")
    t.mark_ready()
    assert t.status is TunnelStatus.READY
    events = t.pull_pending_events()
    types = [e.event_type for e in events]
    assert "tunnel.create.requested.v1" in types
    assert "tunnel.created.v1" in types


def test_invalid_transition_raises():
    t = _new()
    with pytest.raises(ValueError):
        t.mark_ready()


def test_failure_marks_failed_and_emits_event():
    t = _new()
    t.begin_provisioning()
    t.mark_failed(step="x", code="E", message="boom", compensations=["a", "b"])
    assert t.status is TunnelStatus.FAILED
    events = t.pull_pending_events()
    assert any(e.event_type == "tunnel.creation_failed.v1" for e in events)
