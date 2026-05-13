# Observability

## Signals

| Signal | Backend | Where to look |
|---|---|---|
| Logs | Loki / SigNoz Logs | `{app="tunnel-orchestrator"} |= "saga"` |
| Metrics | Prometheus / Mimir | Grafana dashboard `tunnel-orchestrator` |
| Traces | SigNoz / Tempo | filter by `service.name=tunnel-orchestrator` |
| Audit | PostgreSQL `audit_log` table | Grafana data source `Postgres-Audit` |

## Key metrics

```promql
# Saga success rate (per saga type)
sum(rate(saga_completed_total{outcome="succeeded"}[5m])) by (saga_type)
/
sum(rate(saga_completed_total[5m])) by (saga_type)

# P95 saga duration
histogram_quantile(0.95, sum(rate(saga_step_duration_seconds_bucket[5m])) by (le, saga_type))

# Cloudflare API latency P95 by op
histogram_quantile(0.95, sum(rate(cloudflare_api_call_duration_seconds_bucket[5m])) by (le, operation))

# Consumer lag total
sum(kafka_consumer_lag) by (topic)

# Compensation rate (any > 0 is a smell, > 0.05 is bad)
sum(rate(saga_compensations_total{outcome="succeeded"}[5m])) /
sum(rate(saga_started_total[5m]))
```

## Alerts (excerpt)

```yaml
- alert: TunnelCreationFailureRateHigh
  expr: |
    sum(rate(saga_completed_total{saga_type="create_tunnel",outcome="failed"}[10m])) /
    sum(rate(saga_started_total{saga_type="create_tunnel"}[10m])) > 0.05
  for: 5m
  labels: { severity: warning, team: platform }

- alert: KafkaConsumerLagHigh
  expr: max(kafka_consumer_lag) by (topic) > 1000
  for: 5m
  labels: { severity: warning }

- alert: CompensationFailedAny
  expr: increase(saga_compensations_total{outcome="failed"}[5m]) > 0
  labels: { severity: page, team: platform }

- alert: OutboxBacklogGrowing
  expr: |
    deriv(pg_stat_user_tables_n_live_tup{relname="outbox_events"}[10m]) > 10
  for: 10m
  labels: { severity: warning }
```

## Dashboards

Suggested panels (copy into Grafana JSON):

1. **Saga overview**: started/completed/failed by type, P50/P95 duration.
2. **Saga steps heatmap**: `saga_step_duration_seconds` per step.
3. **Cloudflare**: calls/sec, error rate by status, rate-limit headroom per tenant.
4. **Kubernetes**: deployment-ready latency P95, error rate by op.
5. **Kafka**: lag by topic+partition, messages/sec consumed by outcome.
6. **DB / outbox**: outbox depth, oldest pending row age.

## Trace propagation

- API: `traceparent` from incoming HTTP → span → propagated to Kafka header on outbox write.
- Worker: extracts `traceparent` from Kafka header → continues the same trace through the saga and outbound CF/K8s calls.
- This means a single trace ID covers UI → API → Kafka → Saga → Cloudflare/K8s → DNS verify → success event.
