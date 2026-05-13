"""Kubernetes API client factory.

Resolves credentials from either ``incluster`` or kubeconfig (with
optional context). Caches a single ``ApiClient`` per cluster and
exposes typed sub-clients (``CoreV1``, ``AppsV1``).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

from kubernetes_asyncio import client, config
from kubernetes_asyncio.client import ApiClient, AppsV1Api, CoreV1Api

from shared.config import get_settings
from shared.logging import get_logger

log = get_logger(__name__)


@dataclass(slots=True)
class _ClusterClients:
    api_client: ApiClient
    core: CoreV1Api
    apps: AppsV1Api
    cluster: str


class KubernetesClientFactory:
    """One factory per process; resolves a cluster on demand."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._cache: dict[str, _ClusterClients] = {}
        self._multi: dict[str, str] = {}
        self._load_multi_cluster_config()

    def _load_multi_cluster_config(self) -> None:
        cfg = get_settings().kubernetes.multi_cluster_config
        if not cfg:
            return
        try:
            self._multi = json.loads(cfg)
        except Exception as e:  # noqa: BLE001
            log.error("k8s.multi_cluster_config.invalid", error=str(e))

    async def get(self, cluster: str = "default") -> _ClusterClients:
        cached = self._cache.get(cluster)
        if cached:
            return cached
        async with self._lock:
            cached = self._cache.get(cluster)
            if cached:
                return cached
            api_client = await self._build_api_client(cluster)
            bundle = _ClusterClients(
                api_client=api_client,
                core=CoreV1Api(api_client),
                apps=AppsV1Api(api_client),
                cluster=cluster,
            )
            self._cache[cluster] = bundle
            return bundle

    async def close_all(self) -> None:
        for bundle in list(self._cache.values()):
            try:
                await bundle.api_client.close()
            except Exception:  # noqa: BLE001
                log.warning("k8s.client.close_failed", cluster=bundle.cluster)
        self._cache.clear()

    async def _build_api_client(self, cluster: str) -> ApiClient:
        settings = get_settings().kubernetes
        if settings.mode == "incluster":
            config.load_incluster_config()
            return ApiClient()

        kubeconfig_path: str | None
        context: str | None = settings.context
        if cluster != "default" and cluster in self._multi:
            kubeconfig_path = self._multi[cluster]
            context = None
        else:
            kubeconfig_path = (
                str(settings.kubeconfig_path) if settings.kubeconfig_path else None
            )

        await config.load_kube_config(
            config_file=kubeconfig_path, context=context
        )
        return ApiClient()
