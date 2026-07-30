"""Tests for the eval execution-backend seam (gateway/evals/backends.py).

Covers backend selection (cloud never touches the Docker socket), every pod
hardening item, and the full mocked-K8s pod lifecycle including timeout and
failure paths.
"""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gateway.config.evals import EvalRunSettings
from gateway.evals.backends import (
    TIMED_OUT,
    ContainerRun,
    DockerBackend,
    KubernetesBackend,
    eval_pod_manifest,
    get_execution_backend,
)


# Cloud mode requires the runner image to be digest-pinned, so the shared fixture
# uses a digest; the local-mode cases override it with a floating tag.
_DIGEST_IMAGE = "reg.example.com/eval-runner@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


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


# ─── Backend selection ───────────────────────────────────────────────────────


class TestBackendSelection:
    def test_local_mode_selects_docker(self, monkeypatch):
        monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)
        backend = get_execution_backend(_settings(), org_id="org-1")
        assert isinstance(backend, DockerBackend)

    def test_cloud_mode_selects_kubernetes(self, monkeypatch):
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        backend = get_execution_backend(_settings(), org_id="org-1")
        assert isinstance(backend, KubernetesBackend)

    def test_cloud_mode_never_constructs_a_docker_transport(self, monkeypatch):
        """The uds transport is the residual risk — it must never be built in cloud."""
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        with patch("httpx.AsyncHTTPTransport") as transport:
            get_execution_backend(_settings(), org_id="org-1")
        transport.assert_not_called()

    def test_local_mode_does_construct_a_docker_transport(self, monkeypatch):
        monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)
        with patch("httpx.AsyncHTTPTransport") as transport:
            get_execution_backend(_settings(), org_id="org-1")
        transport.assert_called_once()
        assert transport.call_args[1]["uds"] == "/var/run/docker.sock"

    def test_kubernetes_backend_requires_org_id(self):
        with pytest.raises(ValueError, match="org_id"):
            KubernetesBackend(_settings(), org_id="")

    @pytest.mark.asyncio
    async def test_cloud_backend_does_not_fall_back_to_docker(self, monkeypatch):
        """A cluster the gateway cannot reach fails the run; it never opens the socket."""
        monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
        monkeypatch.setenv("SP_NOTEBOOK_UPSTREAM_MODE", "pod_ip")
        backend = get_execution_backend(_settings(), org_id="org-1")

        orch = MagicMock()
        orch._ensure_client = AsyncMock()
        orch._core_api = None  # _ensure_client swallows a bad kubeconfig
        with (
            patch("gateway.orchestrator.kubernetes.KubernetesOrchestrator", return_value=orch),
            patch("httpx.AsyncHTTPTransport") as transport,
            pytest.raises(RuntimeError, match="do not fall back to the Docker socket"),
        ):
            await backend.run(_spec())
        transport.assert_not_called()


# ─── Pod manifest hardening ──────────────────────────────────────────────────


@pytest.fixture
def manifest(monkeypatch):
    monkeypatch.setenv("SP_NOTEBOOK_RUNTIME_CLASS", "gvisor")
    monkeypatch.setenv("SP_NOTEBOOK_UPSTREAM_MODE", "pod_ip")
    import importlib

    import gateway.orchestrator.kubernetes as k8s_mod

    importlib.reload(k8s_mod)
    try:
        yield eval_pod_manifest(
            pod_name="sp-eval-abc123def456",
            namespace="sp-eval-0011223344556677",
            spec=_spec(),
            secret_name="sp-eval-env-sp-eval-abc123def456",
        )
    finally:
        monkeypatch.delenv("SP_NOTEBOOK_RUNTIME_CLASS", raising=False)
        importlib.reload(k8s_mod)


