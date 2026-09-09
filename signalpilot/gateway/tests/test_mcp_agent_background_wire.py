"""The same observable run/wait lifecycle works in both MCP protocol eras."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from mcp.client import Client

from gateway.agent_execution import artifacts, events
from gateway.mcp import mcp
from gateway.mcp.context import mcp_org_id_var, mcp_scopes_var, mcp_user_id_var

from .fast.test_mcp_agent_service import service


@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_background_query_activity_is_returned_before_completion(service, monkeypatch, mode):
    entered, release = asyncio.Event(), asyncio.Event()
    thread = {}

    async def runtime(**kwargs):
        await events.append_event(
            service.factory,
            thread["thread_id"],
            kwargs["run_id"],
            "org",
            {
                "type": "query_started",
                "tool": "query_database",
                "sql": "SELECT order_id FROM my_orders WHERE customer_id = 'private'",
            },
        )
        entered.set()
        await release.wait()
        return {"status": "completed", "summary": "Verified model"}, artifacts.pack(
            {"models/my_orders.sql": b"select 2\n"}
        )

    service.runtime.run = runtime
    monkeypatch.setattr("gateway.mcp.tools.agent.AgentService", lambda: service)
    monkeypatch.setattr("gateway.mcp.audit._audit_tool_call", AsyncMock())
    tokens = [
        (v, v.set(value))
        for v, value in ((mcp_org_id_var, "org"), (mcp_user_id_var, "owner"), (mcp_scopes_var, ["agent:run"]))
    ]
    worker = None
    try:
        async with Client(mcp, mode=mode) as client:
            started = await client.call_tool(
                "run_signalpilot_agent",
                {"task": "Inspect my_orders", "project_id": "project", "revision": 1, "connection_name": "warehouse"},
            )
            assert not started.is_error
            thread.update(started.structured_content)
            assert thread["status"] == "queued"
            worker = asyncio.create_task(service.run_once())
            await asyncio.wait_for(entered.wait(), 3)
            waited = await client.call_tool(
                "wait_signalpilot_agent",
                {"thread_id": thread["thread_id"], "run_id": thread["run_id"], "wait_seconds": 0},
            )
            assert not worker.done()
            assert waited.structured_content["status"] == "running"
            assert "SELECT order_id FROM my_orders" in waited.content[0].text
            assert "private" not in waited.content[0].text
            cursor = waited.structured_content["next_sequence"]
            assert cursor >= 2
            release.set()
            await worker
            completed = await client.call_tool(
                "wait_signalpilot_agent",
                {
                    "thread_id": thread["thread_id"],
                    "run_id": thread["run_id"],
                    "after_sequence": cursor,
                    "wait_seconds": 0,
                },
            )
            assert completed.structured_content["status"] == "completed"
            assert "patch_url" in completed.content[0].text
            assert completed.structured_content["changed_files"] == ["models/my_orders.sql"]
    finally:
        release.set()
        if worker is not None:
            await asyncio.gather(worker, return_exceptions=True)
        for variable, token in reversed(tokens):
            variable.reset(token)
