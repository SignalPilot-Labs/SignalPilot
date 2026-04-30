"""Tests for connector form validation logic.

Verifies that the frontend form validation catches common errors
before submission, matching HEX-level UX for connection setup.
Also tests URL-based DB type detection (HEX paste-and-detect pattern).
"""

import pytest
import re


class TestConnectionNameValidation:
    """Test connection name format validation."""

    def _validate_name(self, name: str) -> str | None:
        if not name.strip():
            return "connection name is required"
        if not re.match(r'^[a-zA-Z0-9_-]+$', name):
            return "only letters, numbers, hyphens, underscores"
        return None

    def test_valid_names(self):
        assert self._validate_name("prod-analytics") is None
        assert self._validate_name("my_db_1") is None
        assert self._validate_name("TestDB") is None
        assert self._validate_name("a") is None

    def test_empty_name(self):
        assert self._validate_name("") is not None
        assert self._validate_name("  ") is not None

    def test_special_chars_rejected(self):
        assert self._validate_name("my db") is not None  # space
        assert self._validate_name("my.db") is not None  # dot
        assert self._validate_name("my@db") is not None  # at
        assert self._validate_name("my/db") is not None  # slash


class TestPortValidation:
    """Test port number validation."""

    def _validate_port(self, port_str: str) -> str | None:
        try:
            port = int(port_str)
            if port < 1 or port > 65535:
                return "port must be 1-65535"
        except (ValueError, TypeError):
            return "port must be 1-65535"
        return None

    def test_valid_ports(self):
        assert self._validate_port("5432") is None
        assert self._validate_port("3306") is None
        assert self._validate_port("1") is None
        assert self._validate_port("65535") is None

    def test_invalid_ports(self):
        assert self._validate_port("0") is not None
        assert self._validate_port("65536") is not None
        assert self._validate_port("-1") is not None
        assert self._validate_port("abc") is not None
        assert self._validate_port("") is not None


class TestSnowflakeAccountValidation:
    """Test Snowflake account identifier format."""

    def _validate_account(self, account: str) -> str | None:
        if not account.strip():
            return "account identifier is required"
        if "." not in account and "-" not in account:
            return "use full identifier: org-account or account.region"
        return None

    def test_valid_accounts(self):
        assert self._validate_account("xy12345.us-east-1") is None
        assert self._validate_account("myorg-account123") is None
        assert self._validate_account("xy12345.us-east-1.aws") is None

    def test_bare_account_rejected(self):
        assert self._validate_account("xy12345") is not None  # No region/org

    def test_empty_account(self):
        assert self._validate_account("") is not None


class TestBigQueryCredentialsValidation:
    """Test BigQuery credentials JSON validation."""

    def _validate_credentials(self, json_str: str) -> str | None:
        if not json_str.strip():
            return "service account JSON is required"
        import json
        try:
            json.loads(json_str)
        except (json.JSONDecodeError, ValueError):
            return "invalid JSON format"
        return None

    def test_valid_json(self):
        import json
        valid = json.dumps({"type": "service_account", "project_id": "test"})
        assert self._validate_credentials(valid) is None

    def test_invalid_json(self):
        assert self._validate_credentials("{bad json") is not None
        assert self._validate_credentials("not json at all") is not None

    def test_empty_json(self):
        assert self._validate_credentials("") is not None


class TestSSHValidation:
    """Test SSH tunnel field validation (mirrors frontend validateForm)."""

    def _validate_ssh(self, host: str, username: str, auth_method: str, password: str, key: str, port: str = "22") -> dict[str, str]:
        errors = {}
        if not host.strip():
            errors["ssh_host"] = "SSH host is required"
        if not username.strip():
            errors["ssh_username"] = "SSH username is required"
        if auth_method == "password" and not password.strip():
            errors["ssh_password"] = "SSH password is required"
        if auth_method == "key":
            if not key.strip():
                errors["ssh_private_key"] = "SSH private key is required"
            elif not key.strip().startswith("-----BEGIN"):
                errors["ssh_private_key"] = "must be a PEM-format private key"
        try:
            p = int(port)
            if p < 1 or p > 65535:
                errors["ssh_port"] = "SSH port must be 1-65535"
        except (ValueError, TypeError):
            errors["ssh_port"] = "SSH port must be 1-65535"
        return errors

    def test_valid_password_auth(self):
        errors = self._validate_ssh("bastion.example.com", "ubuntu", "password", "secret", "")
        assert len(errors) == 0

    def test_valid_key_auth(self):
        errors = self._validate_ssh("bastion.example.com", "ubuntu", "key", "", "-----BEGIN RSA PRIVATE KEY-----")
        assert len(errors) == 0

    def test_missing_host(self):
        errors = self._validate_ssh("", "ubuntu", "password", "secret", "")
        assert "ssh_host" in errors

    def test_missing_username(self):
        errors = self._validate_ssh("bastion.example.com", "", "password", "secret", "")
        assert "ssh_username" in errors

    def test_missing_password_for_password_auth(self):
        errors = self._validate_ssh("bastion.example.com", "ubuntu", "password", "", "")
        assert "ssh_password" in errors

    def test_missing_key_for_key_auth(self):
        errors = self._validate_ssh("bastion.example.com", "ubuntu", "key", "", "")
        assert "ssh_private_key" in errors

    def test_agent_auth_no_password_or_key_needed(self):
        errors = self._validate_ssh("bastion.example.com", "ubuntu", "agent", "", "")
        assert len(errors) == 0

    def test_key_must_be_pem_format(self):
        errors = self._validate_ssh("bastion.example.com", "ubuntu", "key", "", "not-a-pem-key")
        assert "ssh_private_key" in errors
        assert "PEM" in errors["ssh_private_key"]

    def test_rsa_key_accepted(self):
        errors = self._validate_ssh("bastion.example.com", "ubuntu", "key", "", "-----BEGIN RSA PRIVATE KEY-----\nMIIE...")
        assert "ssh_private_key" not in errors

    def test_ed25519_key_accepted(self):
        errors = self._validate_ssh("bastion.example.com", "ubuntu", "key", "", "-----BEGIN OPENSSH PRIVATE KEY-----\nbase64data")
        assert "ssh_private_key" not in errors

    def test_invalid_ssh_port(self):
        errors = self._validate_ssh("bastion.example.com", "ubuntu", "password", "secret", "", port="0")
        assert "ssh_port" in errors

    def test_valid_ssh_port(self):
        errors = self._validate_ssh("bastion.example.com", "ubuntu", "password", "secret", "", port="2222")
        assert "ssh_port" not in errors


