"""Hermetic tests for the S3-backed GatewayFileSystem (Runtime v2).

All gateway traffic is served by an httpx.MockTransport — no live services.
"""

from __future__ import annotations

import json

import httpx
import pytest

from signalpilot._server.files import workspace
from signalpilot._server.files.gateway_file_system import (
    GatewayConflictError,
    GatewayFileSystem,
)

PROJECT_ID = "1dbf5492-81e6-4683-835f-f1785c9cfe78"
BRANCH = "agent/feature-1"
BASE = f"/api/workspace-projects/{PROJECT_ID}"


def _entry(path: str, *, size: int = 10, mtime: float = 1000.0) -> dict:
    return {
        "path": path,
        "sha256": "0" * 64,
        "size": size,
        "mode": 0o644,
        "mtime": mtime,
    }


def _make_fs(handler) -> tuple[GatewayFileSystem, list[httpx.Request]]:
    requests: list[httpx.Request] = []

    def recording_handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    fs = GatewayFileSystem(
        gateway_url="http://gateway.test:3300",
        token="session-jwt-token",
        project_id=PROJECT_ID,
        branch=BRANCH,
        transport=httpx.MockTransport(recording_handler),
    )
    return fs, requests


# ── Reads pull on demand ─────────────────────────────────────────────────────


