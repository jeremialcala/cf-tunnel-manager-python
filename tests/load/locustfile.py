"""Load test for the API gateway.

Usage::

    uv run locust -f tests/load/locustfile.py --headless -u 50 -r 5 -t 2m \\
        --host=http://localhost:8000

Requires a valid JWT in env ``TEST_JWT``.
"""

from __future__ import annotations

import os
import random
import uuid

from locust import HttpUser, between, task


class TunnelUser(HttpUser):
    wait_time = between(0.1, 0.5)

    def on_start(self) -> None:
        token = os.environ.get("TEST_JWT")
        if not token:
            raise RuntimeError("Set TEST_JWT to a valid JWT")
        self.client.headers["Authorization"] = f"Bearer {token}"
        self.client.headers["Content-Type"] = "application/json"

    @task(5)
    def list_tunnels(self) -> None:
        self.client.get("/v1/tunnels", name="GET /v1/tunnels")

    @task(1)
    def create_tunnel(self) -> None:
        host = f"svc-{uuid.uuid4().hex[:8]}.example.com"
        body = {
            "hostname": host,
            "cf_zone_id": os.environ.get("TEST_ZONE_ID", "zone-1"),
            "cluster": "default",
            "ingress": [
                {"service": "http://my-svc.svc.cluster.local:8080", "hostname": host},
            ],
        }
        with self.client.post(
            "/v1/tunnels",
            json=body,
            headers={"Idempotency-Key": f"loadtest-{uuid.uuid4()}"},
            name="POST /v1/tunnels",
            catch_response=True,
        ) as r:
            if r.status_code in (202, 200):
                r.success()
            else:
                r.failure(f"unexpected {r.status_code}: {r.text[:200]}")

    @task(1)
    def health(self) -> None:
        self.client.get(
            "/health/ready",
            name="GET /health/ready",
            headers={"Authorization": ""},
        )
