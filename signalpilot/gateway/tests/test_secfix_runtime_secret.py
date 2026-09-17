"""SP-01: the gateway JWT signing secret must never reach a sandbox.

The Vercel backend hands the boot process an env (never the creation spec).
That env must carry the runtime's own bearer tokens and a fresh per-launch
derivation key, and nothing that lets a sandbox mint session tokens.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from gateway.config.notebooks import NotebookSettings
from gateway.notebooks.backends import LaunchRequest, VercelNotebookBackend


def _request(**overrides):
    base = dict(
        org_id="org-1",
        user_id="user-1",
        session_id="sess-abc",
        project_id="proj-1",
        branch="main",
        session_jwt="jwt.value.here",
        notebook_token="nb-token",
    )
    base.update(overrides)
    return LaunchRequest(**base)


def _assert_launch_env(process_env: dict[str, str]) -> None:
    assert "SP_SESSION_JWT_SECRET" not in process_env
    assert not any("JWT_SECRET" in key for key in process_env)
    assert process_env["SP_SESSION_JWT"] == "jwt.value.here"
    assert process_env["SP_NOTEBOOK_TOKEN"] == "nb-token"
    assert process_env["SP_SESSION_ID"] == "sess-abc"
    token_secret = process_env["SP_NOTEBOOK_TOKEN_SECRET"]
    assert isinstance(token_secret, str)
    assert len(token_secret) >= 32


def test_process_env_has_no_signing_secret_and_a_per_launch_token_secret(monkeypatch):
    # Even if the gateway itself holds a secret, it must not be forwarded.
    monkeypatch.setenv("SP_SESSION_JWT_SECRET", "gateway-only-secret-gateway-only-secret")
    process_env = VercelNotebookBackend._process_env(_request())
    _assert_launch_env(process_env)
    assert "gateway-only-secret" not in "".join(process_env.values())


def test_token_secret_is_fresh_per_launch():
    first = VercelNotebookBackend._process_env(_request())
    second = VercelNotebookBackend._process_env(_request())
    assert first["SP_NOTEBOOK_TOKEN_SECRET"] != second["SP_NOTEBOOK_TOKEN_SECRET"]


def test_process_env_does_not_load_the_gateway_secret(monkeypatch):
    """No secret file / env var is needed to build a launch env at all."""
    import gateway.auth.jwt_secret as jwt_secret

    def _boom():  # pragma: no cover - must not be called
        raise AssertionError("load_session_jwt_secret must not run for a launch")

    monkeypatch.setattr(jwt_secret, "load_session_jwt_secret", _boom)
    monkeypatch.delenv("SP_SESSION_JWT_SECRET", raising=False)
    _assert_launch_env(VercelNotebookBackend._process_env(_request()))


@pytest.mark.asyncio
async def test_launch_and_resume_pass_the_clean_env_to_the_boot_process(monkeypatch):
    runtime = AsyncMock()
    runtime.create.return_value = "sbx-x"
    runtime.exec.return_value = SimpleNamespace(ok=True, stdout="", stderr="")
    runtime.routes.return_value = {2718: "https://sbx-x.vercel.run"}
    runtime.start_process.return_value = "proc-1"
    monkeypatch.setenv("SP_NOTEBOOK_VERCEL_IMAGE", "reg/sp-notebook:dev")
    monkeypatch.delenv("SP_DEPLOYMENT_MODE", raising=False)
    backend = VercelNotebookBackend(NotebookSettings(), runtime=runtime)

    await backend.launch(_request())
    spec = runtime.create.await_args.args[0]
    assert spec.env == {}
    _assert_launch_env(runtime.start_process.await_args.kwargs["env"])

    await backend.resume("sbx-x", _request())
    _assert_launch_env(runtime.start_process.await_args.kwargs["env"])
