"""Liveness, readiness, startup probes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from apps.api.dependencies import get_container
from apps.composition import Container

router = APIRouter()


@router.get("/live", summary="Liveness probe")
async def live() -> dict[str, str]:
    """Returns 200 as long as the event loop is responsive."""
    return {"status": "alive"}


@router.get("/ready", summary="Readiness probe")
async def ready(c: Container = Depends(get_container)) -> Response:
    """Verifies all critical dependencies are reachable.

    Returns 503 with details if any dependency check fails so the
    Kubernetes service mesh stops routing to this Pod.
    """
    failures: dict[str, str] = {}

    # ---- DB ----
    try:
        async with c.db.session_factory() as session:
            await session.execute("SELECT 1")  # type: ignore[arg-type]
    except Exception as e:  # noqa: BLE001
        failures["postgres"] = str(e)[:200]

    # ---- Redis ----
    try:
        await c.redis.client.ping()
    except Exception as e:  # noqa: BLE001
        failures["redis"] = str(e)[:200]

    # ---- Kafka ----
    try:
        c.kafka.producer()    # raises if not started
    except Exception as e:  # noqa: BLE001
        failures["kafka"] = str(e)[:200]

    body = {"status": "ready"} if not failures else {"status": "not_ready", "failures": failures}
    status = 200 if not failures else 503
    import orjson
    return Response(content=orjson.dumps(body), media_type="application/json", status_code=status)


@router.get("/startup", summary="Startup probe")
async def startup() -> dict[str, str]:
    return {"status": "started"}
