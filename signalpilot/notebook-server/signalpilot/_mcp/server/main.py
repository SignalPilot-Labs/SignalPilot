# Copyright 2026 SignalPilot. All rights reserved.
"""
MCP (Model Context Protocol) Server Implementation for SignalPilot

This module implements an MCP server that provides LLMs with access to sp
notebook context and functionality.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from signalpilot._cli.errors import SpCLIMissingDependencyError
from signalpilot._dependencies.dependencies import DependencyManager
from signalpilot._loggers import sp_logger
from signalpilot._server.ai.tools.base import ToolContext
from signalpilot._server.ai.tools.registry import (
    SUPPORTED_BACKEND_AND_MCP_TOOLS,
)

LOGGER = sp_logger()


if TYPE_CHECKING:
    from starlette.applications import Starlette
    from starlette.types import Receive, Scope, Send


def setup_mcp_server(app: Starlette, allow_remote: bool = False) -> None:
    """Create and configure MCP server for sp integration.

    Args:
        app: Starlette application instance for accessing sp state
        server_name: Name for the MCP server instance
        stateless_http: Whether to use stateless HTTP mode
        allow_remote: If True, disable DNS rebinding protection to allow remote access behind proxies.

    Returns:
        StreamableHTTPSessionManager: MCP session manager
    """
    if not DependencyManager.mcp.has():
        raise SpCLIMissingDependencyError(
            "MCP dependencies not available.",
            "sp[mcp]",
        )

    from mcp.server.fastmcp import FastMCP
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse
    from starlette.routing import Mount

    from signalpilot._mcp.server._prompts.registry import (
        SUPPORTED_MCP_PROMPTS,
    )

    transport_security = None
    if allow_remote:
        from mcp.server.transport_security import TransportSecuritySettings

        transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=False,
        )

    mcp = FastMCP(
        "sp-mcp-server",
        stateless_http=True,
        log_level="WARNING",
        # Change base path from /mcp to /server
        streamable_http_path="/server",
        transport_security=transport_security,
    )

    # Create context for tools and prompts
    context = ToolContext(app=app)

    # Register all tools
    for tool in SUPPORTED_BACKEND_AND_MCP_TOOLS:
        tool_with_context = tool(context)
        mcp.tool()(tool_with_context.as_mcp_tool_fn())

    # Register all prompts
    for prompt in SUPPORTED_MCP_PROMPTS:
        prompt_with_context = prompt(context)
        mcp.prompt()(prompt_with_context.as_mcp_prompt_fn())

    # Initialize streamable HTTP app
    mcp_app = mcp.streamable_http_app()

    # Middleware to require edit scope
    class RequiresEditMiddleware(BaseHTTPMiddleware):
        async def __call__(
            self, scope: Scope, receive: Receive, send: Send
        ) -> None:
            auth = scope.get("auth")
            if auth is None or "edit" not in auth.scopes:
                response = JSONResponse(
                    {"detail": "Forbidden"},
                    status_code=403,
                )
                return await response(scope, receive, send)

            return await self.app(scope, receive, send)

    mcp_app.add_middleware(RequiresEditMiddleware)

    # Add to the top of the routes to avoid conflicts with other routes
    app.routes.insert(0, Mount("/mcp", mcp_app))
    app.state.mcp = mcp
