# ADR 0004 — Transactional Outbox for exactly-once eventing

- Status: Accepted
- Date: 2026-04-08

## Context
A saga both mutates PostgreSQL state *and* publishes Kafka events. Naive code uses `kafka.send()` after `session.commit()` — the classic dual-write problem. If the process crashes between the two, we either lose the event or, with the order reversed, publish without commit.

## Decision
All Kafka publishing goes through an `outbox_events` PG table inside the same transaction as the domain mutation. A background `OutboxRelay` task drains the table into Kafka transactionally and marks rows `SENT`.

## Rationale
- Atomicity: if the DB transaction commits, the event will eventually be published.
- Decouples saga latency from Kafka latency.
- Survives transient Kafka outages — backlog grows then drains.

## Consequences
- Adds the `outbox_events` table and a background task.
- Operators need to monitor outbox depth (alert in `observability.md`).
- Slightly higher write amplification on PG.
