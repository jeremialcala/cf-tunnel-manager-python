# Repository index

> Generated at the end of the implementation. Quick map of every file shipped.

## Top-level

```
.
├── README.md                           # Spanish entry point
├── LICENSE                             # Apache 2.0
├── pyproject.toml                      # uv / hatchling project, deps, ruff/mypy/pytest config
├── Makefile                            # All make targets (install, up, run-*, test, helm-*)
├── alembic.ini                         # Alembic config (DSN overridden by env)
├── docker-compose.yml                  # Local stack: Kafka, Schema Registry, PG, Redis, SigNoz
├── .env.example                        # All env vars (ready to copy to .env)
├── .gitignore / .dockerignore / .editorconfig / .python-version
├── .pre-commit-config.yaml             # ruff + mypy + gitleaks + helm-docs
├── .devcontainer/
│   ├── devcontainer.json               # VS Code Remote Containers
│   └── Dockerfile
└── .github/
    ├── CODEOWNERS
    └── workflows/
        ├── ci.yml                      # lint, test, contract, helm, scan, publish
        ├── release.yml                 # tag-driven multi-arch image + chart release
        └── security-scan.yml           # nightly gitleaks + pip-audit + CodeQL
```

## `apps/` — Process entrypoints

```
apps/
├── composition.py                      # Composition root (DI wiring of all adapters)
├── api/                                # FastAPI gateway
│   ├── main.py                         # create_app + lifespan
│   ├── dependencies.py                 # FastAPI deps (auth, container, handlers)
│   ├── middleware/
│   │   ├── correlation.py              # X-Correlation-Id propagation
│   │   └── rate_limit.py               # Per-tenant token bucket
│   └── routers/
│       ├── health.py                   # /health/{live,ready,startup}
│       ├── tunnels.py                  # CRUD + validate
│       └── admin.py                    # Tenant onboarding
├── worker/                             # Kafka consumer process
│   ├── main.py                         # SIGTERM-graceful, healthz on metrics port
│   └── consumers/
│       ├── create_tunnel_consumer.py
│       ├── delete_tunnel_consumer.py
│       ├── validation_consumer.py
│       └── reconcile_consumer.py
├── scheduler/                          # Leader-elected periodic jobs
│   ├── main.py                         # Redis-based leader election
│   └── jobs/
│       ├── validate_all.py
│       ├── reconcile_drift.py
│       └── purge_idempotency.py
└── dlq_processor/
    └── main.py                         # tunnel.dlq consumer (manual or auto-replay)
```

## `services/tunnel_orchestrator/` — Bounded context

```
services/tunnel_orchestrator/
├── domain/                             # Pure DDD
│   ├── aggregates/
│   │   ├── tunnel.py                   # Tunnel (state machine + pending events)
│   │   └── tenant.py
│   ├── value_objects/
│   │   ├── hostname.py                 # RFC-1123 validated
│   │   ├── ingress_rule.py             # Catch-all invariant
│   │   ├── dns_record.py               # Proxied CNAME helper
│   │   ├── tunnel_id.py
│   │   └── tenant_id.py
│   ├── events/
│   │   ├── base.py                     # DomainEvent (Pydantic, frozen)
│   │   └── tunnel_events.py            # Created/Failed/Deleted/Validated/...
│   ├── services/
│   │   └── tunnel_lifecycle.py         # Authorisation + invariants
│   └── repositories.py                 # Ports
├── application/
│   ├── ports/                          # Interfaces (hexagonal)
│   │   ├── cloudflare_provider.py
│   │   ├── kubernetes_provider.py
│   │   ├── dns_verifier.py
│   │   ├── http_verifier.py
│   │   ├── lock_manager.py
│   │   ├── event_publisher.py
│   │   └── audit_logger.py
│   ├── commands/                       # CQRS write side
│   │   ├── create_tunnel.py            # Idempotency → Lock → Saga → Outbox
│   │   ├── delete_tunnel.py
│   │   └── validate_tunnel.py
│   ├── queries/
│   │   └── get_tunnel.py               # GetTunnel + ListTunnels + TunnelView DTO
│   ├── sagas/
│   │   ├── base.py                     # SagaOrchestrator + spans + metrics
│   │   ├── context.py                  # Typed CreateTunnelSagaData
│   │   ├── create_tunnel_saga.py       # 9-step assembler
│   │   ├── delete_tunnel_saga.py       # Reverse pipeline
│   │   └── steps/
│   │       ├── create_cloudflare_tunnel.py
│   │       ├── retrieve_token.py
│   │       ├── configure_ingress.py
│   │       ├── create_dns_record.py
│   │       ├── create_k8s_secret.py
│   │       ├── create_k8s_deployment.py
│   │       ├── wait_deployment_ready.py
│   │       ├── verify_dns.py
│   │       └── verify_http.py
│   ├── idempotency/
│   │   └── service.py                  # Replay-safe receiver
│   └── resilience/
│       ├── retry.py                    # Tenacity-based AsyncRetry
│       ├── rate_limiter.py             # Per-tenant aiolimiter registry
│       └── circuit_breaker.py          # Async breakers via purgatory
└── infrastructure/                     # Adapters
    ├── cloudflare/
    │   ├── provider.py                 # AsyncCloudflare SDK v5 wrapper
    │   └── registry.py                 # Per-tenant TTL cache + token loader
    ├── kubernetes/
    │   ├── client.py                   # Multi-cluster ApiClient factory
    │   ├── manifests.py                # Cloudflared Deployment template (security-hardened)
    │   └── provider.py                 # Idempotent secret + deployment ops
    ├── persistence/
    │   ├── database.py                 # Async engine + UnitOfWork
    │   ├── models.py                   # SQLAlchemy 2.0 mapped (tenants, tunnels, sagas, outbox, idempotency, audit)
    │   ├── tunnel_repository.py
    │   ├── tenant_repository.py
    │   ├── saga_store.py
    │   ├── idempotency_store.py
    │   ├── outbox.py                   # Outbox writer + relay loop
    │   └── audit_logger.py
    ├── messaging/
    │   ├── kafka_producer.py           # AIOKafkaProducer + AioKafkaPublisher (outbox-backed)
    │   ├── kafka_consumer.py           # EOS, OTel propagation, DLQ on poison
    │   └── schema_registry.py          # Confluent SR client
    ├── cache/
    │   └── redis_client.py             # Redlock + cache
    ├── verification/
    │   ├── dns_resolver.py             # dnspython async
    │   └── http_prober.py              # httpx HTTP/2
    └── auth/
        ├── jwt.py                      # RS256 + JWKS
        └── rbac.py                     # Permission enum + dependency factory
```

