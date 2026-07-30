"""Tests for CookieAuthCsrfMiddleware.

Covers the cookie-only mutation decision table. The browser-driven counterpart
lives in signalpilot/web/e2e/cloud-cookie-csrf/ — these tests pin the server-side
logic so it cannot regress without a browser present.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gateway.http.middleware.csrf import CookieAuthCsrfMiddleware

ALLOWED_ORIGIN = "https://app.example.com"


def _make_client(enabled: bool = True, *, with_cookie: bool = False) -> TestClient:
    app = FastAPI()
    app.add_middleware(
        CookieAuthCsrfMiddleware,
        allowed_origins=[ALLOWED_ORIGIN],
        enabled=enabled,
    )

    @app.get("/api/thing")
    async def get_thing():
        return {"ok": "read"}

    @app.post("/api/thing")
    async def post_thing():
        return {"ok": "mutated"}

    @app.post("/api/github/webhook")
    async def webhook():
        return {"ok": "webhook"}

    client = TestClient(app)
    if with_cookie:
        client.cookies.set("__session", "sess_abc")
    return client


class TestSafeMethodsAndExemptions:
    def test_get_is_never_blocked(self):
        r = _make_client(with_cookie=True).get("/api/thing", headers={"origin": "https://evil.test"})
        assert r.status_code == 200

    def test_request_without_session_cookie_passes(self):
        """Bearer / API-key / anonymous callers are not this middleware's concern."""
        r = _make_client().post("/api/thing", headers={"origin": "https://evil.test"})
        assert r.status_code == 200

    def test_exempt_path_passes_even_cross_site(self):
        r = _make_client(with_cookie=True).post(
            "/api/github/webhook",
            headers={"origin": "https://evil.test", "sec-fetch-site": "cross-site"},
        )
        assert r.status_code == 200

    def test_disabled_middleware_passes_everything(self):
        r = _make_client(enabled=False, with_cookie=True).post(
            "/api/thing", headers={"sec-fetch-site": "cross-site"}
        )
        assert r.status_code == 200


class TestCookieOnlyMutations:
    def test_cross_site_cookie_mutation_is_403(self):
        r = _make_client(with_cookie=True).post(
            "/api/thing",
            headers={"origin": "https://evil.test", "sec-fetch-site": "cross-site"},
        )
        assert r.status_code == 403

    def test_no_origin_and_no_sec_fetch_site_is_403(self):
        """A non-browser cookie replay carries neither signal — fail closed."""
        r = _make_client(with_cookie=True).post("/api/thing")
        assert r.status_code == 403

    def test_same_origin_passes(self):
        r = _make_client(with_cookie=True).post("/api/thing", headers={"sec-fetch-site": "same-origin"})
        assert r.status_code == 200

    def test_allowlisted_origin_passes(self):
        r = _make_client(with_cookie=True).post("/api/thing", headers={"origin": ALLOWED_ORIGIN})
        assert r.status_code == 200

    def test_allowlisted_origin_with_trailing_slash_passes(self):
        r = _make_client(with_cookie=True).post("/api/thing", headers={"origin": ALLOWED_ORIGIN + "/"})
        assert r.status_code == 200

    def test_referer_fallback_passes_when_origin_absent(self):
        r = _make_client(with_cookie=True).post(
            "/api/thing", headers={"referer": f"{ALLOWED_ORIGIN}/some/page"}
        )
        assert r.status_code == 200

    def test_foreign_referer_is_403(self):
        r = _make_client(with_cookie=True).post("/api/thing", headers={"referer": "https://evil.test/x"})
        assert r.status_code == 403


class TestBearerTakesPrecedence:
    """A non-cookie credential is primary, matching auth.py semantics."""

    def test_bearer_alongside_cookie_passes(self):
        r = _make_client(with_cookie=True).post(
            "/api/thing",
            headers={"authorization": "Bearer tok", "sec-fetch-site": "cross-site"},
        )
        assert r.status_code == 200

    def test_api_key_header_alongside_cookie_passes(self):
        r = _make_client(with_cookie=True).post(
            "/api/thing",
            headers={"x-api-key": "sp_abc", "sec-fetch-site": "cross-site"},
        )
        assert r.status_code == 200


class TestSameSiteIsRejected:
    """A site ignores port and scheme.

    Accepting `same-site` would admit every subdomain of the registrable domain,
    any port, and plain http — so a subdomain takeover, a marketing-site XSS, or
    a stray http vhost would become a full CSRF bypass.
    """

    def test_same_site_is_not_sufficient(self):
        r = _make_client(with_cookie=True).post("/api/thing", headers={"sec-fetch-site": "same-site"})
        assert r.status_code == 403

    def test_same_site_token_absent_from_allowlist(self):
        assert "same-site" not in CookieAuthCsrfMiddleware.SAME_SITE_TOKENS

    def test_sibling_subdomain_origin_is_403(self):
        r = _make_client(with_cookie=True).post(
            "/api/thing",
            headers={"origin": "https://marketing.example.com", "sec-fetch-site": "same-site"},
        )
        assert r.status_code == 403

    def test_same_host_different_scheme_is_403(self):
        r = _make_client(with_cookie=True).post(
            "/api/thing",
            headers={"origin": "http://app.example.com", "sec-fetch-site": "same-site"},
        )
        assert r.status_code == 403

    def test_same_host_different_port_is_403(self):
        r = _make_client(with_cookie=True).post(
            "/api/thing",
            headers={"origin": "https://app.example.com:8443", "sec-fetch-site": "same-site"},
        )
        assert r.status_code == 403

    def test_same_origin_still_works_after_tightening(self):
        """Regression guard: tightening same-site must not lock out same-origin."""
        r = _make_client(with_cookie=True).post("/api/thing", headers={"sec-fetch-site": "same-origin"})
        assert r.status_code == 200


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_every_unsafe_method_is_guarded(method: str):
    app = FastAPI()
    app.add_middleware(CookieAuthCsrfMiddleware, allowed_origins=[ALLOWED_ORIGIN], enabled=True)

    @app.api_route("/api/thing", methods=["POST", "PUT", "PATCH", "DELETE"])
    async def thing():
        return {"ok": True}

    client = TestClient(app)
    client.cookies.set("__session", "sess_abc")
    r = client.request(method, "/api/thing", headers={"sec-fetch-site": "cross-site"})
    assert r.status_code == 403
