"""Tests for the eval execution-backend seam (gateway/evals/backends.py).

Covers backend selection (cloud never touches the Docker socket) and the
Docker backend's hardening.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gateway.config.evals import EvalRunSettings
from gateway.evals.backends import (
    ContainerRun,
    DockerBackend,
    get_execution_backend,
)

# Cloud mode requires the runner image to be digest-pinned, so the shared fixture
# uses a digest; the local-mode cases override it with a floating tag.
_DIGEST_IMAGE = "reg.example.com/eval-runner@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


def _postgres_dsn(authority: str) -> str:
    return "postgresql" + "://" + authority


def _settings(**overrides) -> EvalRunSettings:
    base = {
        "SP_EVAL_RUNNER_IMAGE": _DIGEST_IMAGE,
        "SP_EVAL_DOCKER_SOCKET": "/var/run/docker.sock",
        "SP_EVAL_MCP_URL": "http://gateway:3300/mcp",
        "SP_EVAL_TIMEOUT_SECONDS": "600",
    }
    base.update(overrides)
    return EvalRunSettings(**base)


def _spec(**overrides) -> ContainerRun:
    kwargs = {
        "image": "sp-eval-runner:latest",
        "command": ["sh", "-lc", "true"],
        "env": {"SP_PROMPT": "how many orders?", "SP_MODEL": "sonnet"},
        "secret_env": {
            "SP_MCP_JSON_B64": "eyJ4IjoxfQ==",
            "CLAUDE_CODE_OAUTH_TOKEN": "sk-oauth-supersecret",
            "ANTHROPIC_API_KEY": "sk-ant-supersecret",
        },
        "labels": {"run": "run-20260101-010101-aaaaaa", "question": "t1:fan/out"},
        "memory_bytes": 2 * 1024 * 1024 * 1024,
        "nano_cpus": 2_000_000_000,
        "timeout_seconds": 600,
    }
    kwargs.update(overrides)
    return ContainerRun(**kwargs)


# Verify backend selection.


class TestBackendSelection:
    def test_cloud_setup_image_requires_a_digest(self, monkeypatch):
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        with pytest.raises(ValueError, match="must reference a digest"):
            _settings(SP_EVAL_SETUP_IMAGE="registry.example/setup:latest")

    def test_local_setup_image_may_use_a_tag(self, monkeypatch):
        monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)
        settings = _settings(SP_EVAL_SETUP_IMAGE="sp-eval-setup:latest")
        assert settings.setup_image == "sp-eval-setup:latest"

    def test_local_mode_selects_docker(self, monkeypatch):
        monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)
        backend = get_execution_backend(_settings(), org_id="org-1")
        assert isinstance(backend, DockerBackend)

    def test_cloud_mode_without_vercel_backend_raises(self, monkeypatch):
        """The Kubernetes eval backend was removed; cloud requires vercel."""
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        with pytest.raises(RuntimeError, match="SP_EVAL_EXECUTION_BACKEND=vercel"):
            get_execution_backend(_settings(), org_id="org-1")

    def test_cloud_mode_never_constructs_a_docker_transport(self, monkeypatch):
        """Verify that cloud mode does not construct a Unix socket transport."""
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        with patch("httpx.AsyncHTTPTransport") as transport:
            with pytest.raises(RuntimeError):
                get_execution_backend(_settings(), org_id="org-1")
        transport.assert_not_called()

    def test_local_mode_does_construct_a_docker_transport(self, monkeypatch):
        monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)
        with patch("httpx.AsyncHTTPTransport") as transport:
            get_execution_backend(_settings(), org_id="org-1")
        transport.assert_called_once()
        assert transport.call_args[1]["uds"] == "/var/run/docker.sock"


# Verify Docker backend security controls.


class TestDockerBackendHardened:
    @pytest.mark.asyncio
    async def test_manifest_cannot_attach_an_extra_network(self):
        backend = DockerBackend(_settings())
        backend._client.post = AsyncMock()

        with pytest.raises(RuntimeError, match="may not attach"):
            await backend.run(_spec(extra_network="signalpilot_default"))

        backend._client.post.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_create_body_matches_the_pre_seam_shape(self):
        backend = DockerBackend(_settings())

        create = MagicMock(status_code=201)
        create.json.return_value = {"Id": "cid1"}
        wait = MagicMock(status_code=200)
        wait.json.return_value = {"StatusCode": 0}
        logs = MagicMock(content=b"out")
        backend._client.post = AsyncMock(side_effect=[create, MagicMock(status_code=204), wait])
        backend._client.get = AsyncMock(return_value=logs)
        backend._client.delete = AsyncMock()

        exit_code, out = await backend.run(_spec())

        assert (exit_code, out) == (0, "out")
        body = backend._client.post.call_args_list[0][1]["json"]
        assert body["Image"] == "sp-eval-runner:latest"
        assert body["Tty"] is True
        assert body["User"] == "65532:65532"
        assert "HOME=/work" in body["Env"]
        assert body["Labels"]["signalpilot.eval"] == "1"
        assert body["Labels"]["signalpilot.eval.run"] == "run-20260101-010101-aaaaaa"
        assert body["HostConfig"]["Memory"] == 2 * 1024 * 1024 * 1024
        assert body["HostConfig"]["NanoCpus"] == 2_000_000_000
        host = body["HostConfig"]
        assert host["NetworkMode"] == "signalpilot_eval_runtime"
        assert host["ReadonlyRootfs"] is True
        assert host["CapDrop"] == ["ALL"]
        assert host["SecurityOpt"] == ["no-new-privileges:true"]
        assert host["PidsLimit"] == 256
        assert set(host["Tmpfs"]) == {"/work", "/tmp", "/repo"}
        # Docker passes the model credential through the container environment.
        assert "ANTHROPIC_API_KEY=sk-ant-supersecret" in body["Env"]
        backend._client.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_windows_repo_bind_does_not_get_duplicate_tmpfs(self):
        backend = DockerBackend(_settings())
        create = MagicMock(status_code=201)
        create.json.return_value = {"Id": "cid1"}
        wait = MagicMock(status_code=200)
        wait.json.return_value = {"StatusCode": 0}
        backend._client.post = AsyncMock(side_effect=[create, MagicMock(status_code=204), wait])
        backend._client.get = AsyncMock(return_value=MagicMock(content=b"out"))
        backend._client.delete = AsyncMock()

        await backend.run(_spec(binds=["C:/repo/eval-set:/repo:ro"]))

        host = backend._client.post.call_args_list[0][1]["json"]["HostConfig"]
        assert "/repo" not in host["Tmpfs"]


# Verify the task specification builders in runner.py.


def _task(task_id: str = "t1", task_class: str = "write"):
    from gateway.evals.manifest import EvalTask

    return EvalTask(
        id=task_id,
        task_class=task_class,
        kind="query",
        title=task_id,
        why="",
        prompt="p",
        doc="",
        gt="",
        checks=[],
        grade={"kind": "checks"},
    )


class TestRunnerSpecs:
    def test_task_spec_routes_every_credential_through_secret_env(self):
        from gateway.evals.runner import _task_spec

        settings = _settings(
            SP_EVAL_CLAUDE_TOKEN="oauth" + "-tok",
            SP_EVAL_ANTHROPIC_KEY="ant" + "-key",
        )
        spec = _task_spec(
            settings,
            prompt="p",
            model="sonnet",
            mcp_json='{"headers":{"X-API-Key":"sp_live_secret"}}',
            labels={"run": "r"},
        )
        assert set(spec.env) == {"SP_PROMPT", "SP_MODEL"}
        assert set(spec.secret_env) == {
            "SP_MCP_JSON_B64",
            "CLAUDE_CODE_OAUTH_TOKEN",
            "ANTHROPIC_API_KEY",
        }
        # The MCP config embeds the per-run API key, so it is a credential too.
        assert "sp_live_secret" not in repr(spec.env)

    def test_task_spec_keeps_the_branch_dsn_and_tarball_url_secret(self):
        from gateway.evals.runner import _task_spec

        spec = _task_spec(
            _settings(),
            prompt="p",
            model="sonnet",
            mcp_json="{}",
            labels={"run": "r"},
            project_tarball_url="https://s3/x?sig=abc",
            warehouse_dsn=_postgres_dsn("u:pw@wh/eval-abc-t1"),
        )
        assert spec.secret_env["SP_PROJECT_TARBALL_URL"] == "https://s3/x?sig=abc"
        assert spec.secret_env["SP_WAREHOUSE_DSN"] == _postgres_dsn("u:pw@wh/eval-abc-t1")
        assert "SP_WAREHOUSE_DSN" not in spec.env
        assert "SP_PROJECT_TARBALL_URL" not in spec.env

    def test_script_spec_routes_env_file_through_secret_env(self, tmp_path):
        from gateway.evals.manifest import EvalSet
        from gateway.evals.runner import _script_spec

        (tmp_path / "warehouse.env").write_text("# creds\nPGPASSWORD=hunter2\nPGHOST=warehouse\n", encoding="utf-8")
        eval_set = EvalSet(
            name="e",
            description="",
            tasks=[],
            setup={"env_file": "warehouse.env", "timeout_seconds": 900},
        )
        spec = _script_spec(
            _settings(),
            eval_set=eval_set,
            repo_dir=tmp_path,
            repo_url="https://example.com/evals.git",
            script_rel="scripts/t1-setup.sh",
            task=_task("t1"),
            phase="setup",
            run_id="run-20260101-010101-aaaaaa",
            warehouse_dsn=_postgres_dsn("x"),
        )
        assert spec.secret_env == {
            "PGPASSWORD": "hunter2",
            "PGHOST": "warehouse",
            "SP_WAREHOUSE_DSN": _postgres_dsn("x"),
        }
        assert spec.env == {
            "SP_EVAL_TASK": "t1",
            "SP_EVAL_PHASE": "setup",
            "SP_EVAL_REPO_URL": "https://example.com/evals.git",
            "HOME": "/tmp",
        }
        assert spec.timeout_seconds == 900
        assert spec.labels == {"run": "run-20260101-010101-aaaaaa", "task": "t1", "phase": "setup"}

    def test_script_spec_clones_remote_repos_and_never_binds(self, tmp_path):
        from gateway.evals.manifest import EvalSet
        from gateway.evals.runner import _script_spec

        spec = _script_spec(
            _settings(),
            eval_set=EvalSet(name="e", description="", tasks=[], setup={}),
            repo_dir=tmp_path,
            repo_url="https://example.com/evals.git",
            script_rel="scripts/setup.py",
            task=_task(),
            phase="teardown",
            run_id="run-20260101-010101-aaaaaa",
            warehouse_dsn=_postgres_dsn("x"),
        )
        assert spec.binds == []
        cmd = spec.command[-1]
        assert "git clone" in cmd
        assert "python3" in cmd  # .py scripts run under python3
