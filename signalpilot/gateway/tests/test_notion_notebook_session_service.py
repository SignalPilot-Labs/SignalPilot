from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock

import pytest
from fastapi import Response

from gateway.models.notebook_sessions import NotebookSessionInfo
from gateway.models.notebook_sessions import NotebookSessionCreate
from gateway.notebooks import session_service
from gateway.orchestrator import PodInfo
from gateway.store.notebook_sessions import NotebookSessionInternal


def _info(
    *,
    session_id: str = "session-1",
    org_id: str = "org-1",
    user_id: str = "user-1",
    project_id: str | None = None,
    branch: str = "main",
    pod_name: str | None = "nb-test",
    pod_ip: str | None = None,
    status: str = "creating",
) -> NotebookSessionInfo:
    return NotebookSessionInfo(
        id=session_id,
        org_id=org_id,
        user_id=user_id,
        project_id=project_id,
        branch=branch,
        pod_name=pod_name,
        pod_ip=pod_ip,
        access_token=None,
        status=status,
        last_ping=time.time(),
        created_at=time.time(),
    )


def _internal(
    *,
    session_id: str = "session-1",
    org_id: str = "org-1",
    user_id: str = "user-1",
    pod_ip_internal: str = "10.2.3.4",
) -> NotebookSessionInternal:
    return NotebookSessionInternal(
        session_id=session_id,
        org_id=org_id,
        user_id=user_id,
        status="running",
        pod_ip_internal=pod_ip_internal,
        access_token="token-1",
    )


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        sp_session_jwt_ttl_seconds=3600,
        sp_public_gateway_url="https://gateway.test",
        sp_notebook_image="registry.test/notebook@sha256:" + "a" * 64,
    )


@pytest.mark.asyncio
async def test_pod_extra_env_includes_gateway_oauth_user_anthropic_key_and_web_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "oauth-token")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "global-ant-key")
    monkeypatch.delenv("SP_WEB_URL", raising=False)
    monkeypatch.setenv("SIGNALPILOT_WEB_URL", "https://app.signalpilot.ai")
    monkeypatch.setattr(
        session_service.user_secrets_store,
        "get_user_anthropic_key",
        AsyncMock(return_value="user-ant-key"),
    )

    env = await session_service._pod_extra_env(
        AsyncMock(),
        org_id="org-1",
        user_id="user-1",
        extra_env={"SP_AGENT_MODE": "true"},
    )

    assert env == {
        "CLAUDE_CODE_OAUTH_TOKEN": "oauth-token",
        "ANTHROPIC_API_KEY": "user-ant-key",
        "SP_WEB_URL": "https://app.signalpilot.ai",
        "SP_AGENT_MODE": "true",
    }


@pytest.mark.asyncio
async def test_pod_extra_env_defaults_web_url_in_cloud_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SP_WEB_URL", raising=False)
    monkeypatch.delenv("SIGNALPILOT_WEB_URL", raising=False)
    monkeypatch.setenv("SP_DEPLOYMENT_MODE", "cloud")
    monkeypatch.setattr(
        session_service.user_secrets_store,
        "get_user_anthropic_key",
        AsyncMock(return_value=None),
    )

    env = await session_service._pod_extra_env(
        AsyncMock(),
        org_id="org-1",
        user_id="user-1",
        extra_env=None,
    )

    assert env == {"SP_WEB_URL": "https://app.signalpilot.ai"}


