from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from services.tunnel_orchestrator.domain.value_objects.hostname import Hostname


class DnsRecordType(str, Enum):
    CNAME = "CNAME"
    A = "A"
    AAAA = "AAAA"


@dataclass(frozen=True, slots=True)
class DnsRecord:
    """A Cloudflare DNS record value object.

    For tunnels we only ever create *proxied* CNAMEs pointing to
    ``{cf_tunnel_id}.cfargotunnel.com``. Other types are modelled to
    keep the value object reusable for reconciliation/diff use cases.
    """

    hostname: Hostname
    target: str
    type: DnsRecordType = DnsRecordType.CNAME
    proxied: bool = True
    ttl: int = 1                       # 1 == "auto" in Cloudflare
    comment: str = field(default="managed-by:tunnel-orchestrator")

    def __post_init__(self) -> None:
        if self.type is DnsRecordType.CNAME and self.proxied is False:
            # Tunnels REQUIRE proxied records to function.
            raise ValueError("Tunnel CNAME records must be proxied")
        if self.ttl < 1:
            raise ValueError("ttl must be >= 1")

    @classmethod
    def for_tunnel(cls, hostname: Hostname, cf_tunnel_id: str) -> "DnsRecord":
        return cls(
            hostname=hostname,
            target=f"{cf_tunnel_id}.cfargotunnel.com",
            type=DnsRecordType.CNAME,
            proxied=True,
        )
