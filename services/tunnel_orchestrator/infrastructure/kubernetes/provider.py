"""Kubernetes provider implementation."""

from __future__ import annotations

import asyncio
import base64
import time

from kubernetes_asyncio.client import (
    V1Namespace,
    V1ObjectMeta,
    V1Secret,
)
from kubernetes_asyncio.client.exceptions import ApiException

from shared.errors import KubernetesAPIError, KubernetesConflict
from shared.logging import get_logger
from shared.observability import metrics
from services.tunnel_orchestrator.application.ports import KubernetesProvider
from services.tunnel_orchestrator.application.ports.kubernetes_provider import (
    CloudflaredDeploymentSpec,
)
from services.tunnel_orchestrator.infrastructure.kubernetes.client import (
    KubernetesClientFactory,
)
from services.tunnel_orchestrator.infrastructure.kubernetes.manifests import (
    build_cloudflared_deployment,
)

log = get_logger(__name__)


class KubernetesProviderImpl(KubernetesProvider):
    def __init__(self, *, factory: KubernetesClientFactory, cluster: str = "default") -> None:
        self._factory = factory
        self.cluster = cluster

    # ------------------------------------------------- Namespace

    async def ensure_namespace(self, namespace: str) -> None:
        api = (await self._factory.get(self.cluster)).core
        try:
            await api.read_namespace(name=namespace)
        except ApiException as e:
            if e.status == 404:
                try:
                    await api.create_namespace(
                        body=V1Namespace(
                            metadata=V1ObjectMeta(
                                name=namespace,
                                labels={"app.kubernetes.io/managed-by": "tunnel-orchestrator"},
                            )
                        )
                    )
                    metrics.k8s_calls_total.labels("create_namespace", "ok").inc()
                except ApiException as ce:
                    if ce.status != 409:
                        metrics.k8s_calls_total.labels("create_namespace", "error").inc()
                        raise KubernetesAPIError(str(ce), cause=ce) from ce
            else:
                raise KubernetesAPIError(str(e), cause=e) from e

    # ---------------------------------------------------- Secret

    async def upsert_secret(
        self,
        namespace: str,
        name: str,
        data: dict[str, str],
        *,
        labels: dict[str, str] | None = None,
    ) -> None:
        api = (await self._factory.get(self.cluster)).core
        encoded = {k: base64.b64encode(v.encode()).decode() for k, v in data.items()}
        body = V1Secret(
            api_version="v1",
            kind="Secret",
            type="Opaque",
            metadata=V1ObjectMeta(name=name, namespace=namespace, labels=labels or {}),
            data=encoded,
        )
        try:
            await api.read_namespaced_secret(name=name, namespace=namespace)
            await api.replace_namespaced_secret(name=name, namespace=namespace, body=body)
            metrics.k8s_calls_total.labels("upsert_secret", "updated").inc()
        except ApiException as e:
            if e.status == 404:
                try:
                    await api.create_namespaced_secret(namespace=namespace, body=body)
                    metrics.k8s_calls_total.labels("upsert_secret", "created").inc()
                except ApiException as ce:
                    metrics.k8s_calls_total.labels("upsert_secret", "error").inc()
                    raise KubernetesAPIError(str(ce), cause=ce) from ce
            else:
                metrics.k8s_calls_total.labels("upsert_secret", "error").inc()
                raise KubernetesAPIError(str(e), cause=e) from e

    async def delete_secret(self, namespace: str, name: str) -> None:
        api = (await self._factory.get(self.cluster)).core
        try:
            await api.delete_namespaced_secret(name=name, namespace=namespace)
            metrics.k8s_calls_total.labels("delete_secret", "ok").inc()
        except ApiException as e:
            if e.status == 404:
                metrics.k8s_calls_total.labels("delete_secret", "not_found").inc()
                return
            metrics.k8s_calls_total.labels("delete_secret", "error").inc()
            raise KubernetesAPIError(str(e), cause=e) from e

    # -------------------------------------------------- Deployment

    async def apply_cloudflared_deployment(self, spec: CloudflaredDeploymentSpec) -> None:
        api = (await self._factory.get(self.cluster)).apps
        body = build_cloudflared_deployment(spec)
        try:
            await api.read_namespaced_deployment(name=spec.name, namespace=spec.namespace)
            await api.patch_namespaced_deployment(
                name=spec.name, namespace=spec.namespace, body=body
            )
            metrics.k8s_calls_total.labels("apply_deployment", "patched").inc()
        except ApiException as e:
            if e.status == 404:
                try:
                    await api.create_namespaced_deployment(
                        namespace=spec.namespace, body=body
                    )
                    metrics.k8s_calls_total.labels("apply_deployment", "created").inc()
                except ApiException as ce:
                    if ce.status == 409:
                        raise KubernetesConflict(str(ce), cause=ce) from ce
                    metrics.k8s_calls_total.labels("apply_deployment", "error").inc()
                    raise KubernetesAPIError(str(ce), cause=ce) from ce
            else:
                metrics.k8s_calls_total.labels("apply_deployment", "error").inc()
                raise KubernetesAPIError(str(e), cause=e) from e

    async def delete_deployment(self, namespace: str, name: str) -> None:
        api = (await self._factory.get(self.cluster)).apps
        try:
            await api.delete_namespaced_deployment(
                name=name, namespace=namespace, propagation_policy="Foreground"
            )
            metrics.k8s_calls_total.labels("delete_deployment", "ok").inc()
        except ApiException as e:
            if e.status == 404:
                metrics.k8s_calls_total.labels("delete_deployment", "not_found").inc()
                return
            metrics.k8s_calls_total.labels("delete_deployment", "error").inc()
            raise KubernetesAPIError(str(e), cause=e) from e

    # -------------------------------------------------- readiness

    async def wait_deployment_ready(
        self, namespace: str, name: str, *, timeout_seconds: float
    ) -> bool:
        api = (await self._factory.get(self.cluster)).apps
        deadline = time.monotonic() + timeout_seconds
        backoff = 1.0
        while time.monotonic() < deadline:
            try:
                dep = await api.read_namespaced_deployment(name=name, namespace=namespace)
            except ApiException as e:
                if e.status == 404:
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 1.5, 5.0)
                    continue
                raise KubernetesAPIError(str(e), cause=e) from e

            spec_replicas = dep.spec.replicas or 0
            available = (dep.status.available_replicas or 0)
            ready = (dep.status.ready_replicas or 0)
            if spec_replicas > 0 and available >= spec_replicas and ready >= spec_replicas:
                return True

            await asyncio.sleep(backoff)
            backoff = min(backoff * 1.5, 5.0)
        return False
