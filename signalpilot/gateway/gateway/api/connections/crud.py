from __future__ import annotations

import asyncio
import logging
import time
import uuid

from fastapi import HTTPException, Query, Request
from fastapi.responses import JSONResponse

from gateway.api.connections._refresh import _auto_schema_refresh
from gateway.api.connections._router import router
from gateway.api.connections._validation import _validate_connection_params
from gateway.api.deps import StoreD
from gateway.auth import OrgAdmin
from gateway.common.ip import request_meta
from gateway.connectors.pool_manager import pool_manager
from gateway.connectors.schema_cache import schema_cache
from gateway.connectors.xata_creds import is_pinned
from gateway.models import AuditEntry, ConnectionCreate, ConnectionUpdate
from gateway.security.scope_guard import RequireScope
from gateway.store import CredentialEncryptionError

logger = logging.getLogger(__name__)

# When adding a new secret-bearing field to ConnectionUpdate, also add
# the field name here so connection_update audit entries correctly flag
# credential rotation. The set is intentionally explicit (not derived
# from the model) to make the audit-policy decision visible at the
# call site.
_SECRET_FIELDS: frozenset[str] = frozenset({
    "connection_string",
    "password",
    "credentials_json",
    "access_token",
    "private_key",
    "private_key_passphrase",
    "ssh_tunnel",
})

# A pinned connection (a demo sandbox) is defined by *where it points*: its
# project, its one branch, and the control-plane it talks to. Those are enforced
# on every request against the connection's stored extras, so allowing an edit
# to move them would hand back everything the pin exists to prevent — a user
# could repoint at another user's branch and pull write credentials for it, or
# repoint xata_api_url at a host of their choosing and be handed the org key as
# a Bearer token. Only cosmetic fields stay editable.
_PINNED_EDITABLE_FIELDS: frozenset[str] = frozenset({
    "description",
    "tags",
    "schema_filter_include",
    "schema_filter_exclude",
})

# Xata identity lives in the encrypted extras, not on ConnectionInfo, so it has
# to be folded back in to revalidate an edit — without it the rebuilt
# ConnectionCreate looks like a connection with no project and no key.
_XATA_IDENTITY_EXTRAS: tuple[str, ...] = (
    "branch",
    "xata_api_key",
    "xata_api_url",
    "xata_organization",
    "xata_project",
    "xata_database",
    "xata_credential_ref",
    "xata_pinned",
)


@router.get("/connections", dependencies=[RequireScope("read")])
async def get_connections(store: StoreD):
    return await store.list_connections()


@router.post("/connections", status_code=201, dependencies=[RequireScope("write")])
async def add_connection(conn: ConnectionCreate, store: StoreD, _role: OrgAdmin):
    # Enforce connection limit based on org's plan tier
    from gateway.governance.plan_limits import check_connection_limit, get_org_limits

    plan = await get_org_limits(store.org_id)
    current_connections = await store.list_connections()
    check_connection_limit(len(current_connections), plan)

    errors = _validate_connection_params(conn)
    if errors:
        raise HTTPException(status_code=422, detail={"validation_errors": errors})
    try:
        info = await store.create_connection(conn)
    except ValueError:
        raise HTTPException(status_code=409, detail="Connection already exists or invalid parameters")

    asyncio.create_task(_auto_schema_refresh(info.name, info.db_type, store))
    return info


@router.get("/connections/{name}", dependencies=[RequireScope("read")])
async def get_connection_detail(name: str, store: StoreD):
    conn = await store.get_connection(name)
    if not conn:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")
    return conn


