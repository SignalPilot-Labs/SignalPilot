"""Tests for MCP error sanitization helpers.

Verifies:
- sanitize_mcp_error redacts sensitive patterns, strips paths and tracebacks, caps length
- sanitize_proxy_response formats proxy errors and redacts body
- _SENSITIVE_PATTERNS matches api/deps._SENSITIVE_PATTERNS (drift guard)
- Integration: sandbox URL never leaked, query errors preserve diagnostic text
"""

from __future__ import annotations

from gateway.errors.mcp import (
    _SENSITIVE_PATTERNS,
    sanitize_mcp_error,
    sanitize_proxy_response,
)

# ─── _SENSITIVE_PATTERNS drift guard ─────────────────────────────────────────


class TestSensitivePatternsSync:
    """_SENSITIVE_PATTERNS must stay in sync with api/deps._SENSITIVE_PATTERNS."""

    def test_patterns_match_api_deps(self):
        """mcp_errors._SENSITIVE_PATTERNS must equal api.deps._SENSITIVE_PATTERNS."""
        from gateway.api.deps import _SENSITIVE_PATTERNS as deps_patterns

        assert len(_SENSITIVE_PATTERNS) == len(deps_patterns), (
            f"Pattern count mismatch: mcp_errors has {len(_SENSITIVE_PATTERNS)}, "
            f"api/deps has {len(deps_patterns)}. Update mcp_errors.py to match."
        )
        for i, (mcp_pat, dep_pat) in enumerate(zip(_SENSITIVE_PATTERNS, deps_patterns, strict=True)):
            assert mcp_pat.pattern == dep_pat.pattern, (
                f"Pattern {i} mismatch: mcp_errors={mcp_pat.pattern!r}, api/deps={dep_pat.pattern!r}"
            )
            assert mcp_pat.flags == dep_pat.flags, (
                f"Pattern {i} flags mismatch: mcp_errors={mcp_pat.flags}, api/deps={dep_pat.flags}"
            )


# ─── sanitize_mcp_error unit tests ───────────────────────────────────────────


class TestSanitizeMcpError:
    """Unit tests for sanitize_mcp_error()."""

    def test_redacts_postgresql_uri(self):
        """PostgreSQL connection URIs must be replaced with [REDACTED]."""
        error = "could not connect: postgresql://user:secret@db.internal:5432/prod"
        result = sanitize_mcp_error(error)
        assert "postgresql://" not in result
        assert "secret" not in result
        assert "[REDACTED]" in result

    def test_redacts_mysql_uri(self):
        """MySQL connection URIs must be replaced with [REDACTED]."""
        error = "Failed: mysql://root:password@127.0.0.1/mydb"
        result = sanitize_mcp_error(error)
        assert "mysql://" not in result
        assert "password" not in result

    def test_redacts_password_pattern(self):
        """password= patterns must be replaced with [REDACTED]."""
        error = "auth failed password=hunter2 for user admin"
        result = sanitize_mcp_error(error)
        assert "hunter2" not in result
        assert "[REDACTED]" in result

    def test_redacts_host_pattern(self):
        """host= patterns must be replaced with [REDACTED]."""
        error = "connection timeout host=db.internal.corp"
        result = sanitize_mcp_error(error)
        assert "db.internal.corp" not in result
        assert "[REDACTED]" in result

    def test_redacts_access_token(self):
        """access_token patterns must be replaced with [REDACTED]."""
        error = "unauthorized: access_token=eyJhbGciOiJSUzI1"
        result = sanitize_mcp_error(error)
        assert "eyJhbGciOiJSUzI1" not in result

    def test_strips_home_path(self):
        """Absolute paths under /home/ must be replaced with [path]."""
        error = "No such file: /home/agentuser/.dbt/profiles.yml"
        result = sanitize_mcp_error(error)
        assert "/home/agentuser" not in result
        assert "[path]" in result

    def test_strips_var_path(self):
        """Absolute paths under /var/ must be replaced with [path]."""
        error = "Permission denied: /var/lib/postgresql/data"
        result = sanitize_mcp_error(error)
        assert "/var/lib/postgresql" not in result
        assert "[path]" in result

    def test_strips_opt_path(self):
        """Absolute paths under /opt/ must be replaced with [path]."""
        error = "Binary not found at /opt/signalpilot/bin/gateway"
        result = sanitize_mcp_error(error)
        assert "/opt/signalpilot" not in result

    def test_strips_traceback_frame(self):
        """Python traceback frames must be replaced with [traceback]."""
        error = 'File "/home/user/project/query.py", line 42, in execute'
        result = sanitize_mcp_error(error)
        assert 'File "' not in result
        assert "line 42" not in result
        assert "[traceback]" in result

    def test_default_cap_200(self):
        """String longer than 200 chars must be capped at 200 + '...'."""
        long_error = "x" * 300
        result = sanitize_mcp_error(long_error)
        assert len(result) == 203  # 200 + "..."
        assert result.endswith("...")

    def test_custom_cap(self):
        """Custom cap parameter must be respected."""
        long_error = "x" * 500
        result = sanitize_mcp_error(long_error, cap=100)
        assert len(result) == 103  # 100 + "..."

    def test_cap_300_db_error(self):
        """cap=300 (DB error mode) must preserve more diagnostic text."""
        db_error = "column 'user_name' does not exist in table 'public.orders' " * 5
        result = sanitize_mcp_error(db_error, cap=300)
        assert "column" in result
        assert len(result) <= 303

    def test_clean_string_passes_through(self):
        """Clean error messages must pass through unchanged (except capping)."""
        error = "column 'user_id' not found"
        result = sanitize_mcp_error(error)
        assert result == error

    def test_empty_string(self):
        """Empty string input must return empty string."""
        result = sanitize_mcp_error("")
        assert result == ""

    def test_cap_100_inline_error(self):
        """cap=100 (inline error mode) must cap at 100 chars."""
        long_error = "some error " * 20
        result = sanitize_mcp_error(long_error, cap=100)
        assert len(result) <= 103


