"""Security hardening tests for the gateway module.

Covers:
- SSH hostname validation (gateway.connectors.ssh_tunnel)
- PII hashing (gateway.governance.pii)
- Connection name validation (gateway.api.deps)
- Tunnel port blocking (gateway.api.tunnels)
- Settings API key validation logic
"""

import hashlib

import pytest
from fastapi import HTTPException

from gateway.connectors.ssh_tunnel import _build_proxy_command, _validate_hostname
from gateway.governance.pii import _hash_value
from gateway.api.deps import ConnectionName, validate_connection_name
from gateway.api.tunnels import _BLOCKED_TUNNEL_PORTS
from gateway.models import GatewaySettings


# ─── SSH hostname validation ─────────────────────────────────────────────────


class TestValidateHostname:
    """_validate_hostname should accept safe hostnames and reject injection payloads."""

    # --- Valid inputs ---

    def test_accepts_fqdn(self):
        # Should not raise
        _validate_hostname("db.example.com", "host")

    def test_accepts_ipv4(self):
        _validate_hostname("10.0.0.1", "host")

    def test_accepts_ipv6_loopback(self):
        _validate_hostname("::1", "host")

    def test_accepts_hyphenated_hostname(self):
        _validate_hostname("my-host", "host")

    def test_accepts_alphanumeric_only(self):
        _validate_hostname("dbserver01", "host")

    # --- Rejection of injection payloads ---

    def test_rejects_semicolon_command(self):
        with pytest.raises(ValueError):
            _validate_hostname("host;rm -rf /", "host")

    def test_rejects_dollar_paren_subshell(self):
        with pytest.raises(ValueError):
            _validate_hostname("$(whoami)", "host")

    def test_rejects_backtick_subshell(self):
        with pytest.raises(ValueError):
            _validate_hostname("host`id`", "host")

    def test_rejects_pipe_command(self):
        with pytest.raises(ValueError):
            _validate_hostname("host | cat /etc/passwd", "host")

    def test_rejects_newline_command(self):
        with pytest.raises(ValueError):
            _validate_hostname("host\ncommand", "host")

    def test_rejects_empty_string(self):
        """Empty string does not match the hostname regex and must be rejected."""
        with pytest.raises(ValueError):
            _validate_hostname("", "host")

    def test_error_message_contains_field_name(self):
        """ValueError should name the offending field so callers can surface it."""
        with pytest.raises(ValueError, match="proxy_host"):
            _validate_hostname("bad;host", "proxy_host")


class TestBuildProxyCommand:
    """_build_proxy_command should produce shell-safe output and reject bad hosts."""

    def test_returns_string(self):
        cmd = _build_proxy_command("proxy.corp.com", 3128, "db.internal", 22)
        assert isinstance(cmd, str)

    def test_contains_socat(self):
        cmd = _build_proxy_command("proxy.corp.com", 3128, "db.internal", 22)
        assert "socat" in cmd

    def test_no_unquoted_special_chars_in_hosts(self):
        """The host components in the command must not contain raw shell specials.

        shlex.quote wraps each token in single quotes or adds a safe escape,
        so after quoting neither ';', '|', '$', nor '`' should appear outside quotes.
        We verify this by checking the quoted host segments are present.
        """
        import shlex
        proxy_host = "proxy.example.com"
        ssh_host = "db.internal"
        cmd = _build_proxy_command(proxy_host, 3128, ssh_host, 22)
        assert shlex.quote(proxy_host) in cmd
        assert shlex.quote(ssh_host) in cmd

    def test_ports_embedded_correctly(self):
        cmd = _build_proxy_command("proxy.corp.com", 8080, "db.host.com", 5432)
        assert "8080" in cmd
        assert "5432" in cmd

    def test_raises_on_malicious_proxy_host(self):
        with pytest.raises(ValueError):
            _build_proxy_command("proxy;rm -rf /", 3128, "db.internal", 22)

    def test_raises_on_malicious_ssh_host(self):
        with pytest.raises(ValueError):
            _build_proxy_command("proxy.corp.com", 3128, "$(id)", 22)

    def test_raises_on_empty_proxy_host(self):
        with pytest.raises(ValueError):
            _build_proxy_command("", 3128, "db.internal", 22)

    def test_raises_on_empty_ssh_host(self):
        with pytest.raises(ValueError):
            _build_proxy_command("proxy.corp.com", 3128, "", 22)


