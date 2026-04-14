"""Tests for Trino connector — connection parsing, HTTPS, timeout handling."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "signalpilot", "gateway"))


class TestTrinoConnectorParsing:
    def test_standard_url_format(self):
        """Standard trino:// URL should be parsed correctly."""
        from gateway.connectors.trino import TrinoConnector
        connector = TrinoConnector()
        result = connector._parse_connection("trino://myuser@trino.example.com:8080/hive/default")
        assert result["host"] == "trino.example.com"
        assert result["port"] == 8080
        assert result["username"] == "myuser"
        assert result["catalog"] == "hive"
        assert result["schema"] == "default"

    def test_https_scheme(self):
        """trino+https:// should set https=True."""
        from gateway.connectors.trino import TrinoConnector
        connector = TrinoConnector()
        result = connector._parse_connection("trino+https://admin@starburst.example.com:443/hive")
        assert result["host"] == "starburst.example.com"
        assert result["port"] == 443
        assert result["https"] is True

    def test_password_in_url(self):
        """Password should be parsed from URL."""
        from gateway.connectors.trino import TrinoConnector
        connector = TrinoConnector()
        result = connector._parse_connection("trino://user:secret@host:8080/catalog")
        assert result["username"] == "user"
        assert result["password"] == "secret"

    def test_host_only_fallback(self):
        """Plain host string should default to trino user on port 8080."""
        from gateway.connectors.trino import TrinoConnector
        connector = TrinoConnector()
        result = connector._parse_connection("trino.internal.company.com")
        assert result["host"] == "trino.internal.company.com"
        assert result["port"] == 8080
        assert result["username"] == "trino"

    def test_request_timeout_from_url(self):
        """request_timeout query param should be parsed."""
        from gateway.connectors.trino import TrinoConnector
        connector = TrinoConnector()
        result = connector._parse_connection("trino://user@host:8080/cat?request_timeout=60")
        assert result["request_timeout"] == "60"

    def test_verify_ssl_param(self):
        """verify query param should be parsed for SSL control."""
        from gateway.connectors.trino import TrinoConnector
        connector = TrinoConnector()
        result = connector._parse_connection("trino+https://user@host:443/cat?verify=false")
        assert result["verify"] == "false"
        assert result["https"] is True

    def test_credential_extras_sets_timeout(self):
        """set_credential_extras should store query_timeout."""
        from gateway.connectors.trino import TrinoConnector
        connector = TrinoConnector()
        connector.set_credential_extras({"query_timeout": 120})
        assert connector._request_timeout == 120


class TestTrinoIdentifierQuoting:
    """Ensure catalog/schema/table names are properly quoted to prevent SQL injection."""

    def test_simple_name(self):
        from gateway.connectors.trino import TrinoConnector
        assert TrinoConnector._quote_ident("hive") == '"hive"'

    def test_name_with_special_chars(self):
        from gateway.connectors.trino import TrinoConnector
        assert TrinoConnector._quote_ident("my-catalog") == '"my-catalog"'

    def test_name_with_double_quotes(self):
        """Embedded double quotes should be escaped by doubling."""
        from gateway.connectors.trino import TrinoConnector
        assert TrinoConnector._quote_ident('cat"alog') == '"cat""alog"'

    def test_sql_injection_attempt(self):
        """SQL injection via catalog name should be neutralized."""
        from gateway.connectors.trino import TrinoConnector
        malicious = 'hive"; DROP TABLE users; --'
        quoted = TrinoConnector._quote_ident(malicious)
        assert quoted == '"hive""; DROP TABLE users; --"'
        # The entire string is a single quoted identifier, not executable SQL

    def test_empty_name(self):
        from gateway.connectors.trino import TrinoConnector
        assert TrinoConnector._quote_ident("") == '""'
