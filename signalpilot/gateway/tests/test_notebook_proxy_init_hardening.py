"""R11-S-4: _init route — Referrer-Policy header and IP rate limit.

Covers:
- Referrer-Policy: no-referrer is present on the 302 redirect response.
- Rate limit returns 429 after _INIT_RATE_MAX requests from the same (ip, session_id).
"""
from __future__ import annotations

import time
from collections import defaultdict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ─── Helpers ─────────────────────────────────────────────────────────────────


def _make_internal_session(
    session_id: str = "testsession123",
    access_token: str = "secret-token-abc",
) -> MagicMock:
    """Build a fake NotebookSessionInternal-like object."""
    sess = MagicMock()
    sess.session_id = session_id
    sess.user_id = "user-1"
    sess.org_id = "org-1"
    sess.access_token = access_token
    sess.status = "running"
    sess.pod_ip_internal = "10.42.0.5"
    return sess


def _build_init_client(monkeypatch, session_id: str, internal_session):
    """Return a TestClient for the _init route, with dependencies stubbed."""
    from fastapi import FastAPI
    from starlette.testclient import TestClient

    import gateway.notebook_proxy.routes as routes_mod
    import gateway.store.notebook_sessions as ns_mod
    from gateway.auth import user as user_mod

    # Stub DB: get_session_internal returns our fake session
    mock_factory = MagicMock()
    mock_db_session = AsyncMock()
    mock_db_session.__aenter__ = AsyncMock(return_value=mock_db_session)
    mock_db_session.__aexit__ = AsyncMock(return_value=False)
    mock_factory.return_value = mock_db_session

    monkeypatch.setattr(
        ns_mod, "get_session_internal", AsyncMock(return_value=internal_session)
    )

    # resolve_user_id raises so we fall through to ?token= path
    async def _raise_user(req):
        raise Exception("no auth")

    monkeypatch.setattr(user_mod, "resolve_user_id", _raise_user)

    app = FastAPI()
    app.add_api_route(
        "/notebook/{session_id}/_init",
        routes_mod.init_notebook,
        methods=["GET"],
    )

    with patch("gateway.db.engine.get_session_factory", return_value=mock_factory), \
         patch("gateway.notebook_proxy.routes.get_k8s_settings") as mock_k8s, \
         patch("gateway.notebook_proxy.routes.is_cloud_mode", return_value=False):
        mock_k8s.return_value.sp_session_jwt_ttl_seconds = 3600
        client = TestClient(app, raise_server_exceptions=False)
        yield client


# ─── Tests ───────────────────────────────────────────────────────────────────


class TestInitHardening:
    """R11-S-4: _init response includes Referrer-Policy and enforces IP rate limit."""

    def test_init_response_has_referrer_policy_no_referrer(self, monkeypatch) -> None:
        """Successful _init 302 response carries Referrer-Policy: no-referrer."""
        from gateway.notebook_proxy.init_token import issue_init_token

        session_id = "testinitsess1"
        access_token = "secret-tok-init"
        internal = _make_internal_session(session_id=session_id, access_token=access_token)

        # Reset rate limit state
        import gateway.notebook_proxy.routes as routes_mod
        monkeypatch.setattr(routes_mod, "_init_hits", defaultdict(list))

        # Mint a one-time handshake token (replaces ?token=access_token).
        init_token = issue_init_token(session_id, internal.user_id)

        for client in _build_init_client(monkeypatch, session_id, internal):
            resp = client.get(
                f"/notebook/{session_id}/_init?token={init_token}",
                follow_redirects=False,
            )

        assert resp.status_code == 302
        referrer_policy = resp.headers.get("referrer-policy", "")
        assert referrer_policy.lower() == "no-referrer"

    def test_init_rate_limit_429_after_threshold(self, monkeypatch) -> None:
        """After _INIT_RATE_MAX requests, the next request returns 429."""
        from gateway.notebook_proxy.init_token import issue_init_token
        from gateway.notebook_proxy.routes import _INIT_RATE_MAX

        session_id = "testinitsess2"
        access_token = "secret-tok-rate"
        internal = _make_internal_session(session_id=session_id, access_token=access_token)

        # Reset rate limit state
        import gateway.notebook_proxy.routes as routes_mod
        monkeypatch.setattr(routes_mod, "_init_hits", defaultdict(list))

        for client in _build_init_client(monkeypatch, session_id, internal):
            # Exhaust the rate limit — each request needs a fresh one-time token.
            for _ in range(_INIT_RATE_MAX):
                token = issue_init_token(session_id, internal.user_id)
                r = client.get(
                    f"/notebook/{session_id}/_init?token={token}",
                    follow_redirects=False,
                )
                assert r.status_code == 302, f"Expected 302, got {r.status_code}"

            # Next request should hit the rate limit (rate limiter fires before token check).
            extra_token = issue_init_token(session_id, internal.user_id)
            r = client.get(
                f"/notebook/{session_id}/_init?token={extra_token}",
                follow_redirects=False,
            )

        assert r.status_code == 429
