"""Centralised, typed configuration loaded from environment variables.

All configuration is sourced via :class:`pydantic_settings.BaseSettings`
to keep the Twelve-Factor contract: zero file-based config, no globals,
no implicit defaults that hide misconfiguration.

Usage
-----

>>> from shared.config import get_settings
>>> settings = get_settings()              # cached, process-wide singleton
>>> settings.kafka.bootstrap_servers
'localhost:9092'

Sub-settings are intentionally split per concern so they can be passed
narrowly to the layer that needs them — keeping infrastructure adapters
unaware of unrelated configuration.
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# -------------------------------------------------------------------- enums


class AppEnv(str, Enum):
    LOCAL = "local"
    DEV = "dev"
    STAGING = "staging"
    PROD = "prod"


class LogFormat(str, Enum):
    JSON = "json"
    CONSOLE = "console"


class KafkaSecurityProtocol(str, Enum):
    PLAINTEXT = "PLAINTEXT"
    SSL = "SSL"
    SASL_SSL = "SASL_SSL"
    SASL_PLAINTEXT = "SASL_PLAINTEXT"


# ---------------------------------------------------------------- sub-settings


class _Base(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


class APISettings(_Base):
    host: str = Field(default="0.0.0.0", validation_alias="API_HOST")
    port: int = Field(default=8000, ge=1, le=65535, validation_alias="API_PORT")
    workers: int = Field(default=1, ge=1, validation_alias="API_WORKERS")
    docs_enabled: bool = Field(default=True, validation_alias="API_DOCS_ENABLED")


class JWTSettings(_Base):
    algorithm: Literal["RS256", "ES256", "HS256"] = Field(
        default="RS256", validation_alias="JWT_ALGORITHM"
    )
    public_key_path: Path | None = Field(default=None, validation_alias="JWT_PUBLIC_KEY_PATH")
    private_key_path: Path | None = Field(default=None, validation_alias="JWT_PRIVATE_KEY_PATH")
    secret: SecretStr | None = Field(default=None, validation_alias="JWT_SECRET")
    issuer: str = Field(default="https://auth.example.com", validation_alias="JWT_ISSUER")
    audience: str = Field(default="tunnel-orchestrator", validation_alias="JWT_AUDIENCE")
    leeway_seconds: int = Field(default=30, ge=0, validation_alias="JWT_LEEWAY_SECONDS")


class DatabaseSettings(_Base):
    url: SecretStr = Field(
        default=SecretStr("postgresql+asyncpg://tunnel:tunnel@localhost:5432/tunnel_orchestrator"),
        validation_alias="DATABASE_URL",
    )
    pool_size: int = Field(default=10, ge=1, validation_alias="DATABASE_POOL_SIZE")
    max_overflow: int = Field(default=20, ge=0, validation_alias="DATABASE_MAX_OVERFLOW")
    echo: bool = Field(default=False, validation_alias="DATABASE_ECHO")
    statement_timeout_ms: int = Field(default=30_000, validation_alias="DATABASE_STMT_TIMEOUT_MS")


class RedisSettings(_Base):
    url: SecretStr = Field(
        default=SecretStr("redis://localhost:6379/0"), validation_alias="REDIS_URL"
    )
    lock_ttl_seconds: int = Field(default=120, ge=5, validation_alias="REDIS_LOCK_TTL_SECONDS")
    cache_ttl_seconds: int = Field(default=300, ge=1, validation_alias="REDIS_CACHE_TTL_SECONDS")


class KafkaSettings(_Base):
    bootstrap_servers: str = Field(
        default="localhost:9092", validation_alias="KAFKA_BOOTSTRAP_SERVERS"
    )
    client_id: str = Field(default="tunnel-orchestrator", validation_alias="KAFKA_CLIENT_ID")
    consumer_group: str = Field(
        default="tunnel-orchestrator-workers", validation_alias="KAFKA_CONSUMER_GROUP"
    )
    security_protocol: KafkaSecurityProtocol = Field(
        default=KafkaSecurityProtocol.PLAINTEXT,
        validation_alias="KAFKA_SECURITY_PROTOCOL",
    )
    sasl_mechanism: str | None = Field(default=None, validation_alias="KAFKA_SASL_MECHANISM")
    sasl_username: str | None = Field(default=None, validation_alias="KAFKA_SASL_USERNAME")
    sasl_password: SecretStr | None = Field(default=None, validation_alias="KAFKA_SASL_PASSWORD")
    schema_registry_url: str = Field(
        default="http://localhost:8081", validation_alias="KAFKA_SCHEMA_REGISTRY_URL"
    )
    transactional_id_prefix: str = Field(
        default="tunnel-orch", validation_alias="KAFKA_TRANSACTIONAL_ID_PREFIX"
    )
    enable_idempotence: bool = Field(default=True, validation_alias="KAFKA_ENABLE_IDEMPOTENCE")
    acks: Literal["0", "1", "all"] = Field(default="all", validation_alias="KAFKA_ACKS")
    compression_type: Literal["gzip", "snappy", "lz4", "zstd"] = Field(
        default="gzip", validation_alias="KAFKA_COMPRESSION_TYPE"
    )
    max_poll_records: int = Field(default=20, ge=1, validation_alias="KAFKA_MAX_POLL_RECORDS")
    session_timeout_ms: int = Field(default=30_000, validation_alias="KAFKA_SESSION_TIMEOUT_MS")
    partitions_default: int = Field(default=12, ge=1, validation_alias="KAFKA_PARTITIONS_DEFAULT")
    replication_factor: int = Field(default=3, ge=1, validation_alias="KAFKA_REPLICATION_FACTOR")
    worker_concurrency: int = Field(default=20, ge=1, validation_alias="KAFKA_WORKER_CONCURRENCY")


class CloudflareSettings(_Base):
    api_token: SecretStr | None = Field(default=None, validation_alias="CLOUDFLARE_API_TOKEN")
    api_base_url: str = Field(
        default="https://api.cloudflare.com/client/v4",
        validation_alias="CLOUDFLARE_API_BASE_URL",
    )
    default_account_id: str | None = Field(
        default=None, validation_alias="CLOUDFLARE_DEFAULT_ACCOUNT_ID"
    )
    rate_limit_per_5min: int = Field(
        default=1200, validation_alias="CLOUDFLARE_RATE_LIMIT_PER_5MIN"
    )
    request_timeout_seconds: float = Field(
        default=30.0, validation_alias="CLOUDFLARE_REQUEST_TIMEOUT_SECONDS"
    )
    tunnel_config_src: Literal["cloudflare", "local"] = Field(
        default="cloudflare", validation_alias="CLOUDFLARE_TUNNEL_CONFIG_SRC"
    )

    @field_validator("tunnel_config_src")
    @classmethod
    def _enforce_remote(cls, v: str) -> str:
        if v != "cloudflare":
            raise ValueError(
                "Locally-managed tunnels are not supported by this platform. "
                "Set CLOUDFLARE_TUNNEL_CONFIG_SRC=cloudflare."
            )
        return v


class KubernetesSettings(_Base):
    mode: Literal["incluster", "kubeconfig"] = Field(
        default="kubeconfig", validation_alias="K8S_MODE"
    )
    kubeconfig_path: Path | None = Field(default=None, validation_alias="K8S_KUBECONFIG_PATH")
    context: str | None = Field(default=None, validation_alias="K8S_CONTEXT")
    default_namespace: str = Field(default="tunnels", validation_alias="K8S_DEFAULT_NAMESPACE")
    cloudflared_image: str = Field(
        default="cloudflare/cloudflared:2024.10.0",
        validation_alias="K8S_CLOUDFLARED_IMAGE",
    )
    cloudflared_replicas: int = Field(
        default=2, ge=1, validation_alias="K8S_CLOUDFLARED_REPLICAS"
    )
    cpu_request: str = Field(default="100m", validation_alias="K8S_CLOUDFLARED_RESOURCES_CPU_REQUEST")
    cpu_limit: str = Field(default="500m", validation_alias="K8S_CLOUDFLARED_RESOURCES_CPU_LIMIT")
    mem_request: str = Field(default="128Mi", validation_alias="K8S_CLOUDFLARED_RESOURCES_MEM_REQUEST")
    mem_limit: str = Field(default="256Mi", validation_alias="K8S_CLOUDFLARED_RESOURCES_MEM_LIMIT")
    multi_cluster_config: str | None = Field(
        default=None, validation_alias="K8S_MULTI_CLUSTER_CONFIG"
    )


class VerificationSettings(_Base):
    dns_timeout_seconds: float = Field(
        default=180.0, validation_alias="DNS_VERIFY_TIMEOUT_SECONDS"
    )
    dns_interval_seconds: float = Field(
        default=5.0, validation_alias="DNS_VERIFY_INTERVAL_SECONDS"
    )
    dns_nameservers: str = Field(
        default="1.1.1.1,8.8.8.8", validation_alias="DNS_VERIFY_NAMESERVERS"
    )
    http_timeout_seconds: float = Field(
        default=120.0, validation_alias="HTTP_VERIFY_TIMEOUT_SECONDS"
    )
    http_interval_seconds: float = Field(
        default=3.0, validation_alias="HTTP_VERIFY_INTERVAL_SECONDS"
    )
    http_expected_status: str = Field(
        default="200,204,301,302", validation_alias="HTTP_VERIFY_EXPECTED_STATUS"
    )

    @property
    def nameservers(self) -> list[str]:
        return [n.strip() for n in self.dns_nameservers.split(",") if n.strip()]

    @property
    def expected_status_codes(self) -> set[int]:
        return {int(s.strip()) for s in self.http_expected_status.split(",") if s.strip()}


class ObservabilitySettings(_Base):
    otlp_endpoint: str = Field(
        default="http://localhost:4317", validation_alias="OTEL_EXPORTER_OTLP_ENDPOINT"
    )
    otlp_protocol: Literal["grpc", "http/protobuf"] = Field(
        default="grpc", validation_alias="OTEL_EXPORTER_OTLP_PROTOCOL"
    )
    service_name: str = Field(
        default="tunnel-orchestrator", validation_alias="OTEL_SERVICE_NAME"
    )
    resource_attributes: str = Field(
        default="service.namespace=platform",
        validation_alias="OTEL_RESOURCE_ATTRIBUTES",
    )
    traces_sampler: str = Field(
        default="parentbased_traceidratio", validation_alias="OTEL_TRACES_SAMPLER"
    )
    traces_sampler_arg: float = Field(default=1.0, validation_alias="OTEL_TRACES_SAMPLER_ARG")
    metrics_port: int = Field(default=9100, validation_alias="PROMETHEUS_METRICS_PORT")


class ResilienceSettings(_Base):
    saga_step_timeout_seconds: float = Field(
        default=120.0, validation_alias="SAGA_STEP_TIMEOUT_SECONDS"
    )
    saga_global_timeout_seconds: float = Field(
        default=600.0, validation_alias="SAGA_GLOBAL_TIMEOUT_SECONDS"
    )
    retry_max_attempts: int = Field(default=5, ge=1, validation_alias="RETRY_MAX_ATTEMPTS")
    retry_initial_delay_ms: int = Field(default=500, validation_alias="RETRY_INITIAL_DELAY_MS")
    retry_max_delay_ms: int = Field(default=15_000, validation_alias="RETRY_MAX_DELAY_MS")
    circuit_breaker_threshold: int = Field(default=5, validation_alias="CIRCUIT_BREAKER_THRESHOLD")
    circuit_breaker_reset_seconds: float = Field(
        default=60.0, validation_alias="CIRCUIT_BREAKER_RESET_SECONDS"
    )


# ----------------------------------------------------------------- root


class Settings(_Base):
    """Aggregate of all sub-settings."""

    name: str = Field(default="tunnel-orchestrator", validation_alias="APP_NAME")
    env: AppEnv = Field(default=AppEnv.LOCAL, validation_alias="APP_ENV")
    log_level: Annotated[str, Field(pattern=r"^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")] = Field(
        default="INFO",
        validation_alias=AliasChoices("APP_LOG_LEVEL", "LOG_LEVEL"),
    )
    log_format: LogFormat = Field(default=LogFormat.JSON, validation_alias="APP_LOG_FORMAT")
    debug: bool = Field(default=False, validation_alias="APP_DEBUG")

    api: APISettings = Field(default_factory=APISettings)
    jwt: JWTSettings = Field(default_factory=JWTSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    kafka: KafkaSettings = Field(default_factory=KafkaSettings)
    cloudflare: CloudflareSettings = Field(default_factory=CloudflareSettings)
    kubernetes: KubernetesSettings = Field(default_factory=KubernetesSettings)
    verification: VerificationSettings = Field(default_factory=VerificationSettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
    resilience: ResilienceSettings = Field(default_factory=ResilienceSettings)

    @property
    def is_production(self) -> bool:
        return self.env is AppEnv.PROD


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton.

    Cached so importing modules can call freely without re-parsing env.
    Override in tests with ``get_settings.cache_clear()`` + monkeypatch.
    """
    return Settings()
