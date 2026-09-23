"""Chat checkouts are seeded with the gateway's compiled dbt manifest."""

from __future__ import annotations

import gzip
import json
from typing import Any

import httpx

from signalpilot._server.api.endpoints import (
    standalone_chat_dbt_manifest as seeding,
)

MANIFEST = {"nodes": {"model.p.m": {"resource_type": "model"}}}


class _Response:
    def __init__(
        self, status: int, body: Any = None, content: bytes = b""
    ) -> None:
        self.status_code = status
        self._body = body
        self.content = content

    def json(self) -> Any:
        return self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=None, response=None)  # type: ignore[arg-type]


def _fake_get(api: _Response, calls: list[str]):
    def get(url: str, **_: Any) -> _Response:
        calls.append(url)
        if url.endswith("/dbt-map/manifest"):
            return api
        return _Response(
            200, content=gzip.compress(json.dumps(MANIFEST).encode())
        )

    return get


def _seed(checkout):
    return seeding.seed_dbt_manifest(
        checkout,
        project_id="p",
        branch="main",
        gateway_url="http://gw",
        gateway_token="t",
    )


def test_writes_manifest_into_the_compiled_project_dir(tmp_path, monkeypatch):
    (tmp_path / "proj").mkdir()
    (tmp_path / "proj" / "dbt_project.yml").write_text("name: p")
    calls: list[str] = []
    api = _Response(
        200,
        {
            "manifest_url": "https://s3/m.gz",
            "dbt_project_dir": "proj",
            "revision": 4,
        },
    )
    monkeypatch.setattr(seeding.httpx, "get", _fake_get(api, calls))

    target = _seed(tmp_path)

    assert target == (tmp_path / "proj" / "target" / "manifest.json").resolve()
    assert json.loads(target.read_text()) == MANIFEST
    # A second run keeps the existing manifest and skips the download.
    calls.clear()
    assert _seed(tmp_path) == target
    assert calls == ["http://gw/api/workspace-projects/p/dbt-map/manifest"]


def test_root_project_without_a_recorded_dir(tmp_path, monkeypatch):
    (tmp_path / "dbt_project.yml").write_text("name: p")
    api = _Response(
        200, {"manifest_url": "https://s3/m.gz", "dbt_project_dir": None}
    )
    monkeypatch.setattr(seeding.httpx, "get", _fake_get(api, []))
    assert _seed(tmp_path) == (tmp_path / "target" / "manifest.json").resolve()


def test_no_compiled_manifest_is_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(seeding.httpx, "get", _fake_get(_Response(404), []))
    assert _seed(tmp_path) is None
    assert not (tmp_path / "target").exists()


def test_escaping_project_dir_is_refused(tmp_path, monkeypatch):
    api = _Response(
        200,
        {"manifest_url": "https://s3/m.gz", "dbt_project_dir": "../outside"},
    )
    monkeypatch.setattr(seeding.httpx, "get", _fake_get(api, []))
    assert _seed(tmp_path / "checkout") is None


def test_gateway_failure_never_raises(tmp_path, monkeypatch):
    def broken(*_: Any, **__: Any) -> None:
        raise httpx.ConnectError("down")

    monkeypatch.setattr(seeding.httpx, "get", broken)
    assert _seed(tmp_path) is None