class TestPodHardening:
    def test_no_service_account_token(self, manifest):
        """The eval workload must not be able to reach the K8s API at all."""
        assert manifest["spec"]["automountServiceAccountToken"] is False

    def test_gvisor_runtime_class(self, manifest):
        assert manifest["spec"]["runtimeClassName"] == "gvisor"
        assert manifest["spec"]["nodeSelector"] == {"signalpilot.ai/notebook": "true"}
        assert manifest["spec"]["tolerations"][0]["effect"] == "NoSchedule"

    def test_runtime_class_omitted_when_unset(self, monkeypatch):
        monkeypatch.delenv("SP_NOTEBOOK_RUNTIME_CLASS", raising=False)
        monkeypatch.setenv("SP_NOTEBOOK_UPSTREAM_MODE", "pod_ip")
        import importlib

        import gateway.orchestrator.kubernetes as k8s_mod

        importlib.reload(k8s_mod)
        m = eval_pod_manifest(
            pod_name="sp-eval-x", namespace="ns", spec=_spec(), secret_name="s"
        )
        assert "runtimeClassName" not in m["spec"]

    def test_pod_security_context_is_non_root(self, manifest):
        sc = manifest["spec"]["securityContext"]
        assert sc["runAsNonRoot"] is True
        assert sc["runAsUser"] == 10002
        assert sc["seccompProfile"] == {"type": "RuntimeDefault"}

    def test_container_security_context(self, manifest):
        sc = manifest["spec"]["containers"][0]["securityContext"]
        assert sc["runAsNonRoot"] is True
        assert sc["allowPrivilegeEscalation"] is False
        assert sc["readOnlyRootFilesystem"] is True
        assert sc["capabilities"] == {"drop": ["ALL"]}

    def test_writable_scratch_is_emptydir_only(self, manifest):
        """readOnlyRootFilesystem is only viable because every write path is a volume."""
        mounts = {m["mountPath"] for m in manifest["spec"]["containers"][0]["volumeMounts"]}
        assert mounts == {"/work", "/tmp", "/repo"}
        assert all("emptyDir" in v for v in manifest["spec"]["volumes"])
        env = {e["name"]: e["value"] for e in manifest["spec"]["containers"][0]["env"]}
        assert env["HOME"] == "/work"
        assert manifest["spec"]["containers"][0]["workingDir"] == "/work"

    def test_explicit_cpu_and_memory_requests_and_limits(self, manifest):
        res = manifest["spec"]["containers"][0]["resources"]
        assert res["limits"] == {"cpu": "2000m", "memory": "2048Mi"}
        # LimitRange maxLimitRequestRatio is 4 for both cpu and memory.
        assert res["requests"] == {"cpu": "500m", "memory": "512Mi"}

    def test_active_deadline_matches_the_timeout(self, manifest):
        assert manifest["spec"]["activeDeadlineSeconds"] == 600

    def test_active_deadline_tracks_a_different_timeout(self):
        m = eval_pod_manifest(
            pod_name="p", namespace="ns", spec=_spec(timeout_seconds=1800), secret_name="s"
        )
        assert m["spec"]["activeDeadlineSeconds"] == 1800

    def test_restart_policy_never(self, manifest):
        assert manifest["spec"]["restartPolicy"] == "Never"
        assert manifest["spec"]["enableServiceLinks"] is False

    def test_secrets_are_not_inline_in_the_pod_spec(self, manifest):
        """kubectl describe / pod events must not surface the tokens."""
        blob = repr(manifest)
        assert "sk-oauth-supersecret" not in blob
        assert "sk-ant-supersecret" not in blob
        assert "eyJ4IjoxfQ==" not in blob
        assert manifest["spec"]["containers"][0]["envFrom"] == [
            {"secretRef": {"name": "sp-eval-env-sp-eval-abc123def456"}}
        ]
        env_names = {e["name"] for e in manifest["spec"]["containers"][0]["env"]}
        assert env_names == {"HOME", "SP_PROMPT", "SP_MODEL"}

    def test_labels_are_kubernetes_safe(self, manifest):
        labels = manifest["metadata"]["labels"]
        assert labels["signalpilot.ai/eval"] == "1"
        assert labels["signalpilot.ai/eval-run"] == "run-20260101-010101-aaaaaa"
        # 't1:fan/out' is not a legal label value.
        assert labels["signalpilot.ai/eval-question"] == "t1-fan-out"


# ─── Kubernetes lifecycle (mocked API) ───────────────────────────────────────


def _pod_status(phase: str, exit_code: int | None = 0, reason: str | None = None) -> MagicMock:
    state = {"terminated": {"exit_code": exit_code}} if exit_code is not None else {}
    resp = MagicMock()
    resp.to_dict.return_value = {
        "status": {
            "phase": phase,
            "reason": reason,
            "container_statuses": [{"state": state}],
        }
    }
    return resp


def _make_core(pod_phases: list[MagicMock]) -> MagicMock:
    core = MagicMock()
    core.create_namespaced_secret = AsyncMock()
    core.delete_namespaced_secret = AsyncMock()
    core.create_namespaced_pod = AsyncMock()
    core.delete_namespaced_pod = AsyncMock()
    core.patch_namespaced_secret = AsyncMock()
    core.read_namespaced_pod_log = AsyncMock(return_value='{"type":"result","result":"42"}')

    meta = MagicMock()
    meta.name = "sp-eval-pod"
    meta.uid = "pod-uid-1"
    owner_read = MagicMock()
    owner_read.metadata = meta
    # First read is the ownerRef lookup, the rest drive the wait loop.
    core.read_namespaced_pod = AsyncMock(side_effect=[owner_read, *pod_phases])
    return core


