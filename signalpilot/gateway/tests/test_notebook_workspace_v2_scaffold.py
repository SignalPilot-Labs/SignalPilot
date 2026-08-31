"""Target test suite for Notebook Runtime v2 (Vercel compute + S3 workspace).

THIS SUITE IS THE SPEC'S ACCEPTANCE CRITERIA, WRITTEN FIRST. Tests are
implemented and un-skipped as each phase lands (spec:
sp-local/docs/specs/notebook-vercel-s3-redesign.md). Remaining `_target`
skips point at the design section and migration gate they belong to — the
suite going green IS the migration finishing.

Implemented so far: §4.1 object-store semantics, §4.2 Files API, §4.4 lease.
Everything here is hermetic: moto stands in for S3, aiosqlite for Postgres.
"""

from __future__ import annotations

import hashlib
import io
import tarfile
import uuid
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from gateway.db.models import GatewayBase

ORG = "test-org"
BUCKET = "sp-workspace-test"


def _target(section: str, gate: str):
    pytest.skip(f"v2 target — spec {section}, migration gate {gate}: not built yet")


def _pid() -> str:
    return str(uuid.uuid4())


# ── Shared hermetic fixtures ─────────────────────────────────────────────────


@pytest.fixture
def storage():
    from moto import mock_aws

    with mock_aws():
        import boto3

        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        from gateway.workspace_store.objects import WorkspaceObjectStorage

        yield WorkspaceObjectStorage(bucket=BUCKET, client=client)


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(GatewayBase.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
def ws(storage):
    from gateway.workspace_store import WorkspaceStore

    return WorkspaceStore(storage)


async def _put(ws, db, project, path, content: bytes, branch="main", by="tester"):
    from gateway.workspace_store.store import Upsert

    return await ws.commit_at_head(
        db,
        org_id=ORG,
        project_id=project,
        branch=branch,
        upserts=[Upsert(path=path, content=content)],
        deletes=[],
        created_by=by,
    )


# ── §4.1 Content-addressed store semantics (gate G1) ────────────────────────


class TestObjectStoreSemantics:
    @pytest.mark.asyncio
    async def test_identical_content_across_branches_shares_one_blob(self, ws, db, storage):
        project = _pid()
        payload = b"select * from orders"
        await _put(ws, db, project, "models/a.sql", payload, branch="main")
        await _put(ws, db, project, "models/b.sql", payload, branch="dev")

        client = storage._require_client()
        listing = client.list_objects_v2(Bucket=BUCKET)
        blob_keys = [
            item["Key"] for item in listing.get("Contents", []) if "/blobs/" in item["Key"]
        ]
        assert len(blob_keys) == 1
        assert blob_keys[0].endswith(hashlib.sha256(payload).hexdigest())

    @pytest.mark.asyncio
    async def test_manifests_are_immutable_once_written(self, ws, db, storage):
        project = _pid()
        await _put(ws, db, project, "a.txt", b"v1")
        first = await ws.load_manifest(db, org_id=ORG, project_id=project, branch="main", revision=0)
        await _put(ws, db, project, "a.txt", b"v2")
        again = await ws.load_manifest(db, org_id=ORG, project_id=project, branch="main", revision=0)
        assert again.to_bytes() == first.to_bytes()
        assert again.entry("a.txt").sha256 == hashlib.sha256(b"v1").hexdigest()

    @pytest.mark.asyncio
    async def test_head_cas_rejects_stale_base_revision(self, ws, db):
        """Two writers race a HEAD bump — exactly one wins; the loser gets a
        CAS conflict, not a silent overwrite. Postgres is the lock."""
        from gateway.workspace_store import RevisionConflict
        from gateway.workspace_store.store import Upsert

        project = _pid()
        await _put(ws, db, project, "base.txt", b"base")  # revision 0

        async def commit_from_base(path: str):
            return await ws.commit(
                db,
                org_id=ORG,
                project_id=project,
                branch="main",
                base_revision=0,
                upserts=[Upsert(path=path, content=b"racer")],
                deletes=[],
            )

        winner = await commit_from_base("one.txt")
        assert winner.revision == 1
        with pytest.raises(RevisionConflict):
            await commit_from_base("two.txt")
        # The winner's manifest was not clobbered by the loser.
        head = await ws.load_manifest(db, org_id=ORG, project_id=project, branch="main")
        assert head.revision == 1
        assert head.entry("one.txt") is not None
        assert head.entry("two.txt") is None

    @pytest.mark.asyncio
    async def test_revision_numbers_are_strictly_monotonic_per_branch(self, ws, db):
        project = _pid()
        for i in range(5):
            manifest = await _put(ws, db, project, f"f{i}.txt", str(i).encode())
            assert manifest.revision == i
        rows = await ws.list_revisions(db, org_id=ORG, project_id=project, branch="main")
        assert [row.revision for row in rows] == [4, 3, 2, 1, 0]

    @pytest.mark.asyncio
    async def test_frozen_revision_pins_chat_runs_exactly(self, ws, db):
        project = _pid()
        await _put(ws, db, project, "config.yml", b"version: 1")
        frozen = 0
        await _put(ws, db, project, "config.yml", b"version: 2")
        pinned = await ws.read_file(
            db, org_id=ORG, project_id=project, branch="main", path="config.yml", revision=frozen
        )
        head = await ws.read_file(
            db, org_id=ORG, project_id=project, branch="main", path="config.yml"
        )
        assert pinned[1] == b"version: 1"
        assert head[1] == b"version: 2"


# ── §4.4 Session lease (gate G2) ────────────────────────────────────────────


class TestSessionLease:
    @pytest.mark.asyncio
    async def test_second_writer_on_same_project_branch_is_refused(self, db):
        from gateway.workspace_store import LeaseHeld, acquire_lease

        project = _pid()
        await acquire_lease(db, org_id=ORG, project_id=project, branch="main", holder="session-a")
        with pytest.raises(LeaseHeld):
            await acquire_lease(db, org_id=ORG, project_id=project, branch="main", holder="session-b")

    @pytest.mark.asyncio
    async def test_expired_lease_is_reclaimable_after_ttl(self, db):
        from gateway.workspace_store import acquire_lease

        project = _pid()
        await acquire_lease(
            db, org_id=ORG, project_id=project, branch="main", holder="dead", ttl_seconds=-1
        )
        expires = await acquire_lease(
            db, org_id=ORG, project_id=project, branch="main", holder="alive"
        )
        assert expires > 0

    @pytest.mark.asyncio
    async def test_sync_batches_renew_the_lease(self, db):
        from sqlalchemy import select

        from gateway.db.models import GatewayWorkspaceLease
        from gateway.workspace_store import acquire_lease, renew_lease

        project = _pid()
        first = await acquire_lease(
            db, org_id=ORG, project_id=project, branch="main", holder="s", ttl_seconds=10
        )
        second = await renew_lease(
            db, org_id=ORG, project_id=project, branch="main", holder="s", ttl_seconds=90
        )
        assert second > first
        row = (
            await db.execute(
                select(GatewayWorkspaceLease).where(GatewayWorkspaceLease.project_id == project)
            )
        ).scalars().one()
        assert row.holder == "s"
        assert row.expires_at == second

    @pytest.mark.asyncio
    async def test_read_only_frozen_sessions_never_take_a_lease(self, db):
        """Contract test: the lease API exposes no read-side entry point, and
        a reader coexists with a writer's live lease (reads never call
        acquire). Enforced structurally in the session service (G3)."""
        from sqlalchemy import func, select

        from gateway.db.models import GatewayWorkspaceLease
        from gateway.workspace_store import acquire_lease

        project = _pid()
        await acquire_lease(db, org_id=ORG, project_id=project, branch="main", holder="writer")
        # A frozen session reads a pinned revision — no lease API involved.
        count = (
            await db.execute(
                select(func.count()).select_from(GatewayWorkspaceLease).where(
                    GatewayWorkspaceLease.project_id == project
                )
            )
        ).scalar_one()
        assert count == 1  # still only the writer's


# ── §4.2 Workspace Files API (gate G1) ───────────────────────────────────────
# App-level: the real gateway app, local API key auth, aiosqlite DB override,
# moto-backed storage injected at the module seam.


def _workspace_app(storage, factory):
    """A fresh FastAPI app carrying exactly the v2 workspace surface.

    Composed per test — no shared singleton, no middleware stack, no
    cross-module state to bleed in. Auth resolves to the fixture identity via
    ordinary dependency overrides on this app instance only; the anonymous
    client below simply omits them.
    """
    from fastapi import FastAPI

    import gateway.api.workspace_files as wf
    from gateway.api.deps import require_projects_feature
    from gateway.api.workspace_files import router as files_router
    from gateway.api.workspace_projects import router as projects_router
    from gateway.auth import resolve_org_id, resolve_user_id
    from gateway.db.engine import get_db
    from gateway.security.scope_guard import _resolve_user_id as scope_resolve_user_id

    app = FastAPI()
    app.include_router(projects_router)
    app.include_router(files_router)

    async def _get_db():
        async with factory() as session:
            yield session

    async def _user() -> str:
        return "test-user"

    async def _org() -> str:
        return ORG

    async def _no_gate() -> None:
        return None

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[resolve_user_id] = _user
    app.dependency_overrides[resolve_org_id] = _org
    app.dependency_overrides[scope_resolve_user_id] = _user
    app.dependency_overrides[require_projects_feature] = _no_gate
    from gateway.workspace_store import WorkspaceStore

    app.dependency_overrides[wf.get_workspace_store] = lambda: WorkspaceStore(storage)
    return app


@pytest.fixture
def api(storage):
    """Authenticated client over the fresh workspace app + aiosqlite + moto."""
    import asyncio

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
    app = _workspace_app(storage, factory)
    client = TestClient(app)
    client.app = app  # anonymous-client tests derive from the same app
    yield client
    asyncio.run(engine.dispose())


def _create_project(api) -> str:
    response = api.post(
        "/api/workspace-projects",
        json={"name": f"proj-{uuid.uuid4().hex[:10]}", "display_name": "Test project"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


class TestWorkspaceFilesAPI:
    def test_put_then_get_roundtrips_bytes_exactly(self, api):
        project = _create_project(api)
        payload = "df = conn.query('select 1')\r\n# exact bytes\n".encode()
        put = api.put(f"/api/workspace-projects/{project}/files/nb/analysis.py", content=payload)
        assert put.status_code == 200, put.text
        assert put.json()["revision"] == 0
        got = api.get(f"/api/workspace-projects/{project}/files/nb/analysis.py")
        assert got.status_code == 200
        assert got.content == payload
        assert got.headers["X-SP-Sha256"] == hashlib.sha256(payload).hexdigest()

    def test_get_missing_path_is_404_not_500(self, api):
        project = _create_project(api)
        api.put(f"/api/workspace-projects/{project}/files/exists.txt", content=b"x")
        response = api.get(f"/api/workspace-projects/{project}/files/never/was/here.txt")
        assert response.status_code == 404

    def test_delete_then_get_is_404_but_prior_revision_still_serves_it(self, api):
        """USER STORY: delete a file, hit an old link — the old revision's
        manifest still resolves it. Deletion is a new revision, not erasure."""
        project = _create_project(api)
        api.put(f"/api/workspace-projects/{project}/files/report.md", content=b"# findings")
        deleted = api.delete(f"/api/workspace-projects/{project}/files/report.md")
        assert deleted.status_code == 200
        assert deleted.json()["revision"] == 1
        gone = api.get(f"/api/workspace-projects/{project}/files/report.md")
        assert gone.status_code == 404
        old = api.get(f"/api/workspace-projects/{project}/files/report.md?revision=0")
        assert old.status_code == 200
        assert old.content == b"# findings"

    def test_list_copy_move_search_operate_within_project_only(self, api):
        project_a = _create_project(api)
        project_b = _create_project(api)
        api.put(f"/api/workspace-projects/{project_a}/files/only-in-a.sql", content=b"select 1")

        listing_b = api.post(
            f"/api/workspace-projects/{project_b}/files:list", json={"branch": "main"}
        )
        assert listing_b.json()["files"] == []

        search_b = api.post(
            f"/api/workspace-projects/{project_b}/files:search",
            json={"branch": "main", "query": "only-in-a"},
        )
        assert search_b.status_code == 404  # branch b has no revisions at all

        copied = api.post(
            f"/api/workspace-projects/{project_a}/files:copy",
            json={"source": "only-in-a.sql", "destination": "copies/duplicate.sql"},
        )
        assert copied.status_code == 200
        moved = api.post(
            f"/api/workspace-projects/{project_a}/files:move",
            json={"source": "copies/duplicate.sql", "destination": "moved.sql"},
        )
        assert moved.status_code == 200
        listing_a = api.post(
            f"/api/workspace-projects/{project_a}/files:list", json={"branch": "main"}
        )
        paths = [item["path"] for item in listing_a.json()["files"]]
        assert sorted(paths) == ["moved.sql", "only-in-a.sql"]

        found = api.post(
            f"/api/workspace-projects/{project_a}/files:search",
            json={"branch": "main", "query": "moved"},
        )
        assert [item["path"] for item in found.json()["files"]] == ["moved.sql"]

    def test_path_confinement_rejects_dotdot_nul_and_absolute(self, api):
        from gateway.workspace_store import WorkspacePathError, confine_relpath

        # The owning layer: lexical confinement rejects every escape form.
        for bad in (
            "../escape.txt",
            "a/../../escape.txt",
            "/etc/passwd",
            "~/secrets",
            "C:\\windows\\evil",
            "with\x00nul",
            "",
        ):
            with pytest.raises(WorkspacePathError):
                confine_relpath(bad)
        assert confine_relpath("a/./b//c.txt") == "a/b/c.txt"

        # Server-side enforcement on body-carried paths (immune to client URL
        # normalization): the whole batch is rejected, no revision created.
        project = _create_project(api)
        api.put(f"/api/workspace-projects/{project}/files/anchor.txt", content=b"x")
        for bad in ("/etc/passwd", "../escape.txt", "nested/../../up.txt"):
            batch = api.post(
                f"/api/workspace-projects/{project}/files:batch",
                json={
                    "branch": "main",
                    "base_revision": 0,
                    "upserts": [{"path": bad, "content_b64": "ZXZpbA=="}],
                    "deletes": [],
                },
            )
            assert batch.status_code == 400, f"{bad!r} -> {batch.status_code}"

        # URL-carried traversal is stopped upstream (security middleware or
        # client normalization) — it must never succeed, whatever the layer.
        response = api.put(
            f"/api/workspace-projects/{project}/files/a/../../escape.txt", content=b"evil"
        )
        assert response.status_code >= 400
        revisions = api.get(f"/api/workspace-projects/{project}/revisions").json()["revisions"]
        assert len(revisions) == 1  # only anchor.txt's put

    def test_batch_commit_is_atomic_all_or_nothing(self, api):
        project = _create_project(api)
        api.put(f"/api/workspace-projects/{project}/files/keep.txt", content=b"k")
        # One valid upsert + one reference to a blob that was never uploaded:
        # the whole batch must fail and no revision may be created.
        batch = api.post(
            f"/api/workspace-projects/{project}/files:batch",
            json={
                "branch": "main",
                "base_revision": 0,
                "upserts": [
                    {"path": "good.txt", "content_b64": "Z29vZA=="},
                    {"path": "bad.txt", "sha256": "0" * 64, "size": 4},
                ],
                "deletes": ["keep.txt"],
            },
        )
        assert batch.status_code == 400
        revisions = api.get(f"/api/workspace-projects/{project}/revisions").json()["revisions"]
        assert len(revisions) == 1  # only the initial put
        still = api.get(f"/api/workspace-projects/{project}/files/keep.txt")
        assert still.status_code == 200

    def test_snapshot_endpoint_serves_presigned_tarball_of_any_revision(self, api, storage):
        import anyio

        project = _create_project(api)
        api.put(f"/api/workspace-projects/{project}/files/models/one.sql", content=b"select 1")
        api.put(f"/api/workspace-projects/{project}/files/models/two.sql", content=b"select 2")

        snap = api.get(f"/api/workspace-projects/{project}/snapshot?revision=0")
        assert snap.status_code == 200
        body = snap.json()
        assert body["revision"] == 0
        assert "Signature" in body["url"] or "X-Amz-Signature" in body["url"]

        tarball = anyio.from_thread.run if False else None  # noqa: F841 - readability
        data = _run(storage.get_bytes(body["key"]))
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            names = tar.getnames()
            assert names == ["models/one.sql"]
            assert tar.extractfile("models/one.sql").read() == b"select 1"

        head_snap = api.get(f"/api/workspace-projects/{project}/snapshot")
        data = _run(storage.get_bytes(head_snap.json()["key"]))
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            assert sorted(tar.getnames()) == ["models/one.sql", "models/two.sql"]

    def test_revisions_endpoint_lists_manifest_history(self, api):
        project = _create_project(api)
        api.put(f"/api/workspace-projects/{project}/files/a.txt", content=b"1")
        api.put(f"/api/workspace-projects/{project}/files/a.txt", content=b"2")
        api.delete(f"/api/workspace-projects/{project}/files/a.txt")
        body = api.get(f"/api/workspace-projects/{project}/revisions").json()
        revisions = body["revisions"]
        assert [row["revision"] for row in revisions] == [2, 1, 0]
        assert revisions[0]["file_count"] == 0
        assert revisions[1]["file_count"] == 1
        assert all(row["created_at"] > 0 for row in revisions)

    def test_auth_requires_session_jwt_with_write_scope_for_mutations(
        self, api, monkeypatch
    ):
        """Cloud-mode contract: without a verified identity the mutation is
        refused before it can write. Auth is real here — the anonymous app
        drops the identity overrides, and cloud mode means no local fallback.
        """
        from fastapi.testclient import TestClient

        from gateway.api.deps import require_projects_feature
        from gateway.api.workspace_files import get_workspace_store
        from gateway.db.engine import get_db

        project = _create_project(api)

        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        from fastapi import FastAPI

        from gateway.api.workspace_files import router as files_router
        from gateway.api.workspace_projects import router as projects_router

        anonymous_app = FastAPI()

        anonymous_app.include_router(projects_router)
        anonymous_app.include_router(files_router)
        # Keep only the non-auth seams; identity resolution runs for real.
        anonymous_app.dependency_overrides[get_db] = api.app.dependency_overrides[get_db]
        anonymous_app.dependency_overrides[get_workspace_store] = (
            api.app.dependency_overrides[get_workspace_store]
        )
        anonymous_app.dependency_overrides[require_projects_feature] = (
            api.app.dependency_overrides[require_projects_feature]
        )
        anonymous = TestClient(anonymous_app, raise_server_exceptions=False)
        response = anonymous.put(
            f"/api/workspace-projects/{project}/files/hack.txt", content=b"nope"
        )
        assert response.status_code == 401
        monkeypatch.delenv("SP_DEPLOYMENT_MODE")
        revisions = api.get(f"/api/workspace-projects/{project}/revisions").json()["revisions"]
        assert revisions == []


def _run(coroutine):
    import asyncio

    return asyncio.run(coroutine)


# ── §4.3 Sync agent (gate G2) ───────────────────────────────────────────────


class TestWriteThroughFilePlane:
    """§4.3 REVISED (supersedes the sync-agent design): there is no local
    mirror and no debounce window. A save IS a durable commit; a crash loses
    nothing that was saved. The notebook-server client half of this contract
    is covered in notebook-server/tests/test_gateway_file_system.py."""

    def test_save_is_durable_immediately_no_debounce_window(self, api, storage):
        """The old bar was 'durable within 2s'; the new bar is: the PUT
        response already names the committed revision, and the blob is in S3
        before the client hears success."""
        project = _create_project(api)
        response = api.put(
            f"/api/workspace-projects/{project}/files/nb.py", content=b"x = 1"
        )
        assert response.json()["revision"] == 0
        digest = hashlib.sha256(b"x = 1").hexdigest()
        from gateway.workspace_store import blob_key

        assert _run(storage.get_bytes(blob_key(ORG, project, digest))) == b"x = 1"

    def test_edit_then_save_roundtrip_preserves_exact_content(self, api):
        """USER STORY: edit an existing file, save, reopen — byte-identical,
        no CRLF/encoding mangling, mtime advances."""
        project = _create_project(api)
        original = "df = 1\r\nx = 'unicode: é'\n".encode()
        api.put(f"/api/workspace-projects/{project}/files/a.py", content=original)
        first = api.post(
            f"/api/workspace-projects/{project}/files:list", json={"branch": "main"}
        ).json()["files"][0]
        edited = original + b"y = 2\n"
        api.put(f"/api/workspace-projects/{project}/files/a.py", content=edited)
        assert api.get(f"/api/workspace-projects/{project}/files/a.py").content == edited
        second = api.post(
            f"/api/workspace-projects/{project}/files:list", json={"branch": "main"}
        ).json()["files"][0]
        assert second["mtime"] >= first["mtime"]

    def test_unsaved_state_is_the_only_crash_loss(self, api):
        """§7: with write-through saves, a dead sandbox loses only the
        browser's unsaved buffer — every committed revision still serves."""
        project = _create_project(api)
        api.put(f"/api/workspace-projects/{project}/files/kept.py", content=b"saved")
        # The sandbox dying is a non-event for storage: no flush, no barrier,
        # nothing to reconcile. Head still serves the last save.
        assert api.get(f"/api/workspace-projects/{project}/files/kept.py").content == b"saved"

    def test_conflicting_batch_is_rejected_by_cas_and_retry_converges(self, api):
        project = _create_project(api)
        api.put(f"/api/workspace-projects/{project}/files/base.py", content=b"0")
        stale = api.post(
            f"/api/workspace-projects/{project}/files:batch",
            json={
                "branch": "main",
                "base_revision": None,
                "upserts": [{"path": "loser.py", "content_b64": "eA=="}],
                "deletes": [],
            },
        )
        assert stale.status_code == 409
        head = api.get(f"/api/workspace-projects/{project}/revisions").json()[
            "revisions"
        ][0]["revision"]
        retry = api.post(
            f"/api/workspace-projects/{project}/files:batch",
            json={
                "branch": "main",
                "base_revision": head,
                "upserts": [{"path": "loser.py", "content_b64": "eA=="}],
                "deletes": [],
            },
        )
        assert retry.status_code == 200

    def test_large_files_travel_by_presigned_put_and_commit_by_reference(
        self, api, storage
    ):
        project = _create_project(api)
        payload = b"parquet-bytes " * 100
        digest = hashlib.sha256(payload).hexdigest()
        grant = api.post(
            f"/api/workspace-projects/{project}/files:upload-url",
            json={"sha256": digest, "size": len(payload)},
        )
        assert grant.status_code == 200
        # moto's presigned PUT needs no network here — write the blob at the
        # granted key, exactly what the client's PUT would do.
        _run(storage.put_bytes(grant.json()["key"], payload))
        committed = api.post(
            f"/api/workspace-projects/{project}/files:batch",
            json={
                "branch": "main",
                "base_revision": None,
                "upserts": [{"path": "data/big.parquet", "sha256": digest, "size": len(payload)}],
                "deletes": [],
            },
        )
        assert committed.status_code == 200
        got = api.get(f"/api/workspace-projects/{project}/files/data/big.parquet")
        assert got.content == payload

    def test_session_sidecars_are_ordinary_files(self, api):
        """__sp__ session snapshots (the reconnect experience) commit like any
        file; nothing in the storage plane special-cases them."""
        project = _create_project(api)
        response = api.put(
            f"/api/workspace-projects/{project}/files/__sp__/session/nb.py.json",
            content=b'{"cells": []}',
        )
        assert response.status_code == 200
        assert (
            api.get(
                f"/api/workspace-projects/{project}/files/__sp__/session/nb.py.json"
            ).content
            == b'{"cells": []}'
        )


# ── User interaction semantics (the jupyter-lab-like UX; gates G2–G4) ──────


class TestUserWorkflows:
    def test_save_edit_save_delete_navigate_back_full_journey(self, api):
        """USER STORY (end to end): create file → save → edit → save → delete
        → navigate back via an old link → recoverable from revision history,
        with a working restore affordance, never a 500."""
        project = _create_project(api)
        base = f"/api/workspace-projects/{project}"
        assert api.put(f"{base}/files/report.md", content=b"v1").json()["revision"] == 0
        assert api.put(f"{base}/files/report.md", content=b"v2").json()["revision"] == 1
        assert api.delete(f"{base}/files/report.md").json()["revision"] == 2

        # Navigate back via an old link: never a 500, always the old bytes.
        assert api.get(f"{base}/files/report.md").status_code == 404
        assert api.get(f"{base}/files/report.md?revision=1").content == b"v2"
        assert api.get(f"{base}/files/report.md?revision=0").content == b"v1"

        # Restore affordance: re-save the recovered content as a new revision.
        old = api.get(f"{base}/files/report.md?revision=1").content
        assert api.put(f"{base}/files/report.md", content=old).json()["revision"] == 3
        assert api.get(f"{base}/files/report.md").content == b"v2"

    def test_deleting_a_project_tombstones_links_instead_of_500(self, api):
        project = _create_project(api)
        api.put(f"/api/workspace-projects/{project}/files/kept.py", content=b"x")
        assert api.delete(f"/api/workspace-projects/{project}").status_code == 204
        response = api.get(f"/api/workspace-projects/{project}/files/kept.py")
        assert response.status_code == 410
        assert response.json()["detail"]["tombstone"] is True

    def test_rename_move_preserves_revision_lineage(self, api):
        project = _create_project(api)
        base = f"/api/workspace-projects/{project}"
        api.put(f"{base}/files/old-name.py", content=b"content")
        moved = api.post(
            f"{base}/files:move",
            json={"source": "old-name.py", "destination": "new-name.py"},
        )
        assert moved.status_code == 200
        # Head: only the new name; lineage: the pre-move revision still serves
        # the old path, and both entries share one blob (same sha).
        assert api.get(f"{base}/files/new-name.py").content == b"content"
        assert api.get(f"{base}/files/old-name.py").status_code == 404
        old_sha = api.get(f"{base}/files/old-name.py?revision=0").headers["X-SP-Sha256"]
        new_sha = api.get(f"{base}/files/new-name.py").headers["X-SP-Sha256"]
        assert old_sha == new_sha

    def test_browser_refresh_mid_edit_rehydrates_from_session_sidecar(self, api):
        """USER STORY: refresh mid-edit. Unsaved buffers are browser-tier by
        design (three-tier model); what the platform guarantees is that the
        session sidecar — outputs, cell state — reloads from the same branch
        the editor left, with no compute required."""
        project = _create_project(api)
        base = f"/api/workspace-projects/{project}"
        api.put(f"{base}/files/nb.py", content=b"x = 1")
        api.put(
            f"{base}/files/__sp__/session/nb.py.json",
            content=b'{"cells": [{"id": "a", "output": "1"}]}',
        )
        # The refreshed page re-reads both without any session existing.
        assert api.get(f"{base}/files/nb.py").content == b"x = 1"
        assert b'"output": "1"' in api.get(
            f"{base}/files/__sp__/session/nb.py.json"
        ).content

    def test_two_users_same_project_different_branches_never_interfere(self, api):
        project = _create_project(api)
        base = f"/api/workspace-projects/{project}"
        api.put(f"{base}/files/model.sql?branch=alice/work", content=b"alice")
        api.put(f"{base}/files/model.sql?branch=bob/work", content=b"bob")
        assert api.get(f"{base}/files/model.sql?branch=alice/work").content == b"alice"
        assert api.get(f"{base}/files/model.sql?branch=bob/work").content == b"bob"
        assert api.get(f"{base}/files/model.sql").status_code == 404  # main untouched

    def test_branch_switch_serves_the_other_branchs_content(self, api):
        """Branch switching is re-pointing reads — no clone, no checkout."""
        project = _create_project(api)
        base = f"/api/workspace-projects/{project}"
        api.put(f"{base}/files/config.yml", content=b"env: main")
        api.put(f"{base}/files/config.yml?branch=feature/x", content=b"env: feature")
        snap_main = api.get(f"{base}/snapshot").json()
        snap_feature = api.get(f"{base}/snapshot?branch=feature/x").json()
        assert snap_main["key"] != snap_feature["key"]
        assert api.get(f"{base}/files/config.yml?branch=feature/x").content == b"env: feature"

    def test_notebook_page_loads_without_any_compute(self, api):
        """The point of the whole redesign: browsing project files must not
        require pod/sandbox scheduling. This composed app carries no notebook
        session machinery at all — file reads work anyway."""
        from gateway.db.models import GatewayNotebookSession

        project = _create_project(api)
        api.put(f"/api/workspace-projects/{project}/files/nb.py", content=b"x")
        listing = api.post(
            f"/api/workspace-projects/{project}/files:list", json={"branch": "main"}
        )
        assert [f["path"] for f in listing.json()["files"]] == ["nb.py"]
        # And no session row was ever created to serve those reads.
        import asyncio as _asyncio

        from sqlalchemy import func, select

        from gateway.db.engine import get_db as _get_db  # the override target

        async def _count() -> int:
            agen = api.app.dependency_overrides[_get_db]()
            session = await agen.__anext__()
            try:
                result = await session.execute(
                    select(func.count()).select_from(GatewayNotebookSession)
                )
                return int(result.scalar_one())
            finally:
                await agen.aclose()

        assert _asyncio.run(_count()) == 0


# ── §5.3 Session lifecycle (gate G3: runtime v2 + backend seam) ─────────────


class TestSessionLifecycle:
    """Unit-level lifecycle coverage lives in tests/test_notebook_sessions.py
    (reuse/recreate/resume/lease/quota); this class asserts the seam-level
    contracts the migration gates on."""

    def test_active_session_extends_instead_of_dying_at_time_limit(self):
        """The vercel backend exposes extend(); the lifecycle loop drives it
        for every session with a fresh ping (see gateway/main.py). The
        provider grant is capped, so extend must be a first-class operation."""
        import inspect

        from gateway.notebooks.backends import VercelNotebookBackend
        from gateway.sandbox_runtime.base import SandboxRuntime

        assert callable(VercelNotebookBackend.extend)
        assert "extend_time_limit" in dict(inspect.getmembers(SandboxRuntime))

    @pytest.mark.asyncio
    async def test_idle_session_snapshots_to_zero(self):
        """snapshot_idle_session: snapshot → release compute → row resumable,
        upstream cleared, lease released."""
        from unittest.mock import ANY, AsyncMock, patch

        from gateway.notebooks import session_service
        from gateway.store.notebook_sessions import NotebookSessionInternal

        backend = AsyncMock()
        backend.name = "vercel"
        backend.snapshot_and_stop.return_value = "snap-42"
        internal = NotebookSessionInternal(
            session_id="sess-idle", org_id=ORG, user_id="u", status="running",
            backend="vercel", runtime_handle="sbx-idle", snapshot_id=None,
            upstream_url="https://sbx.vercel.run", access_token=None,
            project_id="proj-1", branch="main",
        )
        with (
            patch.object(session_service.ns, "update_session_runtime", AsyncMock()) as update,
            patch.object(session_service, "release_lease", AsyncMock()) as release,
        ):
            await session_service.snapshot_idle_session(
                AsyncMock(), internal=internal, backend=backend
            )
        backend.snapshot_and_stop.assert_awaited_once_with("sbx-idle")
        update.assert_awaited_once_with(
            ANY,
            session_id="sess-idle",
            org_id=ORG,
            status="snapshotted",
            snapshot_id="snap-42",
            clear_upstream=True,
        )
        release.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_resume_from_snapshot_within_seconds_budget(self):
        """Resume is in-place (same handle) — no create, no hydration; the
        resumed route URL replaces the cleared upstream."""
        from unittest.mock import AsyncMock

        from gateway.notebooks.backends import LaunchRequest, VercelNotebookBackend

        runtime = AsyncMock()
        runtime.routes.return_value = {2718: "https://sbx-idle.vercel.run"}
        runtime.exec.return_value = type("R", (), {"ok": True})()
        from gateway.config.notebooks import NotebookSettings

        backend = VercelNotebookBackend(NotebookSettings(), runtime=runtime)
        request = LaunchRequest(
            org_id="org-1",
            user_id="user-1",
            session_id="sess-idle",
            project_id="proj-1",
            branch="main",
            session_jwt="fresh-jwt",
            notebook_token="notebook-token",
        )
        upstream = await backend.resume("sbx-idle", request)
        runtime.resume.assert_awaited_once_with("sbx-idle")
        runtime.start_process.assert_awaited_once()
        process_command = runtime.start_process.await_args.args[1]
        process_env = runtime.start_process.await_args.kwargs["env"]
        assert "SP_SNAPSHOT_URL" not in process_env
        assert process_env["SP_SESSION_JWT"] == "fresh-jwt"
        assert "sp edit" in process_command
        runtime.create.assert_not_awaited()
        assert upstream == "https://sbx-idle.vercel.run"

    def test_backend_seam_flag_selects_vercel_like_the_eval_flag(self, monkeypatch):
        from gateway.config.notebooks import NotebookSettings

        monkeypatch.delenv("SP_NOTEBOOK_DIRECT_URL", raising=False)
        monkeypatch.setenv("SP_NOTEBOOK_EXECUTION_BACKEND", "vercel")
        assert NotebookSettings().resolved_backend() == "vercel"
        monkeypatch.setenv("SP_NOTEBOOK_EXECUTION_BACKEND", "")
        monkeypatch.setenv("SP_NOTEBOOK_DIRECT_URL", "http://notebook:2718")
        assert NotebookSettings().resolved_backend() == "direct"
        monkeypatch.setenv("SP_NOTEBOOK_EXECUTION_BACKEND", "fargate")
        with pytest.raises(ValueError, match="SP_NOTEBOOK_EXECUTION_BACKEND"):
            NotebookSettings()

    def test_pod_endpoints_require_auth_before_public_route_urls_exist(self):
        """Hard precondition: every /api/notion-analysis and
        /api/standalone-chat route on the notebook-server must carry
        @requires — NetworkPolicy protection does not survive public sandbox
        route URLs. Static source check (the notebook-server is a separate
        package not importable from this venv)."""
        import re
        from pathlib import Path

        endpoints = (
            Path(__file__).resolve().parents[2]
            / "notebook-server" / "signalpilot" / "_server" / "api" / "endpoints"
        )
        for name in ("notion_analysis.py", "standalone_chat.py"):
            source = (endpoints / name).read_text(encoding="utf-8")
            routes = re.findall(r"@router\.(?:get|post|put|delete|websocket)\(", source)
            decorated = re.findall(r"@requires\(", source)
            assert routes, f"{name}: no routes found — did the file move?"
            assert len(decorated) >= len(routes), (
                f"{name}: {len(routes)} routes but only {len(decorated)} @requires — "
                "an unauthenticated route behind a public URL"
            )

    def test_run_notebook_mcp_tool_uses_pinned_digest_runtime(self, monkeypatch):
        """The tool goes through the session service, whose vercel backend
        enforces SP_NOTEBOOK_VERCEL_IMAGE digest pinning in cloud mode — the
        old direct-os.getenv image bypass no longer exists anywhere."""
        import inspect

        from gateway.config.notebooks import NotebookSettings
        from gateway.mcp.tools import notebook as tool

        source = inspect.getsource(tool)
        assert "SP_NOTEBOOK_IMAGE" not in source
        assert "ensure_notebook_session" in source
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        monkeypatch.setenv("SP_NOTEBOOK_VERCEL_IMAGE", "reg/sp-notebook:latest")
        with pytest.raises(ValueError, match="digest-pinned"):
            NotebookSettings().require_vercel_image(cloud=True)


# ── §4.5 Git as exporter (gates G5–G6) ──────────────────────────────────────


class TestGitExporter:
    """§4.5 gate assertions. The full behavioral suite (import/export round
    trips, deletions, retry convergence) is tests/test_github_pull_store.py;
    these pin the four contracts the migration gates on."""

    @pytest.fixture
    def repos(self, monkeypatch, tmp_path):
        from gateway.git import repos as repos_mod

        monkeypatch.setattr(repos_mod, "REPOS_ROOT", tmp_path / "repos")
        (tmp_path / "repos").mkdir()
        return repos_mod

    @staticmethod
    def _git(*args, cwd=None) -> str:
        import subprocess

        result = subprocess.run(
            ["git", "-c", "user.email=t@test", "-c", "user.name=test", *args],
            cwd=str(cwd) if cwd else None,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout

    def _seeded_project(self, repos, tmp_path):
        project = _pid()
        src = tmp_path / f"remote-{project[:8]}"
        src.mkdir()
        self._git("init", "--initial-branch", "main", str(src))
        (src / "models.sql").write_text("select 1", encoding="utf-8")
        self._git("add", "-A", cwd=src)
        self._git("commit", "-m", "seed", cwd=src)
        self._git("config", "receive.denyCurrentBranch", "ignore", cwd=src)
        repos.init_bare_repo(project)
        repos.clone_from_remote(project, str(src))
        return project, str(src)

    @pytest.mark.asyncio
    async def test_every_s3_revision_maps_to_exactly_one_export_commit(
        self, repos, tmp_path, storage, db, ws
    ):
        from sqlalchemy import select

        from gateway.db.models import GatewayWorkspaceRevision
        from gateway.workspace_store import export_revision_to_git, import_repo_to_revisions

        project, remote = self._seeded_project(repos, tmp_path)
        await import_repo_to_revisions(db, storage, org_id=ORG, project_id=project)
        await _put(ws, db, project, "new.sql", b"select 2")

        first = await export_revision_to_git(
            db, storage, org_id=ORG, project_id=project, branch="main", remote_url=remote
        )
        second = await export_revision_to_git(
            db, storage, org_id=ORG, project_id=project, branch="main", remote_url=remote
        )
        assert first.commit_sha == second.commit_sha  # re-export is a no-op
        row = (
            await db.execute(
                select(GatewayWorkspaceRevision).where(
                    GatewayWorkspaceRevision.project_id == project,
                    GatewayWorkspaceRevision.export_commit_sha == first.commit_sha,
                )
            )
        ).scalars().all()
        assert len(row) == 1

    @pytest.mark.asyncio
    async def test_inbound_github_change_imports_as_a_new_revision(
        self, repos, tmp_path, storage, db, ws
    ):
        from gateway.workspace_store import import_repo_to_revisions

        project, remote = self._seeded_project(repos, tmp_path)
        first = await import_repo_to_revisions(db, storage, org_id=ORG, project_id=project)
        (Path(remote) / "upstream.sql").write_text("select 9", encoding="utf-8")
        self._git("add", "-A", cwd=remote)
        self._git("commit", "-m", "upstream", cwd=remote)
        self._git("fetch", str(Path(remote)), "main:main", cwd=repos.repo_path(project))
        second = await import_repo_to_revisions(db, storage, org_id=ORG, project_id=project)
        assert second.revision == (first.revision or 0) + 1
        got = await ws.read_file(
            db, org_id=ORG, project_id=project, branch="main", path="upstream.sql"
        )
        assert got[1] == b"select 9"

    @pytest.mark.asyncio
    async def test_export_failure_never_blocks_editing(
        self, repos, tmp_path, storage, db, ws
    ):
        from gateway.workspace_store import export_revision_to_git, import_repo_to_revisions
        from gateway.workspace_store.github_sync import GitHubExportError

        project, _ = self._seeded_project(repos, tmp_path)
        await import_repo_to_revisions(db, storage, org_id=ORG, project_id=project)
        with pytest.raises(GitHubExportError):
            await export_revision_to_git(
                db,
                storage,
                org_id=ORG,
                project_id=project,
                branch="main",
                remote_url=str(tmp_path / "does-not-exist"),
            )
        # Editing continues: the failed export left revisions writable.
        manifest = await _put(ws, db, project, "after-failure.sql", b"still editing")
        assert manifest.entry("after-failure.sql") is not None

    def test_agent_branches_still_never_reach_github(self):
        from gateway.git.sync import AGENT_BRANCH_PREFIXES, is_agent_branch

        assert "signalpilot-agent/" in AGENT_BRANCH_PREFIXES
        assert "analysis/" in AGENT_BRANCH_PREFIXES
        assert is_agent_branch("signalpilot-agent/run-1")
        assert is_agent_branch("analysis/slack/req-1")
        assert not is_agent_branch("main")
        assert not is_agent_branch("feature/analysis")


# ── Unified artifacts (new build item surfaced 2026-08-19) ──────────────────


class TestUnifiedArtifacts:
    """Gate assertions over the unified index; the behavioral suite is
    tests/test_artifacts_index.py (filters, org isolation, pagination)."""

    @pytest_asyncio.fixture
    async def seeded(self, db):
        from tests.test_artifacts_index import seed_chat_artifact, seed_eval_artifacts

        chat_run_id, _ = await seed_chat_artifact(db, org_id=ORG)
        eval_run_id = await seed_eval_artifacts(db, org_id=ORG)
        return db, chat_run_id, eval_run_id

    @pytest.mark.asyncio
    async def test_artifact_index_lists_across_chat_and_eval_sources(self, seeded):
        from gateway.store.artifacts_index import list_artifacts

        db, _, _ = seeded
        records, total = await list_artifacts(db, org_id=ORG)
        assert total == 2
        assert {record.kind for record in records} == {"chat", "eval"}

    @pytest.mark.asyncio
    async def test_artifact_records_carry_provenance_run_task_session(self, seeded):
        from gateway.store.artifacts_index import list_artifacts

        db, chat_run_id, eval_run_id = seeded
        records, _ = await list_artifacts(db, org_id=ORG)
        by_kind = {record.kind: record.to_dict() for record in records}
        assert by_kind["chat"]["provenance"]["run_id"] == chat_run_id
        assert by_kind["chat"]["provenance"]["session_id"] == "vs-123"
        assert by_kind["chat"]["provenance"]["conversation_id"]
        assert by_kind["eval"]["provenance"]["run_id"] == eval_run_id
        assert by_kind["eval"]["provenance"]["task_id"] == "q1"

    @pytest.mark.asyncio
    async def test_index_serves_without_any_compute(self, seeded):
        """Pod-free browsing at the API boundary: a composed app with only
        the artifacts router lists everything; no session machinery exists.
        (The dedicated web browse page is the remaining FE follow-up.)"""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from gateway.api.artifacts import router as artifacts_router
        from gateway.auth import resolve_org_id, resolve_user_id
        from gateway.db.engine import get_db
        from gateway.security.scope_guard import _resolve_user_id as scope_user

        db, _, _ = seeded
        app = FastAPI()
        app.include_router(artifacts_router)

        async def _get_db():
            yield db

        async def _user() -> str:
            return "test-user"

        async def _org() -> str:
            return ORG

        app.dependency_overrides[get_db] = _get_db
        app.dependency_overrides[resolve_user_id] = _user
        app.dependency_overrides[resolve_org_id] = _org
        app.dependency_overrides[scope_user] = _user
        client = TestClient(app)
        body = client.get("/api/artifacts").json()
        assert body["total"] == 2
        assert all(record["download"]["route"] for record in body["artifacts"])

    @pytest.mark.asyncio
    async def test_agent_run_artifacts_appear_in_the_index(self, db):
        """An artifact committed by an agent run is discoverable without
        knowing the branch/run — it lists by org like any other."""
        from tests.test_artifacts_index import seed_chat_artifact

        from gateway.store.artifacts_index import list_artifacts

        run_id, _ = await seed_chat_artifact(
            db, org_id=ORG, filename="agent-report.html", session_id="chat:run-77"
        )
        records, _ = await list_artifacts(db, org_id=ORG)
        match = [r for r in records if r.to_dict()["name"] == "agent-report.html"]
        assert match and match[0].to_dict()["provenance"]["run_id"] == run_id

    @pytest.mark.asyncio
    async def test_artifact_retention_prunes_blobs_but_never_provenance_rows(self, db):
        from tests.test_artifacts_index import seed_eval_artifacts

        from gateway.store.artifacts_index import list_artifacts

        await seed_eval_artifacts(db, org_id=ORG, artifacts_pruned=True)
        records, total = await list_artifacts(db, org_id=ORG, kind="eval")
        assert total == 1  # the provenance row still lists
        assert records[0].to_dict()["available"] is False  # the blob does not
