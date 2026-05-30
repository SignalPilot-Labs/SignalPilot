"""R13: One-time handshake token for /notebook/{id}/_init.

Unit tests (1-8): target init_token.py directly.
Integration tests (9-15): TestClient against init_notebook route + handshake endpoint.
"""

from __future__ import annotations

import re
import time
from collections import defaultdict
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ─── Unit test helpers ────────────────────────────────────────────────────────


def _clear_store() -> None:
    """Empty the module-level _store between tests."""
    import gateway.notebook_proxy.init_token as tok_mod

    tok_mod._store.clear()


# ─── Integration test helpers ─────────────────────────────────────────────────

_SESSION_ID = "aabbccddeeff11"
_USER_ID = "user-hs-1"
_ORG_ID = "org-hs-1"
_ACCESS_TOKEN = "proxy-cookie-token-xyz"


def _make_internal_session(
    session_id: str = _SESSION_ID,
    user_id: str = _USER_ID,
    access_token: str = _ACCESS_TOKEN,
) -> MagicMock:
    sess = MagicMock()
    sess.session_id = session_id
    sess.user_id = user_id
    sess.org_id = _ORG_ID
    sess.access_token = access_token
    sess.status = "running"
    sess.pod_ip_internal = "10.42.0.9"
    return sess


def _build_init_client(monkeypatch, internal_session: Any):
    """Yield a TestClient for the _init route with all deps stubbed."""
    from fastapi import FastAPI
    from starlette.testclient import TestClient

    import gateway.notebook_proxy.routes as routes_mod
    import gateway.store.notebook_sessions as ns_mod
    from gateway.auth import user as user_mod

    mock_factory = MagicMock()
    mock_db_session = AsyncMock()
    mock_db_session.__aenter__ = AsyncMock(return_value=mock_db_session)
    mock_db_session.__aexit__ = AsyncMock(return_value=False)
    mock_factory.return_value = mock_db_session

    monkeypatch.setattr(ns_mod, "get_session_internal", AsyncMock(return_value=internal_session))

    async def _raise_user(req):
        raise Exception("no Clerk auth")

    monkeypatch.setattr(user_mod, "resolve_user_id", _raise_user)

    # Reset rate limit state to avoid test cross-contamination.
    monkeypatch.setattr(routes_mod, "_init_hits", defaultdict(list))

    app = FastAPI()
    app.add_api_route(
        "/notebook/{session_id}/_init",
        routes_mod.init_notebook,
        methods=["GET"],
    )

    with (
        patch("gateway.db.engine.get_session_factory", return_value=mock_factory),
        patch("gateway.notebook_proxy.routes.get_k8s_settings") as mock_k8s,
        patch("gateway.notebook_proxy.routes.is_cloud_mode", return_value=False),
    ):
        mock_k8s.return_value.sp_session_jwt_ttl_seconds = 3600
        client = TestClient(app, raise_server_exceptions=False)
        yield client


# ─── Unit tests ───────────────────────────────────────────────────────────────


