"""Schema overview, diff, refresh-status and Xata branch endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException, Path, Query
from pydantic import BaseModel, Field

from gateway.api.deps import (
    StoreD,
    get_filtered_schema,
    require_connection,
    sanitize_db_error,
)
from gateway.api.schema._router import router
from gateway.auth import OrgRole
from gateway.auth.permissions import ADMIN_ROLE_REQUIRED, OWNERSHIP_DENIAL
from gateway.auth.user import is_org_admin_role
from gateway.connectors.pool_manager import pool_manager
from gateway.connectors.schema_cache import _compute_schema_diff, schema_cache
from gateway.connectors.xata_creds import is_pinned
from gateway.schema.utils import _infer_implicit_joins
from gateway.security.scope_guard import RequireScope
from gateway.store import xata_branches as branch_owners

logger = logging.getLogger(__name__)


class XataBranchCreate(BaseModel):
    branch_name: str = Field(..., pattern=r"^[A-Za-z0-9_.-]{1,64}$")
    parent_id: str = Field(..., pattern=r"^[A-Za-z0-9_-]{1,64}$")


@router.get("/connections/{name}/schema/overview", dependencies=[RequireScope("read")])
async def get_schema_overview(name: str, store: StoreD):
    """Quick database overview -- table count, total columns, total rows, FK graph density."""
    info = await require_connection(store, name)
    filtered = await get_filtered_schema(store, name, info)

    total_tables = len(filtered)
    total_columns = 0
    total_rows = 0
    total_fks = 0
    total_size_mb = 0.0
    schemas_set: set[str] = set()
    tables_with_fks: set[str] = set()
    largest_tables: list[dict] = []

    for key, table in filtered.items():
        cols = table.get("columns", [])
        total_columns += len(cols)
        row_count = table.get("row_count", 0) or 0
        total_rows += row_count
        total_size_mb += table.get("size_mb", 0) or 0
        schemas_set.add(table.get("schema", ""))
        fks = table.get("foreign_keys", [])
        total_fks += len(fks)
        if fks:
            tables_with_fks.add(key)
        entry: dict = {
            "table": key,
            "columns": len(cols),
            "rows": row_count,
            "fks": len(fks),
        }
        for meta_key in (
            "engine",
            "sorting_key",
            "diststyle",
            "sortkey",
            "clustering_key",
            "partitioning",
            "clustering_fields",
            "size_bytes",
            "size_mb",
            "total_bytes",
        ):
            val = table.get(meta_key)
            if val:
                entry[meta_key] = val
        largest_tables.append(entry)

    largest_tables.sort(key=lambda t: t["rows"], reverse=True)

    inferred_joins = _infer_implicit_joins(filtered)

    return {
        "connection_name": name,
        "db_type": info.db_type,
        "schemas": sorted(schemas_set),
        "schema_count": len(schemas_set),
        "table_count": total_tables,
        "total_columns": total_columns,
        "total_rows": total_rows,
        "total_size_mb": round(total_size_mb, 2),
        "total_foreign_keys": total_fks,
        "tables_with_fks": len(tables_with_fks),
        "avg_columns_per_table": round(total_columns / total_tables, 1) if total_tables else 0,
        "largest_tables": largest_tables[:10],
        "estimated_schema_tokens": total_columns * 8 + total_tables * 20,
        "recommendation": ("compact" if total_columns > 200 else "full" if total_columns < 50 else "enriched"),
        "inferred_joins": len(inferred_joins),
        "spider2_hints": {
            "needs_compression": total_columns > 500,
            "has_partitioned_tables": any("_20" in (t.get("name", "") or "") for t in filtered.values()),
            "join_complexity": (
                "high"
                if (total_fks + len(inferred_joins)) > 15
                else "medium"
                if (total_fks + len(inferred_joins)) > 5
                else "low"
            ),
            "has_implicit_joins": len(inferred_joins) > 0,
        },
    }


@router.get("/connections/{name}/schema/diff", dependencies=[RequireScope("read")])
async def get_schema_diff(name: str, store: StoreD):
    """Compare current database schema against cached version."""
    info = await require_connection(store, name)

    conn_str = await store.get_connection_string(name)
    if not conn_str:
        raise HTTPException(status_code=400, detail="No credentials stored")

    try:
        extras = await store.get_credential_extras(name)
        async with pool_manager.connection(
            info.db_type, conn_str, credential_extras=extras, connection_name=name
        ) as connector:
            new_schema = await connector.get_schema()
    except Exception as e:
        raise HTTPException(status_code=500, detail=sanitize_db_error(str(e), info.db_type))

    diff = schema_cache.diff(name, new_schema)
    if diff is None:
        schema_cache.put(name, new_schema)
        return {
            "connection_name": name,
            "has_cached": False,
            "message": "No cached schema to compare. Current schema cached as baseline.",
            "table_count": len(new_schema),
            "fingerprint": schema_cache.get_fingerprint(name),
        }

    schema_cache.put(name, new_schema, track_diff=True)

    return {
        "connection_name": name,
        "has_cached": True,
        "diff": diff,
        "table_count": len(new_schema),
        "fingerprint": schema_cache.get_fingerprint(name),
    }


async def _live_schema(store, name: str) -> dict[str, Any]:
    """Introspect a connection's current live schema (no cache)."""
    info = await require_connection(store, name)
    conn_str = await store.get_connection_string(name)
    if not conn_str:
        raise HTTPException(status_code=400, detail=f"No credentials stored for '{name}'")
    extras = await store.get_credential_extras(name)
    try:
        async with pool_manager.connection(
            info.db_type, conn_str, credential_extras=extras, connection_name=name
        ) as connector:
            return await connector.get_schema()
    except Exception as e:
        raise HTTPException(status_code=500, detail=sanitize_db_error(str(e), info.db_type))


