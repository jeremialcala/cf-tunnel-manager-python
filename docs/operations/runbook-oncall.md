# On-call runbook

This runbook is the first thing the on-call engineer reads at 03:00.
Each section follows the format: **Symptom → Triage → Mitigation → Root cause search**.

> Pages from this service are routed to the `tunnel-orchestrator-oncall` PagerDuty service.

## At a glance

| Where | URL |
|---|---|
| Grafana dashboard | https://grafana.example.com/d/tunnel-orchestrator |
| SigNoz traces | https://signoz.example.com/services/tunnel-orchestrator |
| Logs (Loki) | `{app="tunnel-orchestrator"}` |
| ArgoCD app | https://argocd.example.com/applications/tunnel-orchestrator |
| Source | https://github.com/your-org/tunnel-orchestrator |

## Common alerts

### `TunnelCreationFailureRateHigh`

- **Symptom**: > 5% of `tunnel.create.request` events end in `tunnel.create.failure` over 10 min.
- **Triage**:
  1. Open Grafana → "Saga step failures" panel. Identify the failing step.
  2. If it's `verify_dns` or `verify_http`: probably Cloudflare propagation lag — check Cloudflare status page.
  3. If it's `create_cloudflare_tunnel`: check `cloudflare_api_calls_total{status="api_5xx"}`.
  4. If it's `create_k8s_deployment`: check the target cluster API server health.
- **Mitigation**: pause the producing topic by scaling consumers to zero (`kubectl scale deploy/tunnel-orchestrator-worker --replicas=0`). Backlog will accumulate but nothing is lost (Kafka retention 7d).
- **Root cause**: traces in SigNoz filtered by `error.code` show the upstream error.

### `KafkaConsumerLagHigh`

- **Symptom**: `kafka_consumer_lag` > 1000 for any partition for > 5 min.
- **Triage**: check pod CPU + saga in-flight gauge. If CPU saturated, scale (HPA usually does it; if KEDA-driven, verify `ScaledObject` reports correct lag).
- **Mitigation**: `kubectl scale deploy/tunnel-orchestrator-worker --replicas=N` (max safely = number of partitions).
- **Root cause**: a tenant flooding requests, or downstream Cloudflare 429s slowing sagas.

### `OutboxBacklogGrowing`

- **Symptom**: `select count(*) from outbox_events where status='PENDING'` keeps growing.
- **Triage**: check `outbox.relay` logs for `outbox.relay.send_failed`.
- **Mitigation**: ensure Kafka producer is healthy; restart workers to reinitialise it.
- **Root cause**: Kafka cluster degraded, or schema registry returning 5xx blocking serialisation.

### `CloudflareUnauthorized`

- **Symptom**: `cloudflare_api_calls_total{status="unauthorized"}` > 0.
- **Triage**: identify the affected `tenant_id` from the metric labels. The token has been revoked / rotated externally.
- **Mitigation**: rotate the token via `make rotate-tenant-token TENANT=<slug>`; the registry's TTL cache will pick the new token within 5 min, or call `/v1/admin/tenants/{id}/rotate` to invalidate immediately.

### `CompensationFailed` (PAGER)

- **Symptom**: `saga_compensations_total{outcome="failed"}` > 0.
- **Severity**: HIGH. The system left orphaned resources somewhere.
- **Triage**: query `saga_steps where status='FAILED' AND saga_id IN (select id from saga_instances where status='COMPENSATION_FAILED')`. The error column tells you which compensation didn't run.
- **Mitigation**: manually clean up:
  - Orphan Cloudflare tunnel: `cloudflared tunnel delete <id>` or via Dash.
  - Orphan DNS record: delete in Cloudflare DNS UI.
  - Orphan K8s `Deployment`/`Secret`: `kubectl -n <ns> delete deploy,secret -l tunnel-orchestrator.io/tunnel-id=<id>`.
- After: re-run the saga from the DLQ if appropriate.

## Useful queries

```bash
# Sagas currently in flight, sorted by oldest
kubectl exec -n tunnel-orchestrator deploy/tunnel-orchestrator-api -- \
  psql "$DATABASE_URL" -c \
  "select id, type, status, created_at from saga_instances
   where status in ('PENDING','IN_PROGRESS','COMPENSATING')
   order by created_at asc limit 50;"

# DLQ messages waiting for triage
kubectl exec -n tunnel-orchestrator deploy/tunnel-orchestrator-dlq -- \
  python scripts/dlq_inspect.py --limit 20

# Tunnel state for one tenant
kubectl exec ... -- psql ... -c \
  "select id, hostname, status, last_error from tunnels where tenant_id='<uuid>';"
```

## Manual replay from DLQ

```bash
# Inspect
python scripts/dlq_replay.py --inspect --topic tunnel.dlq --max 50

# Replay specific message id back to its origin topic
python scripts/dlq_replay.py --replay --event-id 01HM9...
```

## Escalation

- **Cloudflare-side incident** → contact CF Enterprise support (case template in Confluence).
- **Kubernetes API outage in tenant cluster** → page the SRE rotation for that cluster.
- **Schema Registry down** → page `messaging-platform`.
