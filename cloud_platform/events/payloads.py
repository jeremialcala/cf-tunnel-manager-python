"""Strongly-typed business payloads (one model per topic)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from shared.types import HostnameStr, NonEmptyStr, utcnow


class _Payload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


# ============================================================
# CREATE
# ============================================================


class IngressRulePayload(_Payload):
    service: NonEmptyStr
    hostname: HostnameStr | None = None
    path: str | None = None
    origin_request: dict[str, Any] | None = None


class TunnelCreateRequestPayload(_Payload):
    """Inbound request to provision a tunnel."""

    tenant_id: UUID
    hostname: HostnameStr
    cf_zone_id: NonEmptyStr
    cluster: NonEmptyStr = Field(default="default")
    ingress: list[IngressRulePayload] = Field(min_length=1)
    requested_by: str | None = None


class TunnelCreateSuccessPayload(_Payload):
    tenant_id: UUID
    tunnel_id: UUID
    cf_tunnel_id: NonEmptyStr
    hostname: HostnameStr
    cluster: NonEmptyStr
    namespace: NonEmptyStr
    deployment_name: NonEmptyStr
    ready_at: datetime = Field(default_factory=utcnow)


class TunnelCreateFailurePayload(_Payload):
    tenant_id: UUID
    tunnel_id: UUID | None = None
    hostname: HostnameStr
    failed_step: NonEmptyStr
    error_code: NonEmptyStr
    error_message: str
    compensations_run: list[str] = Field(default_factory=list)
    failed_at: datetime = Field(default_factory=utcnow)


# ============================================================
# DELETE
# ============================================================


class TunnelDeleteRequestPayload(_Payload):
    tenant_id: UUID
    tunnel_id: UUID
    requested_by: str | None = None


class TunnelDeleteSuccessPayload(_Payload):
    tenant_id: UUID
    tunnel_id: UUID
    cf_tunnel_id: NonEmptyStr
    deleted_at: datetime = Field(default_factory=utcnow)


class TunnelDeleteFailurePayload(_Payload):
    tenant_id: UUID
    tunnel_id: UUID
    cf_tunnel_id: NonEmptyStr | None = None
    failed_step: NonEmptyStr
    error_code: NonEmptyStr
    error_message: str
    failed_at: datetime = Field(default_factory=utcnow)


# ============================================================
# UPDATE
# ============================================================


class TunnelUpdateRequestPayload(_Payload):
    tenant_id: UUID
    tunnel_id: UUID
    ingress: list[IngressRulePayload] | None = None
    requested_by: str | None = None


# ============================================================
# VALIDATION
# ============================================================


class TunnelValidationRequestPayload(_Payload):
    tenant_id: UUID
    tunnel_id: UUID


class TunnelValidationSuccessPayload(_Payload):
    tenant_id: UUID
    tunnel_id: UUID
    cf_tunnel_id: NonEmptyStr
    hostname: HostnameStr
    dns_ok: bool
    http_ok: bool
    latency_ms: float | None = None
    validated_at: datetime = Field(default_factory=utcnow)


class TunnelValidationFailurePayload(_Payload):
    tenant_id: UUID
    tunnel_id: UUID
    cf_tunnel_id: NonEmptyStr
    hostname: HostnameStr
    reason: NonEmptyStr
    failed_at: datetime = Field(default_factory=utcnow)


# ============================================================
# RECONCILIATION
# ============================================================


class TunnelReconcileRequestPayload(_Payload):
    tenant_id: UUID
    tunnel_id: UUID | None = None
    scope: str = "tunnel"          # "tunnel" | "tenant" | "all"


# ============================================================
# DLQ / Audit
# ============================================================


class TunnelDlqPayload(_Payload):
    """Carries the failed message and reason for operator triage."""

    original_topic: NonEmptyStr
    original_partition: int
    original_offset: int
    original_event_type: str
    original_payload_b64: str
    original_headers: dict[str, str] = Field(default_factory=dict)
    dlq_reason: NonEmptyStr
    dlq_stack: str | None = None
    first_seen_at: datetime = Field(default_factory=utcnow)
    attempts: int = 1
