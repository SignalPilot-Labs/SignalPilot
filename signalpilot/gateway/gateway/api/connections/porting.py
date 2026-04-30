from __future__ import annotations

import logging
import time

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from gateway.api.connections._router import router
from gateway.api.connections._validation import _validate_connection_params
from gateway.api.deps import StoreD
from gateway.models import ConnectionCreate
from gateway.security.scope_guard import RequireScope, require_scopes
from gateway.store import CredentialEncryptionError

logger = logging.getLogger(__name__)


class ExportRequest(BaseModel):
    include_credentials: bool
    confirm: bool


@router.post("/connections/export", dependencies=[RequireScope("write")])
async def export_connections(
    body: ExportRequest,
    store: StoreD,
    request: Request,
):
    """Export all connections as a portable JSON manifest.

    Requires explicit confirmation via POST body.
    Credential export is audit-logged.
    Exporting credentials requires admin scope in addition to write scope.
    """
    if body.include_credentials:
        require_scopes(request, "admin")

    if not body.confirm:
        return JSONResponse(
            status_code=400,
            content={"error": "Export requires confirm=true in the request body."},
        )

    logger.warning(
        "Credential export requested by org %s, include_credentials=%s",
        store.org_id,
        body.include_credentials,
    )

    all_conns = await store.list_connections()
    exported = []
    for conn in all_conns:
        conn_dict = conn.model_dump() if hasattr(conn, "model_dump") else dict(conn)
        entry: dict = {
            "name": conn_dict.get("name", ""),
            "db_type": conn_dict.get("db_type", ""),
            "description": conn_dict.get("description", ""),
            "tags": conn_dict.get("tags", []),
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
            "location",
            "maximum_bytes_billed",
            "schema_filter_include",
            "schema_filter_exclude",
            "schema_refresh_interval",
            "connection_timeout",
            "query_timeout",
            "keepalive_interval",
        ):
            val = conn_dict.get(field)
            if val is not None:
                entry[field] = val

        if body.include_credentials:
            try:
                conn_str = await store.get_connection_string(entry["name"])
                if conn_str:
                    entry["connection_string"] = conn_str
            except CredentialEncryptionError:
                return JSONResponse(
                    status_code=422,
                    content={"error": "Failed to decrypt connection credentials."},
                )
            if conn_dict.get("ssl_config"):
                entry["ssl_config"] = conn_dict["ssl_config"]
            if conn_dict.get("ssh_tunnel"):
                entry["ssh_tunnel"] = conn_dict["ssh_tunnel"]

        exported.append(entry)

    return {
        "version": "1.0",
        "exported_at": time.time(),
        "connection_count": len(exported),
        "includes_credentials": body.include_credentials,
        "connections": exported,
    }


@router.post("/connections/import", dependencies=[RequireScope("write")])
async def import_connections(manifest: dict, store: StoreD):
    """Import connections from an exported JSON manifest."""
    connections = manifest.get("connections", [])
    if len(connections) > 500:
        raise HTTPException(status_code=422, detail="Maximum 500 connections per import")
    results = {"imported": 0, "skipped": [], "errors": []}

    for entry in connections:
        name = entry.get("name", "")
        if not name:
            results["errors"].append({"name": "(empty)", "error": "Missing connection name"})
            continue

        if await store.get_connection(name):
            results["skipped"].append(name)
            continue

        try:
            conn = ConnectionCreate(**entry)
            errors = _validate_connection_params(conn)
            if errors:
                results["errors"].append({"name": name, "error": errors[0]})
                continue
            await store.create_connection(conn)
            results["imported"] += 1
        except Exception:
            results["errors"].append({"name": name, "error": "Failed to import connection"})

    return results
