from __future__ import annotations

from services.tunnel_orchestrator.application.ports import KubernetesProvider
from services.tunnel_orchestrator.application.sagas.base import SagaContext, SagaStep
from services.tunnel_orchestrator.application.sagas.context import CreateTunnelSagaData


class CreateK8sSecretStep(SagaStep[CreateTunnelSagaData]):
    """Create the namespace-scoped Secret holding the cloudflared token.

    The Secret name is deterministic so re-runs are idempotent (the
    provider does upsert).
    """

    name = "create_k8s_secret"

    def __init__(self, k8s: KubernetesProvider) -> None:
        self._k8s = k8s

    async def execute(self, ctx: SagaContext[CreateTunnelSagaData]) -> str:
        if not ctx.data.remote_token:
            raise RuntimeError("remote_token missing — retrieve_token must run first")

        secret_name = self._secret_name(ctx)
        await self._k8s.ensure_namespace(ctx.data.namespace)
        await self._k8s.upsert_secret(
            namespace=ctx.data.namespace,
            name=secret_name,
            data={"TUNNEL_TOKEN": ctx.data.remote_token},
            labels={
                "app.kubernetes.io/managed-by": "tunnel-orchestrator",
                "tunnel-orchestrator.io/tunnel-id": str(ctx.data.tunnel.id.value),
                "tunnel-orchestrator.io/tenant-id": str(ctx.tenant_id),
            },
        )
        ctx.data.secret_name = secret_name
        return secret_name

    async def compensate(self, ctx: SagaContext[CreateTunnelSagaData]) -> None:
        if not ctx.data.secret_name:
            return
        await self._k8s.delete_secret(ctx.data.namespace, ctx.data.secret_name)
        ctx.data.compensations_executed.append(self.name)

    @staticmethod
    def _secret_name(ctx: SagaContext[CreateTunnelSagaData]) -> str:
        return f"cloudflared-token-{ctx.data.tunnel.id.value.hex[:12]}"
