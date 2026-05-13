from __future__ import annotations

from shared.errors import DnsVerificationFailed
from services.tunnel_orchestrator.application.ports import DnsVerifier
from services.tunnel_orchestrator.application.sagas.base import SagaContext, SagaStep
from services.tunnel_orchestrator.application.sagas.context import CreateTunnelSagaData


class VerifyDnsStep(SagaStep[CreateTunnelSagaData]):
    """Resolve the hostname against external resolvers until success."""

    name = "verify_dns"

    def __init__(self, verifier: DnsVerifier) -> None:
        self._verifier = verifier

    async def execute(self, ctx: SagaContext[CreateTunnelSagaData]) -> dict[str, object]:
        result = await self._verifier.verify(ctx.data.tunnel.hostname)
        if not result.resolved:
            raise DnsVerificationFailed(
                f"DNS for {ctx.data.tunnel.hostname} did not resolve in time"
            )
        return {
            "elapsed_seconds": result.elapsed_seconds,
            "answers": list(result.answers),
            "nameservers": list(result.nameservers_used),
        }