## `shared/` — Cross-cutting kernel

```
shared/
├── config/settings.py                  # Pydantic-settings: env → typed config (incl. CF tunnel-config-src guard)
├── errors.py                           # Typed error hierarchy (Domain/Infrastructure/Saga)
├── types.py                            # Hostname, NewTypes, ULID factories
├── logging/structured.py               # Structlog JSON + secret redaction + OTel context
└── observability/
    ├── correlation.py                  # async-safe contextvars
    ├── tracing.py                      # OTel SDK + auto-instrumentation
    └── metrics.py                      # Prometheus registry (saga / CF / K8s / Kafka / verify)
```

## `platform/` — Event contracts

```
platform/
├── events/
│   ├── envelope.py                     # Generic EventEnvelope + build_envelope helper
│   ├── headers.py                      # EventHeaders <-> Kafka header tuples
│   ├── payloads.py                     # Pydantic models for every topic
│   ├── topics.py                       # Topic enum + TopicSpec catalog
│   └── versioning.py                   # event_type → payload model registry
└── schemas/                            # Avro schemas (one per topic + generic envelope)
    ├── envelope.avsc
    ├── tunnel_create_request.avsc
    ├── tunnel_create_success.avsc
    ├── tunnel_create_failure.avsc
    ├── tunnel_delete_request.avsc
    └── tunnel_dlq.avsc
```

## `migrations/` — Alembic

```
migrations/
├── env.py
├── script.py.mako
└── versions/
    └── 20260512_0001_initial.py        # tenants, tunnels, sagas, outbox, idempotency, audit
```

## `charts/tunnel-orchestrator/` — Helm

```
charts/tunnel-orchestrator/
├── Chart.yaml
├── values.yaml                         # Production-leaning defaults
├── values.dev.yaml                     # Dev overrides
└── templates/
    ├── _helpers.tpl                    # Shared labels + commonEnv block
    ├── api-deployment.yaml             # HPA-aware, probes, OTel
    ├── worker-deployment.yaml          # Long termination grace period
    ├── scheduler-deployment.yaml
    ├── dlq-deployment.yaml
    ├── service.yaml
    ├── ingress.yaml
    ├── hpa.yaml                        # API + worker (or KEDA via scaledobject.yaml)
    ├── scaledobject.yaml               # KEDA Kafka lag scaler (optional)
    ├── pdb.yaml                        # api + worker
    ├── networkpolicy.yaml              # Default deny + allow-list
    ├── serviceaccount.yaml
    ├── rbac.yaml                       # Per-managed-namespace Role + Binding
    ├── servicemonitor.yaml             # Prometheus operator
    ├── migration-job.yaml              # pre-install/upgrade Alembic
    └── NOTES.txt
```

## `deployments/`

