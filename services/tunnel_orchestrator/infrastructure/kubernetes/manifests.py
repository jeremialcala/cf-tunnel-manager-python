"""Manifest templates for cloudflared deployments.

Pure functions: take a :class:`CloudflaredDeploymentSpec` and return a
``V1Deployment``. Keeping this separate from the provider lets us test
the rendered manifest without any K8s client.
"""

from __future__ import annotations

from kubernetes_asyncio.client import (
    V1Container,
    V1ContainerPort,
    V1Deployment,
    V1DeploymentSpec,
    V1DeploymentStrategy,
    V1EnvVar,
    V1EnvVarSource,
    V1LabelSelector,
    V1ObjectMeta,
    V1PodSpec,
    V1PodTemplateSpec,
    V1Probe,
    V1ResourceRequirements,
    V1RollingUpdateDeployment,
    V1SecretKeySelector,
    V1SecurityContext,
    V1Toleration,
)

from services.tunnel_orchestrator.application.ports.kubernetes_provider import (
    CloudflaredDeploymentSpec,
)


def build_cloudflared_deployment(spec: CloudflaredDeploymentSpec) -> V1Deployment:
    labels: dict[str, str] = {
        "app.kubernetes.io/name": "cloudflared",
        "app.kubernetes.io/instance": spec.name,
        "app.kubernetes.io/managed-by": "tunnel-orchestrator",
        "app.kubernetes.io/component": "tunnel",
    }
    if spec.extra_labels:
        labels.update(spec.extra_labels)

    annotations: dict[str, str] = {
        "tunnel-orchestrator.io/source": "remotely-managed",
    }
    if spec.extra_annotations:
        annotations.update(spec.extra_annotations)

    container = V1Container(
        name="cloudflared",
        image=spec.image,
        image_pull_policy="IfNotPresent",
        args=[
            "tunnel",
            "--no-autoupdate",
            "--metrics", "0.0.0.0:2000",
            "run",
        ],
        env=[
            V1EnvVar(
                name="TUNNEL_TOKEN",
                value_from=V1EnvVarSource(
                    secret_key_ref=V1SecretKeySelector(
                        name=spec.secret_name, key="TUNNEL_TOKEN", optional=False
                    )
                ),
            ),
        ],
        ports=[V1ContainerPort(name="metrics", container_port=2000)],
        resources=V1ResourceRequirements(
            requests={"cpu": spec.cpu_request, "memory": spec.mem_request},
            limits={"cpu": spec.cpu_limit, "memory": spec.mem_limit},
        ),
        liveness_probe=V1Probe(
            http_get={"path": "/ready", "port": 2000},  # type: ignore[arg-type]
            initial_delay_seconds=10,
            period_seconds=10,
            timeout_seconds=3,
            failure_threshold=3,
        ),
        readiness_probe=V1Probe(
            http_get={"path": "/ready", "port": 2000},  # type: ignore[arg-type]
            initial_delay_seconds=5,
            period_seconds=5,
            timeout_seconds=3,
            failure_threshold=3,
        ),
        security_context=V1SecurityContext(
            run_as_non_root=True,
            run_as_user=65532,
            allow_privilege_escalation=False,
            read_only_root_filesystem=True,
            capabilities={"drop": ["ALL"]},          # type: ignore[arg-type]
        ),
    )

    return V1Deployment(
        api_version="apps/v1",
        kind="Deployment",
        metadata=V1ObjectMeta(
            name=spec.name, namespace=spec.namespace,
            labels=labels, annotations=annotations,
        ),
        spec=V1DeploymentSpec(
            replicas=spec.replicas,
            revision_history_limit=3,
            strategy=V1DeploymentStrategy(
                type="RollingUpdate",
                rolling_update=V1RollingUpdateDeployment(
                    max_surge=1, max_unavailable=0
                ),
            ),
            selector=V1LabelSelector(
                match_labels={
                    "app.kubernetes.io/name": "cloudflared",
                    "app.kubernetes.io/instance": spec.name,
                }
            ),
            template=V1PodTemplateSpec(
                metadata=V1ObjectMeta(labels=labels, annotations=annotations),
                spec=V1PodSpec(
                    automount_service_account_token=False,
                    termination_grace_period_seconds=30,
                    enable_service_links=False,
                    containers=[container],
                    tolerations=[
                        V1Toleration(
                            key="node.kubernetes.io/not-ready",
                            operator="Exists",
                            effect="NoExecute",
                            toleration_seconds=120,
                        ),
                    ],
                ),
            ),
        ),
    )
