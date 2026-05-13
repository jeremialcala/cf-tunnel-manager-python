"""Application layer: use cases, sagas and ports.

This layer orchestrates the domain — it knows what to do, but never
*how* the side effects happen. The "how" lives in
:pymod:`services.tunnel_orchestrator.infrastructure`.
"""
