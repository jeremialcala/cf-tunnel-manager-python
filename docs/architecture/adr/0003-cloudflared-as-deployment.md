# ADR 0003 — cloudflared as an independent Deployment, never a sidecar

- Status: Accepted
- Date: 2026-04-08

## Context
The Cloudflare community offers two deployment shapes for cloudflared in Kubernetes:
1. **Sidecar** in the application Pod.
2. **Independent Deployment** in the same namespace, fronting the application via cluster Service.

## Decision
We **only** ship cloudflared as an independent Deployment.

## Rationale
- Lifecycle decoupling: rolling the application doesn't drop tunnel connections (and vice versa).
- Connection pool sharing: multiple application instances share the cloudflared replicas; tunnels stay warm.
- Clear blast radius: if cloudflared crashes, only egress to Cloudflare is affected, not the app.
- Easier RBAC: orchestrator only needs to manage `Deployment` + `Secret`, never the app's Pod spec.

## Consequences
- Application teams **must** expose their service via a normal cluster Service.
- Slightly higher resource usage (separate Pod) — offset by fewer cloudflared replicas needed overall.
- The orchestrator's `KubernetesProvider` is the only entity that creates/updates cloudflared workloads.
