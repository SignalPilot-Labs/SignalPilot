from __future__ import annotations

import asyncio

from fastapi import HTTPException, Query
from fastapi.responses import JSONResponse

from gateway.api.connections._refresh import _auto_schema_refresh
from gateway.api.connections._router import router
from gateway.api.connections._validation import _validate_connection_params
from gateway.api.deps import StoreD
from gateway.auth import OrgAdmin
from gateway.connectors.pool_manager import pool_manager
from gateway.connectors.schema_cache import schema_cache
from gateway.models import ConnectionCreate, ConnectionUpdate
from gateway.scope_guard import RequireScope
from gateway.store import CredentialEncryptionError


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


@router.delete("/connections/{name}", status_code=204, dependencies=[RequireScope("write")])
async def remove_connection(name: str, store: StoreD, _role: OrgAdmin):
    if not await store.delete_connection(name):
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")
    schema_cache.invalidate(name)


@router.put("/connections/{name}", dependencies=[RequireScope("write")])
async def edit_connection(name: str, update: ConnectionUpdate, store: StoreD, _role: OrgAdmin):
    """Update an existing connection. Only provided fields are changed."""
    existing = await store.get_connection(name)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Connection '{name}' not found")

    update_data = update.model_dump(exclude_none=True)
    if update_data:
        merged_db_type = update_data.get("db_type", existing.db_type)
        merged = ConnectionCreate(
            name=name,
            db_type=merged_db_type,
            **{
                k: v
                for k, v in {**existing.model_dump(), **update_data}.items()
                if k not in ("id", "created_at", "last_used", "status", "name", "db_type")
            },
        )
        errors = _validate_connection_params(merged)
        if errors:
            raise HTTPException(status_code=422, detail={"validation_errors": errors})

    old_conn_str = await store.get_connection_string(name)

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
