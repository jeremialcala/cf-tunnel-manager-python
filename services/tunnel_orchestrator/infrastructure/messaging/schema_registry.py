"""Tiny Confluent Schema Registry HTTP client.

Used at startup to register/lookup Avro schemas listed in
``cloud_platform/schemas/``. Avoids a hard runtime dependency on the official
client to keep the runtime image small.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from shared.config import get_settings
from shared.errors import SchemaRegistryError
from shared.logging import get_logger

log = get_logger(__name__)


class SchemaRegistryClient:
    def __init__(self, base_url: str | None = None, timeout: float = 5.0) -> None:
        self._base_url = (base_url or get_settings().kafka.schema_registry_url).rstrip("/")
        self._timeout = timeout

    async def register(self, subject: str, schema: dict | str) -> int:
        """Register or fetch existing id for a schema. Returns ``schema_id``."""
        body = {"schema": schema if isinstance(schema, str) else json.dumps(schema)}
        url = f"{self._base_url}/subjects/{subject}/versions"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.post(
                url, json=body, headers={"Content-Type": "application/vnd.schemaregistry.v1+json"}
            )
        if r.status_code >= 400:
            raise SchemaRegistryError(
                f"register({subject}) -> {r.status_code} {r.text}",
                context={"subject": subject},
            )
        return int(r.json()["id"])

    async def latest(self, subject: str) -> dict:
        url = f"{self._base_url}/subjects/{subject}/versions/latest"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.get(url)
        if r.status_code == 404:
            raise SchemaRegistryError(f"subject {subject!r} not found")
        r.raise_for_status()
        return r.json()

    async def register_directory(self, schemas_dir: Path | str) -> dict[str, int]:
        """Register every ``*.avsc`` in ``schemas_dir``.

        Subject name = ``<filename>-value`` (Confluent default for value schemas).
        """
        result: dict[str, int] = {}
        path = Path(schemas_dir)
        for file in sorted(path.glob("*.avsc")):
            subject = f"{file.stem}-value"
            with file.open() as f:
                content = f.read()
            schema_id = await self.register(subject, content)
            result[subject] = schema_id
            log.info("schema.registered", subject=subject, schema_id=schema_id)
        return result
