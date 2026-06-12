"""Tests for SSH tunnel socat ProxyCommand injection hardening.

Covers:
- _validate_socat_host: accept/reject cases for socat address-spec injection prevention
- _validate_socat_port: accept/reject cases for port range validation
- _build_proxy_command: correct output for valid inputs, ValueError for invalid inputs
"""

from __future__ import annotations

import pytest

from gateway.connectors.ssh_tunnel import (
    _build_proxy_command,
    _validate_socat_host,
    _validate_socat_port,
)


class TestValidateSocatHostAccepts:
    def test_accepts_dns_name(self):
        assert _validate_socat_host("host", "bastion.example.com") == "bastion.example.com"

    def test_accepts_bare_ipv4(self):
        assert _validate_socat_host("host", "10.0.0.1") == "10.0.0.1"

    def test_accepts_hyphenated_subdomain(self):
        assert _validate_socat_host("host", "host-1.sub.example.com") == "host-1.sub.example.com"

    def test_accepts_underscore_host(self):
        assert _validate_socat_host("host", "my_host") == "my_host"

    def test_strips_leading_trailing_whitespace(self):
        assert _validate_socat_host("host", "  bastion.corp  ") == "bastion.corp"

    def test_accepts_253_chars(self):
        val = "a" * 253
        assert _validate_socat_host("host", val) == val


class TestValidateSocatHostRejects:
    def test_rejects_comma_file_injection(self):
        with pytest.raises(ValueError, match="disallowed characters"):
            _validate_socat_host("host", "x,FILE:/tmp/x")

    def test_rejects_comma_reuseaddr(self):
        with pytest.raises(ValueError, match="disallowed characters"):
            _validate_socat_host("host", "x,reuseaddr")

    def test_rejects_colon(self):
        with pytest.raises(ValueError, match="disallowed characters"):
            _validate_socat_host("host", "host:22")

    def test_rejects_equals(self):
        with pytest.raises(ValueError, match="disallowed characters"):
            _validate_socat_host("host", "host=value")

    def test_rejects_slash(self):
        with pytest.raises(ValueError, match="disallowed characters"):
            _validate_socat_host("host", "host/path")

    def test_rejects_backslash(self):
        with pytest.raises(ValueError, match="disallowed characters"):
            _validate_socat_host("host", "host\\extra")

    def test_rejects_space(self):
        with pytest.raises(ValueError, match="disallowed characters"):
            _validate_socat_host("host", "a b")

    def test_rejects_empty_string(self):
        with pytest.raises(ValueError, match="must not be empty"):
            _validate_socat_host("host", "")

    def test_rejects_whitespace_only(self):
        with pytest.raises(ValueError, match="must not be empty"):
            _validate_socat_host("host", "   ")

    def test_rejects_254_chars(self):
        with pytest.raises(ValueError, match="disallowed characters"):
            _validate_socat_host("host", "a" * 254)

    def test_error_message_does_not_echo_value(self):
        """Error messages must not include attacker-controlled input."""
        malicious = "x,OPEN:/etc/passwd"
        with pytest.raises(ValueError) as exc_info:
            _validate_socat_host("host", malicious)
        assert malicious not in str(exc_info.value)


class TestValidateSocatPortAccepts:
    def test_accepts_int_22(self):
        assert _validate_socat_port("port", 22) == 22

    def test_accepts_string_3128(self):
        assert _validate_socat_port("port", "3128") == 3128

    def test_accepts_min_port(self):
        assert _validate_socat_port("port", 1) == 1

    def test_accepts_max_port(self):
        assert _validate_socat_port("port", 65535) == 65535


class TestValidateSocatPortRejects:
    def test_rejects_zero(self):
        with pytest.raises(ValueError, match="must be in range"):
            _validate_socat_port("port", 0)

    def test_rejects_negative(self):
        with pytest.raises(ValueError, match="must be in range"):
            _validate_socat_port("port", -1)

    def test_rejects_above_max(self):
        with pytest.raises(ValueError, match="must be in range"):
            _validate_socat_port("port", 65536)

    def test_rejects_non_numeric_string(self):
        with pytest.raises(ValueError, match="must be an integer"):
            _validate_socat_port("port", "abc")

    def test_rejects_none(self):
        with pytest.raises(ValueError, match="must be an integer"):
            _validate_socat_port("port", None)

    def test_rejects_empty_string(self):
        with pytest.raises(ValueError, match="must be an integer"):
            _validate_socat_port("port", "")


class TestBuildProxyCommand:
    def test_returns_correct_socat_string(self):
        result = _build_proxy_command("proxy.corp", 3128, "bastion.example.com", 22)
        assert result == "socat - PROXY:proxy.corp:bastion.example.com:22,proxyport=3128"

    def test_raises_on_injected_proxy_host(self):
        with pytest.raises(ValueError):
            _build_proxy_command("x,OPEN:/etc/passwd", 3128, "bastion.example.com", 22)

    def test_raises_on_injected_ssh_host(self):
        with pytest.raises(ValueError):
            _build_proxy_command("proxy.corp", 3128, "x,EXEC:cmd", 22)

    def test_raises_on_invalid_ssh_port(self):
        with pytest.raises(ValueError):
            _build_proxy_command("proxy.corp", 3128, "bastion.example.com", 0)

    def test_raises_on_invalid_proxy_port(self):
        with pytest.raises(ValueError):
            _build_proxy_command("proxy.corp", "x;y", "bastion.example.com", 22)
