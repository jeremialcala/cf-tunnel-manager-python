"""Use case: create a tunnel.

Coordinates:

* idempotency check (replay-safe);
* distributed lock (one in-flight saga per ``tenant:hostname``);
* domain authorisation (quota, zone allow-list);
* persisting the new aggregate;
* running the saga;
* publishing SUCCESS / FAILURE events through the outbox.

Returns a typed :class:`CreateTunnelOutcome` so callers (API + worker)
can surface a useful response.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Iterable
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from platform.events.envelope import build_envelope
from platform.events.payloads import (
    TunnelCreateFailurePayload,
    TunnelCreateSuccessPayload,
)
from platform.events.topics import Topic
from shared.config import get_settings
from shared.errors import (
    Conflict,
    LockAcquisitionFailed,
    SagaCompensationFailed,
    TunnelAlreadyExists,
)
from shared.logging import get_logger
from shared.types import HostnameStr, NonEmptyStr, utcnow
from services.tunnel_orchestrator.application.idempotency import (
    IdempotencyOutcome,
    IdempotencyService,
)
from services.tunnel_orchestrator.application.ports import (
    AuditLogger,
    EventPublisher,
    LockManager,
)
from services.tunnel_orchestrator.application.sagas import SagaStatus
from services.tunnel_orchestrator.application.sagas.base import (
    SagaContext,
    new_saga_id,
)
from services.tunnel_orchestrator.application.sagas.context import CreateTunnelSagaData
from services.tunnel_orchestrator.application.sagas.create_tunnel_saga import (
    CreateTunnelSaga,
    CreateTunnelSagaDeps,
)
from services.tunnel_orchestrator.domain.aggregates import Tunnel
from services.tunnel_orchestrator.domain.repositories import (
    TenantRepository,
    TunnelRepository,
)
from services.tunnel_orchestrator.domain.services import TunnelLifecycleService
from services.tunnel_orchestrator.domain.value_objects import (
    Hostname,
    IngressOriginConfig,
    IngressRule,
    IngressRuleSet,
    TenantIdVO,
)

log = get_logger(__name__)


# ----------------------------------------------------------- command


class IngressRuleInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    service: NonEmptyStr
    hostname: HostnameStr | None = None
    path: str | None = None
    origin_request: dict[str, str | bool] | None = None


class CreateTunnelCommand(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant_id: UUID
    hostname: HostnameStr
    cf_zone_id: NonEmptyStr
    cluster: NonEmptyStr = "default"
    ingress: tuple[IngressRuleInput, ...]
    requested_by: str | None = None
    correlation_id: str | None = None
    idempotency_key: str | None = None


@dataclass(frozen=True, slots=True)
class CreateTunnelOutcome:
    tunnel_id: UUID
    cf_tunnel_id: str | None
    status: str                       # "READY" | "FAILED" | "REPLAY"
    failed_step: str | None = None
    duration_seconds: float = 0.0
    correlation_id: str | None = None


# ----------------------------------------------------------- handler


class CreateTunnelHandler:
    """The single entry point for creating a tunnel.

    Same code-path serves both the API gateway and the Kafka consumer:
    constructing the command from an HTTP request body or a Kafka
    payload is a thin adapter concern.
    """

    PRODUCER = "tunnel-orchestrator/create-handler"

    def __init__(
        self,
        *,
        tunnels: TunnelRepository,
        tenants: TenantRepository,
        lock_manager: LockManager,
        idempotency: IdempotencyService,
        publisher: EventPublisher,
        saga_deps: CreateTunnelSagaDeps,
        audit: AuditLogger,
    ) -> None:
        self._tunnels = tunnels
        self._tenants = tenants
        self._lock = lock_manager
        self._idem = idempotency
        self._publisher = publisher
        self._saga_factory = CreateTunnelSaga(saga_deps)
        self._audit = audit

    async def handle(self, cmd: CreateTunnelCommand) -> CreateTunnelOutcome:
        started = time.monotonic()
        tenant_vo = TenantIdVO(cmd.tenant_id)
        hostname = Hostname.parse(cmd.hostname)
        idempotency_key = cmd.idempotency_key or self._idem.make_key(
            cmd.tenant_id, "hostname", str(hostname)
        )

        # ---------- idempotency ----------
        outcome, cached = await self._idem.begin(
            key=idempotency_key,
            tenant_id=cmd.tenant_id,
            request=cmd.model_dump(mode="json"),
        )
        if outcome is IdempotencyOutcome.REPLAY and cached:
            log.info("create_tunnel.replay", idempotency_key=idempotency_key)
            return CreateTunnelOutcome(
                tunnel_id=UUID(cached["tunnel_id"]),
                cf_tunnel_id=cached.get("cf_tunnel_id"),
                status="REPLAY",
                correlation_id=cached.get("correlation_id"),
            )

        # ---------- authorise + load tenant ----------
        tenant = await self._tenants.get(tenant_vo)
        existing = await self._tunnels.find_by_hostname(tenant_vo, hostname)
        if existing is not None:
            raise TunnelAlreadyExists(
                f"Tunnel for {hostname} already exists",
                context={"existing_tunnel_id": str(existing.id.value)},
            )
        TunnelLifecycleService.authorize_creation(
            tenant=tenant, hostname=hostname, cf_zone_id=cmd.cf_zone_id, current_count=0
        )
        assert tenant is not None  # narrowed by authorize_creation

        # ---------- build aggregate ----------
        ingress = _build_ingress(hostname, cmd.ingress)
        tunnel = Tunnel.request(
            tenant_id=tenant_vo,
            hostname=hostname,
            ingress=ingress,
            cf_zone_id=cmd.cf_zone_id,
            cluster=tenant.k8s_cluster or cmd.cluster,
            namespace=tenant.k8s_namespace,
            requested_by=cmd.requested_by,
        )
        tunnel.begin_provisioning()
        await self._tunnels.add(tunnel)

        # ---------- run saga under distributed lock ----------
        saga = self._saga_factory.build()
        ctx = SagaContext[CreateTunnelSagaData](
            saga_id=new_saga_id(),
            correlation_id=cmd.correlation_id or "",
            tenant_id=cmd.tenant_id,
            started_at=time.monotonic(),
            data=CreateTunnelSagaData(
                tunnel=tunnel,
                cf_zone_id=cmd.cf_zone_id,
                cluster=tunnel.cluster,
                namespace=tunnel.namespace,
                image=get_settings().kubernetes.cloudflared_image,
                replicas=get_settings().kubernetes.cloudflared_replicas,
            ),
        )

        outcome_str: str
        failed_step: str | None = None
        try:
            async with self._lock.lock(
                f"create_tunnel:{tenant_vo}:{hostname}",
                ttl_seconds=int(get_settings().resilience.saga_global_timeout_seconds),
            ):
                result = await saga.run(ctx)
        except LockAcquisitionFailed as e:
            tunnel.mark_failed(
                step="acquire_lock",
                code="LOCK_ACQUISITION_FAILED",
                message=str(e),
                compensations=[],
            )
            await self._tunnels.save(tunnel)
            raise Conflict("Another saga is in progress for this tunnel") from e
        except SagaCompensationFailed as e:
            tunnel.mark_failed(
                step="<compensation>",
                code=e.code,
                message=e.message,
                compensations=ctx.data.compensations_executed,
            )
            await self._tunnels.save(tunnel)
            await self._publish_failure(tunnel, ctx, "<compensation>", e.code, e.message)
            await self._audit.record(
                actor=cmd.requested_by or "system",
                tenant_id=cmd.tenant_id,
                action="tunnel.create",
                resource=f"tunnel/{tunnel.id.value}",
                outcome="COMPENSATION_FAILED",
                correlation_id=ctx.correlation_id,
            )
            raise

        # ---------- post-saga ----------
        if result.status is SagaStatus.SUCCEEDED:
            tunnel.mark_ready()
            await self._tunnels.save(tunnel)
            await self._publish_success(tunnel, ctx)
            await self._audit.record(
                actor=cmd.requested_by or "system",
                tenant_id=cmd.tenant_id,
                action="tunnel.create",
                resource=f"tunnel/{tunnel.id.value}",
                outcome="SUCCESS",
                correlation_id=ctx.correlation_id,
            )
            outcome_str = "READY"
        else:
            failed_step = result.failed_step or "<unknown>"
            err = result.error
            tunnel.mark_failed(
                step=failed_step,
                code=getattr(err, "code", "SAGA_FAILED"),
                message=getattr(err, "message", str(err)),
                compensations=ctx.data.compensations_executed,
            )
            await self._tunnels.save(tunnel)
            await self._publish_failure(
                tunnel, ctx, failed_step,
                getattr(err, "code", "SAGA_FAILED"),
                getattr(err, "message", str(err)),
            )
            await self._audit.record(
                actor=cmd.requested_by or "system",
                tenant_id=cmd.tenant_id,
                action="tunnel.create",
                resource=f"tunnel/{tunnel.id.value}",
                outcome="FAILED",
                metadata={"failed_step": failed_step},
                correlation_id=ctx.correlation_id,
            )
            outcome_str = "FAILED"

        await self._idem.complete(
            key=idempotency_key,
            response={
                "tunnel_id": str(tunnel.id.value),
                "cf_tunnel_id": tunnel.cf_tunnel_id,
                "status": outcome_str,
                "correlation_id": ctx.correlation_id,
            },
        )

        return CreateTunnelOutcome(
            tunnel_id=tunnel.id.value,
            cf_tunnel_id=tunnel.cf_tunnel_id,
            status=outcome_str,
            failed_step=failed_step,
            duration_seconds=time.monotonic() - started,
            correlation_id=ctx.correlation_id,
        )

    # -------------------------------------------------- emitters

    async def _publish_success(
        self, tunnel: Tunnel, ctx: SagaContext[CreateTunnelSagaData]
    ) -> None:
        env = build_envelope(
            payload=TunnelCreateSuccessPayload(
                tenant_id=tunnel.tenant_id.value,
                tunnel_id=tunnel.id.value,
                cf_tunnel_id=tunnel.cf_tunnel_id or "",
                hostname=str(tunnel.hostname),
                cluster=tunnel.cluster,
                namespace=tunnel.namespace,
                deployment_name=tunnel.deployment_name or "",
                ready_at=utcnow(),
            ),
            event_type="tunnel.create.success.v1",
            tenant_id=tunnel.tenant_id.value,
            producer=self.PRODUCER,
            correlation_id=ctx.correlation_id,
            idempotency_key=f"tenant:{tunnel.tenant_id.value}:hostname:{tunnel.hostname}",
        )
        await self._publisher.publish(Topic.CREATE_SUCCESS, env, key=str(tunnel.id.value))

    async def _publish_failure(
        self,
        tunnel: Tunnel,
        ctx: SagaContext[CreateTunnelSagaData],
        failed_step: str,
        code: str,
        message: str,
    ) -> None:
        env = build_envelope(
            payload=TunnelCreateFailurePayload(
                tenant_id=tunnel.tenant_id.value,
                tunnel_id=tunnel.id.value,
                hostname=str(tunnel.hostname),
                failed_step=failed_step,
                error_code=code,
                error_message=message,
                compensations_run=list(ctx.data.compensations_executed),
                failed_at=utcnow(),
            ),
            event_type="tunnel.create.failure.v1",
            tenant_id=tunnel.tenant_id.value,
            producer=self.PRODUCER,
            correlation_id=ctx.correlation_id,
        )
        await self._publisher.publish(Topic.CREATE_FAILURE, env, key=str(tunnel.id.value))


# --------------------------------------------------------- helpers


def _build_ingress(
    hostname: Hostname, rules: Iterable[IngressRuleInput]
) -> IngressRuleSet:
    parsed: list[IngressRule] = []
    for r in rules:
        parsed.append(
            IngressRule(
                service=r.service,
                hostname=r.hostname or str(hostname),
                path=r.path,
                origin_request=(
                    IngressOriginConfig(**r.origin_request) if r.origin_request else None
                ),
            )
        )
    parsed.append(IngressRule(service="http_status:404"))   # mandatory catch-all
    return IngressRuleSet(tuple(parsed))
