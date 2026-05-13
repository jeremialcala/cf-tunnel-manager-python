"""Shared pytest fixtures and lightweight in-memory fakes."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio

from services.tunnel_orchestrator.application.idempotency import (
    IdempotencyRecord,
    IdempotencyStore,
)
from services.tunnel_orchestrator.application.ports import (
    AuditLogger,
    CloudflareProvider,
    CloudflareProviderRegistry,
    DnsVerifier,
    EventPublisher,
    HttpVerifier,
    KubernetesProvider,
    LockManager,
)
from services.tunnel_orchestrator.application.ports.cloudflare_provider import (
    CloudflareTunnel,
)
from services.tunnel_orchestrator.application.ports.dns_verifier import DnsResult
from services.tunnel_orchestrator.application.ports.http_verifier import HttpResult
from services.tunnel_orchestrator.application.ports.kubernetes_provider import (
    CloudflaredDeploymentSpec,
)
from services.tunnel_orchestrator.application.sagas.base import (
    SagaInstanceStore,
    SagaStatus,
    StepResult,
)
from services.tunnel_orchestrator.domain.aggregates import Tenant, Tunnel
from services.tunnel_orchestrator.domain.repositories import (
    TenantRepository,
    TunnelRepository,
)
from services.tunnel_orchestrator.domain.value_objects import (
    Hostname,
    TenantIdVO,
    TunnelIdVO,
)
from shared.types import utcnow


# ----------------------------------------------------- in-memory repos


class InMemoryTunnelRepository(TunnelRepository):
    def __init__(self) -> None:
        self.items: dict[UUID, Tunnel] = {}

    async def get(self, tunnel_id: TunnelIdVO) -> Tunnel | None:
        return self.items.get(tunnel_id.value)

    async def find_by_hostname(self, tenant_id, hostname) -> Tunnel | None:        # noqa: ANN001
        for t in self.items.values():
            if t.tenant_id == tenant_id and str(t.hostname) == str(hostname):
                return t
        return None

    async def list_by_tenant(self, tenant_id, *, limit=100, cursor=None):           # noqa: ANN001
        return [t for t in self.items.values() if t.tenant_id == tenant_id][:limit]

    async def add(self, tunnel: Tunnel) -> None:
        tunnel.pull_pending_events()  # discard for tests
        self.items[tunnel.id.value] = tunnel

    async def save(self, tunnel: Tunnel) -> None:
        tunnel.pull_pending_events()
        self.items[tunnel.id.value] = tunnel

    async def delete(self, tunnel_id: TunnelIdVO) -> None:
        self.items.pop(tunnel_id.value, None)


class InMemoryTenantRepository(TenantRepository):
    def __init__(self) -> None:
        self.items: dict[UUID, Tenant] = {}

    async def get(self, tenant_id: TenantIdVO) -> Tenant | None:
        return self.items.get(tenant_id.value)

    async def get_by_slug(self, slug: str) -> Tenant | None:
        return next((t for t in self.items.values() if t.slug == slug), None)

    async def list_active(self) -> list[Tenant]:
        return [t for t in self.items.values() if t.status.value == "ACTIVE"]

    async def add(self, tenant: Tenant) -> None:
        self.items[tenant.id.value] = tenant

    async def save(self, tenant: Tenant) -> None:
        self.items[tenant.id.value] = tenant


# ----------------------------------------------------- in-memory ports


class FakeCloudflareProvider(CloudflareProvider):
    def __init__(self) -> None:
        self.tunnels: dict[str, CloudflareTunnel] = {}
        self.dns_records: dict[str, str] = {}        # zone:hostname -> id
        self.ingress: dict[str, list] = {}
        self.calls: list[str] = []

    async def create_tunnel(self, name):                                            # noqa: ANN001
        self.calls.append(f"create_tunnel:{name}")
        cf_id = f"cf-{uuid4().hex[:12]}"
        t = CloudflareTunnel(cf_id, name, "cloudflare")
        self.tunnels[cf_id] = t
        return t

    async def find_tunnel_by_name(self, name):                                      # noqa: ANN001
        return next((t for t in self.tunnels.values() if t.name == name), None)

    async def get_tunnel_token(self, cf_tunnel_id):                                 # noqa: ANN001
        self.calls.append(f"get_token:{cf_tunnel_id}")
        return "fake-token-" + cf_tunnel_id

    async def put_ingress_configuration(self, cf_tunnel_id, rules):                 # noqa: ANN001
        self.ingress[cf_tunnel_id] = rules.to_payload()

    async def reset_ingress_configuration(self, cf_tunnel_id):                      # noqa: ANN001
        self.ingress.pop(cf_tunnel_id, None)

    async def delete_tunnel(self, cf_tunnel_id):                                    # noqa: ANN001
        self.tunnels.pop(cf_tunnel_id, None)

    async def upsert_dns_record(self, zone_id, record):                             # noqa: ANN001
        rid = f"dns-{uuid4().hex[:12]}"
        self.dns_records[f"{zone_id}:{record.hostname.value}"] = rid
        return rid

    async def find_dns_record_id(self, zone_id, hostname):                          # noqa: ANN001
        return self.dns_records.get(f"{zone_id}:{hostname}")

    async def delete_dns_record(self, zone_id, record_id):                          # noqa: ANN001
        for k, v in list(self.dns_records.items()):
            if v == record_id:
                del self.dns_records[k]


class FakeCloudflareRegistry(CloudflareProviderRegistry):
    def __init__(self, provider: CloudflareProvider) -> None:
        self.provider = provider

    async def get(self, tenant_id):                                                 # noqa: ANN001
        return self.provider

    async def invalidate(self, tenant_id):                                          # noqa: ANN001
        return None


class FakeKubernetesProvider(KubernetesProvider):
    cluster = "test"

    def __init__(self) -> None:
        self.namespaces: set[str] = set()
        self.secrets: dict[tuple[str, str], dict] = {}
        self.deployments: dict[tuple[str, str], CloudflaredDeploymentSpec] = {}
        self.always_ready = True

    async def ensure_namespace(self, namespace):                                    # noqa: ANN001
        self.namespaces.add(namespace)

    async def upsert_secret(self, namespace, name, data, *, labels=None):           # noqa: ANN001
        self.secrets[(namespace, name)] = dict(data)

    async def delete_secret(self, namespace, name):                                 # noqa: ANN001
        self.secrets.pop((namespace, name), None)

    async def apply_cloudflared_deployment(self, spec):                             # noqa: ANN001
        self.deployments[(spec.namespace, spec.name)] = spec

    async def delete_deployment(self, namespace, name):                             # noqa: ANN001
        self.deployments.pop((namespace, name), None)

    async def wait_deployment_ready(self, namespace, name, *, timeout_seconds):     # noqa: ANN001
        return self.always_ready


class FakeDnsVerifier(DnsVerifier):
    def __init__(self, ok: bool = True) -> None:
        self.ok = ok

    async def verify(self, hostname, **kw):                                         # noqa: ANN001
        return DnsResult(str(hostname), self.ok, ("cf-tunnel-id.cfargotunnel.com",), 0.1, ("1.1.1.1",))


class FakeHttpVerifier(HttpVerifier):
    def __init__(self, ok: bool = True) -> None:
        self.ok = ok

    async def probe(self, hostname, **kw):                                          # noqa: ANN001
        return HttpResult(f"https://{hostname}/", self.ok, 200 if self.ok else 503, 12.3, None)


class FakeLockManager(LockManager):
    def __init__(self) -> None:
        self.acquired: list[str] = []

    @asynccontextmanager
    async def lock(self, key, *, ttl_seconds=None, wait_seconds=0.0):               # noqa: ANN001
        self.acquired.append(key)
        yield


class FakeIdempotencyStore(IdempotencyStore):
    def __init__(self) -> None:
        self.records: dict[str, IdempotencyRecord] = {}

    async def get(self, key):                                                       # noqa: ANN001
        return self.records.get(key)

    async def insert_pending(self, *, key, tenant_id, request_hash, ttl_seconds=7 * 24 * 3600):  # noqa: ANN001
        if key in self.records:
            return False
        self.records[key] = IdempotencyRecord(
            key=key, tenant_id=tenant_id, request_hash=request_hash,
            response=None, created_at=utcnow(), expires_at=utcnow() + timedelta(seconds=ttl_seconds),
        )
        return True

    async def complete(self, key, response):                                        # noqa: ANN001
        if key in self.records:
            r = self.records[key]
            self.records[key] = IdempotencyRecord(**{**r.__dict__, "response": response})

    async def purge_expired(self, *, batch_size=1000):                              # noqa: ANN001
        return 0


class FakeEventPublisher(EventPublisher):
    def __init__(self) -> None:
        self.published: list[tuple[str, Any]] = []
        self.dlq: list[dict] = []

    async def publish(self, topic, envelope, *, key=None):                          # noqa: ANN001
        self.published.append((str(topic), envelope))

    async def publish_to_dlq(self, **kw):                                           # noqa: ANN001
        self.dlq.append(kw)


class FakeAuditLogger(AuditLogger):
    def __init__(self) -> None:
        self.entries: list[dict] = []

    async def record(self, **kw):                                                   # noqa: ANN001
        self.entries.append(kw)


class FakeSagaStore(SagaInstanceStore):
    def __init__(self) -> None:
        self.instances: dict[UUID, dict] = {}
        self.steps: list[StepResult] = []

    async def begin(self, *, saga_id, type, tenant_id, context):                    # noqa: ANN001, A002
        self.instances[saga_id] = {
            "type": type, "tenant_id": tenant_id,
            "context": context, "status": SagaStatus.PENDING.value,
        }

    async def transition(self, saga_id, status):                                    # noqa: ANN001
        self.instances[saga_id]["status"] = status.value

    async def record_step(self, saga_id, step):                                     # noqa: ANN001
        self.steps.append(step)


# ---------------------------------------------------------------- fixtures


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def tenant() -> Tenant:
    t = Tenant.new(
        name="acme", slug="acme",
        cf_account_id="cf-account-id",
        cf_token_vault_path="secret/tenants/acme/cf_token",
        cf_zone_ids=["zone-1"],
    )
    t.activate()
    return t


@pytest.fixture
def hostname() -> Hostname:
    return Hostname.parse("api.svc.example.com")
