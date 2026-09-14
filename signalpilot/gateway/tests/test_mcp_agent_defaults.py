import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import select

from gateway.agent_execution.contracts import AgentLaunchRequest
from gateway.agent_execution.service import AgentService
from gateway.api.settings import get_mcp_agent_defaults, update_mcp_agent_defaults
from gateway.db.models import GatewaySetting, GatewayWorkspaceProject, GatewayChatConversation
from gateway.models import GatewaySettings
from gateway.models.settings import MCPAgentDefaults
from gateway.store import Store
from .fast.test_mcp_agent_service import service


@pytest_asyncio.fixture
async def defaults(service, monkeypatch):
    async with service.factory() as db:
        db.add(
            GatewaySetting(
                org_id="org",
                settings_json=GatewaySettings(
                    api_key="private-key",
                    sandbox_api_key="sandbox-secret",
                    default_row_limit=123,
                    mcp_agent_default_project_id="project",
                    mcp_agent_default_connection_name="warehouse",
                    mcp_agent_default_branch="saved-branch",
                ).model_dump(),
            )
        )
        db.add(
            GatewayWorkspaceProject(
                id="override",
                org_id="org",
                name="override",
                display_name="Override",
                connection_name="warehouse",
                default_branch="develop",
                status="active",
                created_at=time.time(),
                updated_at=time.time(),
            )
        )
        await db.commit()
    monkeypatch.setattr(service, "_resolve_request", AgentService._resolve_request.__get__(service))
    monkeypatch.setattr(
        "gateway.agent_execution.service.evaluate_project_readiness",
        AsyncMock(return_value=SimpleNamespace(ready=True)),
    )
    monkeypatch.setattr("gateway.agent_execution.service.branch_head_sha", lambda project, branch: "a" * 40)
    monkeypatch.setattr(Store, "get_connection", AsyncMock(return_value=SimpleNamespace(name="warehouse")))
    return service


async def test_task_only_uses_saved_branch_and_idempotent_retry(defaults):
    started = await defaults.start("org", "owner", AgentLaunchRequest(task="Check", client_request_id="retry"))
    async with defaults.factory() as db:
        row = await db.get(GatewayChatConversation, started.thread_id)
        assert row.project_id == "project" and row.branch == "saved-branch" and row.commit_sha == "a" * 40
        settings = await db.scalar(select(GatewaySetting).where(GatewaySetting.org_id == "org"))
        settings.settings_json = {}
        await db.commit()
    assert (
        await defaults.start("org", "owner", AgentLaunchRequest(task="Check", client_request_id="retry"))
    ).thread_id == started.thread_id


async def test_project_override_uses_project_branch(defaults):
    started = await defaults.start("org", "owner", AgentLaunchRequest(task="Check", project_id="override"))
    async with defaults.factory() as db:
        row = await db.get(GatewayChatConversation, started.thread_id)
        assert row.branch == "develop"


async def test_missing_defaults_and_mismatched_connection_are_actionable(defaults):
    with pytest.raises(ValueError, match="Settings"):
        await defaults.start("other", "owner", AgentLaunchRequest(task="Check"))
    with pytest.raises(ValueError, match="project's Chats connection"):
        await defaults.start("org", "owner", AgentLaunchRequest(task="Check", connection_name="other"))


async def test_settings_preserve_secrets_and_other_fields(defaults):
    async with defaults.factory() as db:
        store = Store(db, org_id="org", user_id="owner")
        saved = await update_mcp_agent_defaults(
            MCPAgentDefaults(mcp_agent_default_project_id="override", mcp_agent_default_connection_name="warehouse"),
            store,
            None,
        )
        loaded = await store.load_settings()
        assert loaded.api_key == "private-key" and loaded.sandbox_api_key == "sandbox-secret"
        assert loaded.default_row_limit == 123
        assert await get_mcp_agent_defaults(store) == saved


@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_wire_task_only_and_shared_events(defaults, monkeypatch, mode):
    from mcp.client import Client
    from gateway.mcp import mcp
    from gateway.mcp.context import mcp_org_id_var, mcp_scopes_var, mcp_user_id_var

    monkeypatch.setattr("gateway.mcp.tools.agent.AgentService", lambda: defaults)
    monkeypatch.setattr("gateway.mcp.audit._audit_tool_call", AsyncMock())
    tokens = [
        (var, var.set(value))
        for var, value in [(mcp_org_id_var, "org"), (mcp_user_id_var, "owner"), (mcp_scopes_var, ["agent:run"])]
    ]
    try:
        async with Client(mcp, mode=mode) as client:
            tool = next(tool for tool in (await client.list_tools()).tools if tool.name == "run_signalpilot_agent")
            assert tool.input_schema["required"] == ["task"]
            assert "revision" not in tool.input_schema["properties"]
            started = await client.call_tool("run_signalpilot_agent", {"task": "Check my_orders"})
            assert not started.is_error
            data = started.structured_content
            assert data["status"] == "queued" and "/chats/mcp/" not in data["chat_url"]
            waited = await client.call_tool(
                "wait_signalpilot_agent", {"thread_id": data["thread_id"], "wait_seconds": 0}
            )
            assert waited.structured_content["events"] == data["events"]
            assert data["chat_url"] in waited.content[0].text
    finally:
        for var, token in reversed(tokens):
            var.reset(token)