class TestReadOnDemand:
    def test_open_file_pulls_from_gateway_with_branch_param(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == f"{BASE}/revisions":
                return httpx.Response(200, json={"revisions": [{"revision": 4}]})
            assert request.method == "GET"
            assert request.url.path == f"{BASE}/files/models/stg_orders.sql"
            assert request.url.params["branch"] == BRANCH
            assert request.headers["Authorization"] == "Bearer session-jwt-token"
            return httpx.Response(200, content=b"select 1")

        fs, _ = _make_fs(handler)
        assert fs.open_file("models/stg_orders.sql") == "select 1"

    def test_open_file_missing_raises_file_not_found(self) -> None:
        fs, _ = _make_fs(lambda _req: httpx.Response(404, json={"detail": "File not found"}))
        with pytest.raises(FileNotFoundError, match="nope.sql"):
            fs.open_file("nope.sql")

    def test_get_details_returns_content_and_mime(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == f"{BASE}/revisions":
                return httpx.Response(200, json={"revisions": [{"revision": 4}]})
            return httpx.Response(200, content=b"answer = 1")

        fs, _ = _make_fs(handler)
        details = fs.get_details("notebooks/analysis.py")
        assert details.contents == "answer = 1"
        assert details.file.is_sp_file is True
        assert details.is_base64 is False

    def test_get_details_binary_falls_back_to_base64(self) -> None:
        fs, _ = _make_fs(lambda _req: httpx.Response(200, content=b"\x89PNG\x00\xff"))
        details = fs.get_details("assets/logo.png")
        assert details.is_base64 is True

    def test_list_files_builds_immediate_children(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == f"{BASE}/revisions":
                return httpx.Response(200, json={"revisions": [{"revision": 4}]})
            assert request.url.path == f"{BASE}/files:list"
            body = json.loads(request.content)
            assert body["branch"] == BRANCH
            return httpx.Response(
                200,
                json={
                    "revision": 4,
                    "files": [
                        _entry("dbt_project.yml"),
                        _entry("models/staging/stg_orders.sql"),
                        _entry("models/marts/orders.sql"),
                        _entry("notebooks/analysis.py"),
                    ],
                },
            )

        fs, _ = _make_fs(handler)
        infos = fs.list_files("")
        assert [(i.path, i.is_directory) for i in infos] == [
            ("models", True),
            ("notebooks", True),
            ("dbt_project.yml", False),
        ]

    def test_list_files_scopes_to_prefix_and_caches_the_manifest(self) -> None:
        """The manifest is fetched once per revision and prefix-filtered
        client-side; a second listing at the same head makes no list call."""
        list_calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == f"{BASE}/revisions":
                return httpx.Response(200, json={"revisions": [{"revision": 4}]})
            assert request.url.path == f"{BASE}/files:list"
            list_calls["n"] += 1
            return httpx.Response(
                200,
                json={
                    "revision": 4,
                    "files": [
                        _entry("models/staging/stg_orders.sql"),
                        _entry("models/schema.yml"),
                        _entry("README.md"),
                    ],
                },
            )

        fs, _ = _make_fs(handler)
        infos = fs.list_files("models")
        assert [(i.path, i.is_directory) for i in infos] == [
            ("models/staging", True),
            ("models/schema.yml", False),
        ]
        fs.list_files("models")  # same head revision → served from cache
        assert list_calls["n"] == 1

    def test_search_hits_files_search_with_branch(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == f"{BASE}/revisions":
                return httpx.Response(200, json={"revisions": [{"revision": 4}]})
            assert request.url.path == f"{BASE}/files:search"
            body = json.loads(request.content)
            assert body == {"branch": BRANCH, "query": "orders"}
            return httpx.Response(
                200,
                json={
                    "revision": 4,
                    "files": [_entry("models/marts/orders.sql")],
                },
            )

        fs, _ = _make_fs(handler)
        results = fs.search("orders")
        assert [r.path for r in results] == ["models/marts/orders.sql"]
        assert results[0].is_directory is False


# ── Writes go through as commits ─────────────────────────────────────────────


class TestWriteThrough:
    def test_update_file_is_a_put_with_branch_param(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == f"{BASE}/revisions":
                return httpx.Response(200, json={"revisions": [{"revision": 4}]})
            assert request.method == "PUT"
            assert request.url.path == f"{BASE}/files/models/new.sql"
            assert request.url.params["branch"] == BRANCH
            assert request.content == b"select 2"
            return httpx.Response(200, json={"revision": 5})

        fs, requests = _make_fs(handler)
        info = fs.update_file("models/new.sql", "select 2")
        assert info.path == "models/new.sql"
        assert len(requests) == 1

    def test_create_file_puts_contents(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == f"{BASE}/revisions":
                return httpx.Response(200, json={"revisions": [{"revision": 4}]})
            assert request.method == "PUT"
            assert request.url.path == f"{BASE}/files/models/created.sql"
            assert request.url.params["branch"] == BRANCH
            return httpx.Response(200, json={"revision": 6})

        fs, _ = _make_fs(handler)
        info = fs.create_file_or_directory(
            "models", "file", "created.sql", b"select 3"
        )
        assert info.path == "models/created.sql"

    def test_create_rejects_path_separators_in_name(self) -> None:
        fs, requests = _make_fs(lambda _req: httpx.Response(200))
        with pytest.raises(ValueError, match="path separators"):
            fs.create_file_or_directory("models", "file", "../evil.sql", b"")
        assert requests == []

    def test_delete_file_is_a_delete_with_branch_param(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == f"{BASE}/revisions":
                return httpx.Response(200, json={"revisions": [{"revision": 4}]})
            assert request.method == "DELETE"
            assert request.url.params["branch"] == BRANCH
            return httpx.Response(200, json={"revision": 7})

        fs, _ = _make_fs(handler)
        assert fs.delete_file_or_directory("models/old.sql") is True

    def test_copy_and_move_map_to_colon_endpoints(self) -> None:
        seen: list[tuple[str, dict]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == f"{BASE}/revisions":
                return httpx.Response(200, json={"revisions": [{"revision": 4}]})
            seen.append((request.url.path, json.loads(request.content)))
            return httpx.Response(200, json={"revision": 8})

        fs, _ = _make_fs(handler)
        fs.copy_file_or_directory("a.sql", "b.sql")
        fs.move_file_or_directory("b.sql", "c.sql")
        assert seen == [
            (
                f"{BASE}/files:copy",
                {"branch": BRANCH, "source": "a.sql", "destination": "b.sql"},
            ),
            (
                f"{BASE}/files:move",
                {"branch": BRANCH, "source": "b.sql", "destination": "c.sql"},
            ),
        ]

    def test_directory_delete_batches_and_409_surfaces_as_conflict(self) -> None:
        """A stale batch (another writer won the CAS race) is an error the
        caller sees — never a silent overwrite."""

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == f"{BASE}/revisions":
                return httpx.Response(200, json={"revisions": [{"revision": 4}]})
            if request.method == "DELETE":
                return httpx.Response(404, json={"detail": "File not found"})
            if request.url.path == f"{BASE}/files:list":
                return httpx.Response(
                    200,
                    json={"revision": 4, "files": [_entry("models/a.sql")]},
                )
            assert request.url.path == f"{BASE}/files:batch"
            body = json.loads(request.content)
            assert body["branch"] == BRANCH
            assert body["deletes"] == ["models/a.sql"]
            return httpx.Response(
                409,
                json={"detail": "Revision conflict: base 4, head 5"},
            )

        fs, _ = _make_fs(handler)
        with pytest.raises(GatewayConflictError, match="409"):
            fs.delete_file_or_directory("models")

    def test_put_failure_surfaces_as_error(self) -> None:
        fs, _ = _make_fs(
            lambda _req: httpx.Response(413, json={"detail": "too large"})
        )
        with pytest.raises(OSError, match="413"):
            fs.update_file("big.csv", "x")


# ── Factory selection (the SP_WORKSPACE_MODE=s3 seam) ────────────────────────


class TestFactorySelection:
    @pytest.fixture(autouse=True)
    def _reset_state(self, monkeypatch):
        from signalpilot._server.auth import session_token

        monkeypatch.setattr(workspace, "_current_branch", None)
        session_token._reset_for_test()
        yield
        session_token._reset_for_test()

    def test_s3_mode_selects_gateway_file_system(self, monkeypatch) -> None:
        monkeypatch.setenv("SP_WORKSPACE_MODE", "s3")
        monkeypatch.setenv("SP_PROJECT_ID", PROJECT_ID)
        monkeypatch.setenv("SP_BRANCH", BRANCH)
        monkeypatch.setenv("SP_GATEWAY_URL", "http://gateway.test:3300")
        monkeypatch.setenv("SP_SESSION_JWT", "jwt-abc")

        fs = workspace.create_file_system()
        assert isinstance(fs, GatewayFileSystem)
        assert fs.project_id == PROJECT_ID
        assert fs.branch == BRANCH

    def test_s3_mode_branch_override_wins(self, monkeypatch) -> None:
        monkeypatch.setenv("SP_WORKSPACE_MODE", "s3")
        monkeypatch.setenv("SP_PROJECT_ID", PROJECT_ID)
        monkeypatch.setenv("SP_BRANCH", "main")
        monkeypatch.setenv("SP_SESSION_JWT", "jwt-abc")

        fs = workspace.create_file_system(branch="agent/other")
        assert isinstance(fs, GatewayFileSystem)
        assert fs.branch == "agent/other"

    def test_s3_mode_without_project_id_fails_loudly(self, monkeypatch) -> None:
        monkeypatch.setenv("SP_WORKSPACE_MODE", "s3")
        monkeypatch.delenv("SP_PROJECT_ID", raising=False)
        with pytest.raises(RuntimeError, match="SP_PROJECT_ID"):
            workspace.create_file_system()

    def test_default_mode_selects_os_file_system(self, monkeypatch) -> None:
        from signalpilot._server.files.os_file_system import OSFileSystem

        monkeypatch.delenv("SP_WORKSPACE_MODE", raising=False)
        fs = workspace.create_file_system()
        assert isinstance(fs, OSFileSystem)

    def test_branch_switch_reconstructs_against_new_branch(
        self, monkeypatch
    ) -> None:
        monkeypatch.setenv("SP_WORKSPACE_MODE", "s3")
        monkeypatch.setenv("SP_PROJECT_ID", PROJECT_ID)
        monkeypatch.setenv("SP_BRANCH", "main")
        monkeypatch.setenv("SP_SESSION_JWT", "jwt-abc")

        workspace.set_current_branch("agent/next")
        fs = workspace.create_file_system()
        assert isinstance(fs, GatewayFileSystem)
        assert fs.branch == "agent/next"
