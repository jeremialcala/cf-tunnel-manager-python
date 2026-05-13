"""High-level :class:`CreateTunnelSaga` assembler.

Wires together the steps and constructs the orchestrator with the
correct dependencies. This is the **only** place that knows the
order of steps for a CREATE workflow — adding/removing/reordering
happens here.
"""

from __future__ import annotations

from dataclasses import dataclass

from shared.config import get_settings
from services.tunnel_orchestrator.application.ports import (
    CloudflareProviderRegistry,
    DnsVerifier,
    HttpVerifier,
    KubernetesProvider,
)
from services.tunnel_orchestrator.application.sagas.base import (
    SagaInstanceStore,
    SagaOrchestrator,
)
from services.tunnel_orchestrator.application.sagas.context import CreateTunnelSagaData
from services.tunnel_orchestrator.application.sagas.steps import (
    ConfigureIngressStep,
    CreateCloudflareTunnelStep,
    CreateDnsRecordStep,
    CreateK8sDeploymentStep,
    CreateK8sSecretStep,
    RetrieveTunnelTokenStep,
    VerifyDnsStep,
    VerifyHttpStep,
    WaitDeploymentReadyStep,
)


@dataclass(frozen=True, slots=True)
class CreateTunnelSagaDeps:
    cf_registry: CloudflareProviderRegistry
    k8s: KubernetesProvider
    dns_verifier: DnsVerifier
    http_verifier: HttpVerifier
    store: SagaInstanceStore


class CreateTunnelSaga:
    """Façade: ``CreateTunnelSaga(deps).build()`` returns a ready orchestrator."""

    SAGA_TYPE = "create_tunnel"

    def __init__(self, deps: CreateTunnelSagaDeps) -> None:
        self._deps = deps

    def build(self) -> SagaOrchestrator[CreateTunnelSagaData]:
        settings = get_settings().resilience
        steps = [
            CreateCloudflareTunnelStep(self._deps.cf_registry),
            RetrieveTunnelTokenStep(self._deps.cf_registry),
            ConfigureIngressStep(self._deps.cf_registry),
            CreateDnsRecordStep(self._deps.cf_registry),
            CreateK8sSecretStep(self._deps.k8s),
            CreateK8sDeploymentStep(self._deps.k8s),
            WaitDeploymentReadyStep(self._deps.k8s, timeout_seconds=settings.saga_step_timeout_seconds),
            VerifyDnsStep(self._deps.dns_verifier),
            VerifyHttpStep(self._deps.http_verifier),
        ]
        return SagaOrchestrator(
            saga_type=self.SAGA_TYPE,
            steps=steps,
            store=self._deps.store,
            step_timeout_seconds=settings.saga_step_timeout_seconds,
            global_timeout_seconds=settings.saga_global_timeout_seconds,
        )