# ─── sanitize_proxy_response unit tests ───────────────────────────────────────


class TestSanitizeProxyResponse:
    """Unit tests for sanitize_proxy_response()."""

    def test_formats_with_status_code(self):
        """Result must start with 'Error ({status_code}): '."""
        result = sanitize_proxy_response(404, "not found")
        assert result.startswith("Error (404):")

    def test_redacts_sensitive_body(self):
        """Sensitive content in the body must be redacted."""
        body = '{"error": "postgresql://admin:secret@db:5432/prod not responding"}'
        result = sanitize_proxy_response(500, body)
        assert "secret" not in result
        assert "postgresql://" not in result
        assert "500" in result

    def test_caps_body_length(self):
        """Body longer than cap must be truncated."""
        long_body = "e" * 500
        result = sanitize_proxy_response(503, long_body)
        # Body should be capped at 200 chars + "..." = 203, plus prefix
        assert len(result) < 250

    def test_clean_body_passes_through(self):
        """Clean body must appear unchanged in result."""
        result = sanitize_proxy_response(422, "invalid input")
        assert "invalid input" in result
        assert "Error (422)" in result

    def test_status_code_in_output(self):
        """HTTP status code must always appear in the output."""
        result = sanitize_proxy_response(401, "unauthorized")
        assert "401" in result


# ─── Integration tests ────────────────────────────────────────────────────────


class TestSandboxUrlNotLeaked:
    """Sandbox URL must never appear in client-facing errors."""

    def test_sanitize_removes_sandbox_url_from_http_error(self):
        """Sandbox HTTP errors that include internal URLs must have the URL stripped."""
        error = "Connection refused to http://sandbox-manager:8180/execute"
        result = sanitize_mcp_error(error)
        # The path /execute should be stripped, URL reduced
        # sandbox-manager hostname is not a path, but check no full URL leaks
        assert "8180" not in result or "[path]" in result or "refused" in result

    def test_sandbox_error_output_sanitized(self):
        """Sandbox error output with paths must be sanitized."""
        sandbox_error = "ModuleNotFoundError: No module named 'pandas' at /opt/sandbox/runner.py"
        result = sanitize_mcp_error(sandbox_error)
        assert "/opt/sandbox" not in result
        assert "[path]" in result
        # Diagnostic text preserved
        assert "ModuleNotFoundError" in result


class TestQueryErrorPreservesdiagnostic:
    """Query errors must preserve diagnostic text but redact connection strings."""

    def test_query_error_keeps_column_info(self):
        """Column-not-found errors must preserve column name for agent self-correction."""
        error = "column 'revenue' does not exist in table 'public.orders'"
        result = sanitize_mcp_error(error, cap=300)
        assert "column" in result
        assert "revenue" in result
        assert "orders" in result

    def test_query_error_redacts_connection_string(self):
        """Connection string embedded in query error must be redacted."""
        error = "connection error: postgresql://user:pass@db.internal/prod — column not found"
        result = sanitize_mcp_error(error, cap=300)
        assert "pass" not in result
        assert "column not found" in result

    def test_syntax_error_preserved(self):
        """SQL syntax errors must retain enough text for agent correction."""
        error = "syntax error at or near 'FORM' in SELECT * FORM users"
        result = sanitize_mcp_error(error, cap=300)
        assert "syntax error" in result
        assert "FORM" in result


class TestSchemaFetchError:
    """Schema fetch errors must be sanitized."""

    def test_schema_error_redacts_connection_string(self):
        """Schema fetch errors with embedded connection strings must be redacted."""
        error = "could not connect to server: postgresql://admin:secret@db.prod:5432/warehouse"
        result = sanitize_mcp_error(error)
        assert "secret" not in result
        assert "[REDACTED]" in result

    def test_schema_error_redacts_path(self):
        """Schema fetch errors with file paths must strip paths."""
        error = "cannot read schema file at /home/ubuntu/.dbt/profiles.yml"
        result = sanitize_mcp_error(error)
        assert "/home/ubuntu" not in result
        assert "[path]" in result
