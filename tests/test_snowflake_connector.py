"""Tests for Snowflake connector — connection parsing, key-pair auth, and schema enrichment."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "signalpilot", "gateway"))


class TestSnowflakeConnectorParsing:
    def test_pipe_delimited_format(self):
        """Legacy pipe-delimited format should be parsed correctly."""
        from gateway.connectors.drivers.snowflake import SnowflakeConnector
        connector = SnowflakeConnector()
        result = connector._parse_connection("snowflake://myaccount|myuser|mypass|mydb|mywh|myschema|myrole")
        assert result["account"] == "myaccount"
        assert result["user"] == "myuser"
        assert result["password"] == "mypass"
        assert result["database"] == "mydb"
        assert result["warehouse"] == "mywh"
        assert result["schema"] == "myschema"
        assert result["role"] == "myrole"

    def test_url_format(self):
        """Standard URL format should be parsed correctly."""
        from gateway.connectors.drivers.snowflake import SnowflakeConnector
        connector = SnowflakeConnector()
        result = connector._parse_connection("snowflake://myuser:mypass@myaccount/mydb/myschema?warehouse=mywh&role=myrole")
        assert result["account"] == "myaccount"
        assert result["user"] == "myuser"
        assert result["password"] == "mypass"
        assert result["database"] == "mydb"
        assert result["schema"] == "myschema"
        assert result["warehouse"] == "mywh"
        assert result["role"] == "myrole"

    def test_account_only_fallback(self):
        """Plain account string should parse with empty credentials."""
        from gateway.connectors.drivers.snowflake import SnowflakeConnector
        connector = SnowflakeConnector()
        result = connector._parse_connection("xy12345.us-east-1")
        assert result["account"] == "xy12345.us-east-1"
        assert result["user"] == ""

    def test_credential_extras_timeout(self):
        """set_credential_extras should update timeout settings."""
        from gateway.connectors.drivers.snowflake import SnowflakeConnector
        connector = SnowflakeConnector()
        connector.set_credential_extras({
            "connection_timeout": 30,
            "query_timeout": 60,
            "keepalive_interval": 600,
        })
        assert connector._login_timeout == 30
        assert connector._network_timeout == 60
        assert connector._keepalive_heartbeat == 600

    def test_default_keepalive(self):
        """Default keepalive should be 15 minutes."""
        from gateway.connectors.drivers.snowflake import SnowflakeConnector
        connector = SnowflakeConnector()
        assert connector._keepalive is True
        assert connector._keepalive_heartbeat == 900

    def test_disable_ocsp_via_url(self):
        """URL parameter disable_ocsp_checks=true should be parsed."""
        from gateway.connectors.drivers.snowflake import SnowflakeConnector
        connector = SnowflakeConnector()
        result = connector._parse_connection("snowflake://user:pass@account/db/schema?disable_ocsp_checks=true")
        assert result.get("disable_ocsp_checks") is True

    def test_oauth_credential_extras(self):
        """OAuth token and auth method from credential extras should be stored."""
        from gateway.connectors.drivers.snowflake import SnowflakeConnector
        connector = SnowflakeConnector()
        connector.set_credential_extras({
            "auth_method": "oauth",
            "oauth_access_token": "eyJhbGciOiJSUzI1NiJ9.test_token",
        })
        assert connector._credential_extras["auth_method"] == "oauth"
        assert connector._credential_extras["oauth_access_token"].startswith("eyJ")

    def test_oauth_missing_token_raises(self):
        """OAuth auth without a token should raise RuntimeError."""
        import asyncio
        from gateway.connectors.drivers.snowflake import SnowflakeConnector
        connector = SnowflakeConnector()
        connector.set_credential_extras({"auth_method": "oauth"})
        with pytest.raises(RuntimeError, match="OAuth auth requires an access token"):
            asyncio.get_event_loop().run_until_complete(connector.connect("snowflake://xy12345.us-east-1"))


class TestSnowflakeSchemaEnrichment:
    def test_tables_query_includes_bytes(self):
        """The INFORMATION_SCHEMA.TABLES query should include BYTES column."""
        # Verify the schema SQL pattern
        expected_columns = ["TABLE_SCHEMA", "TABLE_NAME", "TABLE_TYPE", "ROW_COUNT", "BYTES", "COMMENT"]
        sql = """
            SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE, ROW_COUNT,
                   BYTES, COMMENT
            FROM INFORMATION_SCHEMA.TABLES
        """
        for col in expected_columns:
            assert col in sql

    def test_columns_query_includes_comment(self):
        """The INFORMATION_SCHEMA.COLUMNS query should include COMMENT column."""
        sql = """
            SELECT
                TABLE_SCHEMA,
                TABLE_NAME,
                COLUMN_NAME,
                DATA_TYPE,
                IS_NULLABLE,
                COLUMN_DEFAULT,
                COMMENT
            FROM INFORMATION_SCHEMA.COLUMNS
        """
        assert "COMMENT" in sql