@pytest.mark.asyncio
async def test_ensure_notion_session_spawns_without_static_notebook_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SIGNALPILOT_NOTEBOOK_INTERNAL_URL", raising=False)
    monkeypatch.delenv("SIGNALPILOT_NOTEBOOK_URL", raising=False)
    monkeypatch.delenv("SP_NOTEBOOK_DIRECT_URL", raising=False)
    monkeypatch.setenv("SP_WEB_URL", "https://app.test")

    created = _info()
    create_pod_calls: list[dict] = []

    orch = AsyncMock()
    orch._core_api = object()
    orch._ensure_client = AsyncMock()
    orch.ensure_namespace.return_value = "sp-nb-org-1"
    orch.wait_for_running.return_value = PodInfo(name="nb-test", ip="10.2.3.4", status="running", internal_ip="10.2.3.4")
    orch.wait_for_ready.return_value = PodInfo(name="nb-test", ip="10.2.3.4", status="running", internal_ip="10.2.3.4")

    async def create_pod(**kwargs):
        create_pod_calls.append(kwargs)
        return PodInfo(name=kwargs["pod_name"], ip=None, status="pending")

    orch.create_pod = create_pod

    async def create_secret(*args, create_pod_fn, **kwargs):
        return await create_pod_fn()

    monkeypatch.setattr(session_service.ns, "get_active_session", AsyncMock(return_value=None))
    monkeypatch.setattr(session_service.ns, "delete_stopped", AsyncMock())
    monkeypatch.setattr(session_service.ns, "create_session", AsyncMock(return_value=created))
    monkeypatch.setattr(session_service.ns, "update_session_status", AsyncMock())
    monkeypatch.setattr(session_service.ns, "get_session_internal", AsyncMock(return_value=_internal()))
    monkeypatch.setattr(
        session_service.user_secrets_store,
        "get_user_anthropic_key",
        AsyncMock(return_value="sk-ant-user"),
    )
    monkeypatch.setattr(session_service, "_get_orchestrator", AsyncMock(return_value=orch))
    monkeypatch.setattr(session_service, "get_k8s_settings", lambda: _settings())
    monkeypatch.setattr(session_service, "mint_session_jwt", lambda **kwargs: "jwt-1")
    monkeypatch.setattr(session_service, "create_jwt_secret_with_owner_ref", create_secret)

    runtime = await session_service.ensure_notion_notebook_session(AsyncMock(), "org-1", "user-1")

    assert runtime.session_id == "session-1"
    assert runtime.internal_base_url == "http://10.2.3.4:2718/notebook/session-1"
    assert runtime.public_base_url == "https://app.test/notebook/session-1"
    assert create_pod_calls[0]["image"] == _settings().sp_notebook_image
    assert create_pod_calls[0]["extra_env"]["ANTHROPIC_API_KEY"] == "sk-ant-user"
    assert create_pod_calls[0]["extra_env"]["SP_WEB_URL"] == "https://app.test"


