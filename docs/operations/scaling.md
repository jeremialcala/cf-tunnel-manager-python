# Scaling guide

## Reference numbers

Tested on a 3-node cluster (8 vCPU / 16 GiB each) with Kafka MSK 3-broker.

| Metric | Single API pod | Single worker pod |
|---|---|---|
| Sustained RPS (POST /tunnels) | ~150 | — |
| Sustained sagas / min | — | ~120 |
| P95 saga duration (happy path) | — | 18 s (DNS dominates) |
| Memory steady-state | 280 MiB | 420 MiB |
| CPU steady-state @ load | 0.55 vCPU | 0.85 vCPU |

> The sustained throughput is bounded by **Cloudflare API rate limits** (1200 req/5 min per token) far more often than by our resources. Each create saga issues ~6 CF calls. So ~200 sagas / 5 min per tenant token.

## Scaling primitives

### API
- **HPA on CPU + RPS**. RPS via `keda-prometheus` scaler (optional); CPU is sufficient for most loads.
- Horizontal scaling is linear up to ~12 pods; beyond that, PG connection pool becomes the bottleneck (raise `DATABASE_POOL_SIZE`).

### Worker
- **HPA on consumer lag (KEDA)**. Each pod consumes from one or more partitions; max useful pods = total partitions (default 12).
- For burst tolerance set `maxReplicas = 2 × partitions` and partition rebalancing will sort the rest (cooperative-sticky).

### Topics
- Default 12 partitions per topic. To support more parallelism for one tenant, you'd need to **increase partitions** *and* re-key (e.g. `tenant:hostname-bucket`). Re-keying is a topic migration — see `docs/operations/topic-migration.md`.

### PostgreSQL
- Plan ~50 connections per worker pod (saga + repo + outbox relay).
- Read-replicas are **not** required: all reads go through tenant-scoped queries with proper indexes.
- For > 10⁶ tunnels, partition `tunnels` and `audit_log` by `tenant_id` hash range.

### Redis
- Used only for distributed locks and cache. ~5 ops per saga. A single 1 GiB instance handles ~10k sagas/min.
- For HA, use Redis Sentinel or managed (ElastiCache, Memorystore). Use **Redlock** if you cluster across regions.

### Cloudflare token
- Per-tenant `aiolimiter` keeps you under 1200 req / 5 min.
- For very high-throughput tenants, Cloudflare can grant higher limits — request through your account team.

## Multi-region

- Each region deploys its own Helm release pointing to a regional Kafka cluster.
- PG: option A (recommended) — a single global PG with regional read replicas; option B — regional DBs with Debezium → cross-region outbox replication.
- ArgoCD `ApplicationSet` (`region` generator) keeps releases identical.

## Multi-cluster

- Same orchestrator, multiple tenant clusters: set `K8S_MULTI_CLUSTER_CONFIG`.
- Each tenant's `cluster` field is honoured by `KubernetesClientFactory`.
- For cross-cluster RBAC, replicate the `Role` + `RoleBinding` per cluster (the chart's `rbac.managedNamespaces` accepts cluster-qualified names if you template per-cluster).

## Sizing cheatsheet

> RPS = sagas/sec, P = partitions, T = avg tenant CF rate-limit usage

```
api_replicas    = ceil(RPS / 100) + 1
worker_replicas = min(P, ceil(RPS × P95_saga_duration / WORKER_CONCURRENCY))
db_pool_size    = 10 × worker_replicas + 5 × api_replicas
```
