from __future__ import annotations

from services.tunnel_orchestrator.application.ports import CloudflareProviderRegistry
from services.tunnel_orchestrator.application.sagas.base import SagaContext, SagaStep
from services.tunnel_orchestrator.application.sagas.context import CreateTunnelSagaData
from services.tunnel_orchestrator.domain.value_objects import TenantIdVO


class ConfigureIngressStep(SagaStep[CreateTunnelSagaData]):
    """Install the ingress configuration on the (remote-managed) tunnel.

    Compensation **resets** the ingress to a catch-all-only minimum so
    no traffic can flow even if the saga partially undid other resources
    before the rollback completed.
    """

    name = "configure_ingress"

    def __init__(self, cf_registry: CloudflareProviderRegistry) -> None:
        self._cf = cf_registry

    async def execute(self, ctx: SagaContext[CreateTunnelSagaData]) -> dict[str, object]:
        if not ctx.data.cf_tunnel_id:
            raise RuntimeError("cf_tunnel_id missing — wrong step ordering")
        provider = await self._cf.get(TenantIdVO(ctx.tenant_id))
        await provider.put_ingress_configuration(
            ctx.data.cf_tunnel_id, ctx.data.tunnel.ingress
        )
        return {"rules": len(ctx.data.tunnel.ingress.rules)}

    async def compensate(self, ctx: SagaContext[CreateTunnelSagaData]) -> None:
        if not ctx.data.cf_tunnel_id:
            return
        provider = await self._cf.get(TenantIdVO(ctx.tenant_id))
        await provider.reset_ingress_configuration(ctx.data.cf_tunnel_id)
        ctx.data.compensations_executed.append(self.name)
