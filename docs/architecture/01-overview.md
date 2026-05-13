# Overview

Tunnel Orchestrator is the platform that lets product teams expose internal services through Cloudflare Zero Trust **declaratively, asynchronously, and idempotently**. A team publishes an event and a fully working tunnel — including DNS, ingress rules, and a dedicated Kubernetes deployment of `cloudflared` — is provisioned and verified, or rolled back atomically.

## Component summary

| Component | Path | Responsibility |
|---|---|---|
| API Gateway | `apps/api` | FastAPI process exposing REST endpoints (mostly thin: validate → publish → return 202) and admin endpoints |
| Worker | `apps/worker` | Long-running process consuming Kafka topics and driving Sagas |
| Scheduler | `apps/scheduler` | Singleton (leader-elected) emitting reconciliation/validation requests on a cron-like schedule |
| DLQ Processor | `apps/dlq_processor` | Consumes `tunnel.dlq`, applies replay policy, exposes CLI for ops |
| Saga Orchestrator | `services/.../application/sagas` | Coordinates the multi-step distributed transactions |
| Cloudflare Adapter | `services/.../infrastructure/cloudflare` | Wraps the official `cloudflare` v5 async SDK |
| Kubernetes Adapter | `services/.../infrastructure/kubernetes` | Wraps `kubernetes_asyncio` with idempotent helpers |
| Verification Engine | `services/.../infrastructure/verification` | DNS resolver + HTTP prober |
| Persistence | `services/.../infrastructure/persistence` | SQLAlchemy 2.0 async repositories + outbox |
| Messaging | `services/.../infrastructure/messaging` | aiokafka producer/consumer + Schema Registry client |

## Lifecycle of a single tunnel

1. Producer publishes `tunnel.create.request` (or calls `POST /tunnels` which does it).
2. A worker consumes the message, deserialises with the Pydantic envelope, validates against Avro.
3. The `CreateTunnelSaga` runs its steps (see saga doc).
4. On success, the worker publishes `tunnel.create.success` *transactionally* with the offset commit.
5. The scheduler periodically issues `tunnel.validation.request` for all `READY` tunnels to re-verify DNS+HTTP.
6. The scheduler also issues `tunnel.reconcile.request` when drift is detected (e.g. Cloudflare-side mutation outside our system).

## What lives where (mental model)

```
your service ──HTTP/Kafka──▶ Tunnel Orchestrator ──Cloudflare API──▶ Cloudflare control plane
                                       │
                                       └──Kubernetes API──▶ tenant namespace ──▶ cloudflared Deployment ──▶ Cloudflare edge
```

The orchestrator does **not** sit in the data path. It only programs the control planes (Cloudflare + Kubernetes). End-user traffic flows directly: client → Cloudflare edge → tunnel → tenant service.

## Why event-driven?

- Producers don't need to know about retries, rate limits, or compensations.
- Backpressure is natural: a slow Cloudflare account just slows that tenant's partition.
- Audit trail is free: every state transition is an event.
- Replay is free: rewind a consumer group offset to reprocess a window.

## Why exactly-once?

A tunnel duplicate would be expensive (a second `cloudflared` Deployment + DNS conflict). Avoiding *at-most-once* is also critical: a lost create event would silently leave a service un-exposed. The combination of transactional outbox + Kafka EOS + idempotency keys delivers true exactly-once for the user-visible side effects.
