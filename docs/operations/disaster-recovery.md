# Disaster Recovery

## RTO / RPO targets

| Failure | RTO | RPO |
|---|---|---|
| Single Pod loss | < 30 s | 0 |
| Whole region (cluster) loss | < 30 min | < 5 min |
| PostgreSQL primary loss | < 5 min | 0 (sync replica) |
| Kafka broker loss | < 1 min | 0 |
| Cloudflare API outage | n/a | n/a |

## Backups

- **PostgreSQL**: PITR enabled; nightly base backup + 5-min WAL archiving to object storage. Retention 30 days.
- **Schema Registry**: schemas live in the `_schemas` Kafka topic with `min.insync.replicas=2` + cluster-level mirror to DR region.
- **Vault** (tenant tokens): Raft snapshot every 6h to S3.

## DR rebuild — region failover

1. Promote the DR PG replica (managed service: standard failover).
2. Apply the latest Alembic migration (idempotent; should be a no-op).
3. ArgoCD `ApplicationSet` already deploys the orchestrator in the DR region — point traffic by updating the global LB / GeoDNS.
4. The orchestrator boots, drains its outbox, and resumes consuming from the DR Kafka cluster (mirrored via MirrorMaker 2).
5. Verify a sample `tunnel.create.request` end-to-end.

## DR rebuild — full bootstrap from cold

```bash
# 0) Provision infra (Terraform)
cd deployments/terraform/cloudflare-account
terraform apply -var "tenant_slug=acme" ...

# 1) Restore PG from latest backup, run migrations
make migrate

# 2) Re-register Avro schemas
python scripts/register_schemas.py --schemas-dir platform/schemas

# 3) Re-create Kafka topics (idempotent)
bash scripts/create_topics.sh

# 4) Deploy
helm upgrade --install tunnel-orchestrator charts/tunnel-orchestrator -f values.prod.yaml

# 5) Reconcile state vs Cloudflare (drift detection)
kubectl exec deploy/tunnel-orchestrator-scheduler -- python -m apps.scheduler.jobs.reconcile_drift
```

## Data loss scenarios

### Lost a Kafka topic / partition
- Replay from the **outbox table** if the missing events were produced by us (most cases).
  ```bash
  python scripts/outbox_replay.py --topic tunnel.create.success --since '2026-05-01'
  ```
- Replay from upstream producers if they own the lost events.

### Corrupt PG row
- Tunnels are idempotent: re-create from the source of truth (`tunnel.create.request`) by replaying the event.

### Lost Cloudflare token
- Run `terraform apply` with `force_rotate=true` → new token in Vault → orchestrator picks up on next 5-min cache cycle.

## Game days

Quarterly chaos exercises:

1. Kill all worker pods during peak load.
2. Block egress to Cloudflare API for 5 min.
3. Force a Kafka leader election by cordoning the broker host.
4. Simulate Vault unavailability for 2 min.

Each exercise has a runbook in `docs/operations/gamedays/`.
