"""Cloudflare Tunnel ingress rules — domain value objects.

The Cloudflare ingress configuration is an ordered list of rules
matching incoming requests. The **last** rule must be a catch-all
(``hostname`` and ``path`` both empty) — usually a 404 service. We
encode this invariant in :class:`IngressRuleSet`.

See: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/configure-tunnels/local-management/configuration-file/
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

from shared.errors import InvalidIngressRule

_ORIGIN_URL_RE = re.compile(
    r"^(https?|tcp|ssh|rdp|unix|http_status)://[^\s]+$|^http_status:\d{3}$"
)


@dataclass(frozen=True, slots=True)
class IngressOriginConfig:
    """Per-rule origin tuning. All fields optional."""

    connect_timeout: str | None = None       # e.g. "30s"
    no_tls_verify: bool | None = None
    origin_server_name: str | None = None
    ca_pool: str | None = None
    http_host_header: str | None = None
    disable_chunked_encoding: bool | None = None
    proxy_type: str | None = None            # e.g. "socks"

    def to_dict(self) -> dict[str, object]:
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass(frozen=True, slots=True)
class IngressRule:
    """A single ingress rule.

    A rule is a match clause (``hostname``, ``path``) and a destination
    (``service``). The catch-all rule has empty hostname and path.
    """

    service: str
    hostname: str | None = None
    path: str | None = None
    origin_request: IngressOriginConfig | None = None

    def __post_init__(self) -> None:
        if not self.service:
            raise InvalidIngressRule("ingress rule must define a service")
        if not _ORIGIN_URL_RE.match(self.service) and not self.service.startswith("http_status:"):
            raise InvalidIngressRule(f"invalid ingress service URL: {self.service!r}")

    @property
    def is_catch_all(self) -> bool:
        return not self.hostname and not self.path

    def to_dict(self) -> dict[str, object]:
        d: dict[str, object] = {"service": self.service}
        if self.hostname:
            d["hostname"] = self.hostname
        if self.path:
            d["path"] = self.path
        if self.origin_request:
            d["originRequest"] = self.origin_request.to_dict()
        return d


@dataclass(frozen=True, slots=True)
class IngressRuleSet:
    """Ordered list of rules, last one MUST be catch-all (404 by default)."""

    rules: tuple[IngressRule, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.rules:
            raise InvalidIngressRule("ingress rule set must contain at least one rule")
        if not self.rules[-1].is_catch_all:
            raise InvalidIngressRule("last ingress rule must be the catch-all (no hostname/path)")
        if any(r.is_catch_all for r in self.rules[:-1]):
            raise InvalidIngressRule("only the last rule may be a catch-all")

    @classmethod
    def single(cls, hostname: str, target_service: str) -> "IngressRuleSet":
        """Convenience constructor for the typical hostname → origin rule."""
        return cls(
            rules=(
                IngressRule(service=target_service, hostname=hostname),
                IngressRule(service="http_status:404"),
            )
        )

    @classmethod
    def from_iterable(cls, rules: Iterable[IngressRule]) -> "IngressRuleSet":
        return cls(tuple(rules))

    def to_payload(self) -> list[dict[str, object]]:
        return [r.to_dict() for r in self.rules]