def _backend_with(core: MagicMock) -> KubernetesBackend:
    backend = KubernetesBackend(_settings(), org_id="org-1")
    orch = MagicMock()
    orch._core_api = core
    orch.ensure_namespace = AsyncMock(return_value="sp-eval-0011223344556677")
    orch.close = AsyncMock()
    backend._orchestrator = orch
    return backend


class TestKubernetesLifecycle:
    @pytest.mark.asyncio
    async def test_happy_path_creates_waits_reads_and_deletes(self):
        core = _make_core([_pod_status("Running", None), _pod_status("Succeeded", 0)])
        backend = _backend_with(core)

        exit_code, logs = await backend.run(_spec(timeout_seconds=1))

        assert exit_code == 0
        assert logs == '{"type":"result","result":"42"}'
        core.create_namespaced_secret.assert_called_once()
        core.create_namespaced_pod.assert_called_once()
        core.patch_namespaced_secret.assert_called_once()
        core.read_namespaced_pod_log.assert_called_once()
        core.delete_namespaced_pod.assert_called_once()
        core.delete_namespaced_secret.assert_called()

    @pytest.mark.asyncio
    async def test_secret_carries_the_credentials_base64_encoded(self):
        core = _make_core([_pod_status("Succeeded", 0)])
        backend = _backend_with(core)
        await backend.run(_spec(timeout_seconds=1))

        body = core.create_namespaced_secret.call_args[1]["body"]
        assert set(body.data) == {
            "SP_MCP_JSON_B64",
            "CLAUDE_CODE_OAUTH_TOKEN",
            "ANTHROPIC_API_KEY",
        }
        assert base64.b64decode(body.data["ANTHROPIC_API_KEY"]).decode() == "sk-ant-supersecret"

    @pytest.mark.asyncio
    async def test_secret_owner_ref_points_at_the_pod(self):
        core = _make_core([_pod_status("Succeeded", 0)])
        await _backend_with(core).run(_spec(timeout_seconds=1))

        refs = core.patch_namespaced_secret.call_args[1]["body"]["metadata"]["ownerReferences"]
        assert refs[0]["kind"] == "Pod"
        assert refs[0]["uid"] == "pod-uid-1"
        assert refs[0]["blockOwnerDeletion"] is True

    @pytest.mark.asyncio
    async def test_nonzero_exit_code_is_surfaced(self):
        core = _make_core([_pod_status("Failed", 137)])
        exit_code, _ = await _backend_with(core).run(_spec(timeout_seconds=1))
        assert exit_code == 137

    @pytest.mark.asyncio
    async def test_timeout_reports_timed_out_and_still_cleans_up(self):
        core = _make_core([_pod_status("Running", None)] * 50)
        backend = _backend_with(core)

        with patch(
            "gateway.evals.backends.KubernetesBackend._wait_terminal",
            AsyncMock(return_value=TIMED_OUT),
        ):
            exit_code, _ = await backend.run(_spec(timeout_seconds=1))

        assert exit_code == TIMED_OUT
        core.delete_namespaced_pod.assert_called_once()
        core.delete_namespaced_secret.assert_called()

    @pytest.mark.asyncio
    async def test_active_deadline_kill_reports_the_docker_timeout_code(self):
        """kubelet's DeadlineExceeded must grade like the Docker timeout, not a crash."""
        core = _make_core([_pod_status("Failed", 137, reason="DeadlineExceeded")])
        exit_code, _ = await _backend_with(core).run(_spec(timeout_seconds=1))
        assert exit_code == TIMED_OUT

    @pytest.mark.asyncio
    async def test_wait_loop_gives_up_after_the_deadline(self):
        """_wait_terminal itself returns TIMED_OUT rather than polling forever."""
        core = _make_core([])
        core.read_namespaced_pod = AsyncMock(return_value=_pod_status("Running", None))
        backend = _backend_with(core)

        with patch("gateway.evals.backends.asyncio.sleep", AsyncMock()):
            # Deadline is timeout+60; a negative timeout makes it already expired.
            assert await backend._wait_terminal(core, "p", "ns", -120) == TIMED_OUT

    @pytest.mark.asyncio
    async def test_pod_and_secret_deleted_when_the_run_errors(self):
        core = _make_core([])
        core.read_namespaced_pod = AsyncMock(
            side_effect=[MagicMock(metadata=MagicMock(name="p", uid="u")), RuntimeError("api down")]
        )
        backend = _backend_with(core)

        with pytest.raises(RuntimeError, match="api down"):
            await backend.run(_spec(timeout_seconds=1))

        core.delete_namespaced_pod.assert_called_once()
        core.delete_namespaced_secret.assert_called()

    @pytest.mark.asyncio
    async def test_pod_create_failure_removes_the_secret(self):
        core = _make_core([])
        core.create_namespaced_pod = AsyncMock(side_effect=RuntimeError("quota exceeded"))
        backend = _backend_with(core)

        with pytest.raises(RuntimeError, match="quota exceeded"):
            await backend.run(_spec(timeout_seconds=1))

        core.delete_namespaced_secret.assert_called()

    @pytest.mark.asyncio
    async def test_host_bind_mounts_are_refused(self):
        core = _make_core([])
        backend = _backend_with(core)
        with pytest.raises(RuntimeError, match="host bind mounts"):
            await backend.run(_spec(binds=["/host/repo:/repo:ro"]))
        core.create_namespaced_secret.assert_not_called()

    @pytest.mark.asyncio
    async def test_extra_docker_network_is_refused(self):
        core = _make_core([])
        backend = _backend_with(core)
        with pytest.raises(RuntimeError, match="extra docker network"):
            await backend.run(_spec(extra_network="warehouse_net"))

    def test_default_namespace_prefix_matches_the_admission_policy(self):
        """restrict-rbac-writes rule 5 pins signalpilot.dev/tenant to sp-nb-*."""
        assert _settings().k8s_namespace_prefix == "sp-nb"

    @pytest.mark.asyncio
    async def test_namespace_prefix_comes_from_the_eval_setting(self, monkeypatch):
        monkeypatch.setenv("SP_NOTEBOOK_UPSTREAM_MODE", "pod_ip")
        backend = KubernetesBackend(
            _settings(SP_EVAL_K8S_NAMESPACE_PREFIX="sp-nb"), org_id="org-1"
        )

        orch = MagicMock()
        orch._ensure_client = AsyncMock()
        orch._core_api = MagicMock()
        orch.ensure_namespace = AsyncMock(return_value="sp-nb-0011223344556677")
        with patch(
            "gateway.orchestrator.kubernetes.KubernetesOrchestrator", return_value=orch
        ):
            ns = await backend._namespace()

        assert ns == "sp-nb-0011223344556677"
        assert orch._namespace_prefix == "sp-nb"
        orch.ensure_namespace.assert_awaited_once_with("org-1")