class TestInitTokenUnit:
    """Unit tests for gateway.notebook_proxy.init_token."""

    def setup_method(self) -> None:
        _clear_store()

    def teardown_method(self) -> None:
        _clear_store()

    def test_issue_returns_43_char_urlsafe_string(self) -> None:
        """Test 1: issue_init_token returns 43-char URL-safe string."""
        from gateway.notebook_proxy.init_token import issue_init_token

        token = issue_init_token("sess-1", "user-1")
        assert len(token) == 43, f"Expected 43 chars, got {len(token)}"
        assert re.fullmatch(r"[A-Za-z0-9_-]{43}", token), f"Token has invalid chars: {token!r}"

    def test_consume_returns_true_for_fresh_token(self) -> None:
        """Test 2: consume_init_token returns True for freshly-issued matching token."""
        from gateway.notebook_proxy.init_token import consume_init_token, issue_init_token

        token = issue_init_token("sess-2", "user-2")
        assert consume_init_token(token, "sess-2", "user-2") is True

    def test_consume_returns_false_on_second_call(self) -> None:
        """Test 3: consume_init_token returns False on second call — single-use."""
        from gateway.notebook_proxy.init_token import consume_init_token, issue_init_token

        token = issue_init_token("sess-3", "user-3")
        assert consume_init_token(token, "sess-3", "user-3") is True
        assert consume_init_token(token, "sess-3", "user-3") is False

    def test_consume_returns_false_for_wrong_session_id(self) -> None:
        """Test 4: consume_init_token returns False for wrong session_id."""
        from gateway.notebook_proxy.init_token import consume_init_token, issue_init_token

        token = issue_init_token("sess-4", "user-4")
        assert consume_init_token(token, "wrong-session", "user-4") is False

    def test_consume_returns_false_for_wrong_user_id(self) -> None:
        """Test 5: consume_init_token returns False for wrong user_id."""
        from gateway.notebook_proxy.init_token import consume_init_token, issue_init_token

        token = issue_init_token("sess-5", "user-5")
        assert consume_init_token(token, "sess-5", "wrong-user") is False

    def test_consume_returns_false_after_ttl(self, monkeypatch) -> None:
        """Test 6: consume_init_token returns False after TTL (monkeypatched clock)."""
        import gateway.notebook_proxy.init_token as tok_mod

        clock = [1000.0]

        def _fake_monotonic() -> float:
            return clock[0]

        monkeypatch.setattr(tok_mod, "time", MagicMock(monotonic=_fake_monotonic))

        token = tok_mod.issue_init_token("sess-6", "user-6")

        # Advance past TTL.
        clock[0] = 1000.0 + tok_mod.INIT_TOKEN_TTL_S + 1.0
        assert tok_mod.consume_init_token(token, "sess-6", "user-6") is False

    def test_consume_returns_false_for_unknown_token(self) -> None:
        """Test 7: consume_init_token returns False for unknown token (empty store)."""
        from gateway.notebook_proxy.init_token import consume_init_token

        assert consume_init_token("not-a-real-token", "sess-7", "user-7") is False

    def test_hard_cap_eviction_oldest_entries_removed(self, monkeypatch) -> None:
        """Test 8: hard cap evicts oldest entries; newest survive.

        The clock stays frozen so no entries expire during bulk issuance.
        Each token is given a strictly increasing fake expiry (epoch_offset + i)
        to simulate "older issued first". This forces the hard-cap eviction path
        to select by expires_at order without the expiry sweep confounding it.
        """
        import gateway.notebook_proxy.init_token as tok_mod

        cap = tok_mod.INIT_TOKEN_MAX_ENTRIES

        # Freeze the observable clock so _evict_expired never removes anything.
        # We manually set expires_at by injecting into _store after issuing,
        # but we can also just freeze the clock at a base time and give each
        # token a unique offset > 0.
        base_time = 5_000_000.0
        call_counter = [0]

        def _fake_monotonic() -> float:
            # Returns base_time + small increment per call so tokens are
            # distinguishable by expiry but none are expired (base is far future).
            val = base_time + call_counter[0] * 0.001
            call_counter[0] += 1
            return val

        monkeypatch.setattr(tok_mod, "time", MagicMock(monotonic=_fake_monotonic))

        issued: list[str] = []
        for i in range(cap + 50):
            token = tok_mod.issue_init_token(f"sess-cap-{i}", "user-cap")
            issued.append(token)

        assert len(tok_mod._store) <= cap

        # The last batch of tokens (newest expires_at) must survive.
        newest = issued[-(cap // 2) :]
        for token in newest:
            assert token in tok_mod._store, "Newest token was evicted but should survive"

        # The very first tokens (smallest expires_at = oldest) should be evicted.
        oldest = issued[:10]
        for token in oldest:
            assert token not in tok_mod._store, "Oldest token should have been evicted"


# ─── Integration tests ────────────────────────────────────────────────────────


class TestInitHandshakeIntegration:
    """Integration tests: TestClient against init_notebook route."""

    def setup_method(self) -> None:
        _clear_store()

    def teardown_method(self) -> None:
        _clear_store()

    def test_issued_token_redeems_to_302(self, monkeypatch) -> None:
        """Test 9: Issue token then GET /_init?token=<issued> → 302 + cookie set."""
        from gateway.notebook_proxy.init_token import issue_init_token

        internal = _make_internal_session()
        token = issue_init_token(_SESSION_ID, _USER_ID)

        for client in _build_init_client(monkeypatch, internal):
            resp = client.get(
                f"/notebook/{_SESSION_ID}/_init?token={token}",
                follow_redirects=False,
            )

        assert resp.status_code == 302
        cookie_header = resp.headers.get("set-cookie", "")
        assert "sp_nb_" in cookie_header

    def test_second_redemption_returns_401(self, monkeypatch) -> None:
        """Test 10: Same token used twice → 401 on second attempt."""
        from gateway.notebook_proxy.init_token import issue_init_token

        internal = _make_internal_session()
        token = issue_init_token(_SESSION_ID, _USER_ID)

        for client in _build_init_client(monkeypatch, internal):
            first = client.get(
                f"/notebook/{_SESSION_ID}/_init?token={token}",
                follow_redirects=False,
            )
            second = client.get(
                f"/notebook/{_SESSION_ID}/_init?token={token}",
                follow_redirects=False,
            )

        assert first.status_code == 302
        assert second.status_code == 401

    def test_garbage_token_returns_401(self, monkeypatch) -> None:
        """Test 11: GET /_init?token=<garbage> → 401."""
        internal = _make_internal_session()

        for client in _build_init_client(monkeypatch, internal):
            resp = client.get(
                f"/notebook/{_SESSION_ID}/_init?token=totallygarbage",
                follow_redirects=False,
            )

        assert resp.status_code == 401

    def test_no_token_no_clerk_returns_401(self, monkeypatch) -> None:
        """Test 12: GET /_init with no ?token= and no Clerk auth → 401."""
        internal = _make_internal_session()

        for client in _build_init_client(monkeypatch, internal):
            resp = client.get(
                f"/notebook/{_SESSION_ID}/_init",
                follow_redirects=False,
            )

        assert resp.status_code == 401

    def test_legacy_access_token_returns_401(self, monkeypatch) -> None:
        """Test 13: Legacy ?token=<access_token> (old URL shape) → 401.

        Locks the closure of the old compare_digest path. A client that
        copy-pasted a pre-rollout URL shape must not succeed.
        """
        internal = _make_internal_session(access_token=_ACCESS_TOKEN)

        for client in _build_init_client(monkeypatch, internal):
            resp = client.get(
                f"/notebook/{_SESSION_ID}/_init?token={_ACCESS_TOKEN}",
                follow_redirects=False,
            )

        assert resp.status_code == 401

    def test_stale_db_row_notebook_url_has_no_token(self) -> None:
        """Test 14: Stale DB row read via _to_info produces a tokenless notebook_url.

        Proves the read path can never re-leak the access_token in a URL,
        regardless of how old or stale the row is.
        """
        from gateway.store.notebook_sessions import _to_info

        row = MagicMock()
        row.id = "stale-session-id-abc"
        row.org_id = "org-stale"
        row.user_id = "user-stale"
        row.project_id = None
        row.branch = "main"
        row.pod_name = "nb-stale"
        row.pod_ip = "10.0.0.1"  # non-None triggers notebook_url construction
        row.pod_ip_internal = "10.0.0.1"
        row.access_token = "stale-secret-xyz"
        row.status = "running"
        row.last_ping = time.time()
        row.created_at = time.time()

        info = _to_info(row)

        assert info.notebook_url is not None
        assert "?" not in (info.notebook_url or "")
        assert "token=" not in (info.notebook_url or "")
        assert "stale-secret-xyz" not in (info.notebook_url or "")
        assert info.notebook_url == f"/notebook/{row.id}/_init"

    def _build_handshake_client(self, monkeypatch, session_lookup_result):
        """Return a TestClient for the handshake endpoint with all deps stubbed."""
        from fastapi import FastAPI
        from starlette.testclient import TestClient

        import gateway.api.deps as deps_mod
        import gateway.api.notebook_sessions as api_mod
        import gateway.store.notebook_sessions as ns_mod
        from gateway.auth import resolve_org_id, resolve_user_id
        from gateway.store import Store

        monkeypatch.setattr(ns_mod, "get_session_by_id", AsyncMock(return_value=session_lookup_result))

        mock_store = MagicMock(spec=Store)
        mock_store.org_id = _ORG_ID
        mock_store.user_id = _USER_ID
        mock_store.session = AsyncMock()

        app = FastAPI()
        app.include_router(api_mod.router)

        async def _fake_user_id(request) -> str:
            return _USER_ID

        async def _fake_org_id(request, uid) -> str:
            return _ORG_ID

        async def _fake_store() -> Store:
            return mock_store

        app.dependency_overrides[resolve_user_id] = _fake_user_id
        app.dependency_overrides[resolve_org_id] = _fake_org_id
        app.dependency_overrides[deps_mod.get_store] = _fake_store

        return TestClient(app, raise_server_exceptions=False)

    def test_handshake_endpoint_authed(self, monkeypatch) -> None:
        """Test 15a: Authed POST /api/notebook-sessions/{id}/handshake → 200 with url."""
        session_info = MagicMock()
        session_info.id = _SESSION_ID
        session_info.user_id = _USER_ID
        session_info.org_id = _ORG_ID

        _clear_store()
        client = self._build_handshake_client(monkeypatch, session_info)
        resp = client.post(f"/api/notebook-sessions/{_SESSION_ID}/handshake")

        assert resp.status_code == 200
        data = resp.json()
        assert "url" in data
        url = data["url"]
        assert url.startswith(f"/notebook/{_SESSION_ID}/_init?token=")
        token_part = url.split("?token=")[1]
        assert len(token_part) == 43
        assert re.fullmatch(r"[A-Za-z0-9_-]{43}", token_part)

    def test_handshake_endpoint_token_redeemable(self, monkeypatch) -> None:
        """Test 15b: Token from handshake endpoint successfully redeems at /_init."""
        from gateway.notebook_proxy.init_token import consume_init_token, issue_init_token

        # Simulate what the handshake endpoint does.
        token = issue_init_token(_SESSION_ID, _USER_ID)
        internal = _make_internal_session()

        for client in _build_init_client(monkeypatch, internal):
            resp = client.get(
                f"/notebook/{_SESSION_ID}/_init?token={token}",
                follow_redirects=False,
            )

        assert resp.status_code == 302
        # After redemption, the token is consumed — second attempt must fail.
        assert consume_init_token(token, _SESSION_ID, _USER_ID) is False

    def test_handshake_endpoint_unknown_id_returns_404(self, monkeypatch) -> None:
        """Test 15c: Unknown session_id → 404 from handshake endpoint."""
        client = self._build_handshake_client(monkeypatch, None)
        resp = client.post("/api/notebook-sessions/nonexistent-id-abc/handshake")
        assert resp.status_code == 404
