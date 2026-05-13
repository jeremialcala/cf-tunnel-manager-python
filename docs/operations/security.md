# Security model

See also `docs/architecture/05-zero-trust.md` for design rationale.

## Trust boundaries

```
[Client] --HTTPS+JWT--> [API pod] --gRPC/TLS--> [PG / Redis / Kafka]
                                  --HTTPS--> [Cloudflare API]
                                  --mTLS--> [Kubernetes API server]
```

- API → PG / Redis / Kafka: in-cluster TLS (cert-manager managed) when crossing cluster boundaries.
- API → Cloudflare: TLS, account-owned token in env (mounted from Secret).
- Worker → K8s API: in-cluster ServiceAccount; for cross-cluster, kubeconfig with **client cert** preferred over static token.

## Token lifecycle

| Token | Lifetime | Rotation | Storage |
|---|---|---|---|
| User JWT | 15 min | OIDC refresh | Browser / client memory |
| Cloudflare API token (per tenant) | 90 days | quarterly + on-demand | Vault (`secret/tenants/{slug}/cf_token`) |
| Cloudflared remote-managed token | until tunnel deleted | re-created with tunnel | K8s `Secret` in tenant namespace |
| Internal service-to-service (mTLS) | 24 h | cert-manager auto-renew | Pod-scoped Secret |

## Threat model summary

| Threat | Mitigation |
|---|---|
| Stolen tenant token | Limited blast radius (Tunnel:Edit + DNS:Edit on listed zones). Rotate via Vault + force-invalidate cache. |
| Compromised orchestrator pod | NetworkPolicy blocks lateral movement; SA RBAC limited to `secrets`/`deployments` in listed namespaces. |
| Cross-tenant data leak | All queries go through tenant-scoped repos; `import-linter` rule forbids bare `select`. Audit log captures every cross-tenant attempt. |
| Replay attack on event bus | Idempotency table + Kafka `read_committed` prevent re-processing. |
| DLQ-based RCE | DLQ replay re-uses the **original** payload only — no eval/templating. |
| Secret exfiltration via logs | `shared.logging.structured._redact` strips `*token*`/`*secret*`/`*password*` before serialise. |

## Secret rotation procedures

### Cloudflare token (per tenant)
```bash
# Re-run terraform with rotation flag
cd deployments/terraform/cloudflare-account
terraform apply -var-file="${TENANT}.tfvars" -var "force_rotate=true"

# Force the orchestrator to drop its cached client
curl -X POST -H "Authorization: Bearer ${ADMIN_JWT}" \
  https://tunnels.example.com/v1/admin/tenants/${TENANT_ID}/rotate
```

### JWT signing key
1. Generate new key pair, publish JWKS.
2. Wait one JWKS cache TTL (10 min) for orchestrator to pick up.
3. Auth issuer flips signing to new key.
4. After old token TTL elapses, retire old key from JWKS.

### Database credentials
- Rotate via your Postgres operator / managed service.
- Update Vault path; rolling restart of orchestrator pods picks up the new DSN.

## Audit

- `audit_log` table captures every state-changing API call with `actor`, `tenant_id`, `before`, `after`.
- `tunnel.audit` Kafka topic mirrors entries for ingestion into your SIEM.
- Retention: 30 days in Postgres, 90 days in SIEM.

## Compliance hooks

- **PII**: by design we only handle hostnames + tunnel IDs. No PII enters this system.
- **SOC2**: change management via PR + ArgoCD; access via OIDC SSO; audit log immutable (append-only + S3 mirror).
- **GDPR / data residency**: per-region deployments are independent — no cross-region replication of tenant data.
