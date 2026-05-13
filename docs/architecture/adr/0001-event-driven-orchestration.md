# ADR 0001 — Event-driven orchestration over RPC

- Status: Accepted
- Date: 2026-04-08

## Context
We need to provision tunnels on behalf of many internal teams. Provisioning involves several external systems (Cloudflare, Kubernetes, DNS) each of which is occasionally slow or rate-limited. We must support back-pressure, retries, replay, and audit, and we must not lose requests.

## Decision
Use Apache Kafka as the source of truth for incoming intents and Sagas for the orchestration. The HTTP API is a thin adapter over the same handlers — it is *not* the system of record.

## Consequences
- Producers don't need to wait for slow upstreams; they fire-and-forget into Kafka.
- We can reprocess history by rewinding consumer offsets — useful for backfills and disaster recovery.
- Adds operational complexity (Kafka, Schema Registry, outbox).
- Forces strict idempotency everywhere.
