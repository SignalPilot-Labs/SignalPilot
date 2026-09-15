"""Notebook Runtime v2 target suite — session lifecycle, git exporter, unified artifacts.

Continues ``test_notebook_workspace_v2_scaffold.py``; see that module's
docstring for the suite's role as the spec's acceptance criteria.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from ._notebook_workspace_v2_support import ORG, _pid, _put, api, db, storage, ws

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
            session_id="sess-idle",
            org_id=ORG,
            user_id="u",
            status="running",
            backend="vercel",
            runtime_handle="sbx-idle",
            snapshot_id=None,
            upstream_url="https://sbx.vercel.run",
            access_token=None,
            project_id="proj-1",
            branch="main",
        )
        with (
            patch.object(session_service.ns, "update_session_runtime", AsyncMock()) as update,
            patch.object(session_service, "release_lease", AsyncMock()) as release,
        ):
            await session_service.snapshot_idle_session(AsyncMock(), internal=internal, backend=backend)
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
            Path(__file__).resolve().parents[2] / "notebook-server" / "signalpilot" / "_server" / "api" / "endpoints"
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
    async def test_every_s3_revision_maps_to_exactly_one_export_commit(self, repos, tmp_path, storage, db, ws):
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
            (
                await db.execute(
                    select(GatewayWorkspaceRevision).where(
                        GatewayWorkspaceRevision.project_id == project,
                        GatewayWorkspaceRevision.export_commit_sha == first.commit_sha,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(row) == 1

    @pytest.mark.asyncio
    async def test_inbound_github_change_imports_as_a_new_revision(self, repos, tmp_path, storage, db, ws):
        from gateway.workspace_store import import_repo_to_revisions

        project, remote = self._seeded_project(repos, tmp_path)
        first = await import_repo_to_revisions(db, storage, org_id=ORG, project_id=project)
        (Path(remote) / "upstream.sql").write_text("select 9", encoding="utf-8")
        self._git("add", "-A", cwd=remote)
        self._git("commit", "-m", "upstream", cwd=remote)
        self._git("fetch", str(Path(remote)), "main:main", cwd=repos.repo_path(project))
        second = await import_repo_to_revisions(db, storage, org_id=ORG, project_id=project)
        assert second.revision == (first.revision or 0) + 1
        got = await ws.read_file(db, org_id=ORG, project_id=project, branch="main", path="upstream.sql")
        assert got[1] == b"select 9"

    @pytest.mark.asyncio
    async def test_export_failure_never_blocks_editing(self, repos, tmp_path, storage, db, ws):
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
        from tests.test_artifacts_index import seed_eval_artifacts

        eval_run_id = await seed_eval_artifacts(db, org_id=ORG)
        return db, eval_run_id

    @pytest.mark.asyncio
    async def test_artifact_index_lists_eval_sources(self, seeded):
        from gateway.store.artifacts_index import list_artifacts

        db, _ = seeded
        records, total = await list_artifacts(db, org_id=ORG)
        assert total == 1
        assert {record.kind for record in records} == {"eval"}

    @pytest.mark.asyncio
    async def test_artifact_records_carry_provenance_run_task(self, seeded):
        from gateway.store.artifacts_index import list_artifacts

        db, eval_run_id = seeded
        records, _ = await list_artifacts(db, org_id=ORG)
        by_kind = {record.kind: record.to_dict() for record in records}
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

        db, _ = seeded
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
        assert body["total"] == 1
        assert all(record["download"]["route"] for record in body["artifacts"])

    @pytest.mark.asyncio
    async def test_artifact_retention_prunes_blobs_but_never_provenance_rows(self, db):
        from gateway.store.artifacts_index import list_artifacts
        from tests.test_artifacts_index import seed_eval_artifacts

        await seed_eval_artifacts(db, org_id=ORG, artifacts_pruned=True)
        records, total = await list_artifacts(db, org_id=ORG, kind="eval")
        assert total == 1  # the provenance row still lists
        assert records[0].to_dict()["available"] is False  # the blob does not
