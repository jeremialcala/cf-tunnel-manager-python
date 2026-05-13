# Local development setup

## Prerequisites

- Docker 24+ and Docker Compose v2
- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- `make`, `kubectl`, `helm`

Optional: VS Code + Dev Containers extension (`.devcontainer/` ready).

## Bootstrap

```bash
git clone https://github.com/your-org/tunnel-orchestrator.git
cd tunnel-orchestrator
make install         # uv sync + pre-commit install
make env             # creates .env from .env.example
$EDITOR .env         # set CLOUDFLARE_API_TOKEN if you want to hit a real account
make up              # docker-compose: kafka, schema-registry, postgres, redis, signoz
make bootstrap       # alembic upgrade + create kafka topics
```

## Run

Open three terminals:

```bash
make run-api         # http://localhost:8000  (Swagger /docs)
make run-worker      # consumes Kafka topics
make run-scheduler   # leader-elected reconciliation
```

A fourth (DLQ processor) is optional locally:

```bash
make run-dlq
```

## Smoke test

The smoke script issues a CREATE_TUNNEL command and asserts it ends in `READY`.
**Real Cloudflare account required** (`CLOUDFLARE_API_TOKEN` + a test zone).

```bash
make smoke
```

If you don't have a CF account, run unit tests instead:

```bash
make test            # unit
make test-contract   # avro/pydantic parity
```

## Useful UIs

| URL | What |
|---|---|
| http://localhost:8000/docs | FastAPI Swagger |
| http://localhost:8000/metrics | Prometheus metrics |
| http://localhost:8080 | Kafka UI (Provectus) |
| http://localhost:8081 | Schema Registry HTTP |
| http://localhost:3301 | SigNoz UI |
| http://localhost:5432 | PostgreSQL (creds in .env) |
| http://localhost:6379 | Redis |

## Common tasks

```bash
# Generate a new alembic migration
make migrate-rev M="add column foo"

# Reset the local stack (drops volumes!)
make destroy
make up
make bootstrap

# Tail logs of one service
docker compose logs -f kafka

# Inspect Kafka topic
docker exec -it tunnel-kafka kafka-console-consumer \
  --bootstrap-server localhost:29092 \
  --topic tunnel.create.success --from-beginning
```

## Troubleshooting (local)

- **`make up` hangs on Kafka health**: increase Docker Desktop memory to 6 GiB+.
- **`make run-worker` exits with `LookupError: Tenant not found`**: create a tenant first via the API (`POST /v1/admin/tenants`). The local SQL in `scripts/seed_db.py` does this.
- **Cloudflare 401 in smoke**: token lacks `Cloudflare Tunnel:Edit` or doesn't include the test zone.
