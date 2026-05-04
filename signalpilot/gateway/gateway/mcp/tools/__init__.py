"""Tool modules — importing each triggers @audited_tool(mcp) registrations."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from gateway.mcp.server import mcp as _mcp

# Sanity: nothing has rebound mcp.tool to a non-method. If this ever fails,
# something has reintroduced a monkey-patch and audited_tool may double-wrap.
assert type(_mcp).tool is FastMCP.tool, (
    "mcp.tool has been rebound; audited_tool wraps it explicitly — remove the rebinding."
)

# Side-effect imports: each submodule registers its tools via @audited_tool(mcp).
# The "as X" form tells ruff these are explicit re-exports (not unused imports).
from gateway.mcp.tools import connections as connections  # noqa: E402
from gateway.mcp.tools import dbt_project as dbt_project  # noqa: E402
from gateway.mcp.tools import knowledge as knowledge  # noqa: E402
from gateway.mcp.tools import model_verify as model_verify  # noqa: E402
from gateway.mcp.tools import projects as projects  # noqa: E402
from gateway.mcp.tools import query as query  # noqa: E402
from gateway.mcp.tools import schema as schema  # noqa: E402
