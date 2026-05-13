"""Contract tests: every Pydantic payload model has a matching .avsc and they round-trip."""

from __future__ import annotations

import json
from pathlib import Path

import fastavro
import orjson
import pytest

from platform.events.payloads import (
    TunnelCreateFailurePayload,
    TunnelCreateRequestPayload,
    TunnelCreateSuccessPayload,
    TunnelDeleteRequestPayload,
    TunnelDlqPayload,
)

pytestmark = pytest.mark.contract

SCHEMAS_DIR = Path(__file__).resolve().parents[2] / "platform" / "schemas"

# Pydantic model ↔ Avro file mapping
_PAIRS = [
    (TunnelCreateRequestPayload,  "tunnel_create_request.avsc"),
    (TunnelCreateSuccessPayload,  "tunnel_create_success.avsc"),
    (TunnelCreateFailurePayload,  "tunnel_create_failure.avsc"),
    (TunnelDeleteRequestPayload,  "tunnel_delete_request.avsc"),
    (TunnelDlqPayload,            "tunnel_dlq.avsc"),
]


@pytest.mark.parametrize("model,filename", _PAIRS)
def test_avro_schema_exists_and_parses(model, filename):
    schema_path = SCHEMAS_DIR / filename
    assert schema_path.exists(), f"missing avro schema for {model.__name__}: {filename}"
    parsed = fastavro.parse_schema(json.loads(schema_path.read_text()))
    assert parsed["name"]


@pytest.mark.parametrize("model,filename", _PAIRS)
def test_avro_field_names_intersect_pydantic(model, filename):
    avro = json.loads((SCHEMAS_DIR / filename).read_text())
    avro_fields = {f["name"] for f in avro["fields"]}
    pyd_fields = set(model.model_fields.keys())
    intersection = avro_fields & pyd_fields
    # Pydantic models may carry extra defaults (e.g. timestamps with default_factory)
    # but every Avro field MUST exist in the Pydantic model.
    missing = avro_fields - pyd_fields
    assert not missing, f"avro fields not present in {model.__name__}: {missing}"
    assert intersection, "no field overlap"


def test_envelope_avro_loads():
    parsed = fastavro.parse_schema(json.loads((SCHEMAS_DIR / "envelope.avsc").read_text()))
    assert parsed["name"] == "EventEnvelope"


def test_orjson_roundtrips_a_request_payload():
    p = TunnelCreateRequestPayload(
        tenant_id="0123abcd-0123-abcd-0123-abcdef012345",  # type: ignore[arg-type]
        hostname="api.example.com",
        cf_zone_id="zone-1",
        ingress=[{"service": "http://svc:8000"}],
    )
    raw = orjson.dumps(p.model_dump(mode="json"))
    back = TunnelCreateRequestPayload.model_validate(orjson.loads(raw))
    assert back == p
