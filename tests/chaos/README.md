# Chaos test scripts

Reusable chaos experiments for staging environments. Each script is
self-contained and idempotent — re-running cleans up any pre-existing
state before applying new fault.

| Script | Fault | Expected behaviour |
|---|---|---|
| `kill_kafka_broker.sh` | Stops one Kafka broker pod | Producer keeps retrying via idempotent producer; outbox grows briefly then drains; **no double publish** |
| `partition_redis.sh` | Adds iptables drop rules to Redis | API returns 503 from `/health/ready`; sagas fail at `acquire_lock` and roll back cleanly |
| `cf_429_storm.sh` | Returns 429 for 60s via mock-CF | RetryPolicy honours `Retry-After`; circuit breaker opens; **no DLQ entries** until breaker stays open beyond saga timeout |
| `slow_dns.sh` | tc adds 5s latency to UDP/53 | Verify step retries; saga eventually succeeds within `DNS_VERIFY_TIMEOUT_SECONDS` |

> Run from a jumpbox in the staging cluster with `kubectl` + `helm`
> already configured. **Never** run in production.
