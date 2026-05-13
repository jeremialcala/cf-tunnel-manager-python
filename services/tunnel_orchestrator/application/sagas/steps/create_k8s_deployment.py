from __future__ import annotations

from shared.config import get_settings
from services.tunnel_orchestrator.application.ports import KubernetesProvider
from services.tunnel_orchestrator.application.ports.kubernetes_provider import (
    CloudflaredDeploymentSpec,
)
from services.tunnel_orchestrator.application.sagas.base import SagaContext, SagaStep
from services.tunnel_orchestrator.application.sagas.context import CreateTunnelSagaData


class CreateK8sDeploymentStep(SagaStep[CreateTunnelSagaData]):
    """Create / upsert the **independent** cloudflared Deployment.

    *Never* a sidecar — explicit hard requirement of the platform.
    """

    name = "create_k8s_deployment"

    def __init__(self, k8s: KubernetesProvider) -> None:
        self._k8s = k8s

    async def execute(self, ctx: SagaContext[CreateTunnelSagaData]) -> str:
        if not ctx.data.secret_name:
            raise RuntimeError("secret_name missing — create_k8s_secret must run first")

        settings = get_settings().kubernetes
        deployment_name = self._deployment_name(ctx)
        spec = CloudflaredDeploymentSpec(
            namespace=ctx.data.namespace,
            name=deployment_name,
            image=ctx.data.image or settings.cloudflared_image,
            replicas=ctx.data.replicas or settings.cloudflared_replicas,
            secret_name=ctx.data.secret_name,
            cpu_request=settings.cpu_request,
            cpu_limit=settings.cpu_limit,
            mem_request=settings.mem_request,
            mem_limit=settings.mem_limit,
            extra_labels={
                "tunnel-orchestrator.io/tunnel-id": str(ctx.data.tunnel.id.value),
                "tunnel-orchestrator.io/tenant-id": str(ctx.tenant_id),
                "tunnel-orchestrator.io/cf-tunnel-id": ctx.data.cf_tunnel_id or "",
            },
            extra_annotations={
                "tunnel-orchestrator.io/saga-id": str(ctx.saga_id),
                "tunnel-orchestrator.io/correlation-id": ctx.correlation_id,
            },
        )
        await self._k8s.apply_cloudflared_deployment(spec)
        ctx.data.deployment_name = deployment_name
        ctx.data.tunnel.attach_kubernetes_resources(
            deployment=deployment_name, secret=ctx.data.secret_name
        )
        return deployment_name

    async def compensate(self, ctx: SagaContext[CreateTunnelSagaData]) -> None:
        if not ctx.data.deployment_name:
            return
        await self._k8s.delete_deployment(ctx.data.namespace, ctx.data.deployment_name)
        ctx.data.compensations_executed.append(self.name)

    @staticmethod
    def _deployment_name(ctx: SagaContext[CreateTunnelSagaData]) -> str:
        return f"cloudflared-{ctx.data.tunnel.id.value.hex[:12]}"
