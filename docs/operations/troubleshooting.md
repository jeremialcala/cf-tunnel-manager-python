# Troubleshooting

Symptom-first index. Use Ctrl+F.

## "Tunnel created but DNS never resolves"

1. Check `verify_dns` step output in `saga_steps`:
   ```sql
   select error, output from saga_steps
   where name='verify_dns' and saga_id=(
     select id from saga_instances where context->>'tunnel_id'='<id>'
   );
   ```
2. If output shows resolved=false: increase `DNS_VERIFY_TIMEOUT_SECONDS` (some zones propagate slowly) or check the zone's NS delegation in Cloudflare.
3. If a CNAME exists but points to the wrong target: someone edited it in the dashboard. Re-run reconciliation: `POST /v1/tunnels/{id}/validate`.

## "POST /tunnels returns 409 TUNNEL_ALREADY_EXISTS but I never created one"

A previous saga partially succeeded *and* the row exists. Either:

- the saga is still running → check `saga_instances.status`;
- the saga succeeded → the tunnel is real, list it: `GET /v1/tunnels`;
- the row is stale → delete it via `DELETE /v1/tunnels/{id}` (will run cleanup).

## "Cloudflare 401 from one tenant only"

The token was rotated externally. Two paths:

```bash
# Force-refresh the in-memory cache
curl -X POST -H "Authorization: Bearer ${ADMIN_JWT}" \
  https://tunnels.example.com/v1/admin/tenants/${TENANT_ID}/rotate

# Or rotate via Terraform and let the 5-min cache TTL pick it up
cd deployments/terraform/cloudflare-account
terraform apply -var-file="${TENANT}.tfvars"
```

## "Worker keeps OOMKilled at start"

Likely Kafka rebalance triggered all consumers in the group to fetch. Increase `resources.limits.memory` to 1.5Gi and lower `KAFKA_MAX_POLL_RECORDS`.

## "Outbox grows but never drains"

Almost always Kafka producer issue:

```bash
kubectl logs deploy/tunnel-orchestrator-worker | grep outbox.relay
```

Common errors:
- `MessageTooLarge`: payload exceeds broker `message.max.bytes`. Reduce verbose context or raise broker config.
- `RequestTimedOut`: broker overloaded; check Kafka cluster.
- `InvalidProducerEpoch`: another worker took over the transactional id; should self-heal in 30 s.

## "Idempotency conflict: same key, different request"

Means the caller reused an idempotency key with a different body. Surface a 409 to them with the diff:

```sql
select request_hash, response from idempotency_keys where key='<key>';
```

## "Cloudflared deployment never becomes Ready"

```bash
kubectl -n tunnels-${tenant} describe deploy cloudflared-${tunnel_id}
kubectl -n tunnels-${tenant} logs deploy/cloudflared-${tunnel_id} --tail=200
```

Common causes:
- Bad token (Cloudflare returns "tunnel not found" → rotate token).
- Network policy blocks egress to `*.cloudflare.com:7844` → check `NetworkPolicy`.
- Image pull failure → check pull secret.

## "Saga timeout (SAGA_TIMEOUT)"

The total wall time exceeded `SAGA_GLOBAL_TIMEOUT_SECONDS`. Look at step durations:
```sql
select name, duration_seconds, status from saga_steps where saga_id='<id>' order by created_at;
```
Most often `verify_dns` or `wait_deployment_ready`. Either tune timeouts or fix the upstream.

## "All requests are 401 even with a valid JWT"

JWT signing key rotated and JWKS cache hasn't refreshed:

```bash
kubectl rollout restart deploy/tunnel-orchestrator-api
```

## "Cluster is full but worker autoscaler reports 0 lag"

Lag-based scaler can't see *future* load. If you know a burst is coming, scale manually:

```bash
kubectl scale deploy/tunnel-orchestrator-worker --replicas=12
```
