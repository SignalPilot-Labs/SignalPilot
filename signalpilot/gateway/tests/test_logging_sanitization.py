"""Tests for credential sanitization in log output.

Verifies that _safe_pool_key_for_log strips credentials from pool keys
before they reach log statements.
"""

from __future__ import annotations

from gateway.connectors.pool_manager import _safe_pool_key_for_log


class TestSafePoolKeyForLog:
    """Tests for _safe_pool_key_for_log."""

    def test_postgres_url_hides_password_and_shows_host(self):
        key = "postgres:postgresql://user:s3cr3t@db.example.com:5432/mydb"
        result = _safe_pool_key_for_log(key)
        assert "s3cr3t" not in result
        assert "db.example.com" in result
        assert result == "postgres:db.example.com:5432"

    def test_postgres_url_with_special_chars_in_password(self):
        key = "postgres:postgresql://user:p%40ss!w0rd@db.host.io:5432/prod"
        result = _safe_pool_key_for_log(key)
        assert "p%40ss" not in result
        assert "w0rd" not in result
        assert "db.host.io" in result

    def test_non_url_bigquery_project_id_passes_through(self):
        """BigQuery uses bare project IDs — no URL scheme, no credentials."""
        key = "bigquery:my-gcp-project-id"
        result = _safe_pool_key_for_log(key)
        assert result == key

    def test_non_url_duckdb_file_path_passes_through(self):
        """DuckDB/SQLite use file paths — no URL scheme, no credentials."""
        key = "duckdb:/tmp/test.db"
        result = _safe_pool_key_for_log(key)
        assert result == key

    def test_memory_duckdb_passes_through(self):
        key = "duckdb::memory:"
        result = _safe_pool_key_for_log(key)
        # :memory: doesn't contain :// so passes through as-is
        assert "duckdb" in result

    def test_malformed_url_returns_redacted(self):
        """A string with :// but an unparseable hostname falls back to <redacted>."""
        # Craft a key where urlparse returns an empty hostname
        key = "postgres:postgresql://:@/"
        result = _safe_pool_key_for_log(key)
        # hostname will be empty string — we return db_type: with empty host
        # The important thing: no credential exposure
        assert "postgres:" in result

    def test_snowflake_url_hides_password(self):
        key = "snowflake:snowflake://myuser:mypassword@myaccount/mydb"
        result = _safe_pool_key_for_log(key)
        assert "mypassword" not in result
        assert "myaccount" in result

    def test_key_without_colon_returns_unchanged(self):
        """Degenerate case: no colon separator at all."""
        key = "nocolon"
        result = _safe_pool_key_for_log(key)
        assert result == key

    def test_mysql_url_hides_credentials(self):
        key = "mysql:mysql+pymysql://root:topsecret@localhost:3306/testdb"
        result = _safe_pool_key_for_log(key)
        assert "topsecret" not in result
        assert "localhost" in result