@router.delete("/connections/{name}", status_code=204, response_model=None, dependencies=[RequireScope("write")])
async def remove_connection(name: str, store: StoreD, _role: OrgAdmin, request: Request):
    # Demo connections own a private Xata branch: capture the cleanup (with the
    # connection's stored credentials) BEFORE the row is deleted, run it after.
    from gateway.api.demo import prepare_demo_branch_cleanup

    demo_cleanup = await prepare_demo_branch_cleanup(store, name)

    if not await store.delete_connection(name):
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")
    schema_cache.invalidate(name)

    if demo_cleanup is not None:
        await demo_cleanup()

    client_ip, user_agent = request_meta(request)
    # Audit-DB failure must not block the completed deletion; best-effort observability.
    try:
        await store.append_audit(
            AuditEntry(
                id=str(uuid.uuid4()),
                timestamp=time.time(),
                event_type="connection_delete",
                metadata={"name": name},
                client_ip=client_ip,
                user_agent=user_agent,
            )
        )
    except Exception:
        logger.warning("Failed to append audit log for connection_delete name=%s", name)


@router.put("/connections/{name}", dependencies=[RequireScope("write")])
async def edit_connection(name: str, update: ConnectionUpdate, store: StoreD, _role: OrgAdmin, request: Request):
    """Update an existing connection. Only provided fields are changed."""
    existing = await store.get_connection(name)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    stored_extras = await store.get_credential_extras(name) or {}

    update_data = update.model_dump(exclude_none=True)
    if is_pinned(stored_extras):
        moved = sorted(update_data.keys() - _PINNED_EDITABLE_FIELDS)
        if moved:
            raise HTTPException(
                status_code=403,
                detail=(
                    "This is a fixed sandbox connection; "
                    f"{', '.join(moved)} cannot be changed. Remove it and add it again instead."
                ),
            )

    if update_data:
        merged_db_type = update_data.get("db_type", existing.db_type)
        identity = {k: stored_extras[k] for k in _XATA_IDENTITY_EXTRAS if k in stored_extras}
        merged = ConnectionCreate(
            name=name,
            db_type=merged_db_type,
            **{
                k: v
                for k, v in {**existing.model_dump(), **identity, **update_data}.items()
                if k not in ("id", "created_at", "last_used", "status", "name", "db_type")
            },
        )
        errors = _validate_connection_params(merged)
        if errors:
            raise HTTPException(status_code=422, detail={"validation_errors": errors})

    old_conn_str = await store.get_connection_string(name)
    credentials_changed = bool(_SECRET_FIELDS & update_data.keys())

    try:
        result = await store.update_connection(name, update)
    except CredentialEncryptionError:
        return JSONResponse(
            status_code=422,
            content={"error": "Failed to update connection credentials."},
        )
    if not result:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    schema_cache.invalidate(name)
    if old_conn_str:
        await pool_manager.close_pool(old_conn_str)

    client_ip, user_agent = request_meta(request)
    # Audit-DB failure must not block the completed update; best-effort observability.
    try:
        await store.append_audit(
            AuditEntry(
                id=str(uuid.uuid4()),
                timestamp=time.time(),
                event_type="connection_update",
                metadata={"name": name, "credentials_changed": credentials_changed},
                client_ip=client_ip,
                user_agent=user_agent,
            )
        )
    except Exception:
        logger.warning("Failed to append audit log for connection_update name=%s", name)

    return result


@router.post("/connections/{name}/clone", dependencies=[RequireScope("write")])
async def clone_connection(name: str, store: StoreD, new_name: str = Query(..., min_length=1, max_length=64)):
    """Clone an existing connection with a new name."""
    existing = await store.get_connection(name)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    if await store.get_connection(new_name):
        raise HTTPException(status_code=409, detail=f"Connection '{new_name}' already exists")

    clone_desc = f"Clone of {name}" if not existing.description else f"{existing.description} (clone)"
    create_data: dict = {
        "name": new_name,
        "db_type": existing.db_type,
        "description": clone_desc,
    }
    for field in (
        "host",
        "port",
        "database",
        "username",
        "account",
        "warehouse",
        "schema_name",
        "role",
        "project",
        "dataset",
        "http_path",
        "catalog",
    ):
        val = getattr(existing, field, None)
        if val is not None:
            create_data[field] = val

    conn_str = await store.get_connection_string(name)
    if conn_str:
        create_data["connection_string"] = conn_str

    conn = ConnectionCreate(**create_data)
    try:
        result = await store.create_connection(conn)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return result
