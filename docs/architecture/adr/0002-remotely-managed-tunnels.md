# ADR 0002 — Remotely-managed Cloudflare Tunnels (no local YAML)

- Status: Accepted
- Date: 2026-04-08

## Context
Cloudflare offers two ingress configuration modes:
1. **Locally-managed**: cloudflared reads `config.yml` from a `ConfigMap` / volume.
2. **Remotely-managed**: ingress configuration lives in Cloudflare; cloudflared only needs the token.

## Decision
We use **remotely-managed** exclusively. The `CLOUDFLARE_TUNNEL_CONFIG_SRC` setting validator rejects any other value at process start.

## Rationale
- Single source of truth for ingress (Cloudflare account) → no drift between K8s `ConfigMap` and Cloudflare dashboard.
- Token rotation does not require Pod restarts.
- The Cloudflare audit log captures every ingress mutation — invaluable for compliance.
- Reduces Pod blast radius: a compromised cloudflared Pod cannot rewrite ingress rules itself; the orchestrator must.

## Consequences
- We must keep our `tunnels` table in sync with Cloudflare via reconciliation (handled by the scheduler).
- Operators editing in the Cloudflare dashboard create drift — the scheduler emits a `tunnel.drift_detected` event so we surface it.