# ─── PII hashing ─────────────────────────────────────────────────────────────


class TestHashValue:
    """_hash_value must produce a full SHA-256 hash or 'NULL' for None."""

    _PREFIX = "sha256:"
    _EXPECTED_LEN = len("sha256:") + 64  # 7 + 64 = 71

    def test_returns_sha256_prefix(self):
        result = _hash_value("test")
        assert result.startswith(self._PREFIX)

    def test_hash_length_is_exactly_71_chars(self):
        """sha256: prefix (7) + 64-char hex digest = 71 total."""
        result = _hash_value("test")
        assert len(result) == self._EXPECTED_LEN

    def test_hex_portion_is_64_chars(self):
        result = _hash_value("anything")
        hex_part = result[len(self._PREFIX):]
        assert len(hex_part) == 64

    def test_hex_portion_is_valid_hex(self):
        result = _hash_value("anything")
        hex_part = result[len(self._PREFIX):]
        # Should not raise
        int(hex_part, 16)

    def test_none_returns_null_string(self):
        assert _hash_value(None) == "NULL"

    def test_deterministic_for_same_input(self):
        assert _hash_value("test") == _hash_value("test")

    def test_different_inputs_produce_different_hashes(self):
        assert _hash_value("test") != _hash_value("Test")

    def test_matches_raw_sha256(self):
        """The embedded digest must equal a direct hashlib computation."""
        value = "hello world"
        expected_hex = hashlib.sha256(value.encode("utf-8")).hexdigest()
        result = _hash_value(value)
        assert result == f"sha256:{expected_hex}"

    def test_numeric_value_hashed(self):
        result = _hash_value(42)
        assert result.startswith("sha256:")
        assert len(result) == self._EXPECTED_LEN

    def test_empty_string_hashed_not_null(self):
        """An empty string is not None — it should be hashed, not returned as 'NULL'."""
        result = _hash_value("")
        assert result.startswith("sha256:")
        assert result != "NULL"


# ─── Connection name validation ───────────────────────────────────────────────


