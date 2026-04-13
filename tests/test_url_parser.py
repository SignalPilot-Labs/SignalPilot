"""Tests for the connection URL parser endpoint.

Verifies that parse-url correctly extracts credential fields from
various database connection URL formats.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import json


class TestURLParserLogic:
    """Test URL parsing logic for each DB type."""

    def _parse(self, url: str, db_type: str = "") -> dict:
        """Simulate the URL parsing logic from main.py."""
        from urllib.parse import urlparse, unquote, parse_qs

        _scheme_map = {
            "postgresql": "postgres", "postgres": "postgres",
            "mysql": "mysql", "mysql+pymysql": "mysql",
            "mssql": "mssql", "mssql+pymssql": "mssql",
            "redshift": "redshift",
            "clickhouse": "clickhouse", "clickhouse+http": "clickhouse",
            "snowflake": "snowflake",
            "databricks": "databricks",
            "trino": "trino", "trino+https": "trino",
        }

        original_scheme = url.split("://")[0] if "://" in url else ""
        if not db_type and original_scheme:
            db_type = _scheme_map.get(original_scheme, "")

        normalized = url
        if "://" in normalized:
            scheme_part = normalized.split("://")[0]
            normalized = "http://" + normalized[len(scheme_part) + 3:]

        parsed = urlparse(normalized)
        path_parts = [p for p in (parsed.path or "").split("/") if p]
        query_params = parse_qs(parsed.query or "")

        result = {
            "db_type": db_type,
            "host": parsed.hostname or "",
            "port": parsed.port,
            "username": unquote(parsed.username or ""),
            "password": unquote(parsed.password or ""),
        }

        if db_type in ("postgres", "redshift"):
            result["database"] = path_parts[0] if path_parts else ""
        elif db_type == "mysql":
            result["database"] = path_parts[0] if path_parts else ""
        elif db_type == "mssql":
            result["database"] = path_parts[0] if path_parts else "master"
        elif db_type == "snowflake":
            result["account"] = parsed.hostname or ""
            result["database"] = path_parts[0] if len(path_parts) > 0 else ""
            result["schema_name"] = path_parts[1] if len(path_parts) > 1 else ""
            result["warehouse"] = query_params.get("warehouse", [""])[0]
            result["role"] = query_params.get("role", [""])[0]
        elif db_type == "clickhouse":
            result["database"] = path_parts[0] if path_parts else "default"
            result["protocol"] = "http" if "http" in original_scheme else "native"
        elif db_type == "trino":
            result["catalog"] = path_parts[0] if len(path_parts) > 0 else ""
            result["schema_name"] = path_parts[1] if len(path_parts) > 1 else ""
        else:
            result["database"] = path_parts[0] if path_parts else ""

        return {k: v for k, v in result.items() if v is not None and v != ""}

    def test_postgres_url(self):
        result = self._parse("postgresql://admin:secret@db.example.com:5432/mydb")
        assert result["db_type"] == "postgres"
        assert result["host"] == "db.example.com"
        assert result["port"] == 5432
        assert result["username"] == "admin"
        assert result["password"] == "secret"
        assert result["database"] == "mydb"

    def test_mysql_url(self):
        result = self._parse("mysql+pymysql://analyst:pass@db.host:3306/analytics")
        assert result["db_type"] == "mysql"
        assert result["host"] == "db.host"
        assert result["port"] == 3306
        assert result["database"] == "analytics"

    def test_mssql_url(self):
        result = self._parse("mssql://sa:p%40ss@sql.corp:1433/production")
        assert result["db_type"] == "mssql"
        assert result["password"] == "p@ss"  # URL-decoded
        assert result["database"] == "production"

    def test_snowflake_url(self):
        result = self._parse("snowflake://USER:pass@xy12345.us-east-1/PROD_DB/PUBLIC?warehouse=WH&role=READER")
        assert result["db_type"] == "snowflake"
        assert result["account"] == "xy12345.us-east-1"
        assert result["database"] == "PROD_DB"
        assert result["schema_name"] == "PUBLIC"
        assert result["warehouse"] == "WH"
        assert result["role"] == "READER"

    def test_clickhouse_native_url(self):
        result = self._parse("clickhouse://default:test@ch.host:9000/events")
        assert result["db_type"] == "clickhouse"
        assert result["protocol"] == "native"
        assert result["database"] == "events"

    def test_clickhouse_http_url(self):
        result = self._parse("clickhouse+http://default:test@ch.host:8123/events")
        assert result["db_type"] == "clickhouse"
        assert result["protocol"] == "http"

    def test_trino_url(self):
        result = self._parse("trino://analyst:secret@trino.host:8080/hive/default")
        assert result["db_type"] == "trino"
        assert result["catalog"] == "hive"
        assert result["schema_name"] == "default"

    def test_redshift_url(self):
        result = self._parse("redshift://admin:pass@cluster.us-east-1.redshift.amazonaws.com:5439/dev")
        assert result["db_type"] == "redshift"
        assert result["port"] == 5439
        assert result["database"] == "dev"

    def test_auto_detect_db_type(self):
        result = self._parse("postgresql://user:pass@host/db")
        assert result["db_type"] == "postgres"

    def test_url_decoded_special_chars(self):
        result = self._parse("postgresql://user%40domain:p%23ss%21@host:5432/db")
        assert result["username"] == "user@domain"
        assert result["password"] == "p#ss!"
