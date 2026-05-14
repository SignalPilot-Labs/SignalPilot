"""Tests for the signalpilot-sp SDK."""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _reset_sp():
    import sp
    sp._gw = None
    yield
    sp._gw = None


# ---------------------------------------------------------------------------
# Mock gateway
# ---------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/connections":
            self._json_ok([{"name": "default"}, {"name": "analytics"}])
        elif self.path.startswith("/api/connections/") and self.path.endswith("/schema/overview"):
            self._json_ok({"table_count": 5, "total_rows": 10000})
        elif "/schema/explore-table" in self.path:
            self._json_ok({"columns": [{"name": "id", "type": "int"}, {"name": "email", "type": "varchar"}]})
        elif "/schema/sample-values" in self.path:
            self._json_ok({"values": ["active", "inactive", "pending"]})
        elif "/schema/join-paths" in self.path:
            self._json_ok({"paths": [{"from": "orders", "to": "users", "via": "user_id"}]})
        elif "/schema" in self.path:
            self._json_ok({"tables": [{"name": "users"}, {"name": "orders"}]})
        else:
            self.send_error(404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        if self.path == "/api/query":
            self._json_ok({"rows": [{"id": 1, "name": "test"}], "row_count": 1})
        elif self.path == "/api/query/explain":
            self._json_ok({"plan": "Seq Scan on users", "estimated_cost": 0.01})
        else:
            self.send_error(404)

    def _json_ok(self, data):
        payload = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args):
        pass


@pytest.fixture(scope="module")
def gateway_url():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    t = Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()


# ---------------------------------------------------------------------------
# _is_local_url
# ---------------------------------------------------------------------------

class TestIsLocalUrl:
    def test_localhost(self):
        from sp._client import _is_local_url
        assert _is_local_url("http://localhost:3300") is True

    def test_127(self):
        from sp._client import _is_local_url
        assert _is_local_url("http://127.0.0.1:3300") is True

    def test_ipv6_loopback(self):
        from sp._client import _is_local_url
        assert _is_local_url("http://[::1]:3300") is True

    def test_remote(self):
        from sp._client import _is_local_url
        assert _is_local_url("https://gateway.example.com") is False

    def test_lan_ip(self):
        from sp._client import _is_local_url
        assert _is_local_url("http://192.168.1.100:3300") is False


# ---------------------------------------------------------------------------
# sp.init()
# ---------------------------------------------------------------------------

class TestInit:
    def test_local_no_key(self):
        import sp
        sp.init(gateway_url="http://localhost:3300")
        assert sp._gw is not None

    def test_remote_requires_key(self):
        import sp
        with pytest.raises(ValueError, match="API key required"):
            sp.init(gateway_url="https://cloud.example.com")

    def test_remote_with_key(self):
        import sp
        sp.init(gateway_url="https://cloud.example.com", api_key="sp_test123")
        assert sp._gw is not None
        assert sp._gw._token == "sp_test123"

    def test_session_token_takes_precedence(self):
        import sp
        sp.init(gateway_url="http://localhost:3300", api_key="sp_key", session_token="tok_session")
        assert sp._gw._token == "tok_session"

    def test_env_vars(self):
        import sp
        with patch.dict(os.environ, {"SP_GATEWAY_URL": "http://localhost:9999", "SP_API_KEY": "sp_env"}):
            sp.init()
            assert sp._gw._url == "http://localhost:9999"
            assert sp._gw._token == "sp_env"

    def test_explicit_overrides_env(self):
        import sp
        with patch.dict(os.environ, {"SP_GATEWAY_URL": "http://localhost:9999"}):
            sp.init(gateway_url="http://localhost:8888")
            assert sp._gw._url == "http://localhost:8888"

    def test_default_url(self):
        import sp
        sp.init()
        assert sp._gw._url == "http://localhost:3300"


# ---------------------------------------------------------------------------
# Not initialized
# ---------------------------------------------------------------------------

class TestNotInitialized:
    def test_connect_raises(self):
        import sp
        with pytest.raises(RuntimeError, match="sp not initialized"):
            sp.connect("default")

    def test_connections_raises(self):
        import sp
        with pytest.raises(RuntimeError, match="sp not initialized"):
            sp.connections()


# ---------------------------------------------------------------------------
# connections()
# ---------------------------------------------------------------------------

class TestConnections:
    def test_list(self, gateway_url):
        import sp
        sp.init(gateway_url=gateway_url)
        names = sp.connections()
        assert names == ["default", "analytics"]


# ---------------------------------------------------------------------------
# Connection object
# ---------------------------------------------------------------------------

class TestConnection:
    def test_repr(self, gateway_url):
        import sp
        sp.init(gateway_url=gateway_url)
        db = sp.connect("default")
        assert repr(db) == "Connection('default')"

    def test_query(self, gateway_url):
        import sp
        sp.init(gateway_url=gateway_url)
        db = sp.connect("default")
        rows = db.query("SELECT 1")
        assert rows == [{"id": 1, "name": "test"}]

    def test_tables(self, gateway_url):
        import sp
        sp.init(gateway_url=gateway_url)
        db = sp.connect("default")
        tables = db.tables()
        assert tables == [{"name": "users"}, {"name": "orders"}]

    def test_describe(self, gateway_url):
        import sp
        sp.init(gateway_url=gateway_url)
        db = sp.connect("default")
        cols = db.describe("users")
        assert cols[0]["name"] == "id"
        assert cols[1]["name"] == "email"

    def test_explain(self, gateway_url):
        import sp
        sp.init(gateway_url=gateway_url)
        db = sp.connect("default")
        plan = db.explain("SELECT * FROM users")
        assert plan["plan"] == "Seq Scan on users"
        assert plan["estimated_cost"] == 0.01

    def test_sample_values(self, gateway_url):
        import sp
        sp.init(gateway_url=gateway_url)
        db = sp.connect("default")
        vals = db.sample_values("users", "status")
        assert vals == ["active", "inactive", "pending"]

    def test_join_path(self, gateway_url):
        import sp
        sp.init(gateway_url=gateway_url)
        db = sp.connect("default")
        paths = db.join_path("orders", "users")
        assert paths[0]["via"] == "user_id"

    def test_schema_overview(self, gateway_url):
        import sp
        sp.init(gateway_url=gateway_url)
        db = sp.connect("default")
        overview = db.schema_overview()
        assert overview["table_count"] == 5
