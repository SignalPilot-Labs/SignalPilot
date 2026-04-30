"""Tests for SSRF host validation in network_validation.py.

Covers:
- Blocked IPs: loopback, link-local (including metadata 169.254.169.254),
  RFC1918 ranges, unspecified addresses
- IPv4-mapped IPv6 bypass attempts (::ffff:127.0.0.1, etc.)
- Legitimate external hosts are allowed
- Connection string URL parsing extracts and validates hosts
- SP_ALLOW_PRIVATE_CONNECTIONS=true: RFC1918 allowed, loopback still blocked
- DNS resolution failure = rejection (fail closed)
- Non-TCP db_types skip SSRF validation entirely
- TCP db_types get SSRF validation
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from gateway.network_validation import (
    TCP_DB_TYPES,
    validate_connection_host,
    validate_connection_params,
)

# ─── Helpers ─────────────────────────────────────────────────────────────────


def _mock_getaddrinfo(resolved_ip: str):
    """Return a mock getaddrinfo that returns a single resolved IP."""
    return [(None, None, None, None, (resolved_ip, 0))]


def _patch_dns(resolved_ip: str):
    """Patch socket.getaddrinfo to return a specific IP."""
    return patch(
        "gateway.network_validation.socket.getaddrinfo",
        return_value=_mock_getaddrinfo(resolved_ip),
    )


def _patch_dns_failure():
    """Patch socket.getaddrinfo to raise a DNS failure."""
    import socket

    return patch(
        "gateway.network_validation.socket.getaddrinfo",
        side_effect=socket.gaierror("Name or service not known"),
    )


def _patch_env_allow_private(enabled: bool):
    """Patch SP_ALLOW_PRIVATE_CONNECTIONS environment variable."""
    value = "true" if enabled else ""
    return patch.dict("os.environ", {"SP_ALLOW_PRIVATE_CONNECTIONS": value})


# ─── TestBlockedAddresses ─────────────────────────────────────────────────────


class TestBlockedAddresses:
    """Tests that blocked IP ranges are rejected."""

    def test_loopback_ipv4_127_0_0_1_is_blocked(self):
        with _patch_dns("127.0.0.1"):
            with pytest.raises(ValueError, match="blocked"):
                validate_connection_host("malicious-host.example.com")

    def test_loopback_ipv4_127_0_0_100_is_blocked(self):
        with _patch_dns("127.0.0.100"):
            with pytest.raises(ValueError, match="blocked"):
                validate_connection_host("localhost")

    def test_loopback_ipv6_is_blocked(self):
        with _patch_dns("::1"):
            with pytest.raises(ValueError, match="blocked"):
                validate_connection_host("ip6-localhost")

    def test_link_local_metadata_ip_is_blocked(self):
        """169.254.169.254 is the AWS metadata endpoint — must always be blocked."""
        with _patch_dns("169.254.169.254"):
            with pytest.raises(ValueError, match="blocked"):
                validate_connection_host("metadata.internal")

    def test_link_local_range_is_blocked(self):
        with _patch_dns("169.254.1.50"):
            with pytest.raises(ValueError, match="blocked"):
                validate_connection_host("apipa.example.com")

    def test_link_local_ipv6_is_blocked(self):
        with _patch_dns("fe80::1"):
            with pytest.raises(ValueError, match="blocked"):
                validate_connection_host("link-local.example.com")

    def test_rfc1918_10_0_0_0_is_blocked_by_default(self):
        with _patch_dns("10.0.0.1"):
            with pytest.raises(ValueError, match="blocked"):
                validate_connection_host("internal.corp")

    def test_rfc1918_172_16_is_blocked_by_default(self):
        with _patch_dns("172.16.0.5"):
            with pytest.raises(ValueError, match="blocked"):
                validate_connection_host("db.internal.corp")

    def test_rfc1918_192_168_is_blocked_by_default(self):
        with _patch_dns("192.168.1.1"):
            with pytest.raises(ValueError, match="blocked"):
                validate_connection_host("router.local")

    def test_unspecified_ipv4_is_blocked(self):
        with _patch_dns("0.0.0.0"):
            with pytest.raises(ValueError, match="blocked"):
                validate_connection_host("any.example.com")

    def test_unspecified_ipv6_is_blocked(self):
        with _patch_dns("::"):
            with pytest.raises(ValueError, match="blocked"):
                validate_connection_host("any6.example.com")


# ─── TestIPv4MappedIPv6Bypass ─────────────────────────────────────────────────


class TestIPv4MappedIPv6Bypass:
    """Tests that IPv4-mapped IPv6 addresses do not bypass SSRF checks."""

    def test_ipv4_mapped_loopback_is_blocked(self):
        """::ffff:127.0.0.1 maps to 127.0.0.1 — must be blocked."""
        with _patch_dns("::ffff:127.0.0.1"):
            with pytest.raises(ValueError, match="blocked"):
                validate_connection_host("evil.example.com")

    def test_ipv4_mapped_metadata_is_blocked(self):
        """::ffff:169.254.169.254 maps to AWS metadata IP — must be blocked."""
        with _patch_dns("::ffff:169.254.169.254"):
            with pytest.raises(ValueError, match="blocked"):
                validate_connection_host("evil-metadata.example.com")

    def test_ipv4_mapped_rfc1918_is_blocked_by_default(self):
        """::ffff:10.0.0.1 maps to private 10.x — must be blocked by default."""
        with _patch_dns("::ffff:10.0.0.1"):
            with pytest.raises(ValueError, match="blocked"):
                validate_connection_host("evil-private.example.com")

    def test_ipv4_mapped_cgnat_is_blocked(self):
        """::ffff:100.64.0.1 maps to CGNAT — must be blocked (bypass attempt)."""
        with _patch_dns("::ffff:100.64.0.1"):
            with pytest.raises(ValueError, match="blocked"):
                validate_connection_host("evil-cgnat.example.com")


# ─── TestCGNATBlocking ────────────────────────────────────────────────────────


class TestCGNATBlocking:
    """Tests that CGNAT (100.64.0.0/10, RFC 6598) addresses are always blocked."""

    def test_cgnat_start_of_range_is_blocked(self):
        """100.64.0.1 is in the CGNAT range and must be blocked."""
        with _patch_dns("100.64.0.1"):
            with pytest.raises(ValueError, match="blocked"):
                validate_connection_host("cgnat.example.com")

    def test_cgnat_middle_of_range_is_blocked(self):
        """100.100.100.100 is in the CGNAT range and must be blocked."""
        with _patch_dns("100.100.100.100"):
            with pytest.raises(ValueError, match="blocked"):
                validate_connection_host("cgnat-mid.example.com")

    def test_cgnat_end_of_range_is_blocked(self):
        """100.127.255.254 is the last usable CGNAT address — must be blocked."""
        with _patch_dns("100.127.255.254"):
            with pytest.raises(ValueError, match="blocked"):
                validate_connection_host("cgnat-end.example.com")

    def test_cgnat_blocked_even_when_allow_private_set(self):
        """CGNAT is always blocked regardless of SP_ALLOW_PRIVATE_CONNECTIONS."""
        with _patch_env_allow_private(True), _patch_dns("100.64.0.1"):
            with pytest.raises(ValueError, match="blocked"):
                validate_connection_host("cgnat.example.com")

    def test_cgnat_middle_blocked_even_when_allow_private_set(self):
        """100.100.100.100 is still blocked when SP_ALLOW_PRIVATE_CONNECTIONS=true."""
        with _patch_env_allow_private(True), _patch_dns("100.100.100.100"):
            with pytest.raises(ValueError, match="blocked"):
                validate_connection_host("cgnat-mid.example.com")

    def test_just_below_cgnat_range_is_allowed(self):
        """100.63.255.255 is just below 100.64.0.0/10 — must be allowed."""
        with _patch_dns("100.63.255.255"):
            validate_connection_host("below-cgnat.example.com")  # should not raise

    def test_just_above_cgnat_range_is_allowed(self):
        """100.128.0.0 is just above 100.64.0.0/10 range — must be allowed."""
        with _patch_dns("100.128.0.0"):
            validate_connection_host("above-cgnat.example.com")  # should not raise

    def test_6to4_relay_anycast_is_blocked(self):
        """192.88.99.1 is in the deprecated 6to4 relay range (RFC 7526) — must be blocked."""
        with _patch_dns("192.88.99.1"):
            with pytest.raises(ValueError, match="blocked"):
                validate_connection_host("6to4-relay.example.com")

    def test_6to4_relay_blocked_even_when_allow_private_set(self):
        """192.88.99.0/24 is always blocked even when SP_ALLOW_PRIVATE_CONNECTIONS=true."""
        with _patch_env_allow_private(True), _patch_dns("192.88.99.1"):
            with pytest.raises(ValueError, match="blocked"):
                validate_connection_host("6to4-relay.example.com")


# ─── TestAllowedExternalHosts ─────────────────────────────────────────────────


class TestAllowedExternalHosts:
    """Tests that legitimate external hosts are allowed."""

    def test_public_ip_is_allowed(self):
        with _patch_dns("8.8.8.8"):
            validate_connection_host("db.example.com")  # should not raise

    def test_another_public_ip_is_allowed(self):
        with _patch_dns("52.0.0.1"):
            validate_connection_host("rds.amazonaws.com")  # should not raise

    def test_empty_host_raises(self):
        with pytest.raises(ValueError):
            validate_connection_host("")

    def test_whitespace_only_host_raises(self):
        with pytest.raises(ValueError):
            validate_connection_host("   ")


# ─── TestDNSFailure ──────────────────────────────────────────────────────────


class TestDNSFailure:
    """Tests that DNS resolution failure is treated as rejection (fail closed)."""

    def test_dns_failure_raises_value_error(self):
        with _patch_dns_failure():
            with pytest.raises(ValueError, match="DNS resolution failed"):
                validate_connection_host("nonexistent-host.invalid")

    def test_dns_failure_message_mentions_host(self):
        with _patch_dns_failure():
            with pytest.raises(ValueError) as exc_info:
                validate_connection_host("bad-host.example.com")
            assert "bad-host.example.com" in str(exc_info.value)


# ─── TestSPAllowPrivateConnections ───────────────────────────────────────────


class TestSPAllowPrivateConnections:
    """Tests SP_ALLOW_PRIVATE_CONNECTIONS=true behavior."""

    def test_rfc1918_allowed_when_env_set(self):
        """RFC1918 addresses are allowed when SP_ALLOW_PRIVATE_CONNECTIONS=true."""
        with _patch_env_allow_private(True), _patch_dns("10.0.0.5"):
            validate_connection_host("internal-db.corp")  # should not raise

    def test_rfc1918_172_allowed_when_env_set(self):
        with _patch_env_allow_private(True), _patch_dns("172.16.1.1"):
            validate_connection_host("db.internal")  # should not raise

    def test_rfc1918_192_168_allowed_when_env_set(self):
        with _patch_env_allow_private(True), _patch_dns("192.168.0.10"):
            validate_connection_host("local-db")  # should not raise

    def test_loopback_still_blocked_when_env_set(self):
        """Loopback must always be blocked even when private connections allowed."""
        with _patch_env_allow_private(True), _patch_dns("127.0.0.1"):
            with pytest.raises(ValueError, match="blocked"):
                validate_connection_host("localhost")

    def test_link_local_still_blocked_when_env_set(self):
        """Link-local (including metadata) must always be blocked."""
        with _patch_env_allow_private(True), _patch_dns("169.254.169.254"):
            with pytest.raises(ValueError, match="blocked"):
                validate_connection_host("metadata.internal")

    def test_ipv6_loopback_still_blocked_when_env_set(self):
        with _patch_env_allow_private(True), _patch_dns("::1"):
            with pytest.raises(ValueError, match="blocked"):
                validate_connection_host("ip6-localhost")

    def test_rfc1918_blocked_when_env_false(self):
        """RFC1918 is blocked when SP_ALLOW_PRIVATE_CONNECTIONS is false."""
        with _patch_env_allow_private(False), _patch_dns("10.0.0.1"):
            with pytest.raises(ValueError, match="blocked"):
                validate_connection_host("internal-db.corp")


# ─── TestConnectionStringParsing ─────────────────────────────────────────────


class TestConnectionStringParsing:
    """Tests that connection string URL parsing extracts and validates hosts."""

    def test_connection_string_host_extracted_and_validated(self):
        """When connection_string is provided, its host is extracted and checked."""
        with _patch_dns("127.0.0.1"):
            with pytest.raises(ValueError, match="blocked"):
                validate_connection_params(
                    host=None,
                    port=5432,
                    db_type="postgres",
                    connection_string="postgresql://user:pass@localhost:5432/db",
                )

    def test_connection_string_external_host_is_allowed(self):
        with _patch_dns("52.0.0.1"):
            validate_connection_params(
                host=None,
                port=5432,
                db_type="postgres",
                connection_string="postgresql://user:pass@db.example.com:5432/db",
            )  # should not raise

    def test_direct_host_validated_when_no_connection_string(self):
        with _patch_dns("192.168.1.1"):
            with pytest.raises(ValueError, match="blocked"):
                validate_connection_params(
                    host="192.168.1.1",
                    port=5432,
                    db_type="postgres",
                    connection_string=None,
                )

    def test_no_host_no_connection_string_fails_closed(self):
        """If no host can be determined for a TCP db_type, fail closed with ValueError."""
        with pytest.raises(ValueError, match="No host could be determined"):
            validate_connection_params(
                host=None,
                port=None,
                db_type="postgres",
                connection_string=None,
            )


# ─── TestNonTCPDbTypesSkipValidation ─────────────────────────────────────────


class TestNonTCPDbTypesSkipValidation:
    """Tests that non-TCP db_types skip SSRF validation entirely."""

    @pytest.mark.parametrize("db_type", ["duckdb", "sqlite", "snowflake", "bigquery", "databricks"])
    def test_non_tcp_db_type_skips_validation(self, db_type: str):
        """Non-TCP db_types must not trigger SSRF validation."""
        # Even if we provide a loopback host, it should not raise for these types.
        # No need to mock DNS — if validation runs it would call getaddrinfo.
        validate_connection_params(
            host="127.0.0.1",
            port=None,
            db_type=db_type,
            connection_string=None,
        )  # should not raise


# ─── TestTCPDbTypesGetValidation ──────────────────────────────────────────────


class TestTCPDbTypesGetValidation:
    """Tests that TCP db_types get SSRF validation applied."""

    @pytest.mark.parametrize("db_type", sorted(TCP_DB_TYPES))
    def test_tcp_db_type_validates_host(self, db_type: str):
        """TCP db_types must run SSRF validation and block internal addresses."""
        with _patch_dns("127.0.0.1"):
            with pytest.raises(ValueError, match="blocked"):
                validate_connection_params(
                    host="localhost",
                    port=5432,
                    db_type=db_type,
                    connection_string=None,
                )

    def test_tcp_db_types_frozenset_contents(self):
        """Verify the TCP_DB_TYPES set contains exactly the expected types."""
        expected = {"postgres", "mysql", "mssql", "redshift", "clickhouse", "trino"}
        assert TCP_DB_TYPES == expected
