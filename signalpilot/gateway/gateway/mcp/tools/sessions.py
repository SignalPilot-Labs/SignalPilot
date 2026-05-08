"""MCP tools for kernel session management."""

from __future__ import annotations

import httpx

from gateway.errors.mcp import sanitize_mcp_error, sanitize_proxy_response
from gateway.mcp.audit import audited_tool
from gateway.mcp.context import _gateway_url, _gw_headers
from gateway.mcp.server import mcp


@audited_tool(mcp)
async def create_kernel_session(connection_name: str = "", label: str = "") -> str:
    """
    Create a new stateful kernel session for interactive Python execution.

    The kernel maintains a persistent namespace — variables set in one cell
    are available in the next. Use this to start an interactive analysis session.

    A pre-loaded `sp` helper is available in the kernel:
        rows = sp.query("SELECT * FROM users LIMIT 5")
        sp.connections()  # list available connections

    Args:
        connection_name: Optional database connection to associate with session
        label: Optional label for the session

    Returns:
        Session ID and status. Use execute_cell() to run code.
    """
    gw = _gateway_url()
    body = {}
    if connection_name:
        body["connection_name"] = connection_name
    if label:
        body["label"] = label

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"{gw}/api/sessions",
                json=body,
                headers=_gw_headers(),
            )
        if r.status_code != 201:
            return sanitize_proxy_response(r.status_code, r.text)
        data = r.json()
        return (
            f"Session created: {data['id']}\n"
            f"Status: {data.get('status', 'idle')}\n"
            f"The `sp` helper is available — use sp.query('SQL') to query data."
        )
    except Exception as e:
        return f"Error creating session: {sanitize_mcp_error(str(e))}"


@audited_tool(mcp)
async def execute_cell(session_id: str, code: str, timeout: int = 30) -> str:
    """
    Execute Python code in a stateful kernel session.

    Variables persist between cells. The last expression in a cell is
    displayed automatically (like a Jupyter notebook).

    Args:
        session_id: Session ID from create_kernel_session
        code: Python code to execute
        timeout: Max execution time in seconds (default 30)

    Returns:
        Cell output or error message.
    """
    if not session_id or len(session_id) > 128:
        return "Error: Invalid session_id"
    if not code.strip():
        return "Error: Empty code"

    gw = _gateway_url()
    try:
        async with httpx.AsyncClient(timeout=timeout + 10) as client:
            r = await client.post(
                f"{gw}/api/sessions/{session_id}/execute",
                json={"code": code, "timeout": timeout},
                headers=_gw_headers(),
            )
        if r.status_code == 404:
            return "Error: Session not found. Create one with create_kernel_session()."
        if r.status_code != 200:
            return sanitize_proxy_response(r.status_code, r.text)

        data = r.json()
        parts = []
        if data.get("output"):
            parts.append(data["output"])
        if not data.get("success") and data.get("error"):
            parts.append(f"Error:\n{data['error']}")
        if data.get("execution_ms"):
            parts.append(f"\n[{data['execution_ms']:.0f}ms]")
        return "\n".join(parts) if parts else "(no output)"
    except Exception as e:
        return f"Execution error: {sanitize_mcp_error(str(e))}"


@audited_tool(mcp)
async def get_session_history(session_id: str) -> str:
    """
    Get the execution history of a kernel session.

    Shows all cells that have been executed, with their outputs.

    Args:
        session_id: Session ID to get history for

    Returns:
        Formatted history of executed cells.
    """
    if not session_id:
        return "Error: session_id is required"

    gw = _gateway_url()
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                f"{gw}/api/sessions/{session_id}/history",
                headers=_gw_headers(),
            )
        if r.status_code != 200:
            return sanitize_proxy_response(r.status_code, r.text)

        data = r.json()
        cells = data.get("cells", [])
        if not cells:
            return "No cells executed yet in this session."

        lines = [f"Session {session_id} — {len(cells)} cells\n"]
        for i, cell in enumerate(cells, 1):
            status = "OK" if cell.get("success") else "ERR"
            lines.append(f"--- Cell {i} [{status}] ---")
            if cell.get("output"):
                lines.append(cell["output"][:500])
            if not cell.get("success") and cell.get("error"):
                lines.append(f"Error: {cell['error'][:300]}")
            lines.append("")

        return "\n".join(lines)
    except Exception as e:
        return f"Error: {sanitize_mcp_error(str(e))}"


@audited_tool(mcp)
async def kill_kernel_session(session_id: str) -> str:
    """
    Terminate a kernel session and free its resources.

    Args:
        session_id: Session ID to terminate

    Returns:
        Confirmation message.
    """
    if not session_id:
        return "Error: session_id is required"

    gw = _gateway_url()
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.delete(
                f"{gw}/api/sessions/{session_id}",
                headers=_gw_headers(),
            )
        if r.status_code == 204:
            return f"Session {session_id} terminated."
        if r.status_code == 404:
            return "Session not found (may have already been reaped)."
        return sanitize_proxy_response(r.status_code, r.text)
    except Exception as e:
        return f"Error: {sanitize_mcp_error(str(e))}"