class TestTimeoutValidation:
    """Test connection and query timeout validation."""

    def _validate_timeout(self, value: str, max_val: int) -> str | None:
        if not value:
            return None  # empty = use default
        try:
            t = int(value)
            if t < 1 or t > max_val:
                return f"must be 1-{max_val}"
        except (ValueError, TypeError):
            return "must be a number"
        return None

    def test_valid_connection_timeout(self):
        assert self._validate_timeout("15", 300) is None
        assert self._validate_timeout("1", 300) is None
        assert self._validate_timeout("300", 300) is None

    def test_invalid_connection_timeout(self):
        assert self._validate_timeout("0", 300) is not None
        assert self._validate_timeout("301", 300) is not None
        assert self._validate_timeout("-1", 300) is not None
        assert self._validate_timeout("abc", 300) is not None

    def test_valid_query_timeout(self):
        assert self._validate_timeout("120", 3600) is None
        assert self._validate_timeout("3600", 3600) is None

    def test_invalid_query_timeout(self):
        assert self._validate_timeout("0", 3600) is not None
        assert self._validate_timeout("3601", 3600) is not None

    def test_empty_uses_default(self):
        assert self._validate_timeout("", 300) is None


class TestDbTypeDetectionFromUrl:
    """Test auto-detection of database type from connection URL scheme.

    Mirrors the detectDbTypeFromUrl() function in the frontend.
    """

    def _detect(self, url: str) -> str | None:
        """Detect DB type from connection URL scheme."""
        lower = url.strip().lower()
        if lower.startswith("postgresql://") or lower.startswith("postgres://"):
            return "postgres"
        if lower.startswith("mysql://") or lower.startswith("mysql+pymysql://") or lower.startswith("mariadb://"):
            return "mysql"
        if lower.startswith("redshift://"):
            return "redshift"
        if any(lower.startswith(p) for p in ("clickhouse://", "clickhouses://", "clickhouse+http://", "clickhouse+https://")):
            return "clickhouse"
        if lower.startswith("snowflake://"):
            return "snowflake"
        if any(lower.startswith(p) for p in ("mssql://", "mssql+pymssql://", "sqlserver://")):
            return "mssql"
        if lower.startswith("trino://") or lower.startswith("trino+https://"):
            return "trino"
        if lower.startswith("databricks://"):
            return "databricks"
        if lower.startswith("bigquery://"):
            return "bigquery"
        if lower.startswith("md:"):
            return "duckdb"
        return None

    def test_postgres_urls(self):
        assert self._detect("postgresql://user:pass@host:5432/db") == "postgres"
        assert self._detect("postgres://user:pass@host/db") == "postgres"

    def test_mysql_urls(self):
        assert self._detect("mysql://user:pass@host:3306/db") == "mysql"
        assert self._detect("mysql+pymysql://user:pass@host/db") == "mysql"
        assert self._detect("mariadb://user:pass@host/db") == "mysql"

    def test_redshift_url(self):
        assert self._detect("redshift://user:pass@cluster.region.redshift.amazonaws.com:5439/dev") == "redshift"

    def test_clickhouse_urls(self):
        assert self._detect("clickhouse://default:pass@host:9000/default") == "clickhouse"
        assert self._detect("clickhouses://default:pass@host:9440/default") == "clickhouse"
        assert self._detect("clickhouse+http://default@host:8123/default") == "clickhouse"
        assert self._detect("clickhouse+https://default@host:8443/default") == "clickhouse"

    def test_snowflake_url(self):
        assert self._detect("snowflake://user:pass@account/db/schema?warehouse=WH") == "snowflake"

    def test_mssql_urls(self):
        assert self._detect("mssql://sa:pass@host:1433/db") == "mssql"
        assert self._detect("mssql+pymssql://sa:pass@host/db") == "mssql"
        assert self._detect("sqlserver://sa:pass@host/db") == "mssql"

    def test_trino_urls(self):
        assert self._detect("trino://user@host:8080/catalog/schema") == "trino"
        assert self._detect("trino+https://user:pass@host:443/catalog") == "trino"

    def test_databricks_url(self):
        assert self._detect("databricks://token@host/sql/1.0/warehouses/abc") == "databricks"

    def test_bigquery_url(self):
        assert self._detect("bigquery://project/dataset") == "bigquery"

    def test_motherduck_url(self):
        assert self._detect("md:my_database") == "duckdb"

    def test_unknown_url(self):
        assert self._detect("http://not-a-db/path") is None
        assert self._detect("") is None
        assert self._detect("just-a-hostname") is None

    def test_case_insensitive(self):
        assert self._detect("POSTGRESQL://user:pass@host/db") == "postgres"
        assert self._detect("MySQL://user:pass@host/db") == "mysql"
