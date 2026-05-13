from __future__ import annotations

from services.tunnel_orchestrator.application.ports import CloudflareProviderRegistry
from services.tunnel_orchestrator.application.sagas.base import SagaContext, SagaStep
from services.tunnel_orchestrator.application.sagas.context import CreateTunnelSagaData
from services.tunnel_orchestrator.domain.value_objects import TenantIdVO


class CreateCloudflareTunnelStep(SagaStep[CreateTunnelSagaData]):
    """Create the remotely-managed tunnel in Cloudflare.

    **Idempotency**: if a tunnel with the same name already exists for
    this account we adopt it (Cloudflare API returns 409). This handles
    the case of a saga retried after a partial success.
    """

    name = "create_cloudflare_tunnel"

    def __init__(self, cf_registry: CloudflareProviderRegistry) -> None:
        self._cf = cf_registry

    async def execute(self, ctx: SagaContext[CreateTunnelSagaData]) -> str:
        provider = await self._cf.get(TenantIdVO(ctx.tenant_id))
        tunnel_name = self._tunnel_name(ctx)
        existing = await provider.find_tunnel_by_name(tunnel_name)
        if existing is not None:
            cf_id = existing.cf_tunnel_id
        else:
            cf_id = (await provider.create_tunnel(name=tunnel_name)).cf_tunnel_id
        ctx.data.cf_tunnel_id = cf_id
        ctx.data.tunnel.attach_cloudflare_tunnel(cf_id)
        return cf_id

    async def compensate(self, ctx: SagaContext[CreateTunnelSagaData]) -> None:
        if not ctx.data.cf_tunnel_id:
            return
        provider = await self._cf.get(TenantIdVO(ctx.tenant_id))
        await provider.delete_tunnel(ctx.data.cf_tunnel_id)
        ctx.data.compensations_executed.append(self.name)

    @staticmethod
    def _tunnel_name(ctx: SagaContext[CreateTunnelSagaData]) -> str:
        # Stable, idempotent name (no random suffix) — re-running adopts it.
        host = str(ctx.data.tunnel.hostname).replace(".", "-")
        return f"to-{ctx.data.tunnel.tenant_id.value.hex[:8]}-{host}"