@router.get("/connections/{base}/schema/diff/{compare}", dependencies=[RequireScope("read")])
async def get_schema_diff_branches(base: str, compare: str, store: StoreD):
    """Diff the live schema of two connections (e.g. two Xata branches).

    Unlike /schema/diff (which compares one connection against its own cached
    snapshot), this compares two distinct connections head-to-head. The primary
    use case is reviewing an upstream branch before it merges: register the base
    branch and the feature branch as two connections, then diff them to see every
    added/removed/retyped column. Uses the same diff engine as the single-connection
    path (_compute_schema_diff).
    """
    base_schema = await _live_schema(store, base)
    compare_schema = await _live_schema(store, compare)
    diff = _compute_schema_diff(base_schema, compare_schema)
    return {
        "base_connection": base,
        "compare_connection": compare,
        "base_table_count": len(base_schema),
        "compare_table_count": len(compare_schema),
        "diff": diff,
    }


async def _live_schema_for_conn_str(info, conn_str: str, extras: dict, name: str) -> dict[str, Any]:
    """Introspect an arbitrary connection string with a connection's db_type/extras."""
    try:
        async with pool_manager.connection(
            info.db_type, conn_str, credential_extras=extras, connection_name=name
        ) as connector:
            return await connector.get_schema()
    except Exception as e:
        raise HTTPException(status_code=500, detail=sanitize_db_error(str(e), info.db_type))


@router.get("/connections/{name}/xata/branch-diff", dependencies=[RequireScope("read")])
async def get_xata_branch_diff(
    name: str,
    store: StoreD,
    base: str = Query(..., pattern=r"^[A-Za-z0-9_.-]{1,64}$"),
    compare: str = Query(..., pattern=r"^[A-Za-z0-9_.-]{1,64}$"),
):
    """Diff two Xata branches addressed from ONE registered Xata connection.

    The gateway resolves each branch's Postgres endpoint server-side from the
    stored control-plane API key (new Xata: <branchID>.<region>.xata.tech): the
    agent only names the branches, never a URL or key.
    """
    from gateway.connectors.drivers.xata import XataConnector

    info = await require_connection(store, name)
    extras = await store.get_credential_extras(name)
    # A pinned connection can only see its own branch, so there is nothing to diff.
    _require_xata_scope(extras, branch=base)
    _require_xata_scope(extras, branch=compare)
    try:
        base_cs = await XataConnector._resolve_endpoint({**extras, "branch": base})
        compare_cs = await XataConnector._resolve_endpoint({**extras, "branch": compare})
    except Exception as e:
        raise HTTPException(status_code=502, detail=sanitize_db_error(str(e), info.db_type))
    base_schema = await _live_schema_for_conn_str(info, base_cs, extras, f"{name}_base")
    compare_schema = await _live_schema_for_conn_str(info, compare_cs, extras, f"{name}_compare")
    return {
        "connection": name,
        "base_branch": base,
        "compare_branch": compare,
        "diff": _compute_schema_diff(base_schema, compare_schema),
    }


