#!/usr/bin/env bash
# =====================================================================
# Tunnel Orchestrator — Kafka topic bootstrap
# =====================================================================
# Creates all topics declared in the architecture with correct
# partitioning, replication, retention and cleanup policy.
#
# Idempotent: existing topics are left untouched.
# =====================================================================
set -euo pipefail

KAFKA_CONTAINER="${KAFKA_CONTAINER:-tunnel-kafka}"
BOOTSTRAP="${BOOTSTRAP:-kafka:29092}"
PARTITIONS="${PARTITIONS:-12}"
RF="${REPLICATION_FACTOR:-1}"   # 3 in production

declare -a TOPICS=(
  # name|partitions|retention_ms|cleanup_policy
  "tunnel.create.request|${PARTITIONS}|604800000|delete"
  "tunnel.create.processing|${PARTITIONS}|86400000|delete"
  "tunnel.create.success|${PARTITIONS}|2592000000|delete"
  "tunnel.create.failure|${PARTITIONS}|2592000000|delete"
  "tunnel.delete.request|${PARTITIONS}|604800000|delete"
  "tunnel.delete.success|${PARTITIONS}|2592000000|delete"
  "tunnel.delete.failure|${PARTITIONS}|2592000000|delete"
  "tunnel.update.request|${PARTITIONS}|604800000|delete"
  "tunnel.update.success|${PARTITIONS}|2592000000|delete"
  "tunnel.update.failure|${PARTITIONS}|2592000000|delete"
  "tunnel.validation.request|${PARTITIONS}|86400000|delete"
  "tunnel.validation.success|${PARTITIONS}|604800000|delete"
  "tunnel.validation.failure|${PARTITIONS}|2592000000|delete"
  "tunnel.reconcile.request|${PARTITIONS}|86400000|delete"
  "tunnel.dlq|${PARTITIONS}|7776000000|delete"
  "tunnel.audit|${PARTITIONS}|2592000000|delete"
  # Outbox / saga state (compacted — keep latest per key)
  "tunnel.saga.state|${PARTITIONS}|-1|compact"
)

echo "Creating Kafka topics on ${BOOTSTRAP} (partitions=${PARTITIONS}, RF=${RF})"

for entry in "${TOPICS[@]}"; do
  IFS='|' read -r name parts retention policy <<< "${entry}"

  if docker exec "${KAFKA_CONTAINER}" kafka-topics \
        --bootstrap-server "${BOOTSTRAP}" \
        --list 2>/dev/null | grep -Fxq "${name}"; then
    echo "  [skip] ${name} (already exists)"
    continue
  fi

  docker exec "${KAFKA_CONTAINER}" kafka-topics \
    --bootstrap-server "${BOOTSTRAP}" \
    --create \
    --topic "${name}" \
    --partitions "${parts}" \
    --replication-factor "${RF}" \
    --config "retention.ms=${retention}" \
    --config "cleanup.policy=${policy}" \
    --config "min.insync.replicas=$([ "${RF}" -gt 1 ] && echo 2 || echo 1)" \
    --config "compression.type=lz4"

  echo "  [ok]   ${name}"
done

echo "Done."
