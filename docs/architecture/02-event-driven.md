# Event-Driven Architecture

## 1. Topic taxonomy

Topics follow a strict naming convention: `<bounded-context>.<entity>.<intent>`.

| Topic | Producer | Consumer(s) | Key | Partitions | Retention | Cleanup |
|---|---|---|---|---|---|---|
| `tunnel.create.request` | external clients, API GW | `worker` | `tenant_id` | 12 | 7d | delete |
| `tunnel.create.processing` | `worker/saga` | observability sink | `tunnel_id` | 12 | 1d | delete |
| `tunnel.create.success` | `worker/saga` | downstream services | `tunnel_id` | 12 | 30d | delete |
| `tunnel.create.failure` | `worker/saga` | alerting, audit | `tunnel_id` | 12 | 30d | delete |
| `tunnel.delete.request` | external clients, API GW | `worker` | `tenant_id` | 12 | 7d | delete |
| `tunnel.delete.success` | `worker/saga` | downstream | `tunnel_id` | 12 | 30d | delete |
| `tunnel.delete.failure` | `worker/saga` | alerting | `tunnel_id` | 12 | 30d | delete |
| `tunnel.update.request` | external | `worker` | `tenant_id` | 12 | 7d | delete |
| `tunnel.update.success` | `worker/saga` | downstream | `tunnel_id` | 12 | 30d | delete |
| `tunnel.update.failure` | `worker/saga` | alerting | `tunnel_id` | 12 | 30d | delete |
| `tunnel.validation.request` | `scheduler` | `worker` | `tenant_id` | 12 | 1d | delete |
| `tunnel.validation.success` | `worker` | observability | `tunnel_id` | 12 | 7d | delete |
| `tunnel.validation.failure` | `worker` | alerting | `tunnel_id` | 12 | 30d | delete |
| `tunnel.reconcile.request` | `scheduler` | `worker` | `tenant_id` | 12 | 1d | delete |
| `tunnel.dlq` | `worker` (poison handler) | `dlq_processor` | `tenant_id` | 12 | 90d | delete |
| `tunnel.audit` | all | audit sink | `tenant_id` | 12 | 30d | delete |
| `tunnel.saga.state` | `worker` | observability projection | `saga_id` | 12 | ∞ | **compact** |

### Partitioning rationale
- `tenant_id` for *request* topics → all writes for one tenant land on the same partition, preserving order and naturally rate-limiting per tenant.
- `tunnel_id` for downstream events → fine-grained parallelism for consumers projecting per-tunnel state.

## 2. Message envelope

Every payload is wrapped in a generic envelope to keep cross-cutting concerns out of the business schema:

```jsonc
{
  "schema_id": 42,                                // Confluent SR schema id (for Avro)
  "event_id": "01HM9...ULID",                     // ULID, deduplication key
  "event_type": "tunnel.create.request.v1",
  "event_version": 1,
  "occurred_at": "2026-05-11T12:00:00Z",
  "producer": "api-gateway@v1.4.2",
  "correlation_id": "01HM9...",                   // propagates across saga + downstream
  "causation_id": "01HM9...",                     // event_id of the cause
  "tenant_id": "01HM9...",
  "trace_context": { "traceparent": "00-...-01" },
  "idempotency_key": "tenant:abc:hostname:foo.example.com",
  "payload": { ... business payload ... }
}
```

Headers carry the *same* IDs at the Kafka header level so they survive payload re-serialisation and are visible without parsing the body.

## 3. Versioning strategy

- **Major version in `event_type`** (`...v1`, `...v2`) — breaking changes get a new topic *only* if consumers cannot be migrated transparently.
- **Avro `BACKWARD` compatibility** in Schema Registry (default subject naming `topic-value`).
- New optional fields → minor bump, no topic change.
- Removed/renamed fields → new event type *and* parallel publishing of v1+v2 during a deprecation window of ≥ 30 days.

## 4. Producer guarantees

```python
KafkaProducer(
    enable_idempotence=True,
    acks="all",
    max_in_flight_requests_per_connection=5,
    compression_type="lz4",
    transactional_id=f"tunnel-orch-{pod}-{partitions_hash}",
)
```

- All `*.success` / `*.failure` topics are written **transactionally** with the consumer offset commit and the outbox row update — true exactly-once.
- The producer is **shared per process**, never per request, to keep the transactional id stable.

## 5. Consumer guarantees

```python
KafkaConsumer(
    group_id="tunnel-orchestrator-workers",
    enable_auto_commit=False,
    isolation_level="read_committed",
    max_poll_records=20,
    session_timeout_ms=30000,
    heartbeat_interval_ms=3000,
    auto_offset_reset="earliest",
)
```

- Manual offset commit *inside* the producer transaction.
- A **bounded** `asyncio.Semaphore` in the worker limits in-flight sagas per partition.
- A poison message (decode error or repeated step failure with non-retriable code) is published to `tunnel.dlq` **before** committing the offset, so it is never lost.

## 6. Schema Registry layout

Schemas live in `platform/schemas/` and are registered at deploy time by `scripts/register_schemas.sh`. Subject naming:

```
tunnel.create.request-value
tunnel.create.success-value
tunnel.create.failure-value
...
```

Each `.avsc` is paired with a Pydantic model in `platform/events/` whose JSON schema is asserted equivalent in `tests/contract/`.

## 7. Backpressure

- **Producer**: `linger.ms=20`, `batch.size=64KB`, `buffer.memory=64MB`. If buffer fills the producer call awaits — the saga step naturally blocks.
- **Consumer**: `max.poll.records=20` + `Semaphore(20)` ensures a single consumer never holds more than 20 sagas in memory.
- **Cloudflare**: `aiolimiter.AsyncLimiter(1200, 300)` per token. When throttled, the saga step `await`s — the partition advances slower but never drops messages.

## 8. Dead Letter Queue (DLQ)

When a message:

1. Fails Avro decoding → DLQ with `dlq_reason="DECODE_ERROR"`.
2. Fails idempotency lookup with corrupt key → DLQ with `dlq_reason="BAD_IDEMPOTENCY_KEY"`.
3. Throws a non-retriable error after exhausting retries → DLQ with `dlq_reason="STEP_FATAL"` and the failing step name.

`apps/dlq_processor` consumes `tunnel.dlq`, applies a configurable replay policy (manual, scheduled, or skip), and exposes a CLI for ops.
