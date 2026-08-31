"""Tests for the notebook-files compat router (gateway/api/notebook_files.py).

The notebook editor's file plane served directly by the gateway — same JSON
shapes as the notebook-server file explorer, no sandbox involved. Hermetic:
moto stands in for S3, aiosqlite for Postgres (same pattern as
test_notebook_workspace_v2_scaffold.py).
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from gateway.db.models import GatewayBase

ORG = "test-org"
BUCKET = "sp-nbfiles-test"


@pytest.fixture
def storage():
    from moto import mock_aws

    with mock_aws():
        import boto3

        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        from gateway.workspace_store.objects import WorkspaceObjectStorage

        yield WorkspaceObjectStorage(bucket=BUCKET, client=client)


def _app(storage, factory, org: str = ORG):
    """A fresh app carrying the workspace + notebook-files surface, with the
    fixture identity wired through ordinary dependency overrides."""
    from fastapi import FastAPI

    import gateway.api.workspace_files as wf
    from gateway.api.deps import require_projects_feature
    from gateway.api.notebook_files import router as nb_files_router
    from gateway.api.workspace_files import router as files_router
    from gateway.api.workspace_projects import router as projects_router
    from gateway.auth import resolve_org_id, resolve_user_id
    from gateway.db.engine import get_db
    from gateway.security.scope_guard import _resolve_user_id as scope_resolve_user_id
    from gateway.workspace_store import WorkspaceStore

    app = FastAPI()
    app.include_router(projects_router)
    app.include_router(files_router)
    app.include_router(nb_files_router)

    async def _get_db():
        async with factory() as session:
            yield session

    async def _user() -> str:
        return "test-user"

    async def _org() -> str:
        return org

    async def _no_gate() -> None:
        return None

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[resolve_user_id] = _user
    app.dependency_overrides[resolve_org_id] = _org
    app.dependency_overrides[scope_resolve_user_id] = _user
    app.dependency_overrides[require_projects_feature] = _no_gate
    app.dependency_overrides[wf.get_workspace_store] = lambda: WorkspaceStore(storage)
    return app


@pytest.fixture
def api(storage):
    from fastapi.testclient import TestClient

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )

    async def _create_all():
        async with engine.begin() as conn:
            await conn.run_sync(GatewayBase.metadata.create_all)

    asyncio.run(_create_all())
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    app = _app(storage, factory)
    client = TestClient(app)
    client.app = app
    client.db_factory = factory  # foreign-org client reuses the same DB
    client.storage = storage
    yield client
    asyncio.run(engine.dispose())


def _project(api) -> str:
    response = api.post(
        "/api/workspace-projects",
        json={"name": f"proj-{uuid.uuid4().hex[:10]}", "display_name": "Test"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _put(api, project: str, path: str, content: bytes, branch: str = "main"):
    response = api.put(
        f"/api/workspace-projects/{project}/files/{path}?branch={branch}",
        content=content,
    )
    assert response.status_code == 200, response.text


def _nb(api, project: str, op: str, body: dict | None = None, branch: str = "main"):
    return api.post(
        f"/api/workspace-projects/{project}/nb-files/{op}?branch={branch}",
        json=body if body is not None else {},
    )


class TestListFiles:
    def test_one_level_listing_dirs_first_then_files(self, api):
        project = _project(api)
        _put(api, project, "b.txt", b"b")
        _put(api, project, "models/a.sql", b"select 1")
        _put(api, project, "a.py", b"x = 1")

        body = _nb(api, project, "list_files", {"path": ""}).json()
        assert body["root"] == ""
        assert [(f["name"], f["isDirectory"]) for f in body["files"]] == [
            ("models", True),
            ("a.py", False),
            ("b.txt", False),
        ]
        a_py = body["files"][1]
        assert a_py["path"] == "a.py"
        assert a_py["isSpFile"] is True
        assert a_py["lastModified"] > 0

    def test_recursive_listing_ships_full_nested_tree_in_one_response(self, api):
        """The RequestingTree contract: one recursive call re-hydrates the
        whole tree (children nested), no per-directory round trips."""
        project = _project(api)
        _put(api, project, "models/staging/stg_orders.sql", b"select 1")
        _put(api, project, "models/marts/orders.sql", b"select 2")
        _put(api, project, "notebooks/analysis.py", b"x = 1")
        _put(api, project, "README.md", b"# hi")

        body = _nb(api, project, "list_files", {"path": "", "recursive": True}).json()
        top = {f["name"]: f for f in body["files"]}
        assert set(top) == {"models", "notebooks", "README.md"}
        models = {f["name"]: f for f in top["models"]["children"]}
        assert set(models) == {"marts", "staging"}
        assert [c["path"] for c in models["staging"]["children"]] == [
            "models/staging/stg_orders.sql"
        ]
        assert top["notebooks"]["children"][0]["isSpFile"] is True

    def test_recursive_listing_of_a_subdirectory(self, api):
        project = _project(api)
        _put(api, project, "models/a.sql", b"1")
        _put(api, project, "models/deep/b.sql", b"2")
        _put(api, project, "other/c.sql", b"3")

        body = _nb(
            api, project, "list_files", {"path": "models", "recursive": True}
        ).json()
        assert body["root"] == "models"
        names = [f["name"] for f in body["files"]]
        assert names == ["deep", "a.sql"]
        assert body["files"][0]["children"][0]["path"] == "models/deep/b.sql"

    def test_gitkeep_materializes_empty_directory_and_ignore_names_hidden(self, api):
        project = _project(api)
        _put(api, project, "empty-dir/.gitkeep", b"")
        _put(api, project, "__pycache__/junk.pyc", b"x")
        _put(api, project, "keep.txt", b"k")

        body = _nb(api, project, "list_files", {"path": "", "recursive": True}).json()
        names = [f["name"] for f in body["files"]]
        assert names == ["empty-dir", "keep.txt"]
        assert body["files"][0]["isDirectory"] is True
        assert body["files"][0]["children"] == []

    def test_empty_branch_lists_no_files(self, api):
        project = _project(api)
        body = _nb(api, project, "list_files", {"path": ""}).json()
        assert body == {"files": [], "root": ""}


class TestFileDetailsAndUpdate:
    def test_text_file_details_roundtrip(self, api):
        project = _project(api)
        _put(api, project, "nb/analysis.py", "x = 'café'\n".encode())
        body = _nb(api, project, "file_details", {"path": "nb/analysis.py"}).json()
        assert body["contents"] == "x = 'café'\n"
        assert body["isBase64"] is False
        assert body["mimeType"].startswith("text/")
        assert body["file"]["path"] == "nb/analysis.py"
        assert body["file"]["isSpFile"] is True

    def test_binary_file_details_come_back_base64(self, api):
        project = _project(api)
        raw = bytes([0xFF, 0xFE, 0x00, 0x01, 0x80])
        _put(api, project, "data/blob.bin", raw)
        body = _nb(api, project, "file_details", {"path": "data/blob.bin"}).json()
        assert body["isBase64"] is True
        import base64 as b64

        assert b64.b64decode(body["contents"]) == raw

    def test_directory_details_have_no_contents(self, api):
        project = _project(api)
        _put(api, project, "models/a.sql", b"1")
        body = _nb(api, project, "file_details", {"path": "models"}).json()
        assert body["file"]["isDirectory"] is True
        assert body["contents"] is None

    def test_missing_file_is_404(self, api):
        project = _project(api)
        _put(api, project, "exists.txt", b"x")
        assert _nb(api, project, "file_details", {"path": "no/such.txt"}).status_code == 404

    def test_update_writes_through_as_new_revision(self, api):
        project = _project(api)
        _put(api, project, "a.py", b"v1")
        body = _nb(api, project, "update", {"path": "a.py", "contents": "v2"}).json()
        assert body["success"] is True
        assert body["info"]["path"] == "a.py"
        got = api.get(f"/api/workspace-projects/{project}/files/a.py")
        assert got.content == b"v2"


class TestCreate:
    def test_create_file_via_json(self, api):
        project = _project(api)
        _put(api, project, "anchor.txt", b"x")
        body = _nb(
            api, project, "create", {"path": "", "type": "file", "name": "new.sql"}
        ).json()
        assert body["success"] is True
        assert body["info"]["path"] == "new.sql"
        assert api.get(f"/api/workspace-projects/{project}/files/new.sql").content == b""

    def test_create_multipart_upload_carries_the_bytes(self, api):
        project = _project(api)
        _put(api, project, "anchor.txt", b"x")
        payload = b"col1,col2\n1,2\n"
        response = api.post(
            f"/api/workspace-projects/{project}/nb-files/create?branch=main",
            data={"path": "data", "type": "file", "name": "rows.csv"},
            files={"file": ("rows.csv", payload, "text/csv")},
        )
        body = response.json()
        assert body["success"] is True, body
        assert body["info"]["path"] == "data/rows.csv"
        got = api.get(f"/api/workspace-projects/{project}/files/data/rows.csv")
        assert got.content == payload

    def test_create_directory_commits_gitkeep_placeholder(self, api):
        project = _project(api)
        _put(api, project, "anchor.txt", b"x")
        body = _nb(
            api, project, "create", {"path": "", "type": "directory", "name": "newdir"}
        ).json()
        assert body["success"] is True
        assert body["info"]["isDirectory"] is True
        got = api.get(f"/api/workspace-projects/{project}/files/newdir/.gitkeep")
        assert got.status_code == 200

    def test_create_notebook_gets_default_template(self, api):
        project = _project(api)
        _put(api, project, "anchor.txt", b"x")
        body = _nb(
            api, project, "create", {"path": "", "type": "notebook", "name": "nb.py"}
        ).json()
        assert body["success"] is True
        content = api.get(f"/api/workspace-projects/{project}/files/nb.py").content
        assert b"import signalpilot as sp" in content
        assert b"app = sp.App()" in content

    def test_create_rejects_path_separators_in_name(self, api):
        project = _project(api)
        _put(api, project, "anchor.txt", b"x")
        body = _nb(
            api, project, "create", {"path": "", "type": "file", "name": "../evil.txt"}
        ).json()
        assert body["success"] is False
        assert "Invalid name" in body["message"]


class TestDeleteMoveCopySearch:
    def test_delete_single_file(self, api):
        project = _project(api)
        _put(api, project, "gone.txt", b"x")
        assert _nb(api, project, "delete", {"path": "gone.txt"}).json()["success"] is True
        assert api.get(f"/api/workspace-projects/{project}/files/gone.txt").status_code == 404

    def test_delete_directory_removes_whole_subtree_in_one_commit(self, api):
        project = _project(api)
        _put(api, project, "d/a.txt", b"1")
        _put(api, project, "d/nested/b.txt", b"2")
        _put(api, project, "keep.txt", b"3")
        assert _nb(api, project, "delete", {"path": "d"}).json()["success"] is True
        listing = _nb(api, project, "list_files", {"path": ""}).json()
        assert [f["name"] for f in listing["files"]] == ["keep.txt"]

    def test_delete_missing_path_reports_failure_not_500(self, api):
        project = _project(api)
        _put(api, project, "anchor.txt", b"x")
        body = _nb(api, project, "delete", {"path": "never.txt"}).json()
        assert body["success"] is False
        assert "not found" in body["message"].lower()

    def test_move_single_file(self, api):
        project = _project(api)
        _put(api, project, "old.py", b"content")
        body = _nb(
            api, project, "move", {"path": "old.py", "newPath": "new.py"}
        ).json()
        assert body["success"] is True
        assert body["info"]["path"] == "new.py"
        assert api.get(f"/api/workspace-projects/{project}/files/new.py").content == b"content"
        assert api.get(f"/api/workspace-projects/{project}/files/old.py").status_code == 404

    def test_move_directory_moves_every_child(self, api):
        project = _project(api)
        _put(api, project, "src/a.sql", b"1")
        _put(api, project, "src/deep/b.sql", b"2")
        body = _nb(api, project, "move", {"path": "src", "newPath": "dst"}).json()
        assert body["success"] is True
        assert body["info"]["isDirectory"] is True
        assert api.get(f"/api/workspace-projects/{project}/files/dst/deep/b.sql").content == b"2"
        assert api.get(f"/api/workspace-projects/{project}/files/src/a.sql").status_code == 404

    def test_copy_keeps_the_source(self, api):
        project = _project(api)
        _put(api, project, "orig.sql", b"select 1")
        body = _nb(
            api, project, "copy", {"path": "orig.sql", "newPath": "dupe.sql"}
        ).json()
        assert body["success"] is True
        assert api.get(f"/api/workspace-projects/{project}/files/orig.sql").status_code == 200
        assert api.get(f"/api/workspace-projects/{project}/files/dupe.sql").content == b"select 1"

    def test_search_matches_files_and_directories(self, api):
        project = _project(api)
        _put(api, project, "models/orders_mart.sql", b"1")
        _put(api, project, "orders/readme.md", b"2")
        _put(api, project, "unrelated.txt", b"3")
        body = _nb(api, project, "search", {"query": "orders"}).json()
        assert body["query"] == "orders"
        names = {f["name"] for f in body["files"]}
        assert names == {"orders", "orders_mart.sql"}
        assert body["totalFound"] == len(body["files"])
        # Exact-name match ranks first.
        assert body["files"][0]["name"] == "orders"

    def test_search_files_only_flag(self, api):
        project = _project(api)
        _put(api, project, "orders/orders.sql", b"1")
        body = _nb(
            api, project, "search", {"query": "orders", "includeDirectories": False}
        ).json()
        assert [f["name"] for f in body["files"]] == ["orders.sql"]
        assert all(not f["isDirectory"] for f in body["files"])


class TestBranchesAndSafety:
    def test_operations_respect_the_branch_parameter(self, api):
        project = _project(api)
        _put(api, project, "config.yml", b"env: main")
        _put(api, project, "config.yml", b"env: feature", branch="feature/x")
        main = _nb(api, project, "file_details", {"path": "config.yml"}).json()
        feature = _nb(
            api, project, "file_details", {"path": "config.yml"}, branch="feature/x"
        ).json()
        assert main["contents"] == "env: main"
        assert feature["contents"] == "env: feature"

    def test_traversal_outside_project_root_is_rejected(self, api):
        project = _project(api)
        _put(api, project, "anchor.txt", b"x")
        for op, body in (
            ("list_files", {"path": "../other"}),
            ("file_details", {"path": "../../etc/passwd"}),
            ("update", {"path": "nested/../../up.txt", "contents": "evil"}),
            ("delete", {"path": "../anchor.txt"}),
            ("move", {"path": "anchor.txt", "newPath": "../escape.txt"}),
        ):
            response = _nb(api, project, op, body)
            assert response.status_code == 400, f"{op}: {response.status_code}"
        # No revision beyond the anchor put was created.
        revisions = api.get(f"/api/workspace-projects/{project}/revisions").json()[
            "revisions"
        ]
        assert len(revisions) == 1

    def test_foreign_org_cannot_see_or_touch_the_project(self, api, storage):
        from fastapi.testclient import TestClient

        project = _project(api)
        _put(api, project, "secret.txt", b"the goods")

        foreign = TestClient(
            _app(storage, api.db_factory, org="other-org"),
            raise_server_exceptions=False,
        )
        listing = foreign.post(
            f"/api/workspace-projects/{project}/nb-files/list_files?branch=main",
            json={"path": ""},
        )
        # The project row is invisible to the foreign org; the org-agnostic
        # revision probe turns that into a 410 tombstone (same discipline as
        # workspace_files) — never file content.
        assert listing.status_code in (404, 410)
        assert "the goods" not in listing.text

        write = foreign.post(
            f"/api/workspace-projects/{project}/nb-files/update?branch=main",
            json={"path": "secret.txt", "contents": "clobbered"},
        )
        assert write.status_code in (404, 410)
        # And the file is untouched.
        assert (
            api.get(f"/api/workspace-projects/{project}/files/secret.txt").content
            == b"the goods"
        )

    def test_invalid_branch_name_is_rejected(self, api):
        project = _project(api)
        _put(api, project, "a.txt", b"x")
        response = _nb(api, project, "list_files", {"path": ""}, branch="..evil")
        assert response.status_code == 400
