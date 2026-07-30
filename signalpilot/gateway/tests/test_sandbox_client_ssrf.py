"""Tests that SandboxClient runs the BYOS base URL through the SSRF denylist.

Every request the client makes carries the sandbox shared secret, so a base URL
pointed at an internal address is both an SSRF primitive and a token leak.
"""

from __future__ import annotations

import pytest

from gateway.network.sandbox_client import SandboxClient

_BLOCKED_URLS = [
    "http://169.254.169.254",
    "http://127.0.0.1:8000",
    "http://[::1]:8000",
    "http://10.1.2.3:8000",
    "http://192.168.1.5:8000",
]


@pytest.fixture
def cloud_mode(monkeypatch):
    monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
    monkeypatch.setenv("SP_SANDBOX_TOKEN", "sandbox-token-under-test")
    monkeypatch.delenv("SP_ALLOW_PRIVATE_CONNECTIONS", raising=False)
    yield


class TestCloudModeDenylist:
    @pytest.mark.parametrize("url", _BLOCKED_URLS)
    def test_blocked_base_url_rejected(self, cloud_mode, url: str) -> None:
        with pytest.raises(ValueError):
            SandboxClient(base_url=url)

    def test_no_client_and_no_token_when_rejected(self, cloud_mode, monkeypatch) -> None:
        """Construction must fail before any httpx client holds the token."""
        built: list[dict] = []
        import httpx

        original = httpx.AsyncClient

        def _record(*args, **kwargs):
            built.append(kwargs)
            return original(*args, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", _record)

        with pytest.raises(ValueError):
            SandboxClient(base_url="http://169.254.169.254")

        assert built == []

    def test_bad_scheme_still_rejected(self, cloud_mode) -> None:
        with pytest.raises(ValueError):
            SandboxClient(base_url="file:///etc/passwd")

    def test_missing_hostname_still_rejected(self, cloud_mode) -> None:
        with pytest.raises(ValueError):
            SandboxClient(base_url="http:///files")


class TestLocalModeUnchanged:
    def test_localhost_allowed_in_local_mode(self, monkeypatch) -> None:
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "local")
        client = SandboxClient(base_url="http://localhost:8000")
        assert client.base_url == "http://localhost:8000"
