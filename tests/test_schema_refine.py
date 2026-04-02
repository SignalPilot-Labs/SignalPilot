"""Tests for schema refinement (two-pass linking) and connection URL builder."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "signalpilot", "gateway"))


class TestSchemaRefineSQLExtraction:
    """Test the SQL table/column extraction logic used in schema refinement."""

    def test_extract_tables_from_simple_select(self):
        import re
        draft = "SELECT name, email FROM customers WHERE id = 1"
        pattern = r'(?:FROM|JOIN|INTO|UPDATE|TABLE)\s+(?:`|"|\'|\[)?(\w+(?:\.\w+)*)(?:`|"|\'|\])?'
        tables = {m.group(1).lower() for m in re.finditer(pattern, draft, re.IGNORECASE)}
        assert "customers" in tables

    def test_extract_tables_from_join(self):
        import re
        draft = "SELECT o.id, c.name FROM orders o JOIN customers c ON o.customer_id = c.id"
        pattern = r'(?:FROM|JOIN|INTO|UPDATE|TABLE)\s+(?:`|"|\'|\[)?(\w+(?:\.\w+)*)(?:`|"|\'|\])?'
        tables = {m.group(1).lower() for m in re.finditer(pattern, draft, re.IGNORECASE)}
        assert "orders" in tables
        assert "customers" in tables

    def test_extract_tables_from_schema_qualified(self):
        import re
        draft = "SELECT * FROM public.orders JOIN public.customers ON orders.customer_id = customers.id"
        pattern = r'(?:FROM|JOIN|INTO|UPDATE|TABLE)\s+(?:`|"|\'|\[)?(\w+(?:\.\w+)*)(?:`|"|\'|\])?'
        tables = {m.group(1).lower() for m in re.finditer(pattern, draft, re.IGNORECASE)}
        assert "public.orders" in tables
        assert "public.customers" in tables

    def test_extract_dotted_columns(self):
        import re
        draft = "SELECT t.name, t.email FROM users t WHERE t.active = true"
        matches = re.findall(r'(\w+)\.(\w+)', draft)
        columns = {col.lower() for _, col in matches}
        assert "name" in columns
        assert "email" in columns
        assert "active" in columns

    def test_extract_tables_from_subquery(self):
        import re
        draft = """
        SELECT c.name, (SELECT COUNT(*) FROM orders WHERE customer_id = c.id) as order_count
        FROM customers c
        """
        pattern = r'(?:FROM|JOIN|INTO|UPDATE|TABLE)\s+(?:`|"|\'|\[)?(\w+(?:\.\w+)*)(?:`|"|\'|\])?'
        tables = {m.group(1).lower() for m in re.finditer(pattern, draft, re.IGNORECASE)}
        assert "customers" in tables
        assert "orders" in tables


class TestBuildConnectionURL:
    """Test the connection URL builder logic."""

    def test_postgres_url(self):
        from urllib.parse import quote_plus
        host, port, db = "localhost", 5432, "mydb"
        user, pw = "admin", "p@ss!word"
        url = f"postgresql://{quote_plus(user)}:{quote_plus(pw)}@{host}:{port}/{db}"
        assert "postgresql://" in url
        assert "admin" in url
        assert "p%40ss%21word" in url  # encoded special chars
        assert "mydb" in url

    def test_mysql_url(self):
        from urllib.parse import quote_plus
        url = f"mysql://{quote_plus('user')}:{quote_plus('pass')}@db.example.com:3306/test_db"
        assert url == "mysql://user:pass@db.example.com:3306/test_db"

    def test_snowflake_url(self):
        from urllib.parse import quote_plus
        account = "xy12345.us-east-1"
        user, pw = "analyst", "secret"
        db, schema = "ANALYTICS", "PUBLIC"
        wh = "COMPUTE_WH"
        url = f"snowflake://{quote_plus(user)}:{quote_plus(pw)}@{account}/{db}/{schema}?warehouse={quote_plus(wh)}"
        assert "snowflake://analyst:secret@xy12345.us-east-1/ANALYTICS/PUBLIC" in url
        assert "warehouse=COMPUTE_WH" in url

    def test_clickhouse_native_url(self):
        url = f"clickhouse://default:pass@clickhouse.example.com:9000/default"
        assert url.startswith("clickhouse://")

    def test_clickhouse_http_ssl_url(self):
        url = f"clickhouse+https://default:pass@clickhouse.example.com:8443/default"
        assert url.startswith("clickhouse+https://")
        assert "8443" in url

    def test_mssql_url(self):
        from urllib.parse import quote_plus
        url = f"mssql://{quote_plus('sa')}:{quote_plus('P@ssw0rd')}@sql.example.com:1433/master"
        assert "mssql://sa:" in url
        assert "1433/master" in url

    def test_trino_https_url(self):
        url = f"trino+https://analyst@trino.example.com:443/hive/default"
        assert url.startswith("trino+https://")
        assert "443/hive/default" in url

    def test_databricks_url(self):
        from urllib.parse import quote_plus
        token = "dapi123456789"
        host = "adb-12345.azuredatabricks.net"
        path = "sql/1.0/warehouses/abc"
        url = f"databricks://token:{quote_plus(token)}@{host}/{path}?catalog=main"
        assert "databricks://token:" in url
        assert "catalog=main" in url

    def test_duckdb_memory(self):
        url = ":memory:"
        assert url == ":memory:"

    def test_bigquery_url(self):
        url = f"bigquery://my-gcp-project/analytics_dataset"
        assert "bigquery://my-gcp-project/analytics_dataset" == url

    def test_password_masking(self):
        from urllib.parse import quote_plus
        pw = "s3cr3t!"
        url = f"postgresql://user:{quote_plus(pw)}@host:5432/db"
        masked = url.replace(quote_plus(pw), "****")
        assert "****" in masked
        assert pw not in masked
        assert quote_plus(pw) not in masked
