"""Composition root.

The single place where ports get bound to adapters. Both the API and
the workers call :func:`build_container` to materialise a typed
container of singletons. No DI framework — explicit wiring keeps the
graph readable and import-time deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass

from shared.config import Settings, get_settings
from shared.logging import configure_logging
from shared.observability import configure_tracing
from services.tunnel_orchestrator.application.commands import (
    CreateTunnelHandler,
    DeleteTunnelHandler,
    ValidateTunnelHandler,
)
from services.tunnel_orchestrator.application.idempotency import IdempotencyService
from services.tunnel_orchestrator.application.queries import (
    GetTunnelHandler,
    ListTunnelsHandler,
)
from services.tunnel_orchestrator.application.resilience import (
    CircuitBreakerRegistry,
    RetryPolicy,
)
from services.tunnel_orchestrator.application.resilience.rate_limiter import (
    CLOUDFLARE_DEFAULT_LIMIT,
    CLOUDFLARE_WINDOW_SECONDS,
    RateLimiterRegistry,
)
from services.tunnel_orchestrator.application.sagas.create_tunnel_saga import (
    CreateTunnelSagaDeps,
)
from services.tunnel_orchestrator.application.sagas.delete_tunnel_saga import (
    DeleteTunnelSagaDeps,
)
from services.tunnel_orchestrator.infrastructure.cache import (
    RedisClient,
    RedisLockManager,
)
from services.tunnel_orchestrator.infrastructure.cloudflare import (
    CloudflareProviderRegistryImpl,
    TenantTokenLoader,
)
from services.tunnel_orchestrator.infrastructure.cloudflare.registry import (
    DbBackedTokenLoader,
)
from services.tunnel_orchestrator.infrastructure.kubernetes import (
    KubernetesClientFactory,
    KubernetesProviderImpl,
)
from services.tunnel_orchestrator.infrastructure.messaging import (
    AioKafkaPublisher,
    KafkaProducerFactory,
)
from services.tunnel_orchestrator.infrastructure.persistence import (
    Database,
    PgIdempotencyStore,
    PgSagaInstanceStore,
    PgTenantRepository,
    PgTunnelRepository,
)
from services.tunnel_orchestrator.infrastructure.persistence.audit_logger import (
    PgAuditLogger,
)
from services.tunnel_orchestrator.infrastructure.persistence.outbox import OutboxRelay
from services.tunnel_orchestrator.infrastructure.verification import (
    DnsPyVerifier,
    HttpxProber,
)


@dataclass
class Container:
    settings: Settings
    db: Database
    redis: RedisClient
    kafka: KafkaProducerFactory
    k8s_factory: KubernetesClientFactory
    publisher: AioKafkaPublisher
    cf_registry: CloudflareProviderRegistryImpl
    saga_store: PgSagaInstanceStore
    audit_logger: PgAuditLogger
    create_handler: CreateTunnelHandler
    delete_handler: DeleteTunnelHandler
    validate_handler: ValidateTunnelHandler
    get_query: GetTunnelHandler
    list_query: ListTunnelsHandler
    outbox_relay: OutboxRelay


# Default token loader stub: in production replace with Vault CSI reader.
# Reads the env CLOUDFLARE_API_TOKEN as the resolved secret.
async def _env_secret_resolver(_path: str) -> str:
    settings = get_settings()
    if not settings.cloudflare.api_token:
        raise RuntimeError(
            "CLOUDFLARE_API_TOKEN env not set — cannot resolve tenant token without a real "
            "secret manager configured."
        )
    return settings.cloudflare.api_token.get_secret_value()


async def build_container(*, with_outbox_relay: bool = True) -> Container:
    """Wire everything. Idempotent — safe to call once per process."""
    configure_logging()
    configure_tracing()
    settings = get_settings()

    # ----- infra singletons -----
    db = Database()
    redis = RedisClient()
    await redis.connect()
    kafka = KafkaProducerFactory()
    await kafka.start()
    k8s_factory = KubernetesClientFactory()

    # ----- repository / stores (per-call sessions where needed) -----
    publisher = AioKafkaPublisher(db)
    audit_logger = PgAuditLogger(db)
    saga_store = PgSagaInstanceStore(db)
    idempotency_store = PgIdempotencyStore(db)
    idempotency = IdempotencyService(idempotency_store)
    lock_manager = RedisLockManager(redis)

    # ----- cross-cutting registries -----
    rate_limiter = RateLimiterRegistry(
        max_rate=CLOUDFLARE_DEFAULT_LIMIT,
        time_period_seconds=CLOUDFLARE_WINDOW_SECONDS,
    )
    breaker = CircuitBreakerRegistry(
        default_threshold=settings.resilience.circuit_breaker_threshold,
        default_ttl_seconds=settings.resilience.circuit_breaker_reset_seconds,
    )
    retry_policy = RetryPolicy(
        max_attempts=settings.resilience.retry_max_attempts,
        initial_delay_ms=settings.resilience.retry_initial_delay_ms,
        max_delay_ms=settings.resilience.retry_max_delay_ms,
    )

    # ----- providers (need a session for tenants lookup) -----
    # We pass *factories* of session-bound repos; cf_registry uses one
    # short session per cache miss, never long-lived.
    async def _session_scoped_tenant_repo() -> PgTenantRepository:
        # Session is opened ad-hoc by the loader; alive for one query.
        async with db.session_factory() as session:
            return PgTenantRepository(session)

    # The real loader uses a fresh repo per call (multi-tenant safe).
    class _Loader(TenantTokenLoader):
        async def load(self, tenant_id):  # noqa: ANN001
            async with db.session_factory() as session:
                tenants = PgTenantRepository(session)
                tenant = await tenants.get(tenant_id)
                if tenant is None:
                    raise LookupError(f"Tenant {tenant_id} not found")
                token = await _env_secret_resolver(tenant.cf_token_vault_path)
                from services.tunnel_orchestrator.infrastructure.cloudflare.registry import (
                    _TenantCfBundle,
                )
                return _TenantCfBundle(account_id=tenant.cf_account_id, api_token=token)

    cf_registry = CloudflareProviderRegistryImpl(
        loader=_Loader(),
        retry_policy=retry_policy,
        breaker=breaker,
        rate_limiter=rate_limiter,
    )

    k8s_provider = KubernetesProviderImpl(factory=k8s_factory)

    dns_verifier = DnsPyVerifier()
    http_verifier = HttpxProber()

    # ----- handlers (need a per-request UoW so we wrap with factories) -----
    create_saga_deps = CreateTunnelSagaDeps(
        cf_registry=cf_registry,
        k8s=k8s_provider,
        dns_verifier=dns_verifier,
        http_verifier=http_verifier,
        store=saga_store,
    )
    delete_saga_deps = DeleteTunnelSagaDeps(
        cf_registry=cf_registry, k8s=k8s_provider, store=saga_store
    )

    # Repos are short-lived per request: handlers receive a small wrapper
    # that opens a session per call.
    class _RepoSession:
        def __init__(self, db: Database) -> None:
            self._db = db

        async def __aenter__(self):
            self._session = self._db.session_factory()
            await self._session.begin()
            return self._session

        async def __aexit__(self, exc_type, exc, tb):           # noqa: ANN001
            try:
                if exc:
                    await self._session.rollback()
                else:
                    await self._session.commit()
            finally:
                await self._session.close()

    # NOTE: in a more elaborate setup we'd inject a UoW and the handler
    # would manage repo+session lifetime. For brevity we instantiate per
    # call below in the API/worker entrypoints.
    tunnel_repo_factory = lambda session: PgTunnelRepository(session)            # noqa: E731
    tenant_repo_factory = lambda session: PgTenantRepository(session)            # noqa: E731

    # We compose handlers with a session-aware repo by re-creating per-call.
    # The API's dependency layer will rebuild handlers with a fresh session.
    create_handler = CreateTunnelHandler(
        tunnels=PgTunnelRepository(db.session_factory()),  # placeholder; replaced per request
        tenants=PgTenantRepository(db.session_factory()),
        lock_manager=lock_manager,
        idempotency=idempotency,
        publisher=publisher,
        saga_deps=create_saga_deps,
        audit=audit_logger,
    )
    delete_handler = DeleteTunnelHandler(
        tunnels=PgTunnelRepository(db.session_factory()),
        lock_manager=lock_manager,
        idempotency=idempotency,
        publisher=publisher,
        saga_deps=delete_saga_deps,
        audit=audit_logger,
    )
    validate_handler = ValidateTunnelHandler(
        tunnels=PgTunnelRepository(db.session_factory()),
        dns=dns_verifier,
        http=http_verifier,
        publisher=publisher,
    )

    get_query = GetTunnelHandler(PgTunnelRepository(db.session_factory()))
    list_query = ListTunnelsHandler(PgTunnelRepository(db.session_factory()))

    # ----- outbox relay -----
    from services.tunnel_orchestrator.infrastructure.messaging.kafka_producer import (
        DirectKafkaSender,
    )

    relay_sender = DirectKafkaSender(kafka)
    outbox_relay = OutboxRelay(db=db, publisher_send=relay_sender)

    # silence unused-warning on factories — used by API layer per-request rewiring
    _ = tunnel_repo_factory, tenant_repo_factory, _session_scoped_tenant_repo

    return Container(
        settings=settings,
        db=db,
        redis=redis,
        kafka=kafka,
        k8s_factory=k8s_factory,
        publisher=publisher,
        cf_registry=cf_registry,
        saga_store=saga_store,
        audit_logger=audit_logger,
        create_handler=create_handler,
        delete_handler=delete_handler,
        validate_handler=validate_handler,
        get_query=get_query,
        list_query=list_query,
        outbox_relay=outbox_relay,
    )


async def shutdown_container(c: Container) -> None:
    await c.kafka.stop()
    await c.k8s_factory.close_all()
    await c.redis.close()
    await c.db.dispose()
