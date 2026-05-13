"""Prometheus metrics registry — a single source of truth.

Exposed via the API process at ``/metrics`` and via a side-car HTTP
server in workers (``shared.observability.metrics.start_metrics_server``).
"""

from __future__ import annotations

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    start_http_server,
)

from shared.config import get_settings


class _Metrics:
    """Lazy holder so ``import shared.observability`` is cheap."""

    def __init__(self) -> None:
        self.registry = CollectorRegistry(auto_describe=True)

        # ----- HTTP -----
        self.http_requests_total = Counter(
            "http_requests_total",
            "Total HTTP requests",
            labelnames=("method", "route", "status"),
            registry=self.registry,
        )
        self.http_request_duration_seconds = Histogram(
            "http_request_duration_seconds",
            "HTTP request duration",
            labelnames=("method", "route"),
            buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
            registry=self.registry,
        )

        # ----- Saga -----
        self.saga_started_total = Counter(
            "saga_started_total",
            "Sagas started",
            labelnames=("saga_type", "tenant_id"),
            registry=self.registry,
        )
        self.saga_completed_total = Counter(
            "saga_completed_total",
            "Sagas completed",
            labelnames=("saga_type", "outcome", "tenant_id"),
            registry=self.registry,
        )
        self.saga_step_duration_seconds = Histogram(
            "saga_step_duration_seconds",
            "Saga step latency",
            labelnames=("saga_type", "step", "outcome"),
            buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300),
            registry=self.registry,
        )
        self.saga_in_flight = Gauge(
            "saga_in_flight",
            "In-flight sagas",
            labelnames=("saga_type",),
            registry=self.registry,
        )
        self.saga_compensations_total = Counter(
            "saga_compensations_total",
            "Compensating actions executed",
            labelnames=("saga_type", "step", "outcome"),
            registry=self.registry,
        )

        # ----- Cloudflare -----
        self.cloudflare_calls_total = Counter(
            "cloudflare_api_calls_total",
            "Cloudflare API calls",
            labelnames=("operation", "status", "tenant_id"),
            registry=self.registry,
        )
        self.cloudflare_call_duration_seconds = Histogram(
            "cloudflare_api_call_duration_seconds",
            "Cloudflare API latency",
            labelnames=("operation",),
            registry=self.registry,
        )
        self.cloudflare_rate_limit_remaining = Gauge(
            "cloudflare_rate_limit_remaining",
            "Estimated remaining requests in current window",
            labelnames=("tenant_id",),
            registry=self.registry,
        )

        # ----- Kubernetes -----
        self.k8s_calls_total = Counter(
            "kubernetes_api_calls_total",
            "Kubernetes API calls",
            labelnames=("operation", "status"),
            registry=self.registry,
        )
        self.k8s_deployment_ready_seconds = Histogram(
            "kubernetes_deployment_ready_seconds",
            "Time until cloudflared Deployment becomes Ready",
            labelnames=("tenant_id",),
            buckets=(1, 5, 10, 30, 60, 120, 300),
            registry=self.registry,
        )

        # ----- Kafka -----
        self.kafka_messages_consumed_total = Counter(
            "kafka_messages_consumed_total",
            "Messages consumed",
            labelnames=("topic", "outcome"),
            registry=self.registry,
        )
        self.kafka_consumer_lag = Gauge(
            "kafka_consumer_lag",
            "Approximate lag per partition",
            labelnames=("topic", "partition"),
            registry=self.registry,
        )

        # ----- Verification -----
        self.dns_verification_seconds = Histogram(
            "dns_verification_seconds",
            "Time until DNS resolves correctly",
            labelnames=("outcome",),
            buckets=(1, 5, 10, 30, 60, 120, 180, 300),
            registry=self.registry,
        )
        self.http_verification_seconds = Histogram(
            "http_verification_seconds",
            "Time until HTTP probe succeeds",
            labelnames=("outcome",),
            buckets=(1, 5, 10, 30, 60, 120, 300),
            registry=self.registry,
        )

    # ----- helpers -----

    def render(self) -> tuple[bytes, str]:
        return generate_latest(self.registry), CONTENT_TYPE_LATEST

    def start_metrics_server(self, port: int | None = None) -> None:
        port = port or get_settings().observability.metrics_port
        start_http_server(port, registry=self.registry)


metrics = _Metrics()
