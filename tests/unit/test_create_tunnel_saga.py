"""End-to-end test of CreateTunnelSaga with all fakes — validates orchestration logic."""

from __future__ import annotations

import time

import pytest

from services.tunnel_orchestrator.application.sagas import SagaStatus
from services.tunnel_orchestrator.application.sagas.base import (
    SagaContext,
    new_saga_id,
)
from services.tunnel_orchestrator.application.sagas.context import CreateTunnelSagaData
from services.tunnel_orchestrator.application.sagas.create_tunnel_saga import (
    CreateTunnelSaga,
    CreateTunnelSagaDeps,
)
from services.tunnel_orchestrator.domain.aggregates import Tunnel
from services.tunnel_orchestrator.domain.value_objects import IngressRuleSet
from tests.conftest import (
    FakeCloudflareProvider,
    FakeCloudflareRegistry,
    FakeDnsVerifier,
    FakeHttpVerifier,
    FakeKubernetesProvider,
    FakeSagaStore,
)

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


def _build_ctx(tenant, hostname):
    ingress = IngressRuleSet.single(str(hostname), "http://svc.svc.cluster.local:8080")
    tunnel = Tunnel.request(
        tenant_id=tenant.id,
        hostname=hostname,
        ingress=ingress,
        cf_zone_id="zone-1",
        cluster="default",
        namespace="tunnels-acme",
    )
    tunnel.begin_provisioning()
    tunnel.pull_pending_events()  # discard

    return SagaContext[CreateTunnelSagaData](
        saga_id=new_saga_id(),
        correlation_id="corr-1",
        tenant_id=tenant.id.value,
        started_at=time.monotonic(),
        data=CreateTunnelSagaData(
            tunnel=tunnel,
            cf_zone_id="zone-1",
            cluster="default",
            namespace="tunnels-acme",
            image="cloudflare/cloudflared:test",
            replicas=2,
        ),
    )


@pytest.mark.asyncio
async def test_happy_path_succeeds(tenant, hostname):
    cf = FakeCloudflareProvider()
    deps = CreateTunnelSagaDeps(
        cf_registry=FakeCloudflareRegistry(cf),
        k8s=FakeKubernetesProvider(),
        dns_verifier=FakeDnsVerifier(ok=True),
        http_verifier=FakeHttpVerifier(ok=True),
        store=FakeSagaStore(),
    )
    ctx = _build_ctx(tenant, hostname)
    saga = CreateTunnelSaga(deps).build()
    result = await saga.run(ctx)
    assert result.status is SagaStatus.SUCCEEDED
    assert ctx.data.cf_tunnel_id is not None
    assert ctx.data.deployment_name is not None
    assert ctx.data.secret_name is not None
    # ingress was configured
    assert cf.ingress, "ingress configuration was not applied"


@pytest.mark.asyncio
async def test_dns_failure_triggers_full_compensation(tenant, hostname):
    cf = FakeCloudflareProvider()
    k8s = FakeKubernetesProvider()
    deps = CreateTunnelSagaDeps(
        cf_registry=FakeCloudflareRegistry(cf),
        k8s=k8s,
        dns_verifier=FakeDnsVerifier(ok=False),
        http_verifier=FakeHttpVerifier(ok=True),
        store=FakeSagaStore(),
    )
    ctx = _build_ctx(tenant, hostname)
    saga = CreateTunnelSaga(deps).build()
    result = await saga.run(ctx)

    assert result.status is SagaStatus.FAILED
    assert result.failed_step == "verify_dns"
    # all upstream resources cleaned up
    assert not cf.tunnels, "tunnel should have been deleted"
    assert not cf.dns_records, "DNS record should have been deleted"
    assert not k8s.deployments, "deployment should have been deleted"
    assert not k8s.secrets, "secret should have been deleted"
    expected = {
        "configure_ingress",
        "create_dns_record",
        "create_k8s_secret",
        "create_k8s_deployment",
        "create_cloudflare_tunnel",
    }
    assert expected.issubset(set(ctx.data.compensations_executed))


@pytest.mark.asyncio
async def test_deployment_not_ready_triggers_compensation(tenant, hostname):
    cf = FakeCloudflareProvider()
    k8s = FakeKubernetesProvider()
    k8s.always_ready = False
    deps = CreateTunnelSagaDeps(
        cf_registry=FakeCloudflareRegistry(cf),
        k8s=k8s,
        dns_verifier=FakeDnsVerifier(ok=True),
        http_verifier=FakeHttpVerifier(ok=True),
        store=FakeSagaStore(),
    )
    ctx = _build_ctx(tenant, hostname)
    saga = CreateTunnelSaga(deps).build()
    result = await saga.run(ctx)
    assert result.status is SagaStatus.FAILED
    assert result.failed_step == "wait_deployment_ready"
