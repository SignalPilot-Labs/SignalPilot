"""Tests for the _err() error formatting function."""

import httpx
import pytest

from signalpilot_mcp.server import _err


def _make_response(status_code: int, json_body: dict | None = None, text: str = "") -> httpx.Response:
    """Create a mock httpx.Response."""
    if json_body is not None:
        import json
        return httpx.Response(status_code, content=json.dumps(json_body).encode(), headers={"content-type": "application/json"})
    return httpx.Response(status_code, text=text)


def _make_http_error(status_code: int, json_body: dict | None = None, text: str = "") -> httpx.HTTPStatusError:
    """Create an HTTPStatusError with a mock response."""
    response = _make_response(status_code, json_body, text)
    request = httpx.Request("GET", "http://test:3300/api/test")
    return httpx.HTTPStatusError("error", request=request, response=response)


# --- Connection-level errors ---

def test_connect_error():
    err = httpx.ConnectError("Connection refused")
    result = _err(err)
    assert "Cannot reach server" in result
    assert "is it running?" in result


def test_connect_timeout():
    err = httpx.ConnectTimeout("Timed out connecting")
    result = _err(err)
    assert "Connection timed out" in result
    assert "down or unreachable" in result


def test_read_timeout():
    err = httpx.ReadTimeout("Read timed out")
    result = _err(err)
    assert "Request timed out" in result
    assert "too long" in result


def test_write_timeout():
    err = httpx.WriteTimeout("Write timed out")
    result = _err(err)
    assert "Request timed out" in result


def test_pool_timeout():
    err = httpx.PoolTimeout("Pool timed out")
    result = _err(err)
    assert "Request timed out" in result


# --- HTTP 401/403 ---

def test_http_401_with_detail():
    err = _make_http_error(401, {"detail": "Invalid API key"})
    result = _err(err)
    assert "Authentication failed" in result
    assert "SIGNALPILOT_API_KEY" in result
    assert "Invalid API key" in result


def test_http_403_no_detail():
    err = _make_http_error(403, {})
    result = _err(err)
    assert "Authentication failed" in result
    assert "SIGNALPILOT_API_KEY" in result


# --- HTTP 404 ---

def test_http_404_with_detail():
    err = _make_http_error(404, {"detail": "Connection 'prod' not found"})
    result = _err(err)
    assert "Not found" in result
    assert "Connection 'prod' not found" in result


def test_http_404_no_detail():
    err = _make_http_error(404, {})
    result = _err(err)
    assert "Not found" in result


# --- HTTP 409 (conflict) ---

def test_http_409_run_in_progress():
    err = _make_http_error(409, {"detail": "Run already in progress: abc-123"})
    result = _err(err)
    assert "Run already in progress: abc-123" in result
    # Should NOT have "HTTP 409" prefix — just surface the detail
    assert "HTTP 409" not in result


def test_http_409_cannot_pause():
    err = _make_http_error(409, {"detail": "Cannot pause run with status 'completed'"})
    result = _err(err)
    assert "Cannot pause run" in result


def test_http_409_no_detail():
    err = _make_http_error(409, {})
    result = _err(err)
    assert "Conflict" in result


# --- Other HTTP errors ---

def test_http_500_with_json():
    err = _make_http_error(500, {"detail": "Internal server error"})
    result = _err(err)
    assert "HTTP 500" in result
    assert "Internal server error" in result


def test_http_502_with_text():
    err = _make_http_error(502, text="Bad Gateway")
    result = _err(err)
    assert "HTTP 502" in result


def test_http_400_with_detail():
    err = _make_http_error(400, {"detail": "Query blocked: DDL not allowed"})
    result = _err(err)
    assert "HTTP 400" in result
    assert "Query blocked" in result


# --- Generic exceptions ---

def test_generic_exception():
    err = ValueError("something broke")
    result = _err(err)
    assert "Error: something broke" in result


def test_runtime_error():
    err = RuntimeError("unexpected")
    result = _err(err)
    assert "Error: unexpected" in result
