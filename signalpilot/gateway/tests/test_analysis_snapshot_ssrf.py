"""Tests for the analysis-delivery snapshot fetch gate.

The response body of a snapshot fetch is rendered into the report the reader
sees, so a URL outside the SignalPilot origin is a readable exfiltration
channel — not blind SSRF. These tests pin the refusal.
"""

from __future__ import annotations

import pytest

from gateway.notebooks.session_service import NotebookRuntime
from gateway.notion import analysis as notion_analysis


def _runtime() -> NotebookRuntime:
    return NotebookRuntime(
        session_id="runtime-session-1",
        internal_base_url="http://notebook.internal:2718/notebook/runtime-session-1",
        public_base_url="https://app.signalpilot.ai/notebook/runtime-session-1",
    )


class TestInternalUrlRefusals:
    _FOREIGN_URLS = [
        "http://169.254.169.254/latest/meta-data/iam/security-credentials/",
        "http://[fd00::1]/secrets",
        "http://10.1.2.3:8000/internal",
        "http://127.0.0.1:9200/_all/_search",
        "https://evil.test/collect",
        "file:///etc/passwd",
    ]

    @pytest.mark.parametrize("url", _FOREIGN_URLS)
    def test_absolute_foreign_url_refused(self, url: str) -> None:
        with pytest.raises(ValueError):
            notion_analysis._internal_signalpilot_url(url, _runtime())

    def test_runtime_none_refused(self) -> None:
        with pytest.raises(ValueError):
            notion_analysis._internal_signalpilot_url("http://169.254.169.254/latest/meta-data/", None)

    def test_runtime_none_refused_even_for_relative_url(self) -> None:
        with pytest.raises(ValueError):
            notion_analysis._internal_signalpilot_url("/api/notion-analysis/snapshot/1", None)

    def test_relative_url_still_maps_onto_internal_origin(self) -> None:
        resolved = notion_analysis._internal_signalpilot_url(
            "/api/notion-analysis/snapshot/snap-1", _runtime()
        )
        assert resolved.startswith("http://notebook.internal:2718/notebook/runtime-session-1")
        assert resolved.endswith("/api/notion-analysis/snapshot/snap-1")

    def test_internal_absolute_url_accepted(self) -> None:
        url = "http://notebook.internal:2718/notebook/runtime-session-1/api/snapshot/1"
        assert notion_analysis._internal_signalpilot_url(url, _runtime()) == url

    def test_public_absolute_url_mapped_to_internal(self) -> None:
        resolved = notion_analysis._internal_signalpilot_url(
            "https://app.signalpilot.ai/notebook/runtime-session-1/api/snapshot/1", _runtime()
        )
        assert resolved.startswith("http://notebook.internal:2718/notebook/runtime-session-1")

    def test_public_origin_on_blocked_address_refused_in_cloud(self, monkeypatch) -> None:
        """A public base pointed at a link-local address goes through the denylist."""
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        runtime = NotebookRuntime(
            session_id="runtime-session-1",
            internal_base_url="http://notebook.internal:2718/notebook/runtime-session-1",
            public_base_url="http://169.254.169.254/notebook/runtime-session-1",
        )
        with pytest.raises(ValueError):
            notion_analysis._internal_signalpilot_url(
                "http://169.254.169.254/notebook/runtime-session-1/api/snapshot/1", runtime
            )


class TestSnapshotFetcher:
    @pytest.mark.asyncio
    async def test_metadata_url_is_not_fetched(self, monkeypatch) -> None:
        requested: list[str] = []

        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def get(self, url):  # pragma: no cover — must never run
                requested.append(url)
                raise AssertionError("snapshot fetch should have been refused")

        monkeypatch.setattr(notion_analysis.httpx, "AsyncClient", lambda **kw: _Client())

        fetch = notion_analysis._snapshot_fetcher(_runtime())
        result = await fetch({"url": "http://169.254.169.254/latest/meta-data/"})

        assert requested == []
        assert isinstance(result, dict) and result.get("error")

    @pytest.mark.asyncio
    async def test_private_address_is_not_fetched(self, monkeypatch) -> None:
        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def get(self, url):  # pragma: no cover
                raise AssertionError("snapshot fetch should have been refused")

        monkeypatch.setattr(notion_analysis.httpx, "AsyncClient", lambda **kw: _Client())

        fetch = notion_analysis._snapshot_fetcher(_runtime())
        result = await fetch({"url": "http://10.0.0.7:9200/_search"})
        assert isinstance(result, dict) and result.get("error")

    @pytest.mark.asyncio
    async def test_runtime_none_is_not_fetched(self, monkeypatch) -> None:
        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def get(self, url):  # pragma: no cover
                raise AssertionError("snapshot fetch should have been refused")

        monkeypatch.setattr(notion_analysis.httpx, "AsyncClient", lambda **kw: _Client())

        fetch = notion_analysis._snapshot_fetcher(None)
        result = await fetch({"url": "/api/notion-analysis/snapshot/1"})
        assert isinstance(result, dict) and result.get("error")

    @pytest.mark.asyncio
    async def test_internal_snapshot_still_fetched(self, monkeypatch) -> None:
        requested: list[str] = []

        class _Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {"rows": [1, 2, 3]}

        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def get(self, url):
                requested.append(url)
                return _Response()

        monkeypatch.setattr(notion_analysis.httpx, "AsyncClient", lambda **kw: _Client())

        fetch = notion_analysis._snapshot_fetcher(_runtime())
        result = await fetch({"url": "/api/notion-analysis/snapshot/snap-1"})

        assert result == {"rows": [1, 2, 3]}
        assert requested and requested[0].startswith("http://notebook.internal:2718/")
