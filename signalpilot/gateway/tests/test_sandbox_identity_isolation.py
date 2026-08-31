"""The dbt executor sandbox must be unreachable from the agent's tools.

sandbox_exec/read/write accept only chat:* agent identities and reject the
chat-exec:* executor identity — so the credential-holding sandbox has no
agent-facing tool surface.
"""

from __future__ import annotations

from gateway.mcp.context import mcp_capabilities_var, mcp_execution_identity_var
from gateway.mcp.tools.dbt_execute import _denial as dbt_execute_denial
from gateway.mcp.tools.sandbox_vm import _sandbox_denial


def _set(identity: str | None, caps: list[str]):
    mcp_execution_identity_var.set(identity)
    mcp_capabilities_var.set(caps)


def test_sandbox_tools_reject_executor_identity():
    _set("chat-exec:run-1", ["sandbox:execute"])
    assert _sandbox_denial() is not None  # denied


def test_sandbox_tools_accept_agent_identity_with_cap():
    _set("chat:run-1", ["sandbox:execute"])
    assert _sandbox_denial() is None  # allowed


def test_sandbox_tools_require_capability():
    _set("chat:run-1", [])
    assert _sandbox_denial() is not None


def test_sandbox_tools_reject_non_chat_identity():
    _set("improvement-only", ["sandbox:execute"])
    assert _sandbox_denial() is not None


def test_dbt_execute_requires_capability_and_chat_identity():
    _set("chat:run-1", [])
    assert dbt_execute_denial() is not None  # no dbt:execute cap
    _set("chat:run-1", ["dbt:execute"])
    assert dbt_execute_denial() is None
    _set("chat-exec:run-1", ["dbt:execute"])
    assert dbt_execute_denial() is not None  # executor identity can't call it either