# Branches that NEVER yield writable dbt credentials. dbt write access is issued only
# for non-protected (agent-created) branches; production/base branches stay read-only and
# are reachable only through the governed MCP query path. Override/extend per connection
# with a comma-separated `xata_protected_branches` credential extra.
_PROTECTED_BRANCHES = {"main", "master", "staging", "prod", "production", "default"}


def _require_xata_scope(extras: dict, *, project: str | None = None, branch: str | None = None) -> None:
    """403 if a pinned connection (e.g. a demo sandbox) is addressed off-scope.

    Demo connections are backed by an org-wide control-plane key, so without
    this the caller-supplied project/branch would let one workspace reach every
    project in the org and every other user's demo branch.
    """
    from gateway.connectors.xata_creds import XataScopeError, enforce_xata_scope

    try:
        enforce_xata_scope(extras, project=project, branch=branch)
    except XataScopeError as e:
        raise HTTPException(status_code=403, detail=str(e))


def _resolve_protected(extras: dict) -> set[str]:
    protected = set(_PROTECTED_BRANCHES)
    extra = extras.get("xata_protected_branches")
    if extra:
        protected |= {b.strip().lower() for b in str(extra).split(",") if b.strip()}
    return protected


@router.get("/connections/{name}/xata/dbt-profile", dependencies=[RequireScope("write")])
async def get_xata_dbt_profile(
    name: str,
    store: StoreD,
    branch: str = Query(..., pattern=r"^[A-Za-z0-9_.-]{1,64}$"),
    profile: str = Query("default", pattern=r"^[A-Za-z0-9_.-]{1,64}$"),
    target: str | None = Query(default=None, pattern=r"^[A-Za-z0-9_.-]{1,64}$"),
    schema: str = Query("public", pattern=r"^[A-Za-z0-9_.-]{1,64}$"),
):
    """Resolve a NON-protected Xata branch to a dbt `profiles.yml` target block (write path).

    Enforces the protected-branch denylist server-side: main/staging/prod/etc. never yield
    writable dbt credentials: only agent-created branches do, and those are throwaway
    copy-on-write branches. The gateway resolves the branch's Postgres endpoint from the
    stored control-plane key; this is the one place a branch credential is surfaced, and
    only for a non-protected branch.
    """
    from urllib.parse import unquote, urlparse

    from gateway.connectors.drivers.xata import XataConnector

    info = await require_connection(store, name)
    if "xata" not in (info.db_type or "").lower():
        raise HTTPException(status_code=400, detail=f"Connection '{name}' is not a Xata connection")
    extras = await store.get_credential_extras(name)
    # Pinned (demo) connections may only ever be handed credentials for their own
    # branch: branch names are enumerable, so without this one demo user could
    # pull write credentials for another's sandbox.
    _require_xata_scope(extras, branch=branch)
    if branch.lower() in _resolve_protected(extras):
        raise HTTPException(
            status_code=403,
            detail=(
                f"Branch '{branch}' is protected — dbt write credentials are only issued for "
                f"non-protected (agent-created) branches. Fork a new branch first."
            ),
        )
    # Resolve the parent branch for the audit log only. Forking a protected branch
    # (e.g. an agent fork of `main`/`staging`) IS the intended workflow: the fork is an
    # isolated copy-on-write branch, so write credentials to it never touch the parent.
    # The branch-name denylist above is the real gate (creds are never issued for a
    # protected branch itself). Best-effort; never blocks issuance.
    parent: str | None = None
    try:
        project = extras.get("xata_project")
        if project and extras.get("xata_api_key"):
            async with _xata_control_from_extras(extras) as client:
                branches = await client.list_branches(project)
                match = next((b for b in branches if b.get("name") == branch), None)
                parent_id = (match or {}).get("parentID")
                if parent_id:
                    parent_branch_record = next((b for b in branches if b.get("id") == parent_id), None)
                    parent = (parent_branch_record or {}).get("name")
    except Exception:
        parent = None  # Use "?" in the audit log when the control plane is unavailable.
    try:
        cs = await XataConnector._resolve_endpoint({**extras, "branch": branch})
    except Exception as e:
        raise HTTPException(status_code=502, detail=sanitize_db_error(str(e), info.db_type))

    logger.info(
        "xata.dbt_profile.issued connection=%s branch=%s parent_branch=%s org=%s",
        name, branch, parent or "?", getattr(store, "org_id", "?"),
    )
    u = urlparse(cs)
    tgt = target or branch
    params = {
        "host": u.hostname,
        "port": u.port or 5432,
        "user": unquote(u.username or ""),
        "dbname": (u.path or "/").lstrip("/") or "xata",
        "schema": schema,
    }
    password = unquote(u.password or "")
    block = (
        f"      {tgt}:\n"
        f"        type: postgres\n"
        f"        host: {params['host']}\n"
        f"        port: {params['port']}\n"
        f"        user: {params['user']}\n"
        f"        password: <fetched-server-side; see 'output' field>\n"
        f"        dbname: {params['dbname']}\n"
        f"        schema: {params['schema']}\n"
        f"        threads: 4\n"
        f"        sslmode: require\n"
    )
    output = {
        "type": "postgres",
        "host": params["host"],
        "port": params["port"],
        "user": params["user"],
        "password": password,
        "dbname": params["dbname"],
        "schema": params["schema"],
        "threads": 4,
        "sslmode": "require",
    }
    return {
        "connection": name,
        "branch": branch,
        "profile": profile,
        "target": tgt,
        "params": params,  # non-secret connection params (no password)
        "output": output,  # full dbt target incl. password: for direct fetch-to-file
        "profiles_target_block": block,  # template only: password is redacted; fetch via 'output' field for automation
    }


