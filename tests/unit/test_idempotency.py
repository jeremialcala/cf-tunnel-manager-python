from __future__ import annotations

from uuid import uuid4

import pytest

from shared.errors import IdempotencyConflict
from services.tunnel_orchestrator.application.idempotency import (
    IdempotencyOutcome,
    IdempotencyService,
)
from tests.conftest import FakeIdempotencyStore

pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


@pytest.mark.asyncio
async def test_first_call_is_new_then_replays_when_completed():
    svc = IdempotencyService(FakeIdempotencyStore())
    tenant = uuid4()
    key = svc.make_key(tenant, "foo")
    request = {"x": 1}

    out, _ = await svc.begin(key=key, tenant_id=tenant, request=request)
    assert out is IdempotencyOutcome.NEW

    await svc.complete(key=key, response={"status": "READY"})
    out2, cached = await svc.begin(key=key, tenant_id=tenant, request=request)
    assert out2 is IdempotencyOutcome.REPLAY
    assert cached == {"status": "READY"}


@pytest.mark.asyncio
async def test_same_key_different_request_raises_conflict():
    svc = IdempotencyService(FakeIdempotencyStore())
    tenant = uuid4()
    key = svc.make_key(tenant, "foo")

    await svc.begin(key=key, tenant_id=tenant, request={"x": 1})
    with pytest.raises(IdempotencyConflict):
        await svc.begin(key=key, tenant_id=tenant, request={"x": 2})
