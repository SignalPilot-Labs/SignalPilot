"""Every MCP tool is classified and stored-key scopes are enforced centrally."""

from unittest.mock import AsyncMock, patch

import pytest

from gateway.http.middleware.auth import _eval_rest_path_allowed
from gateway.mcp import mcp
from gateway.mcp.audit import EVAL_ALLOWED_MCP_TOOLS, MCP_TOOL_SCOPES
from gateway.mcp.context import (
    _require_mcp_scope,
    mcp_eval_run_var,
    mcp_org_id_var,
    mcp_scopes_var,
)
from gateway.models import VALID_API_KEY_SCOPES


def test_every_registered_tool_has_exactly_one_valid_scope() -> None:
    registered = set(mcp._tool_manager._tools)
    assert registered == set(MCP_TOOL_SCOPES)
    assert set(MCP_TOOL_SCOPES.values()) <= set(VALID_API_KEY_SCOPES)


def test_eval_mcp_surface_is_explicit_and_excludes_history_and_branch_control() -> None:
    assert EVAL_ALLOWED_MCP_TOOLS <= set(MCP_TOOL_SCOPES)
    assert "query_history" not in EVAL_ALLOWED_MCP_TOOLS
    assert "schema_diff_branches" not in EVAL_ALLOWED_MCP_TOOLS
    assert "xata_list_branches" not in EVAL_ALLOWED_MCP_TOOLS


@pytest.mark.parametrize(
    ("method", "path", "allowed"),
    [
        ("POST", "/api/connections/pinned/schema/explore", True),
        ("POST", "/api/connections/pinned/schema/explore-columns", True),
        ("POST", "/api/connections/pinned/test", False),
        ("POST", "/api/connections/pinned/diagnose", False),
        ("GET", "/api/audit", False),
    ],
)
def test_eval_rest_proxy_surface_is_path_specific(method: str, path: str, allowed: bool) -> None:
    assert _eval_rest_path_allowed(method, path, "pinned") is allowed


def test_read_key_cannot_call_query_tool_policy() -> None:
    org_token = mcp_org_id_var.set("org-1")
    scopes_token = mcp_scopes_var.set(["read"])
    try:
        assert _require_mcp_scope("read") is None
        assert _require_mcp_scope("query") == "Error: query scope required for this action"
    finally:
        mcp_scopes_var.reset(scopes_token)
        mcp_org_id_var.reset(org_token)


def test_missing_auth_context_fails_closed() -> None:
    org_token = mcp_org_id_var.set("org-1")
    scopes_token = mcp_scopes_var.set(None)
    try:
        assert "authentication context missing" in _require_mcp_scope("read")
    finally:
        mcp_scopes_var.reset(scopes_token)
        mcp_org_id_var.reset(org_token)


def test_stored_local_key_does_not_bypass_its_scopes() -> None:
    org_token = mcp_org_id_var.set("local")
    scopes_token = mcp_scopes_var.set(["read"])
    try:
        assert _require_mcp_scope("query") == "Error: query scope required for this action"
    finally:
        mcp_scopes_var.reset(scopes_token)
        mcp_org_id_var.reset(org_token)


@pytest.mark.asyncio
async def test_registered_query_tool_is_blocked_before_implementation_runs() -> None:
    org_token = mcp_org_id_var.set("org-1")
    scopes_token = mcp_scopes_var.set(["read"])
    try:
        with patch("gateway.mcp.audit._audit_tool_call", new=AsyncMock()):
            result = await mcp._tool_manager._tools["query_database"].fn(
                "any-connection", "select 1"
            )
        assert result == "Error: query scope required for this action"
    finally:
        mcp_scopes_var.reset(scopes_token)
        mcp_org_id_var.reset(org_token)


@pytest.mark.asyncio
async def test_registered_read_tool_runs_with_read_scope() -> None:
    org_token = mcp_org_id_var.set("org-1")
    scopes_token = mcp_scopes_var.set(["read"])
    try:
        with patch("gateway.mcp.audit._audit_tool_call", new=AsyncMock()):
            result = await mcp._tool_manager._tools["dbt_error_parser"].fn("syntax error")
        assert not result.startswith("Error: read scope required")
    finally:
        mcp_scopes_var.reset(scopes_token)
        mcp_org_id_var.reset(org_token)


@pytest.mark.asyncio
async def test_eval_key_cannot_use_unrelated_read_integration_tool() -> None:
    assert "notion_search" not in EVAL_ALLOWED_MCP_TOOLS
    org_token = mcp_org_id_var.set("org-1")
    scopes_token = mcp_scopes_var.set(["read", "query"])
    eval_token = mcp_eval_run_var.set("run-1")
    try:
        with patch("gateway.mcp.audit._audit_tool_call", new=AsyncMock()):
            result = await mcp._tool_manager._tools["notion_search"].fn("notion", "secret")
        assert result == "Error: eval credentials may not call MCP tool 'notion_search'"
    finally:
        mcp_eval_run_var.reset(eval_token)
        mcp_scopes_var.reset(scopes_token)
        mcp_org_id_var.reset(org_token)
