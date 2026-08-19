"""Three-tier GitHub pull/store flow (spec §4.3 REVISED + §4.5).

    browser = unsaved | S3 revisions = saved working copy | GitHub = canonical

Covers workspace_store/github_sync.py end to end, hermetically:
- moto stands in for S3, aiosqlite for Postgres,
- a local repo on disk stands in for GitHub (same pattern as
  test_project_system_e2e.py),
- the project's bare repo lives under a per-test REPOS_ROOT.

Contracts proven here:
- connect → import produces revision 0 with the repo's files,
- inbound repo change → import produces a new revision (and is idempotent),
- export produces exactly one commit per revision, with matching tree
  content, recorded as export_commit_sha,
- re-export is a no-op returning the recorded sha,
- agent branches (signalpilot-agent/*, analysis/*) never reach the remote,
- export failure (unreachable remote) raises but leaves revisions intact.
"""

from __future__ import annotations

import subprocess
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from gateway.db.models import GatewayBase, GatewayWorkspaceRevision

ORG = "test-org"
BUCKET = "sp-workspace-test"

_GIT_ID = ["-c", "user.email=t@test", "-c", "user.name=test"]


def _pid() -> str:
    return str(uuid.uuid4())


def _git(*args: str, cwd: str | Path | None = None) -> str:
    result = subprocess.run(
        ["git", *_GIT_ID, *args],
        cwd=str(cwd) if cwd else None,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _make_remote(tmp_path: Path, name: str, files: dict[str, str]) -> str:
    """A local stand-in for a GitHub repo with real content."""
    src = tmp_path / name
    src.mkdir()
    _git("init", "--initial-branch", "main", str(src))
    for rel, text in files.items():
        p = src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    _git("add", "-A", cwd=src)
    _git("commit", "-m", "remote content", cwd=src)
    _git("config", "receive.denyCurrentBranch", "ignore", cwd=src)
    return str(src)


def _remote_commit(remote: str, rel: str, text: str) -> str:
    p = Path(remote) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    _git("add", "-A", cwd=remote)
    _git("commit", "-m", "remote update", cwd=remote)
    return _git("rev-parse", "HEAD", cwd=remote).strip()


# ── Hermetic fixtures (scaffold-suite pattern: moto S3 + aiosqlite) ─────────


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
def repos(monkeypatch, tmp_path):
    from gateway.git import repos as repos_mod

    monkeypatch.setattr(repos_mod, "REPOS_ROOT", tmp_path / "repos")
    (tmp_path / "repos").mkdir()
    return repos_mod


@pytest.fixture
def ws(storage):
    from gateway.workspace_store import WorkspaceStore

    return WorkspaceStore(storage)


def _connect(repos, tmp_path, files: dict[str, str]) -> tuple[str, str]:
    """The connect flow: create project scaffold, link the fake GitHub repo."""
    project_id = _pid()
    remote = _make_remote(tmp_path, f"gh-{project_id[:8]}", files)
    repos.init_bare_repo(project_id)
    repos.clone_from_remote(project_id, remote)
    return project_id, remote


async def _revision_row(db, project_id: str, branch: str, revision: int) -> GatewayWorkspaceRevision:
    row = (
        await db.execute(
            select(GatewayWorkspaceRevision).where(
                GatewayWorkspaceRevision.project_id == project_id,
                GatewayWorkspaceRevision.branch == branch,
                GatewayWorkspaceRevision.revision == revision,
            )
        )
    ).scalars().one_or_none()
    assert row is not None, f"no revision row {revision} for {project_id}@{branch}"
    return row


async def _commit_file(ws, db, project_id: str, path: str, content: bytes, branch="main"):
    from gateway.workspace_store.store import Upsert

    return await ws.commit_at_head(
        db,
        org_id=ORG,
        project_id=project_id,
        branch=branch,
        upserts=[Upsert(path=path, content=content)],
        deletes=[],
        created_by="tester",
    )


# ── Pull: connect → import ───────────────────────────────────────────────────


class TestImport:
    @pytest.mark.asyncio
    async def test_connect_import_produces_revision_zero_with_repo_files(
        self, repos, tmp_path, storage, db, ws
    ):
        from gateway.workspace_store.github_sync import import_repo_to_revisions

        project_id, _ = _connect(
            repos, tmp_path,
            {"models/orders.sql": "select 1", "README.md": "# hi\n"},
        )
        result = await import_repo_to_revisions(
            db, storage, org_id=ORG, project_id=project_id, branch="main"
        )
        assert result.imported is True
        assert result.revision == 0

        manifest = await ws.load_manifest(db, org_id=ORG, project_id=project_id, branch="main")
        assert manifest.revision == 0
        assert sorted(manifest.paths()) == ["README.md", "models/orders.sql"]
        entry, blob = await ws.read_file(
            db, org_id=ORG, project_id=project_id, branch="main", path="models/orders.sql"
        )
        assert blob == b"select 1"

    @pytest.mark.asyncio
    async def test_reimport_of_unchanged_repo_is_a_noop(self, repos, tmp_path, storage, db, ws):
        from gateway.workspace_store.github_sync import import_repo_to_revisions

        project_id, _ = _connect(repos, tmp_path, {"a.txt": "x"})
        first = await import_repo_to_revisions(db, storage, org_id=ORG, project_id=project_id)
        assert first.imported and first.revision == 0

        second = await import_repo_to_revisions(db, storage, org_id=ORG, project_id=project_id)
        assert second.imported is False
        assert second.revision == 0
        rows = await ws.list_revisions(db, org_id=ORG, project_id=project_id, branch="main")
        assert [r.revision for r in rows] == [0]

    @pytest.mark.asyncio
    async def test_inbound_repo_change_imports_as_a_new_revision(
        self, repos, tmp_path, storage, db, ws
    ):
        from gateway.git import sync as git_sync
        from gateway.workspace_store.github_sync import import_repo_to_revisions

        project_id, remote = _connect(repos, tmp_path, {"a.txt": "v1"})
        await import_repo_to_revisions(db, storage, org_id=ORG, project_id=project_id)

        # Upstream commits on GitHub, gateway pulls (fetch endpoint's path).
        _git("checkout", "--detach", cwd=remote)
        sha = _remote_commit(remote, "a.txt", "v2")
        _git("update-ref", "refs/heads/main", sha, cwd=remote)
        pulled = git_sync.pull_branch(project_id, remote, "main")
        assert pulled.get("pulled") is True

        result = await import_repo_to_revisions(db, storage, org_id=ORG, project_id=project_id)
        assert result.imported is True
        assert result.revision == 1
        _, blob = await ws.read_file(
            db, org_id=ORG, project_id=project_id, branch="main", path="a.txt"
        )
        assert blob == b"v2"
        # Prior revision still serves the old content — history, not erasure.
        _, old = await ws.read_file(
            db, org_id=ORG, project_id=project_id, branch="main", path="a.txt", revision=0
        )
        assert old == b"v1"

    @pytest.mark.asyncio
    async def test_import_records_deletions_from_the_repo(self, repos, tmp_path, storage, db, ws):
        from gateway.git import sync as git_sync
        from gateway.workspace_store.github_sync import import_repo_to_revisions

        project_id, remote = _connect(repos, tmp_path, {"keep.txt": "k", "drop.txt": "d"})
        await import_repo_to_revisions(db, storage, org_id=ORG, project_id=project_id)

        _git("checkout", "--detach", cwd=remote)
        (Path(remote) / "drop.txt").unlink()
        _git("add", "-A", cwd=remote)
        _git("commit", "-m", "drop", cwd=remote)
        sha = _git("rev-parse", "HEAD", cwd=remote).strip()
        _git("update-ref", "refs/heads/main", sha, cwd=remote)
        git_sync.pull_branch(project_id, remote, "main")

        result = await import_repo_to_revisions(db, storage, org_id=ORG, project_id=project_id)
        assert result.imported is True
        manifest = await ws.load_manifest(db, org_id=ORG, project_id=project_id, branch="main")
        assert manifest.paths() == ["keep.txt"]


# ── Store: export → commit → push ───────────────────────────────────────────


class TestExport:
    @pytest.mark.asyncio
    async def test_export_commits_matching_tree_and_records_sha(
        self, repos, tmp_path, storage, db, ws
    ):
        from gateway.workspace_store.github_sync import (
            export_revision_to_git,
            import_repo_to_revisions,
        )

        project_id, remote = _connect(repos, tmp_path, {"base.txt": "b"})
        await import_repo_to_revisions(db, storage, org_id=ORG, project_id=project_id)
        # A user edit lands in the S3 working copy (revision 1).
        await _commit_file(ws, db, project_id, "nb/analysis.py", b"df = 1\r\n# bytes\n")

        rp = repos.repo_path(project_id)
        before = int(_git("rev-list", "--count", "main", cwd=rp).strip())

        result = await export_revision_to_git(
            db, storage, org_id=ORG, project_id=project_id, branch="main", remote_url=remote
        )
        assert result.revision == 1
        assert result.pushed is True

        # Exactly one new commit, tree content matches the manifest exactly.
        after = int(_git("rev-list", "--count", "main", cwd=rp).strip())
        assert after == before + 1
        assert _git("rev-parse", "main", cwd=rp).strip() == result.commit_sha
        shown = subprocess.run(
            ["git", "show", f"{result.commit_sha}:nb/analysis.py"],
            cwd=str(rp), check=True, capture_output=True,
        ).stdout
        assert shown == b"df = 1\r\n# bytes\n"
        names = _git("ls-tree", "-r", "--name-only", result.commit_sha, cwd=rp).split()
        assert sorted(names) == ["base.txt", "nb/analysis.py"]

        # The remote (fake GitHub) received the same commit.
        assert _git("rev-parse", "main", cwd=remote).strip() == result.commit_sha

        # export_commit_sha recorded on exactly that revision row.
        row = await _revision_row(db, project_id, "main", 1)
        assert row.export_commit_sha == result.commit_sha
        row0 = await _revision_row(db, project_id, "main", 0)
        assert row0.export_commit_sha is None

    @pytest.mark.asyncio
    async def test_reexport_is_a_noop_returning_the_recorded_sha(
        self, repos, tmp_path, storage, db, ws
    ):
        from gateway.workspace_store.github_sync import export_revision_to_git

        project_id = _pid()
        remote = _make_remote(tmp_path, "gh-reexp", {"seed.txt": "s"})
        repos.init_bare_repo(project_id)
        repos.clone_from_remote(project_id, remote)
        await _commit_file(ws, db, project_id, "one.txt", b"1")

        rp = repos.repo_path(project_id)
        first = await export_revision_to_git(
            db, storage, org_id=ORG, project_id=project_id, branch="main", remote_url=remote
        )
        count_after_first = int(_git("rev-list", "--count", "main", cwd=rp).strip())

        second = await export_revision_to_git(
            db, storage, org_id=ORG, project_id=project_id, branch="main", remote_url=remote
        )
        assert second.commit_sha == first.commit_sha
        assert second.pushed is False
        assert second.push_skipped_reason == "already exported"
        assert int(_git("rev-list", "--count", "main", cwd=rp).strip()) == count_after_first

    @pytest.mark.asyncio
    async def test_each_revision_maps_to_exactly_one_export_commit(
        self, repos, tmp_path, storage, db, ws
    ):
        from gateway.workspace_store.github_sync import export_revision_to_git

        project_id = _pid()
        remote = _make_remote(tmp_path, "gh-map", {"seed.txt": "s"})
        repos.init_bare_repo(project_id)
        repos.clone_from_remote(project_id, remote)

        await _commit_file(ws, db, project_id, "a.txt", b"a")  # revision 0
        await _commit_file(ws, db, project_id, "b.txt", b"b")  # revision 1

        r0 = await export_revision_to_git(
            db, storage, org_id=ORG, project_id=project_id, branch="main",
            revision=0, remote_url=remote,
        )
        r1 = await export_revision_to_git(
            db, storage, org_id=ORG, project_id=project_id, branch="main",
            revision=1, remote_url=remote,
        )
        assert r0.commit_sha != r1.commit_sha
        assert (await _revision_row(db, project_id, "main", 0)).export_commit_sha == r0.commit_sha
        assert (await _revision_row(db, project_id, "main", 1)).export_commit_sha == r1.commit_sha
        # r1's commit sits on top of r0's — one commit per revision, chained.
        rp = repos.repo_path(project_id)
        parent = _git("rev-parse", f"{r1.commit_sha}^", cwd=rp).strip()
        assert parent == r0.commit_sha

    @pytest.mark.asyncio
    async def test_agent_branches_never_reach_the_remote(
        self, repos, tmp_path, storage, db, ws
    ):
        from gateway.workspace_store.github_sync import export_revision_to_git

        project_id = _pid()
        remote = _make_remote(tmp_path, "gh-agent", {"seed.txt": "s"})
        repos.init_bare_repo(project_id)
        repos.clone_from_remote(project_id, remote)

        for branch in ("signalpilot-agent/run-7", "analysis/notion/req-1-slug"):
            repos.ensure_branch_from(project_id, branch, "main")
            await _commit_file(ws, db, project_id, "agent.txt", b"local only", branch=branch)
            result = await export_revision_to_git(
                db, storage, org_id=ORG, project_id=project_id, branch=branch, remote_url=remote
            )
            # Committed locally (revision ↔ commit bookkeeping still holds)...
            assert result.commit_sha
            assert result.pushed is False
            assert (await _revision_row(db, project_id, branch, 0)).export_commit_sha == result.commit_sha
            # ...but the remote never sees the branch.
            remote_branches = _git("branch", "--list", "-a", cwd=remote)
            assert branch not in remote_branches

    @pytest.mark.asyncio
    async def test_export_failure_raises_but_leaves_revisions_intact(
        self, repos, tmp_path, storage, db, ws
    ):
        from gateway.workspace_store.github_sync import (
            GitHubExportError,
            export_revision_to_git,
        )

        project_id = _pid()
        repos.init_bare_repo(project_id)
        await _commit_file(ws, db, project_id, "work.txt", b"precious")

        unreachable = str(tmp_path / "no-such-remote")
        with pytest.raises(GitHubExportError):
            await export_revision_to_git(
                db, storage, org_id=ORG, project_id=project_id, branch="main",
                remote_url=unreachable,
            )

        # Editing is never blocked: the revision history and content survive,
        # and the failed export recorded nothing (so a retry re-pushes).
        rows = await ws.list_revisions(db, org_id=ORG, project_id=project_id, branch="main")
        assert [r.revision for r in rows] == [0]
        assert rows[0].export_commit_sha is None
        _, blob = await ws.read_file(
            db, org_id=ORG, project_id=project_id, branch="main", path="work.txt"
        )
        assert blob == b"precious"
        # And a subsequent commit still works — the store is not wedged.
        manifest = await _commit_file(ws, db, project_id, "more.txt", b"still editing")
        assert manifest.revision == 1

    @pytest.mark.asyncio
    async def test_retry_after_failed_push_converges_and_records_sha(
        self, repos, tmp_path, storage, db, ws
    ):
        from gateway.workspace_store.github_sync import (
            GitHubExportError,
            export_revision_to_git,
        )

        project_id = _pid()
        repos.init_bare_repo(project_id)
        await _commit_file(ws, db, project_id, "f.txt", b"x")

        with pytest.raises(GitHubExportError):
            await export_revision_to_git(
                db, storage, org_id=ORG, project_id=project_id, branch="main",
                remote_url=str(tmp_path / "gone"),
            )

        # The remote becomes reachable (empty bare repo — no unrelated history).
        remote = str(tmp_path / "gh-retry.git")
        _git("init", "--bare", "--initial-branch", "main", remote)
        result = await export_revision_to_git(
            db, storage, org_id=ORG, project_id=project_id, branch="main", remote_url=remote
        )
        assert result.pushed is True
        assert (await _revision_row(db, project_id, "main", 0)).export_commit_sha == result.commit_sha

    @pytest.mark.asyncio
    async def test_roundtrip_import_export_import_is_stable(
        self, repos, tmp_path, storage, db, ws
    ):
        """Pull → edit → store → pull again: the re-import after an export
        sees identical content and creates no spurious revision."""
        from gateway.workspace_store.github_sync import (
            export_revision_to_git,
            import_repo_to_revisions,
        )

        project_id, remote = _connect(repos, tmp_path, {"m.sql": "select 1"})
        await import_repo_to_revisions(db, storage, org_id=ORG, project_id=project_id)
        await _commit_file(ws, db, project_id, "m.sql", b"select 2")
        exported = await export_revision_to_git(
            db, storage, org_id=ORG, project_id=project_id, branch="main", remote_url=remote
        )
        assert exported.pushed is True

        result = await import_repo_to_revisions(db, storage, org_id=ORG, project_id=project_id)
        assert result.imported is False  # git head == S3 head, by construction
        assert result.revision == 1
