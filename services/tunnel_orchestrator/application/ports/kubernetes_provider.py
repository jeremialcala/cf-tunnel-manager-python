"""Port: Kubernetes provider — namespace-scoped Secret + Deployment ops."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CloudflaredDeploymentSpec:
    """Inputs needed to render and apply a ``cloudflared`` Deployment."""

    namespace: str
    name: str
    image: str
    replicas: int
    secret_name: str               # holds the remote-managed token
    cpu_request: str
    cpu_limit: str
    mem_request: str
    mem_limit: str
    extra_labels: dict[str, str] | None = None
    extra_annotations: dict[str, str] | None = None


class KubernetesProvider(ABC):
    """Adapter façade. Implementations may be cluster-aware (multi-cluster)."""

    cluster: str

    @abstractmethod
    async def ensure_namespace(self, namespace: str) -> None: ...

    @abstractmethod
    async def upsert_secret(
        self,
        namespace: str,
        name: str,
        data: dict[str, str],
        *,
        labels: dict[str, str] | None = None,
    ) -> None:
        """Create or update an opaque Secret. ``data`` values are plain text — adapter base64-encodes."""

    @abstractmethod
    async def delete_secret(self, namespace: str, name: str) -> None: ...

    @abstractmethod
    async def apply_cloudflared_deployment(
        self, spec: CloudflaredDeploymentSpec
    ) -> None: ...

    @abstractmethod
    async def delete_deployment(self, namespace: str, name: str) -> None: ...

    @abstractmethod
    async def wait_deployment_ready(
        self, namespace: str, name: str, *, timeout_seconds: float
    ) -> bool:
        """Block until ``status.availableReplicas == spec.replicas`` or timeout."""
