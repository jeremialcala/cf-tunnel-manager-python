"""DeleteTunnelSaga.

Delete is naturally inverse to create. There is **no** compensation
because the steps are themselves "compensations" of the create flow:

1. Delete Kubernetes Deployment.
2. Delete Kubernetes Secret.
3. Delete Cloudflare DNS record.
4. Reset Cloudflare ingress to catch-all.
5. Delete Cloudflare tunnel.

If a step fails we surface the error; ops re-runs the saga (it is
idempotent because each step swallows ``404 Not Found``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.tunnel_orchestrator.application.ports import (
    CloudflareProviderRegistry,
    KubernetesProvider,
)
from services.tunnel_orchestrator.application.sagas.base import (
    SagaContext,
    SagaInstanceStore,
    SagaOrchestrator,
    SagaStep,
)
from services.tunnel_orchestrator.application.sagas.context import DeleteTunnelSagaData
from services.tunnel_orchestrator.domain.value_objects import TenantIdVO


# ---- steps (delete is purely forward — no compensations) ----


class DeleteK8sDeploymentStep(SagaStep[DeleteTunnelSagaData]):
    name = "delete_k8s_deployment"

    def __init__(self, k8s: KubernetesProvider) -> None:
        self._k8s = k8s

    async def execute(self, ctx: SagaContext[DeleteTunnelSagaData]) -> None:
        if ctx.data.tunnel.deployment_name:
            await self._k8s.delete_deployment(
                ctx.data.tunnel.namespace, ctx.data.tunnel.deployment_name
            )


class DeleteK8sSecretStep(SagaStep[DeleteTunnelSagaData]):
    name = "delete_k8s_secret"

    def __init__(self, k8s: KubernetesProvider) -> None:
        self._k8s = k8s

    async def execute(self, ctx: SagaContext[DeleteTunnelSagaData]) -> None:
        if ctx.data.tunnel.secret_name:
            await self._k8s.delete_secret(
                ctx.data.tunnel.namespace, ctx.data.tunnel.secret_name
            )


class DeleteDnsRecordStep(SagaStep[DeleteTunnelSagaData]):
    name = "delete_dns_record"

    def __init__(self, cf_registry: CloudflareProviderRegistry) -> None:
        self._cf = cf_registry

    async def execute(self, ctx: SagaContext[DeleteTunnelSagaData]) -> Any:
        provider = await self._cf.get(TenantIdVO(ctx.tenant_id))
        record_id = ctx.data.tunnel.cf_dns_record_id
        if not record_id:
            record_id = await provider.find_dns_record_id(
                ctx.data.cf_zone_id, ctx.data.tunnel.hostname
            )
        if record_id:
            await provider.delete_dns_record(ctx.data.cf_zone_id, record_id)
        return {"record_id": record_id}


class ResetCloudflareIngressStep(SagaStep[DeleteTunnelSagaData]):
    name = "reset_cloudflare_ingress"

    def __init__(self, cf_registry: CloudflareProviderRegistry) -> None:
        self._cf = cf_registry

    async def execute(self, ctx: SagaContext[DeleteTunnelSagaData]) -> None:
        if ctx.data.tunnel.cf_tunnel_id:
            provider = await self._cf.get(TenantIdVO(ctx.tenant_id))
            await provider.reset_ingress_configuration(ctx.data.tunnel.cf_tunnel_id)


class DeleteCloudflareTunnelStep(SagaStep[DeleteTunnelSagaData]):
    name = "delete_cloudflare_tunnel"

    def __init__(self, cf_registry: CloudflareProviderRegistry) -> None:
        self._cf = cf_registry

    async def execute(self, ctx: SagaContext[DeleteTunnelSagaData]) -> None:
        if ctx.data.tunnel.cf_tunnel_id:
            provider = await self._cf.get(TenantIdVO(ctx.tenant_id))
            await provider.delete_tunnel(ctx.data.tunnel.cf_tunnel_id)


# ---- assembler ----


@dataclass(frozen=True, slots=True)
class DeleteTunnelSagaDeps:
    cf_registry: CloudflareProviderRegistry
    k8s: KubernetesProvider
    store: SagaInstanceStore


class DeleteTunnelSaga:
    SAGA_TYPE = "delete_tunnel"

    def __init__(self, deps: DeleteTunnelSagaDeps) -> None:
        self._deps = deps

    def build(self) -> SagaOrchestrator[DeleteTunnelSagaData]:
        from shared.config import get_settings
        settings = get_settings().resilience
        steps = [
            DeleteK8sDeploymentStep(self._deps.k8s),
            DeleteK8sSecretStep(self._deps.k8s),
            DeleteDnsRecordStep(self._deps.cf_registry),
            ResetCloudflareIngressStep(self._deps.cf_registry),
            DeleteCloudflareTunnelStep(self._deps.cf_registry),
        ]
        return SagaOrchestrator(
            saga_type=self.SAGA_TYPE,
            steps=steps,
            store=self._deps.store,
            step_timeout_seconds=settings.saga_step_timeout_seconds,
            global_timeout_seconds=settings.saga_global_timeout_seconds,
        )
