"""Tests for diagnostics endpoint URL parsing.

Verifies that the regex-based scheme normalization correctly extracts
host and port from all supported connection string formats.
"""

import re
import pytest
from urllib.parse import urlparse


def _extract_host_port(conn_str: str, db_type: str) -> tuple[str, int]:
    """Replicate the diagnostics endpoint URL parsing logic."""
    normalized = re.sub(r'^[a-zA-Z][a-zA-Z0-9+.\-]*://', 'http://', conn_str)
    parsed = urlparse(normalized)
    host = parsed.hostname or ""
    _default_ports = {
        "postgres": 5432, "mysql": 3306, "mssql": 1433, "redshift": 5439,
        "snowflake": 443, "bigquery": 443, "clickhouse": 9000,
        "databricks": 443, "trino": 8080, "duckdb": 0, "sqlite": 0,
    }
    port = parsed.port or _default_ports.get(db_type, 0)
    return host, port


class TestPostgresURLs:
    def test_postgresql_scheme(self):
        h, p = _extract_host_port("postgresql://user:pass@db.example.com:5432/mydb", "postgres")
        assert h == "db.example.com"
        assert p == 5432

    def test_postgres_scheme(self):
        h, p = _extract_host_port("postgres://user:pass@db.example.com/mydb", "postgres")
        assert h == "db.example.com"
        assert p == 5432  # default

    def test_with_options(self):
        h, p = _extract_host_port("postgresql://user:pass@host:5433/db?sslmode=require", "postgres")
        assert h == "host"
        assert p == 5433


class TestMySQLURLs:
    def test_mysql_scheme(self):
        h, p = _extract_host_port("mysql://user:pass@mysql.example.com:3306/db", "mysql")
        assert h == "mysql.example.com"
        assert p == 3306

    def test_pymysql_scheme(self):
        h, p = _extract_host_port("mysql+pymysql://user:pass@host:3307/db", "mysql")
        assert h == "host"
        assert p == 3307

    def test_mariadb_scheme(self):
        h, p = _extract_host_port("mariadb://user:pass@host/db", "mysql")
        assert h == "host"
        assert p == 3306  # default


class TestMSSQLURLs:
    def test_mssql_scheme(self):
        h, p = _extract_host_port("mssql://sa:pass@host:1433/db", "mssql")
        assert h == "host"
        assert p == 1433

    def test_pymssql_scheme(self):
        h, p = _extract_host_port("mssql+pymssql://sa:pass@host:1434/db", "mssql")
        assert h == "host"
        assert p == 1434

    def test_sqlserver_scheme(self):
        h, p = _extract_host_port("sqlserver://sa:pass@host/db", "mssql")
        assert h == "host"
        assert p == 1433


class TestClickHouseURLs:
    def test_native_scheme(self):
        h, p = _extract_host_port("clickhouse://default:pass@ch.example.com:9000/default", "clickhouse")
        assert h == "ch.example.com"
        assert p == 9000

    def test_secure_scheme(self):
        h, p = _extract_host_port("clickhouses://default:pass@ch.example.com:9440/default", "clickhouse")
        assert h == "ch.example.com"
        assert p == 9440

    def test_http_scheme(self):
        h, p = _extract_host_port("clickhouse+http://default@host:8123/default", "clickhouse")
        assert h == "host"
        assert p == 8123

    def test_https_scheme(self):
        h, p = _extract_host_port("clickhouse+https://default@host:8443/default", "clickhouse")
        assert h == "host"
        assert p == 8443

    def test_no_port_uses_default(self):
        h, p = _extract_host_port("clickhouse://default@host/db", "clickhouse")
        assert h == "host"
        assert p == 9000


class TestSnowflakeURLs:
    def test_snowflake_url(self):
        h, p = _extract_host_port("snowflake://user:pass@account.snowflakecomputing.com/db", "snowflake")
        assert h == "account.snowflakecomputing.com"
        assert p == 443

    def test_with_warehouse(self):
        h, p = _extract_host_port("snowflake://user:pass@xy12345.us-east-1.aws/db?warehouse=WH", "snowflake")
        assert h == "xy12345.us-east-1.aws"
        assert p == 443


class TestRedshiftURLs:
    def test_redshift_url(self):
        h, p = _extract_host_port("redshift://user:pass@cluster.abc.us-east-1.redshift.amazonaws.com:5439/dev", "redshift")
        assert h == "cluster.abc.us-east-1.redshift.amazonaws.com"
        assert p == 5439


class TestTrinoURLs:
    def test_trino_url(self):
        h, p = _extract_host_port("trino://user@trino.example.com:8080/catalog/schema", "trino")
        assert h == "trino.example.com"
        assert p == 8080

    def test_trino_https(self):
        h, p = _extract_host_port("trino+https://user:pass@host:443/catalog", "trino")
        assert h == "host"
        assert p == 443


class TestDatabricksURLs:
    def test_databricks_url(self):
        h, p = _extract_host_port("databricks://token@adb-12345.azuredatabricks.net/sql/1.0/warehouses/abc", "databricks")
        assert h == "adb-12345.azuredatabricks.net"
        assert p == 443


class TestBigQueryURLs:
    def test_bigquery_url(self):
        h, p = _extract_host_port("bigquery://my-project/dataset", "bigquery")
        assert h == "my-project"
        assert p == 443


class TestEdgeCases:
    def test_ipv4_host(self):
        h, p = _extract_host_port("postgresql://user:pass@192.168.1.100:5432/db", "postgres")
        assert h == "192.168.1.100"
        assert p == 5432

    def test_localhost(self):
        h, p = _extract_host_port("mysql://root:pass@localhost:3306/test", "mysql")
        assert h == "localhost"
        assert p == 3306

    def test_password_with_special_chars(self):
        """Passwords with @ should not break host extraction."""
        h, p = _extract_host_port("postgresql://user:p%40ss@host:5432/db", "postgres")
        assert h == "host"
        assert p == 5432

    def test_empty_host(self):
        """Empty host should return empty string."""
        h, p = _extract_host_port("postgresql:///db", "postgres")
        assert h == ""