# ─── Docker backend keeps today's behaviour ──────────────────────────────────


class TestDockerBackendUnchanged:
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
        assert body["Labels"]["signalpilot.eval"] == "1"
        assert body["Labels"]["signalpilot.eval.run"] == "run-20260101-010101-aaaaaa"
        assert body["HostConfig"]["Memory"] == 2 * 1024 * 1024 * 1024
        assert body["HostConfig"]["NanoCpus"] == 2_000_000_000
        assert body["HostConfig"]["NetworkMode"] == "signalpilot_default"
        # Docker keeps credentials inline in Env — that is today's behaviour.
        assert "ANTHROPIC_API_KEY=sk-ant-supersecret" in body["Env"]
        backend._client.delete.assert_called_once()


# ─── Spec builders in runner.py ──────────────────────────────────────────────


class TestRunnerSpecs:
    def test_question_spec_routes_every_credential_through_secret_env(self):
        from gateway.evals.runner import _question_spec

        settings = _settings(
            SP_EVAL_CLAUDE_TOKEN="oauth-tok", SP_EVAL_ANTHROPIC_KEY="ant-key"
        )
        spec = _question_spec(
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

    def test_setup_spec_routes_env_file_through_secret_env(self, tmp_path):
        from gateway.evals.runner import EvalSet, _setup_spec

        (tmp_path / "warehouse.env").write_text(
            "# creds\nPGPASSWORD=hunter2\nPGHOST=warehouse\n", encoding="utf-8"
        )
        eval_set = EvalSet(
            name="e", description="", questions=[],
            setup={"env_file": "warehouse.env", "timeout_seconds": 900},
        )
        spec = _setup_spec(
            _settings(),
            eval_set=eval_set,
            repo_dir=tmp_path,
            repo_url="https://example.com/evals.git",
            script_rel="states/clean/setup.sh",
            state="clean",
            run_id="run-20260101-010101-aaaaaa",
        )
        assert spec.secret_env == {"PGPASSWORD": "hunter2", "PGHOST": "warehouse"}
        assert spec.env == {
            "SP_EVAL_STATE": "clean",
            "SP_EVAL_REPO_URL": "https://example.com/evals.git",
            "HOME": "/tmp",
        }
        assert spec.timeout_seconds == 900
