"""SQLAlchemy 2.0 mapped models.

These are the **persistence projection** of domain aggregates — never
imported by application/domain layers. Repositories translate to/from
the domain via :pyfunc:`Tunnel.hydrate`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    type_annotation_map = {dict: JSONB, dict[str, Any]: JSONB}


# ---------------------------------------------------------------- tenant


class TenantRow(Base):
    __tablename__ = "tenants"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    slug: Mapped[str] = mapped_column(String(63), nullable=False, unique=True)
    cf_account_id: Mapped[str] = mapped_column(String(64), nullable=False)
    cf_token_vault_path: Mapped[str] = mapped_column(String(255), nullable=False)
    k8s_namespace: Mapped[str] = mapped_column(String(63), nullable=False)
    k8s_cluster: Mapped[str] = mapped_column(String(64), nullable=False, default="default")
    cf_zone_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    quota_max_tunnels: Mapped[int] = mapped_column(Integer, nullable=False, default=200)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PROVISIONING")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# ---------------------------------------------------------------- tunnel


class TunnelRow(Base):
    __tablename__ = "tunnels"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False
    )
    hostname: Mapped[str] = mapped_column(String(253), nullable=False)
    cf_zone_id: Mapped[str] = mapped_column(String(64), nullable=False)
    cluster: Mapped[str] = mapped_column(String(64), nullable=False, default="default")
    namespace: Mapped[str] = mapped_column(String(63), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="REQUESTED")
    cf_tunnel_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cf_dns_record_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    deployment_name: Mapped[str | None] = mapped_column(String(253), nullable=True)
    secret_name: Mapped[str | None] = mapped_column(String(253), nullable=True)
    ingress: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "hostname", name="ux_tunnel_tenant_hostname"),
        Index("ix_tunnel_tenant_status", "tenant_id", "status"),
    )


# ----------------------------------------------------------------- saga


class SagaInstanceRow(Base):
    __tablename__ = "saga_instances"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    steps: Mapped[list["SagaStepRow"]] = relationship(
        back_populates="saga", cascade="all, delete-orphan"
    )


class SagaStepRow(Base):
    __tablename__ = "saga_steps"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    saga_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("saga_instances.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_seconds: Mapped[float] = mapped_column(nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    saga: Mapped[SagaInstanceRow] = relationship(back_populates="steps")

    __table_args__ = (Index("ix_saga_step_saga", "saga_id"),)


# ---------------------------------------------------------------- outbox


class OutboxRow(Base):
    __tablename__ = "outbox_events"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid4)
    topic: Mapped[str] = mapped_column(String(128), nullable=False)
    key: Mapped[bytes] = mapped_column(LargeBinary, nullable=True)
    payload: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    headers: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_outbox_pending", "status", "scheduled_at"),
    )


# ----------------------------------------------------------- idempotency


class IdempotencyRow(Base):
    __tablename__ = "idempotency_keys"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_idempotency_expires", "expires_at"),)


# --------------------------------------------------------------- audit


class AuditRow(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    tenant_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    resource: Mapped[str] = mapped_column(String(255), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    extra_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_audit_tenant_ts", "tenant_id", "ts"),
        Index("ix_audit_correlation", "correlation_id"),
    )
