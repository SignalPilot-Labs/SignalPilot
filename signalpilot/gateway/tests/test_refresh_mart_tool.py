"""refresh_mart writes through the chat's own connection: into its database by
default, into a sibling database the agent names, or into the deployment
default (SP_CHAT_DEV_DATABASE) when neither is given."""

from __future__ import annotations

import types
from contextlib import asynccontextmanager

import pytest

from gateway.mcp import context as mcp_context
from gateway.mcp.tools import refresh_mart as tool
from gateway.standalone_chat.dbt_executor import DBT_EXECUTE_CAPABILITY, RefreshTarget

IDENTITY = "chat:run-1234abcd"


class FakeStore:
    def __init__(self, settings: dict | None):
        self.session = None
        self._settings = settings

    async def get_workspace_project(self, project_id):
        return types.SimpleNamespace(id=project_id, settings=self._settings)


@pytest.fixture()
def bound_session(monkeypatch):
    """A chat session bound to project p1 reading through connection 'prod'."""
    variables = [
        mcp_context.mcp_scopes_var,
        mcp_context.mcp_user_id_var,
        mcp_context.mcp_capabilities_var,
        mcp_context.mcp_execution_identity_var,
        mcp_context.mcp_org_id_var,
        mcp_context.mcp_project_id_var,
        mcp_context.mcp_branch_var,
        mcp_context.mcp_allowed_connection_var,
    ]
    tokens = [
        mcp_context.mcp_scopes_var.set(["read", "query", "execute"]),
        mcp_context.mcp_user_id_var.set("u"),
        mcp_context.mcp_capabilities_var.set([DBT_EXECUTE_CAPABILITY]),
        mcp_context.mcp_execution_identity_var.set(IDENTITY),
        mcp_context.mcp_org_id_var.set("org"),
        mcp_context.mcp_project_id_var.set("p1"),
        mcp_context.mcp_branch_var.set("main"),
        mcp_context.mcp_allowed_connection_var.set("prod"),
    ]
    monkeypatch.delenv("SP_CHAT_DEV_DATABASE", raising=False)
    calls: dict = {}

    async def ensure_executor(db, **kw):
        calls["ensure"] = kw
        return "sbx", "dbt", "dbo"

    async def run_dbt_command(sandbox_id, argv, dbt_dir):
        calls["argv"] = argv
        return "exit_code: 0"

    monkeypatch.setattr(tool, "ensure_executor", ensure_executor)
    monkeypatch.setattr(tool, "run_dbt_command", run_dbt_command)
    yield calls
    for var, token in zip(variables, tokens, strict=True):
        var.reset(token)


def _use_store(monkeypatch, settings):
    @asynccontextmanager
    async def session():
        yield FakeStore(settings)

    monkeypatch.setattr(tool, "_store_session", session)


@pytest.mark.asyncio
async def test_refreshes_through_the_chat_connection_by_default(monkeypatch, bound_session):
    _use_store(monkeypatch, {})
    result = await tool.refresh_mart("fct_sales_lines")
    assert result.startswith("refreshed fct_sales_lines into connection prod (schema default dbo)")
    kw = bound_session["ensure"]
    assert kw["refresh"] == RefreshTarget(connection_name="prod")
    assert bound_session["argv"][bound_session["argv"].index("--select") + 1] == "+fct_sales_lines"


@pytest.mark.asyncio
async def test_agent_can_name_a_sibling_database(monkeypatch, bound_session):
    _use_store(monkeypatch, {})
    result = await tool.refresh_mart("fct_sales_lines", database="Analytics_dev")
    assert result.startswith(
        "refreshed fct_sales_lines into connection prod, database Analytics_dev"
    )
    assert bound_session["ensure"]["refresh"] == RefreshTarget(
        connection_name="prod", database_override="Analytics_dev"
    )


@pytest.mark.asyncio
async def test_env_default_database_applies_when_none_is_named(monkeypatch, bound_session):
    monkeypatch.setenv("SP_CHAT_DEV_DATABASE", "Analytics_dev")
    _use_store(monkeypatch, {})
    await tool.refresh_mart("fct_sales_lines")
    assert bound_session["ensure"]["refresh"].database_override == "Analytics_dev"
    # ...but an explicit database still wins.
    await tool.refresh_mart("fct_sales_lines", database="Analytics_qa")
    assert bound_session["ensure"]["refresh"].database_override == "Analytics_qa"


@pytest.mark.asyncio
async def test_unsafe_database_name_is_an_error_not_a_build(monkeypatch, bound_session):
    _use_store(monkeypatch, {})
    result = await tool.refresh_mart("fct_sales_lines", database="Analytics;DROP")
    assert result.startswith("Error: database must be a bare database name")
    assert "ensure" not in bound_session