def _xata_control_from_extras(extras: dict) -> Any:
    """Build a XataControlClient from a connection's stored extras.

    Send the control-plane API key as a bearer token with xata_organization.
    Obtain the key from xata_api_key or xata_credential_ref.
    """
    from gateway.connectors.xata_control import XataControlClient, XataControlConfig
    from gateway.connectors.xata_creds import XataCredentialError, resolve_xata_extras

    # Demo connections reference the server-side secret instead of the organization key.
    # Resolve the secret before the function creates the client.
    try:
        extras = resolve_xata_extras(extras)
    except XataCredentialError as e:
        raise HTTPException(status_code=503, detail=str(e))

    api_url = extras.get("xata_api_url") or "https://api.xata.tech"
    org = extras.get("xata_organization") or extras.get("xata_org")
    if not org:
        raise HTTPException(
            status_code=400,
            detail="xata_organization not configured for this connection",
        )

    api_key = extras.get("xata_api_key")
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail="No Xata control-plane credentials configured (set xata_api_key)",
        )
    return XataControlClient(XataControlConfig(api_url=api_url, org=org, bearer_token=api_key))


@router.get("/connections/{name}/xata/projects/{project}/branches", dependencies=[RequireScope("read")])
async def list_xata_branches(
    name: str,
    store: StoreD,
    project: str = Path(..., pattern=r"^[A-Za-z0-9_-]{1,64}$"),
):
    """List branches in a Xata project (control plane)."""
    info = await require_connection(store, name)
    extras = await store.get_credential_extras(name)
    _require_xata_scope(extras, project=project)
    try:
        async with _xata_control_from_extras(extras) as client:
            return {"branches": await client.list_branches(project)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=sanitize_db_error(str(e), info.db_type))


