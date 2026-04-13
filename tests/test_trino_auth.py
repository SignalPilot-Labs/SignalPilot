"""Tests for Trino connector auth method parsing and configuration."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "signalpilot", "gateway"))


class TestTrinoConnectionParsing:
    """Test Trino URL parsing for various formats."""

    def test_basic_url(self):
        from gateway.connectors.trino import TrinoConnector
        c = TrinoConnector()
        params = c._parse_connection("trino://admin@trino.example.com:8080/hive/default")
        assert params["host"] == "trino.example.com"
        assert params["port"] == 8080
        assert params["username"] == "admin"
        assert params["catalog"] == "hive"
        assert params["schema"] == "default"

    def test_https_url(self):
        from gateway.connectors.trino import TrinoConnector
        c = TrinoConnector()
        params = c._parse_connection("trino+https://user:pass@starburst.example.com:443/galaxy")
        assert params["host"] == "starburst.example.com"
        assert params["port"] == 443
        assert params["username"] == "user"
        assert params["password"] == "pass"
        assert params["catalog"] == "galaxy"
        assert params["https"] is True

    def test_url_with_auth_method(self):
        from gateway.connectors.trino import TrinoConnector
        c = TrinoConnector()
        params = c._parse_connection("trino+https://admin@host:443/cat?auth_method=jwt")
        assert params["auth_method"] == "jwt"
        assert params["https"] is True

    def test_fallback_host_only(self):
        from gateway.connectors.trino import TrinoConnector
        c = TrinoConnector()
        params = c._parse_connection("trino.local")
        assert params["host"] == "trino.local"
        assert params["port"] == 8080
        assert params["username"] == "trino"


class TestTrinoAuthMethods:
    """Test Trino connector auth method configuration."""

    def test_default_auth_is_none(self):
        from gateway.connectors.trino import TrinoConnector
        c = TrinoConnector()
        assert c._auth_method == "none"

    def test_jwt_credential_extras(self):
        from gateway.connectors.trino import TrinoConnector
        c = TrinoConnector()
        c.set_credential_extras({
            "auth_method": "jwt",
            "jwt_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.test",
        })
        assert c._auth_method == "jwt"
        assert c._jwt_token.startswith("eyJ")

    def test_certificate_credential_extras(self):
        from gateway.connectors.trino import TrinoConnector
        c = TrinoConnector()
        c.set_credential_extras({
            "auth_method": "certificate",
            "client_cert": "-----BEGIN CERTIFICATE-----\nMIIBtest\n-----END CERTIFICATE-----",
            "client_key": "-----BEGIN PRIVATE KEY-----\nMIIBtest\n-----END PRIVATE KEY-----",
        })
        assert c._auth_method == "certificate"
        assert "BEGIN CERTIFICATE" in c._client_cert
        assert "BEGIN PRIVATE KEY" in c._client_key

    def test_kerberos_credential_extras(self):
        from gateway.connectors.trino import TrinoConnector
        c = TrinoConnector()
        c.set_credential_extras({
            "auth_method": "kerberos",
            "kerberos_config": {"service_name": "trino", "delegate": True},
        })
        assert c._auth_method == "kerberos"
        assert c._kerberos_config["service_name"] == "trino"
        assert c._kerberos_config["delegate"] is True

    def test_query_timeout_from_extras(self):
        from gateway.connectors.trino import TrinoConnector
        c = TrinoConnector()
        c.set_credential_extras({"query_timeout": 60})
        assert c._request_timeout == 60

    def test_password_auth_inferred_from_url(self):
        from gateway.connectors.trino import TrinoConnector
        c = TrinoConnector()
        params = c._parse_connection("trino+https://user:mypass@host:443/cat")
        assert params["password"] == "mypass"
        assert params["https"] is True


class TestTrinoQuoting:
    """Test Trino identifier quoting for SQL injection prevention."""

    def test_simple_name(self):
        from gateway.connectors.trino import TrinoConnector
        assert TrinoConnector._quote_ident("my_table") == '"my_table"'

    def test_name_with_double_quote(self):
        from gateway.connectors.trino import TrinoConnector
        assert TrinoConnector._quote_ident('my"table') == '"my""table"'

    def test_empty_name(self):
        from gateway.connectors.trino import TrinoConnector
        assert TrinoConnector._quote_ident("") == '""'
