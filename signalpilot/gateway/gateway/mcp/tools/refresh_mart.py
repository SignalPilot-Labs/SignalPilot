"""refresh_mart — the agent's only warehouse WRITE action.

The one problem this solves: an analytic mart is stale (e.g. a nightly build,
so today isn't in it yet) and the agent needs it current to answer. refresh_mart
rebuilds that mart's lineage from the raw prod sources INTO the shared dev
database (SP_CHAT_DEV_DATABASE, e.g. Analytics_dev) — production `Analytics`
stays strictly read-only.

It runs `dbt run --select +<mart>` in the same gateway-held executor as
dbt_execute (credentials never reach the agent), but targets the dev database
with the project's normal schemas so the refreshed mart is shared by everyone.
A per-mart lock collapses concurrent refreshes of the same mart into one build.
"""

from __future__ import annotations

import asyncio
import re

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
    dev_database,
    ensure_executor,
    run_dbt_command,
)

# dbt node names only — the tool supplies the `+` upstream selector itself, so a
# caller can never smuggle selector/flag syntax through this field.
_MART_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# One lock per (org, project, branch, mart) so simultaneous requests for the
# same mart run a single build and the rest reuse it, instead of racing two
# `dbt run`s at the same target objects (which SQL Server would deadlock).
_mart_locks: dict[str, asyncio.Lock] = {}
_locks_guard = asyncio.Lock()


async def _lock_for(key: str) -> asyncio.Lock:
    async with _locks_guard:
        lock = _mart_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _mart_locks[key] = lock
        return lock


def _denial() -> str | None:
    capabilities = mcp_capabilities_var.get(None) or []
    if DBT_EXECUTE_CAPABILITY not in capabilities:
        return "Error: refresh_mart is not enabled for this session"
    identity = mcp_execution_identity_var.get(None) or ""
    if not identity.startswith("chat:"):
        return "Error: refresh_mart requires a chat execution identity"
    return None


@audited_tool(mcp)
async def refresh_mart(mart: str) -> str:
    """
    Rebuild a stale analytic mart so it reflects the latest raw data.

    Runs `dbt run --select +<mart>` — rebuilding the mart and its upstream
    lineage from the raw production sources — into the shared dev database.
    Production stays read-only; the refreshed mart is materialized in the dev
    database for you (and everyone) to read.

    Use this ONLY when you have checked that the mart is behind (e.g. its
    MAX(date) is older than the period the question needs). After it returns,
    read the mart again — it is now current.

    Args:
        mart: The dbt model name of the analytic mart to refresh (e.g.
            "fct_daily_sales"). A bare node name — no selector or path syntax.
    """
    if denial := _denial():
        return denial

    mart = (mart or "").strip()
    if not _MART_RE.match(mart):
        return "Error: mart must be a bare dbt model name (letters, digits, underscore)"

    database = dev_database()
    if not database:
        return "Error: no dev database is configured for refreshes (SP_CHAT_DEV_DATABASE)"

    identity = mcp_execution_identity_var.get(None) or ""
    org_id = mcp_org_id_var.get(None) or "local"
    project_id = mcp_project_id_var.get(None)
    branch = mcp_branch_var.get(None) or "main"
    connection_name = mcp_allowed_connection_var.get(None)
    if not project_id or not connection_name:
        return "Error: this session has no project/connection binding"

    lock = await _lock_for(f"{org_id}:{project_id}:{branch}:{mart}")
    async with lock:
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
                    target_database=database,
                )
                # Pristine prod code — no sync from the agent sandbox. The point
                # is to reflect the deployed models, not any local edits.
                argv = build_dbt_argv("run", select=f"+{mart}", dbt_dir=dbt_dir)
                result = await run_dbt_command(sandbox_id, argv, dbt_dir)
                return f"refreshed {mart} into {database} (schema default {schema})\n{result}"
        except DbtExecutorError as exc:
            return f"Error: {exc}"
        except Exception as exc:  # never leak provider/credential internals
            return f"Error refreshing mart: {sanitize_mcp_error(str(exc))}"
