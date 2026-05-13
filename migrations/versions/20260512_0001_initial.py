"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-05-12

Creates: tenants, tunnels, saga_instances, saga_steps,
outbox_events, idempotency_keys, audit_log.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("slug", sa.String(63), nullable=False, unique=True),
        sa.Column("cf_account_id", sa.String(64), nullable=False),
        sa.Column("cf_token_vault_path", sa.String(255), nullable=False),
        sa.Column("k8s_namespace", sa.String(63), nullable=False),
        sa.Column("k8s_cluster", sa.String(64), nullable=False, server_default="default"),
        sa.Column("cf_zone_ids", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("quota_max_tunnels", sa.Integer, nullable=False, server_default="200"),
        sa.Column("status", sa.String(32), nullable=False, server_default="PROVISIONING"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "tunnels",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("hostname", sa.String(253), nullable=False),
        sa.Column("cf_zone_id", sa.String(64), nullable=False),
        sa.Column("cluster", sa.String(64), nullable=False, server_default="default"),
        sa.Column("namespace", sa.String(63), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="REQUESTED"),
        sa.Column("cf_tunnel_id", sa.String(64), nullable=True),
        sa.Column("cf_dns_record_id", sa.String(64), nullable=True),
        sa.Column("deployment_name", sa.String(253), nullable=True),
        sa.Column("secret_name", sa.String(253), nullable=True),
        sa.Column("ingress", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("tenant_id", "hostname", name="ux_tunnel_tenant_hostname"),
    )
    op.create_index("ix_tunnel_tenant_status", "tunnels", ["tenant_id", "status"])

    op.create_table(
        "saga_instances",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("correlation_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("context", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "saga_steps",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("saga_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("saga_instances.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="1"),
        sa.Column("output", postgresql.JSONB, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("duration_seconds", sa.Float, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_saga_step_saga", "saga_steps", ["saga_id"])

    op.create_table(
        "outbox_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("topic", sa.String(128), nullable=False),
        sa.Column("key", sa.LargeBinary, nullable=True),
        sa.Column("payload", sa.LargeBinary, nullable=False),
        sa.Column("headers", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("status", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_outbox_pending", "outbox_events", ["status", "scheduled_at"])

    op.create_table(
        "idempotency_keys",
        sa.Column("key", sa.String(255), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("response", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_idempotency_expires", "idempotency_keys", ["expires_at"])

    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("actor", sa.String(255), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("resource", sa.String(255), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("correlation_id", sa.String(64), nullable=True),
        sa.Column("before", postgresql.JSONB, nullable=True),
        sa.Column("after", postgresql.JSONB, nullable=True),
        sa.Column("metadata", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("ts", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_audit_tenant_ts", "audit_log", ["tenant_id", "ts"])
    op.create_index("ix_audit_correlation", "audit_log", ["correlation_id"])


def downgrade() -> None:
    for tbl in (
        "audit_log", "idempotency_keys", "outbox_events",
        "saga_steps", "saga_instances", "tunnels", "tenants",
    ):
        op.drop_table(tbl)
