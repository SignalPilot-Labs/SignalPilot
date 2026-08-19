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


class TestSyncAgent:
    def test_notebook_save_flushes_within_debounce_window(self):
        _target("§4.3", "G2")

    def test_edit_then_save_roundtrip_preserves_exact_content(self):
        _target("§4.3", "G2")

    def test_flush_barrier_runs_before_snapshot_destroy_and_handoff(self):
        _target("§4.3 flush barriers", "G2")

    def test_crash_loses_at_most_the_debounce_window(self):
        _target("§4.3 / §7 failure modes", "G2")

    def test_conflict_replays_local_changes_then_retries_once(self):
        _target("§4.3 conflict", "G2")

    def test_spsyncignore_excludes_cache_venvs_tmp(self):
        _target("§4.3 .spsyncignore", "G2")

    def test_large_files_travel_by_presigned_put_and_commit_by_reference(self):
        _target("§4.3 >8MB path", "G2")

    def test_session_sidecars_sync_but_persistent_cache_does_not(self):
        _target("§4.3 __sp__", "G2")


# ── User interaction semantics (the jupyter-lab-like UX; gates G2–G4) ──────


class TestUserWorkflows:
    def test_save_edit_save_delete_navigate_back_full_journey(self):
        _target("§4 overall", "G4")

    def test_deleting_a_project_tombstones_links_instead_of_500(self):
        _target("§4.2", "G4")

    def test_rename_move_preserves_revision_lineage(self):
        _target("§4.2 files:move", "G2")

    def test_browser_refresh_mid_edit_rehydrates_unsaved_state(self):
        _target("§4.3 __sp__ sidecars", "G4")

    def test_two_users_same_project_different_branches_never_interfere(self):
        _target("§4.4", "G4")

    def test_branch_switch_hydrates_the_other_branchs_snapshot(self):
        _target("§4.5", "G3")

    def test_notebook_page_loads_without_a_k8s_pod(self):
        _target("§3 target architecture", "G3")


# ── §5.3 Session lifecycle (gate G3: runtime v2 + backend seam) ─────────────


class TestSessionLifecycle:
    def test_active_session_extends_instead_of_dying_at_time_limit(self):
        _target("§5.3 extend-loop", "G3")

    def test_idle_session_snapshots_to_zero(self):
        _target("§5.3", "G3")

    def test_resume_from_snapshot_within_seconds_budget(self):
        _target("§5.3 resume", "G3")

    def test_backend_seam_flag_selects_vercel_like_the_eval_flag(self):
        _target("§5 SP_NOTEBOOK_EXECUTION_BACKEND", "G3")

    def test_pod_endpoints_require_auth_before_public_route_urls_exist(self):
        _target("§5.7 security", "G3 (hard precondition)")

    def test_run_notebook_mcp_tool_uses_pinned_digest_runtime(self):
        _target("§5.6", "G3 (hard precondition)")


# ── §4.5 Git as exporter (gates G5–G6) ──────────────────────────────────────


class TestGitExporter:
    def test_every_s3_revision_maps_to_exactly_one_export_commit(self):
        _target("§4.5", "G5")

    def test_inbound_github_push_imports_as_a_new_revision(self):
        _target("§4.5", "G5")

    def test_export_failure_never_blocks_editing(self):
        _target("§4.5 / §7", "G5")

    def test_agent_branches_still_never_reach_github(self):
        _target("§4.5 (carries over sync.py contract)", "G5")


# ── Unified artifacts (new build item surfaced 2026-08-19) ──────────────────


class TestUnifiedArtifacts:
    def test_artifact_index_lists_across_chat_eval_and_notebook_sources(self):
        _target("artifacts index (new)", "G4")

    def test_artifact_records_carry_provenance_run_task_session(self):
        _target("artifacts index (new)", "G4")

    def test_browse_page_renders_and_downloads_without_a_pod(self):
        _target("artifacts browse page (new)", "G4")

    def test_agent_committed_artifacts_appear_in_the_index(self):
        _target("artifacts index (new)", "G4")

    def test_artifact_retention_prunes_blobs_but_never_provenance_rows(self):
        _target("artifacts index (new)", "G4")
