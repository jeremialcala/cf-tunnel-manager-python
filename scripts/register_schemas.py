"""Register all Avro schemas in cloud_platform/schemas/ to the Schema Registry."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.tunnel_orchestrator.infrastructure.messaging import SchemaRegistryClient


async def _main() -> None:
    schemas_dir = Path(__file__).resolve().parent.parent / "cloud_platform" / "schemas"
    client = SchemaRegistryClient()
    result = await client.register_directory(schemas_dir)
    for subject, sid in result.items():
        print(f"  {subject:<48} -> id={sid}")
    print(f"Registered {len(result)} schemas")


if __name__ == "__main__":
    asyncio.run(_main())
