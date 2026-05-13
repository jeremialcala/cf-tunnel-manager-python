"""Centralised topic catalog.

Single source of truth for topic names so producers, consumers and
infrastructure scripts cannot drift.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Topic(StrEnum):
    CREATE_REQUEST     = "tunnel.create.request"
    CREATE_PROCESSING  = "tunnel.create.processing"
    CREATE_SUCCESS     = "tunnel.create.success"
    CREATE_FAILURE     = "tunnel.create.failure"

    DELETE_REQUEST     = "tunnel.delete.request"
    DELETE_SUCCESS     = "tunnel.delete.success"
    DELETE_FAILURE     = "tunnel.delete.failure"

    UPDATE_REQUEST     = "tunnel.update.request"
    UPDATE_SUCCESS     = "tunnel.update.success"
    UPDATE_FAILURE     = "tunnel.update.failure"

    VALIDATION_REQUEST = "tunnel.validation.request"
    VALIDATION_SUCCESS = "tunnel.validation.success"
    VALIDATION_FAILURE = "tunnel.validation.failure"

    RECONCILE_REQUEST  = "tunnel.reconcile.request"

    AUDIT              = "tunnel.audit"
    DLQ                = "tunnel.dlq"
    SAGA_STATE         = "tunnel.saga.state"


@dataclass(frozen=True, slots=True)
class TopicSpec:
    name: Topic
    partitions: int
    retention_ms: int                # -1 == unlimited (compacted)
    cleanup_policy: str              # "delete" | "compact"
    key_field: str                   # which envelope field to use as key


# 7d  = 7  * 24 * 3600 * 1000 = 604_800_000
# 30d = 30 * 24 * 3600 * 1000 = 2_592_000_000
# 90d = 90 * 24 * 3600 * 1000 = 7_776_000_000
TOPIC_CATALOG: tuple[TopicSpec, ...] = (
    TopicSpec(Topic.CREATE_REQUEST,     12, 604_800_000,    "delete",  "tenant_id"),
    TopicSpec(Topic.CREATE_PROCESSING,  12,  86_400_000,    "delete",  "tunnel_id"),
    TopicSpec(Topic.CREATE_SUCCESS,     12, 2_592_000_000,  "delete",  "tunnel_id"),
    TopicSpec(Topic.CREATE_FAILURE,     12, 2_592_000_000,  "delete",  "tunnel_id"),
    TopicSpec(Topic.DELETE_REQUEST,     12, 604_800_000,    "delete",  "tenant_id"),
    TopicSpec(Topic.DELETE_SUCCESS,     12, 2_592_000_000,  "delete",  "tunnel_id"),
    TopicSpec(Topic.DELETE_FAILURE,     12, 2_592_000_000,  "delete",  "tunnel_id"),
    TopicSpec(Topic.UPDATE_REQUEST,     12, 604_800_000,    "delete",  "tenant_id"),
    TopicSpec(Topic.UPDATE_SUCCESS,     12, 2_592_000_000,  "delete",  "tunnel_id"),
    TopicSpec(Topic.UPDATE_FAILURE,     12, 2_592_000_000,  "delete",  "tunnel_id"),
    TopicSpec(Topic.VALIDATION_REQUEST, 12,  86_400_000,    "delete",  "tenant_id"),
    TopicSpec(Topic.VALIDATION_SUCCESS, 12, 604_800_000,    "delete",  "tunnel_id"),
    TopicSpec(Topic.VALIDATION_FAILURE, 12, 2_592_000_000,  "delete",  "tunnel_id"),
    TopicSpec(Topic.RECONCILE_REQUEST,  12,  86_400_000,    "delete",  "tenant_id"),
    TopicSpec(Topic.DLQ,                12, 7_776_000_000,  "delete",  "tenant_id"),
    TopicSpec(Topic.AUDIT,              12, 2_592_000_000,  "delete",  "tenant_id"),
    TopicSpec(Topic.SAGA_STATE,         12, -1,             "compact", "saga_id"),
)
