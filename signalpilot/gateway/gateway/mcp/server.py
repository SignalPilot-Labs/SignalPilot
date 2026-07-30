"""FastMCP instance, transport security config, and main() entry point."""

from __future__ import annotations

import os as _os

from mcp.server.fastmcp import FastMCP

from ..config import get_mcp_settings
from ..config.k8s import get_k8s_settings
from ..runtime.mode import is_cloud_mode

# Allowed hosts for MCP streamable-http transport (DNS rebinding protection)
_allowed_hosts = ["localhost", "127.0.0.1", "host.docker.internal", "0.0.0.0"]
_extra_hosts = get_mcp_settings().sp_mcp_allowed_hosts
if _extra_hosts:
    _allowed_hosts.extend(h.strip() for h in _extra_hosts.split(",") if h.strip())
# Include hosts with port numbers. SP_PUBLIC_GATEWAY_PORT reflects the port
# clients actually connect on (e.g. compose's SP_GATEWAY_PORT override), so
# a remapped host port doesn't get rejected as an invalid Host header.
_gateway_port = get_k8s_settings().sp_public_gateway_port
_allowed_hosts_with_ports = list(_allowed_hosts)
for h in _allowed_hosts:
    _allowed_hosts_with_ports.append(f"{h}:{_gateway_port}")

# In cloud mode behind a reverse proxy (Caddy/nginx), disable host validation entirely
# since the proxy already handles DNS rebinding protection via its own config
if _os.environ.get("SP_DEPLOYMENT_MODE") == "cloud":
    _transport_security = {"enable_dns_rebinding_protection": False}
else:
    _transport_security = {"allowed_hosts": _allowed_hosts_with_ports}

mcp = FastMCP(
    "SignalPilot",
    instructions=(
        "You have access to SignalPilot, a governed platform for AI database access. "
        "Use query_database for read-only SQL with automatic governance (LIMIT injection, "
        "DDL/DML blocking, dangerous function blocking, audit logging). "
        "Use list_connections to see available databases."
    ),
    transport_security=_transport_security,
)


def main():
    """Run the MCP server.

    Transport is selected via SP_MCP_TRANSPORT env var (default: stdio).
    When running as streamable-http, wraps the Starlette app with
    MCPAuthMiddleware and serves it with uvicorn.
    """
    import os as _entry_os

    transport = _entry_os.environ.get("SP_MCP_TRANSPORT", "stdio")

    if transport == "streamable-http":
        import uvicorn

        from gateway.auth.mcp_api_key import MCPAuthMiddleware

        port = int(_entry_os.environ.get("SP_MCP_PORT", "8000"))
        starlette_app = mcp.streamable_http_app()
        authenticated_app = MCPAuthMiddleware(starlette_app)
        uvicorn.run(authenticated_app, host="0.0.0.0", port=port, server_header=False)
    else:
        if is_cloud_mode():
            raise SystemExit(
                "Refusing to start MCP stdio transport in cloud mode — stdio bypasses MCPAuthMiddleware."
            )
        # stdio mode has no auth middleware — set context vars for local access
        from gateway.mcp.context import mcp_org_id_var, mcp_user_id_var

        mcp_org_id_var.set(_os.environ.get("SP_ORG_ID", "local"))
        mcp_user_id_var.set("local")
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
