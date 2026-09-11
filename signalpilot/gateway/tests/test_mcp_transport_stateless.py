"""The MCP streamable-HTTP transport must not hold per-process session state."""

from __future__ import annotations


def test_mcp_streamable_http_is_stateless():
    """A stateful transport loses every in-flight chat run on a gateway
    restart or deploy: the agent keeps sending its old session id and gets
    "Session not found" for the rest of the run."""
    from gateway.mcp.server import mcp, streamable_http_app

    streamable_http_app()
    assert mcp.session_manager.stateless is True