@router.post("/connections/{name}/xata/projects/{project}/branches", dependencies=[RequireScope("write")])
async def create_xata_branch(
    name: str,
    store: StoreD,
    body: XataBranchCreate,
    project: str = Path(..., pattern=r"^[A-Za-z0-9_-]{1,64}$"),
):
    """Create an instant copy-on-write branch from a parent (control plane, write scope).

    The caller is recorded as the branch's creator (gateway_xata_branch_owners),
    which is what the delete route's creator-or-admin rule reads.
    """
    info = await require_connection(store, name)
    extras = await store.get_credential_extras(name)
    _require_xata_scope(extras, project=project)
    if is_pinned(extras):
        # A pinned connection owns exactly one branch; forking more would create
        # branches nothing tracks or cleans up.
        raise HTTPException(
            status_code=403,
            detail="This connection is a fixed sandbox branch and cannot create further branches.",
        )
    try:
        async with _xata_control_from_extras(extras) as client:
            created = await client.create_child_branch(project, body.branch_name, body.parent_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=sanitize_db_error(str(e), info.db_type))
    await branch_owners.record_branch_owner(
        store.session,
        org_id=store.org_id or "local",
        connection_name=name,
        project=project,
        branch=body.branch_name,
        user_id=store.user_id or "local",
    )
    return created


@router.delete(
    "/connections/{name}/xata/projects/{project}/branches/{branch}",
    dependencies=[RequireScope("write")],
)
async def delete_xata_branch(
    name: str,
    store: StoreD,
    role: OrgRole,
    project: str = Path(..., pattern=r"^[A-Za-z0-9_-]{1,64}$"),
    branch: str = Path(..., pattern=r"^[A-Za-z0-9_.-]{1,64}$"),
):
    """Delete a Xata branch by NAME (control plane, write scope). Resolves the
    branch id server-side, then deletes. Used for post-merge cleanup.

    Creator or admin: a member deletes only the branches they created through
    the gateway; a branch with no creator record needs an admin.
    """
    info = await require_connection(store, name)
    extras = await store.get_credential_extras(name)
    _require_xata_scope(extras, project=project)
    if not is_org_admin_role(role):
        owner = await branch_owners.get_branch_owner(
            store.session,
            org_id=store.org_id or "local",
            connection_name=name,
            project=project,
            branch=branch,
        )
        if owner is None:
            raise HTTPException(status_code=403, detail=ADMIN_ROLE_REQUIRED)
        if owner != (store.user_id or "local"):
            raise HTTPException(status_code=403, detail=OWNERSHIP_DENIAL)
    if is_pinned(extras):
        # The demo branch's lifecycle is owned by the connection: it is deleted
        # when the connection is removed, not by the agent.
        raise HTTPException(
            status_code=403,
            detail="This connection is a fixed sandbox branch; remove the connection to delete it.",
        )
    if branch.lower() in _resolve_protected(extras):
        raise HTTPException(
            status_code=403,
            detail=(
                f"Branch '{branch}' is protected — refuse to delete via the agent path."
            ),
        )
    try:
        async with _xata_control_from_extras(extras) as client:
            b = next((x for x in await client.list_branches(project) if x.get("name") == branch), None)
            if not b:
                raise HTTPException(status_code=404, detail=f"branch '{branch}' not found")
            await client.delete_branch(project, b["id"])
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=sanitize_db_error(str(e), info.db_type))
    await branch_owners.forget_branch_owner(
        store.session,
        org_id=store.org_id or "local",
        connection_name=name,
        project=project,
        branch=branch,
    )
    return {"status": "deleted", "branch": branch}


@router.get("/connections/{name}/schema/refresh-status", dependencies=[RequireScope("read")])
async def get_schema_refresh_status(name: str, store: StoreD):
    """Get schema refresh schedule status for a connection."""
    info = await require_connection(store, name)

    cached_stats = schema_cache.get(name)
    return {
        "connection_name": name,
        "schema_refresh_interval": info.schema_refresh_interval,
        "last_schema_refresh": info.last_schema_refresh,
        "next_refresh_at": (
            info.last_schema_refresh + info.schema_refresh_interval
            if info.last_schema_refresh and info.schema_refresh_interval
            else None
        ),
        "cached": cached_stats is not None,
        "cached_table_count": len(cached_stats) if cached_stats else 0,
        "fingerprint": schema_cache.get_fingerprint(name),
    }


@router.get("/connections/{name}/schema/diff-history", dependencies=[RequireScope("read")])
async def get_schema_diff_history(name: str, store: StoreD):
    """Get schema change history for a connection."""
    await require_connection(store, name)

    history = schema_cache.get_diff_history(name)
    return {
        "connection_name": name,
        "events": history,
        "current_fingerprint": schema_cache.get_fingerprint(name),
    }
