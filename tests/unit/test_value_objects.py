"""Unit tests for value objects (pure, no I/O)."""

from __future__ import annotations

import pytest

from shared.errors import InvalidHostname, InvalidIngressRule
from services.tunnel_orchestrator.domain.value_objects import (
    DnsRecord,
    Hostname,
    IngressRule,
    IngressRuleSet,
)


pytestmark = pytest.mark.unit


class TestHostname:
    def test_normalises_to_lowercase(self):
        h = Hostname.parse("API.Svc.Example.COM")
        assert h.value == "api.svc.example.com"

    def test_root_domain(self):
        assert Hostname.parse("api.svc.example.com").root_domain == "example.com"

    def test_subdomain(self):
        assert Hostname.parse("api.svc.example.com").subdomain == "api.svc"

    @pytest.mark.parametrize("bad", ["", "no-tld", "x..y.com", "-bad.com", "a" * 254 + ".com"])
    def test_rejects_invalid(self, bad):
        with pytest.raises(InvalidHostname):
            Hostname.parse(bad)


class TestIngressRule:
    def test_valid_http_service(self):
        r = IngressRule(service="http://svc.svc.cluster.local:8080", hostname="api.example.com")
        assert not r.is_catch_all

    def test_catch_all_via_http_status(self):
        r = IngressRule(service="http_status:404")
        assert r.is_catch_all

    def test_rejects_empty_service(self):
        with pytest.raises(InvalidIngressRule):
            IngressRule(service="")

    def test_rejects_invalid_service(self):
        with pytest.raises(InvalidIngressRule):
            IngressRule(service="not-a-url")


class TestIngressRuleSet:
    def test_requires_catch_all_last(self):
        rules = (IngressRule(service="http://x:8000", hostname="api.example.com"),)
        with pytest.raises(InvalidIngressRule):
            IngressRuleSet(rules)

    def test_only_one_catch_all(self):
        with pytest.raises(InvalidIngressRule):
            IngressRuleSet((IngressRule(service="http_status:404"), IngressRule(service="http_status:404")))

    def test_single_helper(self):
        rs = IngressRuleSet.single("api.example.com", "http://x:8000")
        assert len(rs.rules) == 2
        assert rs.rules[-1].is_catch_all
        payload = rs.to_payload()
        assert payload[-1] == {"service": "http_status:404"}


class TestDnsRecord:
    def test_for_tunnel(self):
        r = DnsRecord.for_tunnel(Hostname.parse("api.example.com"), "abc")
        assert r.target == "abc.cfargotunnel.com"
        assert r.proxied is True

    def test_unproxied_cname_rejected(self):
        with pytest.raises(ValueError):
            DnsRecord(hostname=Hostname.parse("api.example.com"), target="x.cfargotunnel.com", proxied=False)
