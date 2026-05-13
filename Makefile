# =====================================================================
# Tunnel Orchestrator — Makefile
# =====================================================================
# All targets are idempotent. Use `make help` to list available targets.
# =====================================================================

SHELL := /bin/bash
.DEFAULT_GOAL := help

PY ?= python3.12
UV ?= uv
COMPOSE ?= docker compose
HELM ?= helm
KUBECTL ?= kubectl
NS ?= tunnel-orchestrator

ENV_FILE ?= .env
export PYTHONPATH := $(PWD)
export ENV_FILE

# ---------- Colors ----------
GREEN  := \033[0;32m
YELLOW := \033[1;33m
RESET  := \033[0m

# =====================================================================
# Help
# =====================================================================

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  $(GREEN)%-22s$(RESET) %s\n", $$1, $$2}'

# =====================================================================
# Setup / dependencies
# =====================================================================

.PHONY: install
install: ## Install Python deps (dev + test) using uv
	@command -v $(UV) >/dev/null || { echo "Installing uv..."; curl -LsSf https://astral.sh/uv/install.sh | sh; }
	$(UV) sync --all-extras
	$(UV) run pre-commit install

.PHONY: env
env: ## Copy .env.example to .env if missing
	@test -f $(ENV_FILE) || cp .env.example $(ENV_FILE)
	@echo "$(YELLOW)Edit $(ENV_FILE) with your credentials$(RESET)"

# =====================================================================
# Local stack (Docker Compose)
# =====================================================================

.PHONY: up down logs ps
up: ## Start local stack (Kafka, PG, Redis, SigNoz)
	$(COMPOSE) up -d
	@echo "$(GREEN)Stack ready:$(RESET) Kafka:9092  PG:5432  Redis:6379  SigNoz UI:3301"

down: ## Stop local stack (preserve volumes)
	$(COMPOSE) down

destroy: ## Stop local stack and DELETE volumes
	$(COMPOSE) down -v --remove-orphans

logs: ## Tail logs
	$(COMPOSE) logs -f --tail=100

ps: ## Status of local services
	$(COMPOSE) ps

# =====================================================================
# Bootstrap (topics + DB)
# =====================================================================

.PHONY: bootstrap topics migrate seed
bootstrap: topics migrate ## Create Kafka topics + apply DB migrations

topics: ## Create Kafka topics declared in scripts/create_topics.sh
	bash scripts/create_topics.sh

migrate: ## Apply Alembic migrations
	$(UV) run alembic upgrade head

migrate-down: ## Revert one migration
	$(UV) run alembic downgrade -1

migrate-rev: ## Generate new migration (use M="message")
	$(UV) run alembic revision --autogenerate -m "$(M)"

seed: ## Seed reference data
	$(UV) run python scripts/seed_db.py

# =====================================================================
# Run processes locally
# =====================================================================

.PHONY: run-api run-worker run-scheduler run-dlq
run-api: ## Run FastAPI gateway with reload
	$(UV) run uvicorn apps.api.main:app --host 0.0.0.0 --port 8000 --reload

run-worker: ## Run Kafka consumer worker
	$(UV) run python -m apps.worker.main

run-scheduler: ## Run scheduler (reconciliation)
	$(UV) run python -m apps.scheduler.main

run-dlq: ## Run DLQ processor
	$(UV) run python -m apps.dlq_processor.main

# =====================================================================
# Quality (lint, type, format)
# =====================================================================

.PHONY: lint fmt typecheck check
lint: ## Run ruff
	$(UV) run ruff check .

fmt: ## Format with ruff
	$(UV) run ruff format .
	$(UV) run ruff check --fix .

typecheck: ## Run mypy
	$(UV) run mypy services apps shared platform

check: lint typecheck ## Lint + typecheck

# =====================================================================
# Tests
# =====================================================================

.PHONY: test test-unit test-integration test-contract test-load smoke
test: test-unit ## Default: unit tests

test-unit: ## Unit tests
	$(UV) run pytest -m "unit or not integration and not e2e and not slow" tests/

test-integration: ## Integration tests with testcontainers
	$(UV) run pytest -m "integration" tests/

test-contract: ## Avro contract tests
	$(UV) run pytest -m "contract" tests/

test-load: ## Locust load test
	$(UV) run locust -f tests/load/locustfile.py --headless -u 50 -r 5 -t 2m

smoke: ## End-to-end smoke (requires real CF token)
	$(UV) run python scripts/smoke_test.py

# =====================================================================
# Docker images
# =====================================================================

REGISTRY ?= ghcr.io/your-org
TAG ?= dev
IMAGES := api worker scheduler dlq_processor

.PHONY: docker-build docker-push
docker-build: ## Build all images
	@for img in $(IMAGES); do \
		docker build -f deployments/docker/Dockerfile.$$img -t $(REGISTRY)/tunnel-orchestrator-$$img:$(TAG) . ; \
	done

docker-push: ## Push all images
	@for img in $(IMAGES); do \
		docker push $(REGISTRY)/tunnel-orchestrator-$$img:$(TAG) ; \
	done

# =====================================================================
# Helm
# =====================================================================

.PHONY: helm-lint helm-template helm-install helm-uninstall
helm-lint: ## Lint Helm chart
	$(HELM) lint charts/tunnel-orchestrator

helm-template: ## Render chart with dev values
	$(HELM) template tunnel-orchestrator charts/tunnel-orchestrator \
		-f charts/tunnel-orchestrator/values.dev.yaml

helm-install: ## Install / upgrade dev release
	$(HELM) upgrade --install tunnel-orchestrator charts/tunnel-orchestrator \
		-n $(NS) --create-namespace \
		-f charts/tunnel-orchestrator/values.dev.yaml

helm-uninstall: ## Remove release
	$(HELM) uninstall tunnel-orchestrator -n $(NS)

# =====================================================================
# Misc
# =====================================================================

.PHONY: clean
clean: ## Remove caches and build artifacts
	find . -type d \( -name __pycache__ -o -name .pytest_cache -o -name .ruff_cache -o -name .mypy_cache \) -prune -exec rm -rf {} +
	rm -rf .coverage coverage.xml dist build *.egg-info
