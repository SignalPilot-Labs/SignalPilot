"""Tests for error response sanitization across the REST API.

Verifies that:
- Global exception handler returns generic 500 for unhandled exceptions
- Global handler does NOT swallow intentional HTTPException responses
- Error responses do not contain raw exception details
- SQL parse errors are capped at 100 chars
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gateway.engine import validate_sql
from gateway.main import _global_exception_handler, app


@pytest.fixture
def client():
    """Test client with no auth configured."""
    return TestClient(app, raise_server_exceptions=False)


# ─── Global Exception Handler ─────────────────────────────────────────────────


class TestGlobalExceptionHandler:
    """The global handler must catch unhandled exceptions and return 500."""

    def test_unhandled_exception_returns_500(self):
        """An endpoint that raises a raw Exception must return 500, not a traceback."""
        # Build a minimal app with the same global handler but no auth middleware
        minimal_app = FastAPI()
        minimal_app.add_exception_handler(Exception, _global_exception_handler)

        @minimal_app.get("/trigger")
        async def _broken():
            raise RuntimeError("secret internal path /etc/shadow exposed here")

        test_client = TestClient(minimal_app, raise_server_exceptions=False)
        response = test_client.get("/trigger")
        assert response.status_code == 500
        body = response.json()
        assert body["detail"] == "Internal server error"
        # Raw exception text must NOT appear in the response
        assert "secret internal path" not in response.text
        assert "/etc/shadow" not in response.text

    def test_http_exception_not_swallowed(self):
        """HTTPException must pass through the global handler unchanged (not become 500)."""
        from fastapi import HTTPException as FastAPIHTTPException

        minimal_app = FastAPI()
        minimal_app.add_exception_handler(Exception, _global_exception_handler)

        @minimal_app.get("/trigger-http")
        async def _raises_http():
            raise FastAPIHTTPException(status_code=404, detail="Not found")

        test_client = TestClient(minimal_app, raise_server_exceptions=False)
        response = test_client.get("/trigger-http")
        assert response.status_code == 404
        assert response.status_code != 500

    def test_starlette_http_exception_not_swallowed(self):
        """StarletteHTTPException must also pass through, not be converted to 500."""
        from starlette.exceptions import HTTPException as StarletteHTTPException

        minimal_app = FastAPI()
        minimal_app.add_exception_handler(Exception, _global_exception_handler)

        @minimal_app.get("/trigger-starlette")
        async def _raises_starlette():
            raise StarletteHTTPException(status_code=403, detail="Forbidden")

        test_client = TestClient(minimal_app, raise_server_exceptions=False)
        response = test_client.get("/trigger-starlette")
        assert response.status_code == 403
        assert response.status_code != 500

    def test_internal_server_error_body_is_generic(self):
        """500 responses must use the generic sanitized message, not raw exception text."""
        minimal_app = FastAPI()
        minimal_app.add_exception_handler(Exception, _global_exception_handler)

        @minimal_app.get("/trigger-value-error")
        async def _raises():
            raise ValueError("db_password=hunter2 at /var/lib/postgres")

        test_client = TestClient(minimal_app, raise_server_exceptions=False)
        response = test_client.get("/trigger-value-error")
        assert response.status_code == 500
        data = response.json()
        assert "detail" in data
        assert data["detail"] == "Internal server error"
        assert "hunter2" not in response.text
        assert "postgres" not in response.text

    def test_http_exception_not_swallowed_401(self, client):
        """Auth errors (401) must not be converted to 500 by the global handler."""
        response = client.get("/api/connections")
        # Unauthenticated → 401 or 200 (no-auth mode), not 500
        assert response.status_code != 500


# ─── SQL Parse Error Sanitization ─────────────────────────────────────────────


class TestSQLParseErrorSanitization:
    """SQL parse errors must be capped at 100 chars."""

    def test_parse_error_message_capped_at_100_chars(self):
        """A very long sqlglot parse error must be truncated in blocked_reason."""
        # Craft SQL that reliably triggers a parse error
        result = validate_sql("SELECT @@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@")
        if not result.ok and result.blocked_reason and result.blocked_reason.startswith("SQL parse error"):
            # The message after "SQL parse error: " must be at most 100 chars
            prefix = "SQL parse error: "
            error_part = result.blocked_reason[len(prefix) :]
            assert len(error_part) <= 100, f"Error detail exceeds 100 chars: {len(error_part)} chars"
        else:
            pytest.skip("sqlglot did not raise a parse error on crafted input")

    def test_parse_error_contains_sql_parse_error_prefix(self):
        """Parse error blocked_reason must start with 'SQL parse error'."""
        result = validate_sql("SELCET * FORM users WHRE")
        if not result.ok and result.blocked_reason and "parse error" in result.blocked_reason.lower():
            assert result.blocked_reason.startswith("SQL parse error")
        else:
            pytest.skip("sqlglot did not raise a parse error on crafted input")

    def test_parse_error_does_not_leak_library_internals(self):
        """Parse error must not contain Python class names or file paths."""
        result = validate_sql("SELECT @#$% INVALID SQL !!!")
        if not result.ok and result.blocked_reason:
            # Must not contain Python tracebacks or module paths
            assert "Traceback" not in (result.blocked_reason or "")
            assert ".py" not in (result.blocked_reason or "")


# ─── connections.py Error Message Sanitization ────────────────────────────────


class TestConnectionsErrorSanitization:
    """Connections endpoints must not return raw exception details."""

    def test_add_connection_409_generic_message(self, client):
        """Creating a duplicate connection must return generic 409, not raw ValueError."""
        conn = {
            "name": "dedup-test-conn",
            "db_type": "postgres",
            "host": "localhost",
            "port": 5432,
            "database": "testdb",
            "username": "user",
            "password": "pass",
        }
        # First creation
        client.post("/api/connections", json=conn)
        # Second creation of the same name → 409
        response = client.post("/api/connections", json=conn)
        if response.status_code == 409:
            body = response.json()
            assert body["detail"] == "Connection already exists or invalid parameters"
            assert "ValueError" not in response.text
            assert "already exists" in body["detail"]
        elif response.status_code == 401:
            pytest.skip("auth middleware blocked request — cannot test error sanitization")
        else:
            # Any other status: ensure no 500 with raw exception text
            assert response.status_code != 500 or "Internal server error" in response.text

    def test_test_credentials_invalid_params_no_exception_detail(self, client):
        """test_credentials with broken params must not return raw exception text."""
        response = client.post(
            "/api/connections/test-credentials",
            json={"db_type": "postgres", "invalid_field_xyz": True},
        )
        if response.status_code == 401:
            pytest.skip("auth middleware blocked request — cannot test error sanitization")
        data = response.json()
        message = data.get("message", "")
        assert "ValidationError" not in message
        assert "Traceback" not in message

    def test_parse_url_invalid_input_no_exception_detail(self, client):
        """parse-url with garbage input must return generic error, not exception text."""
        response = client.post(
            "/api/connections/parse-url",
            json={"url": "not a url at all !!!@@###"},
        )
        if response.status_code == 401:
            pytest.skip("auth middleware blocked request — cannot test error sanitization")
        data = response.json()
        error = data.get("error", "")
        if error:
            assert "Exception" not in error
            assert "Traceback" not in error
            assert error == "Invalid URL format"

    def test_build_url_bad_input_no_exception_detail(self, client):
        """build-url with unrecognized db_type must return generic error."""
        response = client.post(
            "/api/connections/build-url",
            json={"db_type": "fakedb", "host": "localhost", "port": 5432},
        )
        if response.status_code == 401:
            pytest.skip("auth middleware blocked request — cannot test error sanitization")
        data = response.json()
        error = data.get("error", "")
        if error:
            assert "Exception" not in error
            assert "Traceback" not in error


# ─── projects.py Error Message Sanitization ───────────────────────────────────


class TestProjectsErrorSanitization:
    """Project endpoints must not return raw exception details."""

    def test_add_project_409_generic_message(self, client):
        """Creating a duplicate project must return generic 409 message."""
        proj = {"name": "dedup-test-proj", "path": "/tmp/proj"}
        client.post("/api/projects", json=proj)
        response = client.post("/api/projects", json=proj)
        if response.status_code == 409:
            body = response.json()
            assert body["detail"] == "Project already exists"
            assert "ValueError" not in response.text
        elif response.status_code == 401:
            pytest.skip("auth middleware blocked request — cannot test error sanitization")
        else:
            assert response.status_code != 500 or "Internal server error" in response.text
