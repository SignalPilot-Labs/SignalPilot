"""GET /api/mcp/connectors/{id}/icon: provider favicon proxied through the SSRF guard."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from gateway.mcp_connectors import icons, ssrf

from .mcp_connectors_support import BASE, Harness, create_connector, harness

PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(32))
ICO = b"\x00\x00\x01\x00" + bytes(16)
HTML_WITH_LINK = (
    "<!doctype html><html><head><title>Vendor</title>"
    '<link rel="stylesheet" href="/app.css">'
    "<link rel='shortcut icon' href='/static/logo.ico?v=2'>"
    "</head><body>hi</body></html>"
)


@pytest.fixture(autouse=True)
def _fresh_icon_cache():
    icons.clear_cache()
    yield
    icons.clear_cache()


def _public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _resolve(host: str, port: int | None) -> list[str]:
        return ["93.184.216.34"]

    monkeypatch.setattr(ssrf, "resolve_public_addresses", _resolve)


def _mock_provider(monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]) -> list[str]:
    """Route icon fetches to ``handler`` while keeping the SSRF hooks; returns the URLs requested."""
    calls: list[str] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return handler(request)

    monkeypatch.setattr(
        icons, "make_client", lambda: ssrf.safe_async_client(timeout=1.0, transport=httpx.MockTransport(_handler))
    )
    return calls


def test_icon_happy_path_serves_favicon_with_private_cache_headers(harness: Harness, monkeypatch) -> None:
    _public_dns(monkeypatch)

    def provider(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/favicon.ico":
            return httpx.Response(200, content=PNG, headers={"Content-Type": "image/png"})
        return httpx.Response(404)

    calls = _mock_provider(monkeypatch, provider)
    created = create_connector(harness.as_user("user-a"))
    assert created["icon_url"] == f"/api/mcp/connectors/{created['id']}/icon"

    response = harness.client.get(created["icon_url"])
    assert response.status_code == 200, response.text
    assert response.content == PNG and response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "private, max-age=86400"
    assert calls == ["https://mcp.vendor.example/favicon.ico"]

    # Cached in-process per host: a second request makes no upstream call.
    assert harness.client.get(created["icon_url"]).status_code == 200 and len(calls) == 1
    # Personal connectors stay private: another member gets 404 without any fetch.
    assert harness.as_user("user-b").client.get(created["icon_url"]).status_code == 404 and len(calls) == 1


def test_icon_falls_back_to_link_rel_icon_from_small_html(harness: Harness, monkeypatch) -> None:
    _public_dns(monkeypatch)

    def provider(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/favicon.ico":
            return httpx.Response(404)
        if request.url.path == "/":
            return httpx.Response(200, text=HTML_WITH_LINK, headers={"Content-Type": "text/html; charset=utf-8"})
        if request.url.path == "/static/logo.ico" and request.url.query == b"v=2":
            return httpx.Response(200, content=ICO, headers={"Content-Type": "image/x-icon"})
        return httpx.Response(404)

    calls = _mock_provider(monkeypatch, provider)
    created = create_connector(harness.as_user("user-a"), url="https://mcp.vendor.example:8443/mcp")
    response = harness.client.get(created["icon_url"])
    assert response.status_code == 200 and response.content == ICO
    assert response.headers["content-type"] == "image/x-icon"
    assert calls == [
        "https://mcp.vendor.example:8443/favicon.ico",
        "https://mcp.vendor.example:8443/",
        "https://mcp.vendor.example:8443/static/logo.ico?v=2",
    ]


def test_icon_rejects_non_image_and_oversized_bodies(harness: Harness, monkeypatch) -> None:
    _public_dns(monkeypatch)

    def provider(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/favicon.ico":
            return httpx.Response(200, text="<html>not an icon</html>", headers={"Content-Type": "text/html"})
        if request.url.path == "/":
            return httpx.Response(200, text="<html><head></head></html>", headers={"Content-Type": "text/html"})
        return httpx.Response(404)

    calls = _mock_provider(monkeypatch, provider)
    created = create_connector(harness.as_user("user-a"))
    assert harness.client.get(created["icon_url"]).status_code == 404
    assert calls == ["https://mcp.vendor.example/favicon.ico", "https://mcp.vendor.example/"]
    # A miss is cached too (shorter TTL), so the provider is not hammered.
    assert harness.client.get(created["icon_url"]).status_code == 404 and len(calls) == 2

    icons.clear_cache()
    big = b"\x89PNG" + bytes(icons.ICON_MAX_BYTES + 1)
    _mock_provider(monkeypatch, lambda request: httpx.Response(200, content=big, headers={"Content-Type": "image/png"}))
    assert harness.client.get(created["icon_url"]).status_code == 404


def test_icon_blocked_host_and_stdio_connector_are_404_without_fetching(harness: Harness, monkeypatch) -> None:
    calls = _mock_provider(
        monkeypatch, lambda request: httpx.Response(200, content=PNG, headers={"Content-Type": "image/png"})
    )
    # The harness stubs DNS only for create; the icon fetch runs the real guard, which
    # rejects the private address before any request is made.
    private = create_connector(harness.as_user("user-a"), name="Internal", url="https://10.0.0.5/mcp")
    assert harness.client.get(private["icon_url"]).status_code == 404
    assert calls == []

    sandbox = create_connector(
        harness.as_user("admin-a", "admin"),
        scope="org",
        name="GitHub",
        url=None,
        command="npx -y @modelcontextprotocol/server-github",
    )
    assert sandbox["icon_url"] is None
    assert harness.client.get(f"{BASE}/connectors/{sandbox['id']}/icon").status_code == 404
    assert harness.client.get(f"{BASE}/connectors/does-not-exist/icon").status_code == 404
    assert calls == []


def test_icon_origin_and_link_discovery_helpers() -> None:
    assert icons.icon_origin("https://Mcp.Vendor.Example/mcp") == "https://mcp.vendor.example/"
    assert icons.icon_origin("https://mcp.vendor.example:443/mcp") == "https://mcp.vendor.example/"
    assert icons.icon_origin("https://mcp.vendor.example:8443/mcp") == "https://mcp.vendor.example:8443/"
    assert icons.icon_origin(None) is None and icons.icon_origin("not a url") is None
    page = '<link href="/a.png" rel="apple-touch-icon"><LINK REL=icon HREF=/b.svg><link rel="icon" href="/c.png">'
    assert icons.find_link_icon(page, "https://x.example/") == "https://x.example/b.svg"
    assert icons.find_link_icon('<link rel="stylesheet" href="/x.css">', "https://x.example/") is None
    assert icons.find_link_icon('<link rel="icon" href="//cdn.example/i.png">', "https://x.example/") == (
        "https://cdn.example/i.png"
    )