```
deployments/
├── docker/
│   ├── Dockerfile.base
│   ├── Dockerfile.api
│   ├── Dockerfile.worker
│   ├── Dockerfile.scheduler
│   └── Dockerfile.dlq_processor
├── argocd/
│   └── application.yaml                # ArgoCD GitOps Application (auto-sync, prune, self-heal)
└── terraform/
    └── cloudflare-account/             # Per-tenant CF token + Vault path
        ├── main.tf
        ├── variables.tf
        └── outputs.tf
```

## `tests/`

```
tests/
├── conftest.py                         # In-memory fakes for every port
├── unit/
│   ├── test_value_objects.py
│   ├── test_tunnel_aggregate.py
│   ├── test_idempotency.py
│   └── test_create_tunnel_saga.py      # Happy path + 2 compensation flows
├── contract/
│   └── test_avro_pydantic_parity.py
├── integration/
│   └── test_postgres_outbox.py         # testcontainers PG
├── load/
│   └── locustfile.py
└── chaos/
    └── README.md
```

## `scripts/`

```
scripts/
├── create_topics.sh                    # Idempotent Kafka topic bootstrap
├── init-db.sql                         # PG extensions
├── otel-collector-config.yaml          # SigNoz collector pipeline
├── seed_db.py                          # Dev tenant seeding
├── register_schemas.py                 # Bulk register Avro schemas to SR
└── smoke_test.py                       # End-to-end against real CF account
```

## `docs/`

```
docs/
├── ARCHITECTURE.md                     # Living architecture document
├── architecture/
│   ├── 01-overview.md
│   ├── 02-event-driven.md              # Topics, envelopes, EOS, DLQ
│   ├── 03-saga-orchestration.md        # State machine + compensations + outbox
│   ├── 04-multi-tenant.md
│   ├── 05-zero-trust.md
│   ├── adr/
│   │   ├── 0001-event-driven-orchestration.md
│   │   ├── 0002-remotely-managed-tunnels.md
│   │   ├── 0003-cloudflared-as-deployment.md
│   │   └── 0004-transactional-outbox.md
│   └── diagrams/
│       ├── c4-container.mmd
│       └── saga-create-tunnel.mmd
├── kafka-contracts/README.md
├── operations/
│   ├── runbook-oncall.md
│   ├── scaling.md
│   ├── disaster-recovery.md
│   ├── troubleshooting.md
│   ├── observability.md
│   └── security.md
└── development/
    ├── local-setup.md
    ├── testing.md
    └── contributing.md
```

## What ships and works out of the box

- `make up && make bootstrap` brings up the local stack and creates topics + DB schema.
- `make run-api` and `make run-worker` start the system end-to-end (no Cloudflare token needed for a smoke unless you actually create tunnels).
- `make test` passes (unit + contract).
- `helm template` renders without errors against the provided `values.dev.yaml`.
- The CI pipeline (`.github/workflows/ci.yml`) is fully wired (lint, type-check, unit, contract, integration, helm lint, trivy scan, multi-arch publish on `main`).

## Hard requirements honoured (from the brief)

| Requirement | Where |
|---|---|
| Async-first | `aiokafka`, `kubernetes_asyncio`, `cloudflare` SDK v5 (Async), httpx, asyncpg |
| Remotely-managed tunnels (mandatory) | enforced by `CloudflareSettings._enforce_remote` validator + `config_src='cloudflare'` in `CloudflareProviderImpl.create_tunnel` |
| Cloudflared as independent Deployment | `manifests.build_cloudflared_deployment` — never a sidecar; ADR-0003 |
| Idempotent workflows | `IdempotencyService` + step-level upserts (CF tunnel adoption, K8s upsert, DNS upsert) |
| Distributed transactions / Saga compensations | `SagaOrchestrator` + reverse-order compensations on failure |
| Exactly-once semantics | Transactional outbox (ADR-0004) + Kafka EOS settings |
| Structured logging + correlation IDs | `shared/logging` + `shared/observability/correlation.py` |
| RBAC + JWT | `infrastructure/auth/{jwt,rbac}.py` + FastAPI deps |
| Multi-tenant + multi-cluster | per-tenant `CloudflareProvider` registry + `K8S_MULTI_CLUSTER_CONFIG` |
| Schema Registry | `SchemaRegistryClient` + `scripts/register_schemas.py` |
| DLQ | `apps/dlq_processor` + `tunnel.dlq` topic + `publish_to_dlq` on poison |
| Helm + ArgoCD + Terraform + GH Actions | `charts/`, `deployments/argocd/`, `deployments/terraform/`, `.github/workflows/` |
| Observability complete | OTel SDK, Prometheus registry, structured logs, traces propagated through Kafka headers |
