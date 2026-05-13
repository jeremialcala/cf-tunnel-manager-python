"""Async engine, session factory and a lightweight UnitOfWork.

The :class:`Database` is a process-singleton (one per app/worker).
:class:`UnitOfWork` exposes ``async with`` semantics that:

* open a session,
* begin a transaction,
* commit on success / rollback on exception,
* dispatch ``pending_events`` from any aggregate that has them into
  the outbox table inside the same transaction.
"""

from __future__ import annotations

import contextlib
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from shared.config import get_settings
from shared.logging import get_logger

log = get_logger(__name__)


class Database:
    def __init__(self, *, dsn: str | None = None, echo: bool | None = None) -> None:
        settings = get_settings().database
        self.engine: AsyncEngine = create_async_engine(
            dsn or settings.url.get_secret_value(),
            echo=echo if echo is not None else settings.echo,
            pool_size=settings.pool_size,
            max_overflow=settings.max_overflow,
            pool_pre_ping=True,
            future=True,
        )
        self.session_factory = async_sessionmaker(
            self.engine, expire_on_commit=False, class_=AsyncSession
        )

    async def dispose(self) -> None:
        await self.engine.dispose()


class UnitOfWork:
    """Per-request / per-saga transactional context.

    Aggregates registered via :meth:`track` will have their
    ``pull_pending_events()`` drained into the ``outbox_events`` table
    on commit.
    """

    def __init__(self, db: Database) -> None:
        self._db = db
        self._session: AsyncSession | None = None
        self._tracked: list[object] = []

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("UnitOfWork is not entered")
        return self._session

    def track(self, aggregate: object) -> None:
        self._tracked.append(aggregate)

    async def __aenter__(self) -> "UnitOfWork":
        self._session = self._db.session_factory()
        await self._session.begin()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:           # noqa: ANN001
        assert self._session is not None
        try:
            if exc:
                await self._session.rollback()
                return
            await self._drain_outbox()
            await self._session.commit()
        finally:
            await self._session.close()
            self._session = None

    async def _drain_outbox(self) -> None:
        # Lazy import to avoid circular
        from services.tunnel_orchestrator.infrastructure.persistence.outbox import (
            PgOutboxStore,
        )
        from services.tunnel_orchestrator.domain.aggregates import Tunnel

        store = PgOutboxStore(self.session)
        for agg in self._tracked:
            if isinstance(agg, Tunnel):
                events = agg.pull_pending_events()
                for evt in events:
                    await store.append_domain_event(evt)


@contextlib.asynccontextmanager
async def session_scope(db: Database) -> AsyncIterator[AsyncSession]:
    """Plain session for read-only handlers."""
    session = db.session_factory()
    try:
        yield session
    finally:
        await session.close()
