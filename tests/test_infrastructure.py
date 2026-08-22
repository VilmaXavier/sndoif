"""
Tests for the infrastructure correlation layer's comparison and
detection logic. Uses hardcoded fake data rather than live network
calls, so these tests are fast, repeatable, and don't depend on
external services (WHOIS, crt.sh, DNS) being available.
"""

from infrastructure.whois_lookup import compare_domains, _is_real_value
from infrastructure.hosting_correlation import _subnet_24, cluster_by_shared_ip
from infrastructure.analytics_fingerprint import compare_fingerprints


def test_is_real_value_rejects_redaction_placeholders():
    """Regression test for the real bug found during development:
    WHOIS privacy redaction placeholders must not be treated as real
    matching data.
    """
    assert _is_real_value("REDACTED FOR PRIVACY") is False
    assert _is_real_value(None) is False
    assert _is_real_value("Monzo Bank Ltd") is True


def test_compare_domains_ignores_redacted_registrant_org():
    """Two domains both showing 'REDACTED FOR PRIVACY' must NOT be
    flagged as sharing a registrant org -- this is the exact false
    positive found with monzo.com vs revolut.com during development.
    """
    record_a = {
        "domain": "example-a.com", "registrar": "Registrar One",
        "registrant_org": "REDACTED FOR PRIVACY", "name_servers": ["ns1.a.com"],
    }
    record_b = {
        "domain": "example-b.com", "registrar": "Registrar Two",
        "registrant_org": "REDACTED FOR PRIVACY", "name_servers": ["ns1.b.com"],
    }

    result = compare_domains(record_a, record_b)

    assert result["same_registrant_org"] is False
    assert result["same_registrar"] is False


def test_compare_domains_finds_genuine_match():
    """A real, non-redacted shared registrant org should still be
    correctly detected -- confirming the redaction fix didn't also
    break genuine matches.
    """
    record_a = {
        "domain": "example-a.com", "registrar": "Same Registrar",
        "registrant_org": "Shared Org LLC", "name_servers": ["ns1.shared.com"],
    }
    record_b = {
        "domain": "example-b.com", "registrar": "Same Registrar",
        "registrant_org": "Shared Org LLC", "name_servers": ["ns1.shared.com", "ns2.shared.com"],
    }

    result = compare_domains(record_a, record_b)

    assert result["same_registrant_org"] is True
    assert result["same_registrar"] is True
    assert result["shared_name_servers"] == ["ns1.shared.com"]


def test_subnet_24_computes_correct_block():
    assert _subnet_24("93.184.216.34") == "93.184.216.0/24"
    assert _subnet_24("10.0.0.1") == "10.0.0.0/24"


def test_cluster_by_shared_ip_only_returns_shared_ips(monkeypatch):
    """A domain resolving to a unique IP should not appear in results --
    only IPs shared by 2+ domains count as a correlation signal.
    """
    from infrastructure import hosting_correlation

    fake_resolutions = {
        "shared-a.com": ["1.2.3.4"],
        "shared-b.com": ["1.2.3.4"],
        "unique.com": ["9.9.9.9"],
    }

    def fake_resolve(domain):
        return fake_resolutions.get(domain, [])

    monkeypatch.setattr(hosting_correlation, "resolve_domain", fake_resolve)

    result = cluster_by_shared_ip(["shared-a.com", "shared-b.com", "unique.com"])

    assert "1.2.3.4" in result
    assert set(result["1.2.3.4"]) == {"shared-a.com", "shared-b.com"}
    assert "9.9.9.9" not in result


def test_compare_fingerprints_finds_shared_tracking_id():
    fingerprint_a = {
        "url": "https://site-a.com",
        "tracking_ids": {"google_analytics_ua": ["UA-12345678-1"]},
        "favicon_hash": "hash_a",
    }
    fingerprint_b = {
        "url": "https://site-b.com",
        "tracking_ids": {"google_analytics_ua": ["UA-12345678-1"]},
        "favicon_hash": "hash_b",
    }

    result = compare_fingerprints(fingerprint_a, fingerprint_b)

    assert result["shared_tracking_ids"] == {"google_analytics_ua": ["UA-12345678-1"]}
    assert result["same_favicon"] is False


def test_compare_fingerprints_detects_same_favicon():
    fingerprint_a = {"url": "https://site-a.com", "tracking_ids": {}, "favicon_hash": "identical_hash"}
    fingerprint_b = {"url": "https://site-b.com", "tracking_ids": {}, "favicon_hash": "identical_hash"}

    result = compare_fingerprints(fingerprint_a, fingerprint_b)

    assert result["same_favicon"] is True
