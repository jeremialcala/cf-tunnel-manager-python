from __future__ import annotations

from shared.errors import HttpVerificationFailed
from services.tunnel_orchestrator.application.ports import HttpVerifier
from services.tunnel_orchestrator.application.sagas.base import SagaContext, SagaStep
from services.tunnel_orchestrator.application.sagas.context import CreateTunnelSagaData


class VerifyHttpStep(SagaStep[CreateTunnelSagaData]):
    """End-to-end HTTPS probe through the freshly programmed tunnel."""

    name = "verify_http"

    def __init__(self, verifier: HttpVerifier) -> None:
        self._verifier = verifier

    async def execute(self, ctx: SagaContext[CreateTunnelSagaData]) -> dict[str, object]:
        result = await self._verifier.probe(ctx.data.tunnel.hostname)
        if not result.ok:
            raise HttpVerificationFailed(
                f"HTTPS probe to {ctx.data.tunnel.hostname} failed (status={result.status_code})"
            )
        return {
            "status_code": result.status_code,
            "elapsed_ms": result.elapsed_ms,
            "final_url": result.final_url,
        }
