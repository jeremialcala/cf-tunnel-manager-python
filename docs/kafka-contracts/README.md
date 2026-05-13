# Kafka contracts

This directory documents every Kafka topic the platform produces or consumes.
For every topic you'll find:

- **Schema (Avro)** — `platform/schemas/*.avsc` (the wire contract)
- **Pydantic model** — `platform/events/payloads.py` (the runtime contract)
- **Compatibility level** — `BACKWARD` (default for all topics)
- **Key field** — used for partitioning (single source of truth in `platform/events/topics.py`)

## Envelope

All payloads are wrapped in a generic envelope (`platform/schemas/envelope.avsc`):

| Field | Type | Notes |
|---|---|---|
| `schema_id` | `int?` | Confluent SR id |
| `event_id` | `string` (ULID) | Unique per event, used for dedup |
| `event_type` | `string` | e.g. `tunnel.create.request.v1` |
| `event_version` | `int` | parallel to `event_type` minor version |
| `occurred_at` | `timestamp-micros` | UTC |
| `producer` | `string` | service name + version |
| `correlation_id` | `string` | propagated end-to-end |
| `causation_id` | `string?` | event_id of the cause |
| `tenant_id` | `uuid` | always present |
| `idempotency_key` | `string?` | `tenant:{id}:hostname:{h}` form |
| `trace_context` | record | W3C `traceparent` / `tracestate` |
| `payload_json` | `string` | UTF-8 JSON of the typed payload |

## Topics

| Topic | Producer | Consumer | Key | Schema |
|---|---|---|---|---|
| `tunnel.create.request` | API GW, ext clients | `worker` | `tenant_id` | [tunnel_create_request.avsc](../../platform/schemas/tunnel_create_request.avsc) |
| `tunnel.create.success` | `worker/saga` | downstream | `tunnel_id` | [tunnel_create_success.avsc](../../platform/schemas/tunnel_create_success.avsc) |
| `tunnel.create.failure` | `worker/saga` | alerting | `tunnel_id` | [tunnel_create_failure.avsc](../../platform/schemas/tunnel_create_failure.avsc) |
| `tunnel.delete.request` | API GW, ext clients | `worker` | `tenant_id` | [tunnel_delete_request.avsc](../../platform/schemas/tunnel_delete_request.avsc) |
| `tunnel.delete.success` | `worker/saga` | downstream | `tunnel_id` | (mirrors success shape) |
| `tunnel.delete.failure` | `worker/saga` | alerting | `tunnel_id` | (mirrors failure shape) |
| `tunnel.validation.*` | scheduler / worker | observability | `tenant_id` / `tunnel_id` | (similar shape) |
| `tunnel.dlq` | worker (poison handler) | `dlq_processor` | `tenant_id` | [tunnel_dlq.avsc](../../platform/schemas/tunnel_dlq.avsc) |

## Versioning policy

- **Optional field added** → no schema bump, no topic change.
- **Field removed / renamed / typed differently** → bump `event_type` minor (`v1 → v2`), produce both for ≥ 30 days, drop old after consumers migrated.
- **Topic taxonomy change** → introduce a new topic; mirror writes for ≥ 30 days.

## Pydantic ↔ Avro contract test

`tests/contract/test_avro_pydantic_parity.py` asserts:

- Each Pydantic model in `platform/events/payloads.py` has a sibling `.avsc`.
- Pydantic `model_json_schema()` and `fastavro.parse_schema()` accept each other's example payloads.

This catches drift before it reaches production.
