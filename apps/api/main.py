"""FastAPI gateway entrypoint."""

from __future__ import annotations

import contextlib
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST

from apps.api.middleware import CorrelationIdMiddleware, RateLimitMiddleware
from apps.api.routers import admin, health, tunnels
from apps.composition import build_container, shutdown_container
from shared.config import get_settings
from shared.errors import AppError
from shared.logging import configure_logging, get_logger
from shared.observability import instrument_app, metrics

log = get_logger(__name__)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    container = await build_container()
    app.state.container = container
    log.info("api.startup.complete")
    try:
        yield
    finally:
        log.info("api.shutdown.start")
        await shutdown_container(container)
        log.info("api.shutdown.complete")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Tunnel Orchestrator API",
        description="Programmatic, event-driven Cloudflare Tunnel orchestration.",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.api.docs_enabled else None,
        redoc_url="/redoc" if settings.api.docs_enabled else None,
        openapi_url="/openapi.json" if settings.api.docs_enabled else None,
    )

    # ---- middlewares ----
    app.add_middleware(CorrelationIdMiddleware)
    app.add_middleware(RateLimitMiddleware)

    # ---- routers ----
    app.include_router(health.router, prefix="/health", tags=["health"])
    app.include_router(tunnels.router, prefix="/v1/tunnels", tags=["tunnels"])
    app.include_router(admin.router, prefix="/v1/admin", tags=["admin"])

    # ---- /metrics for Prometheus ----
    @app.get("/metrics", include_in_schema=False)
    async def _metrics() -> Response:
        body, content_type = metrics.render()
        return Response(content=body, media_type=content_type or CONTENT_TYPE_LATEST)

    # ---- exception handlers ----
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.http_status, content=exc.to_dict())

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"code": "REQUEST_VALIDATION_ERROR", "errors": exc.errors()},
        )

    # ---- OTel instrumentation ----
    instrument_app(app)
    return app


app = create_app()


def main() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "apps.api.main:app",
        host=settings.api.host,
        port=settings.api.port,
        workers=settings.api.workers,
        loop="uvloop",
        http="httptools",
        access_log=True,
        server_header=False,
    )


if __name__ == "__main__":
    main()
