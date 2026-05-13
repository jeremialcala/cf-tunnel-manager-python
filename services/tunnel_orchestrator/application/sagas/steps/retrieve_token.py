from __future__ import annotations

from services.tunnel_orchestrator.application.ports import CloudflareProviderRegistry
from services.tunnel_orchestrator.application.sagas.base import SagaContext, SagaStep
from services.tunnel_orchestrator.application.sagas.context import CreateTunnelSagaData
from services.tunnel_orchestrator.domain.value_objects import TenantIdVO


class RetrieveTunnelTokenStep(SagaStep[CreateTunnelSagaData]):
    """Fetch the *remote-managed* token cloudflared needs to authenticate.

    No side effects → no compensation. The token is held in the saga
    context only long enough to land in the K8s Secret; never logged
    (the structured logger redacts ``*token*`` keys).
    """

    name = "retrieve_token"

    def __init__(self, cf_registry: CloudflareProviderRegistry) -> None:
        self._cf = cf_registry

    async def execute(self, ctx: SagaContext[CreateTunnelSagaData]) -> str:
        if not ctx.data.cf_tunnel_id:
            raise RuntimeError("cf_tunnel_id missing — wrong step ordering")
        provider = await self._cf.get(TenantIdVO(ctx.tenant_id))
        token = await provider.get_tunnel_token(ctx.data.cf_tunnel_id)
        ctx.data.remote_token = token
        return "<redacted>"