@pytest.mark.asyncio
async def test_ensure_notion_session_reuses_matching_running_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SP_NOTEBOOK_DIRECT_URL", raising=False)
    monkeypatch.setenv("SP_WEB_URL", "https://app.test")

    existing = _info(status="running", pod_ip="10.2.3.4")
    orch = AsyncMock()
    orch.is_pod_alive.return_value = True

    monkeypatch.setattr(session_service.ns, "get_active_session", AsyncMock(return_value=existing))
    monkeypatch.setattr(session_service.ns, "get_session_internal", AsyncMock(return_value=_internal()))
    monkeypatch.setattr(
        session_service.user_secrets_store,
        "get_user_anthropic_key",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(session_service.ns, "mark_stopped", AsyncMock())
    monkeypatch.setattr(session_service.ns, "delete_stopped", AsyncMock())
    monkeypatch.setattr(session_service.ns, "create_session", AsyncMock())
    monkeypatch.setattr(session_service, "_get_orchestrator", AsyncMock(return_value=orch))

    runtime = await session_service.ensure_notion_notebook_session(AsyncMock(), "org-1", "user-1")

    assert runtime.internal_base_url == "http://10.2.3.4:2718/notebook/session-1"
    session_service.ns.create_session.assert_not_awaited()
    session_service.ns.mark_stopped.assert_not_awaited()


@pytest.mark.asyncio
async def test_ensure_notebook_session_recreates_when_branch_does_not_match(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SP_NOTEBOOK_DIRECT_URL", "http://notebook:2718")
    existing = _info(branch="dev", status="running", pod_ip="notebook:2718")
    created = _info(session_id="session-2", branch="main")

    monkeypatch.setattr(session_service.ns, "get_active_session", AsyncMock(return_value=existing))
    monkeypatch.setattr(session_service.ns, "mark_stopped", AsyncMock())
    monkeypatch.setattr(session_service.ns, "delete_stopped", AsyncMock())
    monkeypatch.setattr(session_service.ns, "create_session", AsyncMock(return_value=created))
    monkeypatch.setattr(session_service.ns, "update_session_status", AsyncMock())
    monkeypatch.setattr(
        session_service.user_secrets_store,
        "get_user_anthropic_key",
        AsyncMock(return_value=None),
    )

    result = await session_service.ensure_notebook_session(
        AsyncMock(),
        org_id="org-1",
        user_id="user-1",
        project_id=None,
        branch="main",
    )

    assert result.id == "session-2"
    session_service.ns.mark_stopped.assert_awaited_once()
    session_service.ns.create_session.assert_awaited_once()


@pytest.mark.asyncio
async def test_ensure_notion_session_marks_error_on_pod_spawn_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SP_NOTEBOOK_DIRECT_URL", raising=False)
    created = _info()

    orch = AsyncMock()
    orch._core_api = object()
    orch._ensure_client = AsyncMock()
    orch.ensure_namespace.return_value = "sp-nb-org-1"
    orch.create_pod.side_effect = RuntimeError("image pull failed")

    async def create_secret(*args, create_pod_fn, **kwargs):
        return await create_pod_fn()

    monkeypatch.setattr(session_service.ns, "get_active_session", AsyncMock(return_value=None))
    monkeypatch.setattr(session_service.ns, "delete_stopped", AsyncMock())
    monkeypatch.setattr(session_service.ns, "create_session", AsyncMock(return_value=created))
    monkeypatch.setattr(session_service.ns, "update_session_status", AsyncMock())
    monkeypatch.setattr(
        session_service.user_secrets_store,
        "get_user_anthropic_key",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(session_service, "_get_orchestrator", AsyncMock(return_value=orch))
    monkeypatch.setattr(session_service, "get_k8s_settings", lambda: _settings())
    monkeypatch.setattr(session_service, "mint_session_jwt", lambda **kwargs: "jwt-1")
    monkeypatch.setattr(session_service, "create_jwt_secret_with_owner_ref", create_secret)

    with pytest.raises(session_service.NotebookSessionError, match="Failed to start notebook pod"):
        await session_service.ensure_notion_notebook_session(AsyncMock(), "org-1", "user-1")

    session_service.ns.update_session_status.assert_awaited_once_with(
        ANY,
        session_id="session-1",
        org_id="org-1",
        status="error",
    )
    orch.delete_pod.assert_awaited_once_with(
        session_service.pod_name_for("org-1", "user-1"),
        org_id="org-1",
    )


@pytest.mark.asyncio
async def test_notebook_session_post_endpoint_delegates_to_shared_service(monkeypatch: pytest.MonkeyPatch) -> None:
    from gateway.api import notebook_sessions as ns_api

    calls: list[dict] = []

    async def ensure_notebook_session(*args, **kwargs):
        calls.append(kwargs)
        return _info(session_id="session-api", status="running", pod_ip="10.2.3.4")

    store = SimpleNamespace(org_id="org-1", user_id="user-1", session=AsyncMock())
    monkeypatch.setattr(ns_api, "is_cloud_mode", lambda: False)
    monkeypatch.setattr(ns_api.session_service, "ensure_notebook_session", ensure_notebook_session)

    result = await ns_api.create_session(
        NotebookSessionCreate(project_id=None, branch="main"),
        store,
        Response(),
    )

    assert result.id == "session-api"
    assert calls[0]["org_id"] == "org-1"
    assert calls[0]["user_id"] == "user-1"
    assert calls[0]["project_id"] is None
    assert calls[0]["branch"] == "main"
