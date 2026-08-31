"""dbt_execute — the chat agent's ONLY interface to warehouse-connected dbt.

The command runs in the per-chat EXECUTOR sandbox (see
standalone_chat/dbt_executor.py), which holds the generated profiles.yml.
The agent has no exec/read/write tool that accepts the executor's identity,
so credentials are structurally out of reach. Argument surface is a hard
allowlist (structured fields, argv-built, never a shell string).
"""

from __future__ import annotations

from gateway.errors.mcp import sanitize_mcp_error
from gateway.mcp.audit import audited_tool
from gateway.mcp.context import (
    _store_session,
    mcp_allowed_connection_var,
    mcp_branch_var,
    mcp_capabilities_var,
    mcp_execution_identity_var,
    mcp_org_id_var,
    mcp_project_id_var,
)
from gateway.mcp.server import mcp
from gateway.standalone_chat.dbt_executor import (
    DBT_EXECUTE_CAPABILITY,
    DbtExecutorError,
    build_dbt_argv,
    ensure_executor,
    run_dbt_command,
    sync_from_agent_sandbox,
)


def _denial() -> str | None:
    capabilities = mcp_capabilities_var.get(None) or []
    if DBT_EXECUTE_CAPABILITY not in capabilities:
        return "Error: dbt_execute is not enabled for this session"
    identity = mcp_execution_identity_var.get(None) or ""
    if not identity.startswith("chat:"):
        return "Error: dbt_execute requires a chat execution identity"
    return None


@audited_tool(mcp)
async def dbt_execute(
    command: str,
    select: str = "",
    exclude: str = "",
    full_refresh: bool = False,
    threads: int = 0,
) -> str:
    """
    Run a dbt command against the project's warehouse connection.

    Executes in a gateway-managed environment that holds the connection
    profile — your own sandbox never has warehouse credentials. Models
    materialize into a per-chat scratch schema (sp_chat_...), never into
    production schemas. Your sandbox's edited model files are synced over
    before the command runs.

    Args:
        command: One of: run, test, build, seed, snapshot, compile, "docs generate".
        select: dbt --select value (node selector syntax), optional.
        exclude: dbt --exclude value, optional.
        full_refresh: Pass --full-refresh (rebuild incremental models).
        threads: Override thread count (1-8), optional.
    """
    if denial := _denial():
        return denial

    identity = mcp_execution_identity_var.get(None) or ""
    org_id = mcp_org_id_var.get(None) or "local"
    project_id = mcp_project_id_var.get(None)
    branch = mcp_branch_var.get(None) or "main"
    connection_name = mcp_allowed_connection_var.get(None)
    if not project_id or not connection_name:
        return "Error: this session has no project/connection binding"

    try:
        async with _store_session() as store:
            sandbox_id, dbt_dir, schema = await ensure_executor(
                store.session,
                identity=identity,
                org_id=org_id,
                project_id=project_id,
                branch=branch,
                connection_name=connection_name,
                store=store,
            )

            # Bring over anything the agent edited in ITS sandbox (if it made one).
            from gateway.mcp.tools.sandbox_vm import _session_sandboxes

            agent_sandbox = _session_sandboxes.get(identity)
            sync_note = ""
            if agent_sandbox:
                sync_note = await sync_from_agent_sandbox(agent_sandbox, sandbox_id)

            argv = build_dbt_argv(
                command,
                select=select,
                exclude=exclude,
                full_refresh=full_refresh,
                threads=threads,
                dbt_dir=dbt_dir,
            )
            result = await run_dbt_command(sandbox_id, argv, dbt_dir)
            header = f"target_schema: {schema}" + (f"\nsync: {sync_note}" if sync_note else "")
            return f"{header}\n{result}"
    except DbtExecutorError as exc:
        return f"Error: {exc}"
    except Exception as exc:  # never leak provider/credential internals
        return f"Error running dbt: {sanitize_mcp_error(str(exc))}"
