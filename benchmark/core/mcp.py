"""MCP config loader + SignalPilot connection registration helpers."""

from __future__ import annotations

import json
import sys

from .logging import log
from .paths import GATEWAY_SRC, MCP_CONFIG


def load_mcp_servers() -> dict:
    """Load MCP server configs from mcp_test_config.json, stripping unsupported 'cwd' key."""
    with open(MCP_CONFIG) as f:
        raw = json.load(f)
    servers = raw.get("mcpServers", {})
    result: dict = {}
    for name, config in servers.items():
        entry = {k: v for k, v in config.items() if k != "cwd"}
        result[name] = entry
    return result


def register_local_connection(instance_id: str, db_path: str) -> bool:
    """Register the task's DuckDB in the local SignalPilot store.

    Always deletes and re-creates to ensure the path matches the current workdir.
    """
    try:
        sys.path.insert(0, str(GATEWAY_SRC))
        from gateway.store import create_connection, delete_connection, get_connection
        from gateway.models import ConnectionCreate, DBType

        existing = get_connection(instance_id)
        if existing:
            delete_connection(instance_id)
            log(f"Deleted stale connection '{instance_id}'")

        create_connection(
            ConnectionCreate(
                name=instance_id,
                db_type=DBType.duckdb,
                database=db_path,
                description=f"Spider2-DBT benchmark: {instance_id}",
            )
        )
        log(f"Registered connection '{instance_id}' -> {db_path}")
        return True
    except Exception as e:
        log(f"Failed to register local connection: {e}", "WARN")
        return False


def delete_local_connection(instance_id: str) -> bool:
    """Delete the registered SignalPilot connection for this instance (best effort)."""
    try:
        sys.path.insert(0, str(GATEWAY_SRC))
        from gateway.store import delete_connection

        delete_connection(instance_id)
        return True
    except Exception:
        return False
