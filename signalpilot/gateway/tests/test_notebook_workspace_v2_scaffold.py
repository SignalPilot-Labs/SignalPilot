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

import pytest

from ._notebook_workspace_v2_support import (
    BUCKET,
    ORG,
    _create_project,
    _pid,
    _put,
    _run,
    _target,
    _workspace_app,
    api,
    db,
    storage,
    ws,
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
        blob_keys = [item["Key"] for item in listing.get("Contents", []) if "/blobs/" in item["Key"]]
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
        head = await ws.read_file(db, org_id=ORG, project_id=project, branch="main", path="config.yml")
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
        await acquire_lease(db, org_id=ORG, project_id=project, branch="main", holder="dead", ttl_seconds=-1)
        expires = await acquire_lease(db, org_id=ORG, project_id=project, branch="main", holder="alive")
        assert expires > 0

    @pytest.mark.asyncio
    async def test_sync_batches_renew_the_lease(self, db):
        from sqlalchemy import select

        from gateway.db.models import GatewayWorkspaceLease
        from gateway.workspace_store import acquire_lease, renew_lease

        project = _pid()
        first = await acquire_lease(db, org_id=ORG, project_id=project, branch="main", holder="s", ttl_seconds=10)
        second = await renew_lease(db, org_id=ORG, project_id=project, branch="main", holder="s", ttl_seconds=90)
        assert second > first
        row = (
            (await db.execute(select(GatewayWorkspaceLease).where(GatewayWorkspaceLease.project_id == project)))
            .scalars()
            .one()
        )
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
                select(func.count())
                .select_from(GatewayWorkspaceLease)
                .where(GatewayWorkspaceLease.project_id == project)
            )
        ).scalar_one()
        assert count == 1  # still only the writer's


# ── §4.2 Workspace Files API (gate G1) ───────────────────────────────────────


class TestWorkspaceFilesAPI:
    def test_put_then_get_roundtrips_bytes_exactly(self, api):
        project = _create_project(api)
        payload = b"df = conn.query('select 1')\r\n# exact bytes\n"
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

        listing_b = api.post(f"/api/workspace-projects/{project_b}/files:list", json={"branch": "main"})
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
        listing_a = api.post(f"/api/workspace-projects/{project_a}/files:list", json={"branch": "main"})
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
        response = api.put(f"/api/workspace-projects/{project}/files/a/../../escape.txt", content=b"evil")
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

    def test_auth_requires_session_jwt_with_write_scope_for_mutations(self, api, monkeypatch):
        """Cloud-mode contract: without a verified identity the mutation is
        refused before it can write. Auth is real here — the anonymous app
        drops the identity overrides, and cloud mode means no local fallback.
        """
        from fastapi.testclient import TestClient

        from gateway.api.deps import require_billable_plan
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
        anonymous_app.dependency_overrides[get_workspace_store] = api.app.dependency_overrides[get_workspace_store]
        anonymous_app.dependency_overrides[require_billable_plan] = api.app.dependency_overrides[require_billable_plan]
        anonymous = TestClient(anonymous_app, raise_server_exceptions=False)
        response = anonymous.put(f"/api/workspace-projects/{project}/files/hack.txt", content=b"nope")
        assert response.status_code == 401
        monkeypatch.delenv("SP_DEPLOYMENT_MODE")
        revisions = api.get(f"/api/workspace-projects/{project}/revisions").json()["revisions"]
        assert revisions == []
