"""The dbt project an eval run evaluates comes from the eval configuration.

Config side: the project repository binding is verified and canonicalized at
save time with the same rules as the eval repository, and a self-host local
path is checked against projects_dir in the form, not inside a run.

Runner side: the tarball is cloned from the configured repository and branch,
a manifest ``project_repo`` only produces a warning, and a run with no project
configured fails fast with the public precondition error.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from gateway.api.eval_config import EvalConfig, verify_eval_config
from gateway.config.evals import get_eval_run_settings
from gateway.evals import runner
from gateway.evals.manifest import PROJECT_REPO_IGNORED, load_eval_set
from gateway.store import github as github_store

ORG = "org-a"
RUN = "run-20260917-120000-abcdef"


@pytest.fixture(autouse=True)
def _settings_cache():
    get_eval_run_settings.cache_clear()
    yield
    get_eval_run_settings.cache_clear()


@pytest.fixture
def projects(tmp_path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "projects"
    (root / "dbt-1" / "models").mkdir(parents=True)
    (root / "dbt-1" / "models" / "fct_orders.sql").write_text("select 1", encoding="utf-8")
    monkeypatch.setenv("SP_EVAL_PROJECTS_DIR", str(root))
    return root


@pytest.fixture
def local_mode(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("gateway.runtime.mode.is_cloud_mode", lambda: False)


@pytest.fixture
def cloud_mode(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("gateway.runtime.mode.is_cloud_mode", lambda: True)


def _config(**updates) -> EvalConfig:
    values = {"repo_url": "https://github.com/acme/evals", "connection": "warehouse"}
    values.update(updates)
    return EvalConfig(**values)


def _github(monkeypatch: pytest.MonkeyPatch, repos: list[dict]) -> None:
    installation = SimpleNamespace(status="active")

    async def get_installation(*args, **kwargs):
        return installation

    async def get_valid_token(*args, **kwargs):
        return "installation-token"

    async def list_repos(token):
        assert token == "installation-token"
        return repos

    monkeypatch.setattr(github_store, "get_installation", get_installation)
    monkeypatch.setattr(github_store, "get_valid_token", get_valid_token)
    monkeypatch.setattr("gateway.github_client.list_installation_repos", list_repos)


_STORE = SimpleNamespace(session=object(), org_id=ORG)


class TestConfigModel:
    def test_project_binding_requires_both_identifiers(self) -> None:
        with pytest.raises(ValidationError, match="project_repo_installation_id and project_repo_id"):
            _config(project_repo_url="https://github.com/acme/dbt", project_repo_installation_id="i-1")
        with pytest.raises(ValidationError):
            _config(project_repo_url="https://github.com/acme/dbt", project_repo_id=7)

    @pytest.mark.parametrize("ref", ["main", "release/2026-09", "feature.v2", "hotfix-1"])
    def test_branch_names_are_accepted(self, ref: str) -> None:
        assert _config(project_repo_url="https://github.com/acme/dbt", project_ref=ref).project_ref == ref

    @pytest.mark.parametrize("ref", ["-flag", "a..b", "x/", "with space", "x.lock", "y."])
    def test_unsafe_refs_are_rejected(self, ref: str) -> None:
        with pytest.raises(ValidationError, match="branch name"):
            _config(project_repo_url="https://github.com/acme/dbt", project_ref=ref)

    def test_a_ref_needs_a_github_project(self, local_mode, projects) -> None:
        with pytest.raises(ValidationError, match="project_ref requires"):
            _config(project_repo_url=str(projects / "dbt-1"), project_ref="main")

    def test_no_project_is_a_valid_config(self) -> None:
        cfg = _config()
        assert cfg.project_repo_url == ""
        assert cfg.project_ref == ""


class TestSaveTimeVerification:
    @pytest.mark.asyncio
    async def test_authorized_project_repo_is_canonicalized(self, monkeypatch, cloud_mode) -> None:
        _github(monkeypatch, [{"id": 7, "full_name": "acme/dbt"}])
        cfg = _config(
            project_repo_url="https://github.com/ACME/dbt",
            project_repo_installation_id="installation-1",
            project_repo_id=7,
            project_ref="main",
        )

        verified = await verify_eval_config(_STORE, cfg)

        assert verified.project_repo_url == "https://github.com/acme/dbt.git"
        assert verified.project_ref == "main"
        assert verified.repo_url == "https://github.com/acme/evals"

    @pytest.mark.asyncio
    async def test_unauthorized_installation_is_rejected(self, monkeypatch, cloud_mode) -> None:
        _github(monkeypatch, [{"id": 99, "full_name": "acme/other"}])
        cfg = _config(
            project_repo_url="https://github.com/acme/dbt",
            project_repo_installation_id="installation-1",
            project_repo_id=7,
        )

        with pytest.raises(HTTPException) as exc:
            await verify_eval_config(_STORE, cfg)

        assert exc.value.status_code == 422
        assert "cannot access this repository" in exc.value.detail

    @pytest.mark.asyncio
    async def test_public_github_project_needs_no_installation(self, cloud_mode) -> None:
        cfg = _config(project_repo_url="https://github.com/acme/dbt")
        verified = await verify_eval_config(_STORE, cfg)
        assert verified.project_repo_url == "https://github.com/acme/dbt"

    @pytest.mark.asyncio
    async def test_self_host_accepts_a_local_path_under_projects_dir(self, local_mode, projects) -> None:
        cfg = _config(project_repo_url=str(projects / "dbt-1"))
        verified = await verify_eval_config(_STORE, cfg)
        assert verified.project_repo_url == str(projects / "dbt-1")

    @pytest.mark.asyncio
    async def test_self_host_rejects_a_missing_local_directory(self, local_mode, projects) -> None:
        with pytest.raises(HTTPException) as exc:
            await verify_eval_config(_STORE, _config(project_repo_url=str(projects / "nope")))
        assert exc.value.status_code == 422
        assert "no directory" in exc.value.detail

    @pytest.mark.asyncio
    async def test_self_host_rejects_a_path_outside_projects_dir(self, local_mode, projects, tmp_path) -> None:
        outside = tmp_path / "elsewhere"
        outside.mkdir()
        with pytest.raises(HTTPException) as exc:
            await verify_eval_config(_STORE, _config(project_repo_url=str(outside)))
        assert exc.value.status_code == 422
        assert "dbt project repository" in exc.value.detail

    @pytest.mark.asyncio
    async def test_cloud_rejects_a_local_path_at_save(self, cloud_mode, projects) -> None:
        with pytest.raises(HTTPException) as exc:
            await verify_eval_config(_STORE, _config(project_repo_url=str(projects / "dbt-1")))
        assert exc.value.status_code == 422
        assert "only https://github.com/ repositories" in exc.value.detail


class _FakeObjectStore:
    def __init__(self) -> None:
        self.uploaded: list[tuple[str, str]] = []

    def project_tarball_key(self, org_id: str, run_id: str) -> str:
        return f"evals/{org_id}/runs/{run_id}/project.tgz"

    async def upload_file(self, key: str, path: str, content_type: str) -> None:
        assert content_type == "application/gzip"
        assert Path(path).is_file()
        self.uploaded.append((key, path))

    async def presign_get(self, key: str, expires_s: int) -> str:
        return f"https://s3.example/{key}?ttl={expires_s}"


class TestShipProjectTarball:
    @pytest.mark.asyncio
    async def test_clones_the_configured_repo_and_branch(self, monkeypatch, cloud_mode, projects) -> None:
        calls: list[list[str]] = []

        async def fake_authed_clone_url(org_id, repo_url, *, repo_installation_id=None, repo_id=None):
            assert (org_id, repo_url) == (ORG, "https://github.com/acme/dbt.git")
            assert (repo_installation_id, repo_id) == ("installation-1", 7)
            return "https://x-access-token:tok@github.com/acme/dbt.git"

        async def fake_git(args, cwd=None, timeout=120):
            calls.append(list(args))
            if args[0] == "clone":
                dest = Path(args[-1])
                (dest / "models").mkdir(parents=True)
                (dest / "models" / "fct_orders.sql").write_text("select 1", encoding="utf-8")
                (dest / ".git").mkdir()
                return 0, ""
            return 0, "abc123def456\n"

        monkeypatch.setattr(runner, "_authed_clone_url", fake_authed_clone_url)
        monkeypatch.setattr(runner, "_git", fake_git)
        obj = _FakeObjectStore()
        cfg = {
            "project_repo_url": "https://github.com/acme/dbt.git",
            "project_repo_installation_id": "installation-1",
            "project_repo_id": 7,
            "project_ref": "release/2026-09",
        }

        url, ref, models = await runner._ship_project_tarball(ORG, RUN, cfg, obj)

        clone = calls[0]
        assert clone[:3] == ["clone", "--depth", "1"]
        assert clone[3:5] == ["--branch", "release/2026-09"]
        assert clone[5] == "https://x-access-token:tok@github.com/acme/dbt.git"
        assert ref == "abc123def456"
        assert [m["name"] for m in models] == ["fct_orders"]
        assert obj.uploaded[0][0] == f"evals/{ORG}/runs/{RUN}/project.tgz"
        assert url.startswith("https://s3.example/")

    @pytest.mark.asyncio
    async def test_default_branch_when_ref_is_empty(self, monkeypatch, cloud_mode) -> None:
        calls: list[list[str]] = []

        async def fake_authed_clone_url(org_id, repo_url, **kwargs):
            return repo_url

        async def fake_git(args, cwd=None, timeout=120):
            calls.append(list(args))
            if args[0] == "clone":
                Path(args[-1]).mkdir(parents=True)
                return 0, ""
            return 0, "feedface\n"

        monkeypatch.setattr(runner, "_authed_clone_url", fake_authed_clone_url)
        monkeypatch.setattr(runner, "_git", fake_git)

        _, ref, _ = await runner._ship_project_tarball(
            ORG, RUN, {"project_repo_url": "https://github.com/acme/dbt", "project_ref": ""}, _FakeObjectStore()
        )

        assert "--branch" not in calls[0]
        assert ref == "feedface"

    @pytest.mark.asyncio
    async def test_self_host_local_path_is_copied(self, local_mode, projects) -> None:
        obj = _FakeObjectStore()
        _, ref, models = await runner._ship_project_tarball(
            ORG, RUN, {"project_repo_url": str(projects / "dbt-1")}, obj
        )
        assert ref.startswith("local-")
        assert [m["name"] for m in models] == ["fct_orders"]
        assert len(obj.uploaded) == 1

    @pytest.mark.asyncio
    async def test_no_project_configured_is_refused(self, cloud_mode) -> None:
        with pytest.raises(runner.RepoRefused, match=runner.PROJECT_REPO_REQUIRED):
            await runner._ship_project_tarball(ORG, RUN, {"project_repo_url": ""}, _FakeObjectStore())

    @pytest.mark.asyncio
    async def test_cloud_refuses_a_local_path(self, cloud_mode, projects) -> None:
        with pytest.raises(runner.RepoRefused):
            await runner._ship_project_tarball(ORG, RUN, {"project_repo_url": str(projects / "dbt-1")}, _FakeObjectStore())


class _FakeRunDB:
    """Records every run update; the run row and config are fixed by the test."""

    def __init__(self, run: dict, cfg: dict) -> None:
        self.run = run
        self.cfg = cfg
        self.updates: list[dict] = []

    async def update_run(self, **fields) -> None:
        self.updates.append(fields)

    async def get_run(self) -> dict:
        return dict(self.run)

    async def store(self):
        cfg = self.cfg

        class _Session:
            async def close(self) -> None:
                return None

        class _Store:
            async def get_eval_config(self) -> dict:
                return dict(cfg)

            async def list_knowledge_docs(self, **kwargs) -> list:
                return []

        return _Session(), _Store()


@pytest.fixture
def run_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SP_EVAL_S3_BUCKET", "sp-eval-runs")
    monkeypatch.setenv("SP_EVAL_RUNNER_IMAGE", "ghcr.io/x/runner@sha256:" + "a" * 64)


def _install_fake_db(monkeypatch: pytest.MonkeyPatch, cfg: dict) -> _FakeRunDB:
    run = {"id": RUN, "org_id": ORG, "status": "preparing", "repo_url": cfg.get("repo_url", ""), "task_filter": None}
    db = _FakeRunDB(run, cfg)
    monkeypatch.setattr(runner, "RunDB", lambda org_id, run_id: db)
    monkeypatch.setattr(runner, "get_object_store", lambda: _FakeObjectStore())
    return db


class TestRunPreconditions:
    @pytest.mark.asyncio
    async def test_missing_project_fails_fast_before_any_clone(self, monkeypatch, run_env) -> None:
        db = _install_fake_db(monkeypatch, {"repo_url": "https://github.com/acme/evals", "project_repo_url": ""})

        async def no_fetch(*args, **kwargs):
            raise AssertionError("the eval repo must not be fetched when no project is configured")

        monkeypatch.setattr(runner, "fetch_eval_repo", no_fetch)

        await runner._execute_run_inner(ORG, RUN, api_key=None)

        failed = [u for u in db.updates if u.get("status") == "failed"]
        assert len(failed) == 1
        assert failed[0]["error"] == "Select the dbt project repository in the eval configuration"

    @pytest.mark.asyncio
    async def test_manifest_project_repo_is_ignored_with_a_warning(self, monkeypatch, run_env, tmp_path) -> None:
        cfg = {
            "repo_url": "https://github.com/acme/evals",
            "project_repo_url": "https://github.com/acme/dbt",
            "max_tasks": 0,
        }
        db = _install_fake_db(monkeypatch, cfg)
        # A task filter that matches nothing stops the run right after the
        # manifest is loaded, before any branch or sandbox work.
        db.run["task_filter"] = ["no-such-task"]

        async def fake_fetch(org_id, repo_url, dest, settings, **kwargs):
            dest.mkdir(parents=True, exist_ok=True)
            manifest = {
                "name": "legacy",
                "project_repo": "https://github.com/acme/old-dbt",
                "tasks": [{"id": "q1", "prompt_text": "how many?", "gt": "1"}],
            }
            (dest / "eval.json").write_text(json.dumps(manifest), encoding="utf-8")
            return "deadbeef"

        monkeypatch.setattr(runner, "fetch_eval_repo", fake_fetch)

        await runner._execute_run_inner(ORG, RUN, api_key=None)

        warned = [u for u in db.updates if "progress" in u and u["progress"].get("warnings")]
        assert warned, db.updates
        assert warned[0]["progress"]["warnings"] == [PROJECT_REPO_IGNORED]
        assert PROJECT_REPO_IGNORED == (
            "eval.json project_repo is ignored; the dbt project comes from the eval configuration"
        )
        failed = [u for u in db.updates if u.get("status") == "failed"]
        assert failed and failed[0]["error"].startswith("no tasks selected")


class TestProgressCarriesWarnings:
    def test_derive_progress_exposes_warnings(self) -> None:
        run = {"id": RUN, "status": "running", "progress": {"phase": "running", "warnings": ["w1"]}}
        assert runner.derive_progress(run)["warnings"] == ["w1"]

    def test_derive_progress_defaults_to_no_warnings(self) -> None:
        assert runner.derive_progress({"id": RUN, "status": "preparing"})["warnings"] == []

    @pytest.mark.asyncio
    async def test_board_keeps_warnings_on_every_flush(self) -> None:
        db = _FakeRunDB({}, {})
        board = runner.ProgressBoard(db, total=1, warnings=["w1"])  # type: ignore[arg-type]
        await board.finished()
        assert db.updates[-1]["progress"]["warnings"] == ["w1"]


def test_manifest_without_project_repo_has_no_warning(tmp_path: Path) -> None:
    repo = tmp_path / "set"
    repo.mkdir()
    (repo / "eval.json").write_text(
        json.dumps({"tasks": [{"id": "q1", "prompt_text": "n?", "gt": "1"}]}), encoding="utf-8"
    )
    assert load_eval_set(repo).warnings == []
