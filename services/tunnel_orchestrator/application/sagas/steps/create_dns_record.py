from __future__ import annotations

from services.tunnel_orchestrator.application.ports import CloudflareProviderRegistry
from services.tunnel_orchestrator.application.sagas.base import SagaContext, SagaStep
from services.tunnel_orchestrator.application.sagas.context import CreateTunnelSagaData
from services.tunnel_orchestrator.domain.value_objects import DnsRecord, TenantIdVO


class CreateDnsRecordStep(SagaStep[CreateTunnelSagaData]):
    """Create / upsert the proxied CNAME pointing to ``{cf_tunnel_id}.cfargotunnel.com``."""

    name = "create_dns_record"

    def __init__(self, cf_registry: CloudflareProviderRegistry) -> None:
        self._cf = cf_registry

    async def execute(self, ctx: SagaContext[CreateTunnelSagaData]) -> str:
        if not ctx.data.cf_tunnel_id:
            raise RuntimeError("cf_tunnel_id missing — wrong step ordering")
        provider = await self._cf.get(TenantIdVO(ctx.tenant_id))
        record = DnsRecord.for_tunnel(ctx.data.tunnel.hostname, ctx.data.cf_tunnel_id)
        record_id = await provider.upsert_dns_record(ctx.data.cf_zone_id, record)
        ctx.data.cf_dns_record_id = record_id
        ctx.data.tunnel.attach_dns_record(record_id)
        return record_id

    async def compensate(self, ctx: SagaContext[CreateTunnelSagaData]) -> None:
        if not ctx.data.cf_dns_record_id:
            return
        provider = await self._cf.get(TenantIdVO(ctx.tenant_id))
        await provider.delete_dns_record(ctx.data.cf_zone_id, ctx.data.cf_dns_record_id)
        ctx.data.compensations_executed.append(self.name)