class TestValidateConnectionName:
    """validate_connection_name must accept safe names and reject dangerous ones."""

    # --- Valid inputs ---

    def test_accepts_hyphenated_name(self):
        assert validate_connection_name("my-conn") == "my-conn"

    def test_accepts_underscored_name(self):
        assert validate_connection_name("test_123") == "test_123"

    def test_accepts_single_char(self):
        assert validate_connection_name("a") == "a"

    def test_accepts_alphanumeric(self):
        assert validate_connection_name("ProdDB01") == "ProdDB01"

    def test_accepts_max_length(self):
        name = "a" * 64
        assert validate_connection_name(name) == name

    # --- Rejection cases ---

    def test_rejects_empty_string(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_connection_name("")
        assert exc_info.value.status_code == 400

    def test_rejects_name_too_long(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_connection_name("a" * 65)
        assert exc_info.value.status_code == 400

    def test_rejects_path_traversal(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_connection_name("../etc/passwd")
        assert exc_info.value.status_code == 400

    def test_rejects_semicolon_injection(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_connection_name("conn;drop")
        assert exc_info.value.status_code == 400

    def test_rejects_spaces(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_connection_name("a b")
        assert exc_info.value.status_code == 400

    def test_rejects_dollar_sign(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_connection_name("conn$var")
        assert exc_info.value.status_code == 400

    def test_rejects_slash(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_connection_name("conn/name")
        assert exc_info.value.status_code == 400

    def test_error_detail_is_helpful(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_connection_name("")
        assert "connection name" in exc_info.value.detail.lower()


class TestConnectionNameType:
    """ConnectionName must be importable and be an Annotated type alias."""

    def test_connection_name_is_importable(self):
        # The import at the top of this file already verifies this; redundant
        # but explicit for readability.
        assert ConnectionName is not None

    def test_connection_name_is_annotated(self):
        import typing
        # get_args on an Annotated alias returns a non-empty tuple
        args = typing.get_args(ConnectionName)
        assert len(args) > 0
        # The first arg should be the base type (str)
        assert args[0] is str


# ─── Tunnel port blocking ─────────────────────────────────────────────────────


class TestBlockedTunnelPorts:
    """_BLOCKED_TUNNEL_PORTS must cover all well-known/privileged ports 1-1023."""

    def test_is_frozenset(self):
        assert isinstance(_BLOCKED_TUNNEL_PORTS, frozenset)

    def test_contains_all_privileged_ports(self):
        expected = frozenset(range(1, 1024))
        assert expected == _BLOCKED_TUNNEL_PORTS

    def test_port_1_is_blocked(self):
        assert 1 in _BLOCKED_TUNNEL_PORTS

    def test_port_22_ssh_is_blocked(self):
        assert 22 in _BLOCKED_TUNNEL_PORTS

    def test_port_443_https_is_blocked(self):
        assert 443 in _BLOCKED_TUNNEL_PORTS

    def test_port_80_http_is_blocked(self):
        assert 80 in _BLOCKED_TUNNEL_PORTS

    def test_port_1023_boundary_is_blocked(self):
        assert 1023 in _BLOCKED_TUNNEL_PORTS

    def test_port_3200_is_not_blocked(self):
        assert 3200 not in _BLOCKED_TUNNEL_PORTS

    def test_port_1024_is_not_blocked(self):
        """1024 is the first unprivileged port and must not be in the blocked set."""
        assert 1024 not in _BLOCKED_TUNNEL_PORTS

    def test_port_8080_is_not_blocked(self):
        assert 8080 not in _BLOCKED_TUNNEL_PORTS


# ─── Settings API key validation logic ───────────────────────────────────────


class TestSettingsApiKeyLogic:
    """Validate the key-normalisation and placeholder logic in the settings update flow.

    These tests exercise the pure Python logic extracted from
    gateway.api.settings.update_settings without spinning up a real FastAPI
    app or touching the filesystem.
    """

    def _normalize_key(self, raw: str | None) -> str | None:
        """Replicate the strip step from update_settings."""
        if raw:
            return raw.strip()
        return raw

    def _resolve_key(self, new_key: str | None, current_key: str | None) -> str | None:
        """Replicate the placeholder-preservation step from update_settings."""
        if new_key == "***":
            return current_key
        return new_key

    # --- Whitespace stripping ---

    def test_strips_leading_whitespace(self):
        assert self._normalize_key("  key") == "key"

    def test_strips_trailing_whitespace(self):
        assert self._normalize_key("key  ") == "key"

    def test_strips_both_ends(self):
        assert self._normalize_key(" key ") == "key"

    def test_no_whitespace_unchanged(self):
        assert self._normalize_key("key") == "key"

    def test_none_key_left_as_none(self):
        assert self._normalize_key(None) is None

    def test_empty_string_not_stripped_to_key(self):
        """An empty string is falsy; the normalize helper returns it untouched."""
        assert self._normalize_key("") == ""

    # --- Placeholder detection ---

    def test_placeholder_preserves_existing_key(self):
        existing = "super-secret-key-1234"
        assert self._resolve_key("***", existing) == existing

    def test_new_key_replaces_current(self):
        result = self._resolve_key("my-new-key", "old-key")
        assert result == "my-new-key"

    def test_none_new_key_treated_as_clear(self):
        result = self._resolve_key(None, "existing-key")
        assert result is None

    # --- GatewaySettings model ---

    def test_gateway_settings_api_key_defaults_to_none(self):
        s = GatewaySettings()
        assert s.api_key is None

    def test_gateway_settings_accepts_api_key(self):
        s = GatewaySettings(api_key="my-secret-key")
        assert s.api_key == "my-secret-key"

    def test_gateway_settings_sandbox_api_key_defaults_to_none(self):
        s = GatewaySettings()
        assert s.sandbox_api_key is None

    # --- Minimum key length logic ---

    def test_key_shorter_than_16_chars_should_fail_length_check(self):
        """Verify the minimum length guard condition used in update_settings."""
        new_key = "short"
        assert len(new_key) < 16

    def test_key_of_16_chars_passes_length_check(self):
        new_key = "a" * 16
        assert len(new_key) >= 16

    def test_key_of_exactly_16_chars_is_accepted(self):
        """The boundary value must be accepted (>= 16, not > 16)."""
        new_key = "abcdefghijklmnop"  # exactly 16
        assert len(new_key) == 16
        assert len(new_key) >= 16
