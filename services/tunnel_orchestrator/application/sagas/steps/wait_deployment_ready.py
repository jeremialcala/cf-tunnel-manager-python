from __future__ import annotations

import time

from shared.errors import KubernetesAPIError
from shared.observability import metrics
from services.tunnel_orchestrator.application.ports import KubernetesProvider
from services.tunnel_orchestrator.application.sagas.base import SagaContext, SagaStep
from services.tunnel_orchestrator.application.sagas.context import CreateTunnelSagaData


class WaitDeploymentReadyStep(SagaStep[CreateTunnelSagaData]):
    """Block until the cloudflared Deployment reports availableReplicas == replicas."""

    name = "wait_deployment_ready"

    def __init__(self, k8s: KubernetesProvider, *, timeout_seconds: float = 120.0) -> None:
        self._k8s = k8s
        self.timeout_seconds = timeout_seconds

    async def execute(self, ctx: SagaContext[CreateTunnelSagaData]) -> dict[str, object]:
        if not ctx.data.deployment_name:
            raise RuntimeError("deployment_name missing")
        started = time.monotonic()
        ready = await self._k8s.wait_deployment_ready(
            ctx.data.namespace,
            ctx.data.deployment_name,
            timeout_seconds=self.timeout_seconds,
        )
        elapsed = time.monotonic() - started
        metrics.k8s_deployment_ready_seconds.labels(str(ctx.tenant_id)).observe(elapsed)
        if not ready:
            raise KubernetesAPIError(
                f"Deployment {ctx.data.deployment_name} not ready after {elapsed:.1f}s"
            )
        return {"elapsed_seconds": elapsed}
