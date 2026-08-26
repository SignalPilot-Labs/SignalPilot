"""MCP config loader + SignalPilot connection registration helpers."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .logging import log
from .paths import BIGQUERY_SA_FILE, GATEWAY_SRC, MCP_CONFIG, SNOWFLAKE_ENV_FILE


def load_mcp_servers() -> dict:
    """Load MCP server configs from mcp_test_config.json.

    - Strips 'cwd' (not supported by SDK) and converts it to a cd+exec wrapper.
    - Injects SP_GATEWAY_URL from the process environment so the MCP subprocess
      can reach the gateway.
    """
    with open(MCP_CONFIG) as f:
        raw = json.load(f)
    servers = raw.get("mcpServers", {})
    gateway_url = os.environ.get("SP_GATEWAY_URL", "http://localhost:3300")
    result: dict = {}
    for name, config in servers.items():
        entry = dict(config)
        # Inject runtime env into MCP subprocess
        env = dict(entry.get("env", {}))
        env["SP_GATEWAY_URL"] = gateway_url
        # Share the Postgres DB so the subprocess sees registered connections
        db_url = os.environ.get("DATABASE_URL", "")
        if db_url:
            env["DATABASE_URL"] = db_url
        entry["env"] = env
        # Convert cwd to a shell wrapper since SDK doesn't support cwd
        cwd = entry.pop("cwd", None)
        if cwd and entry.get("type", "stdio") == "stdio":
            orig_cmd = entry["command"]
            orig_args = entry.get("args", [])
            entry["command"] = "bash"
            entry["args"] = ["-c", f"cd {cwd} && exec {orig_cmd} {' '.join(orig_args)}"]
        result[name] = entry
    return result


def _gateway_url() -> str:
    return os.environ.get("SP_GATEWAY_URL", "http://localhost:3300")


def register_local_connection(instance_id: str, db_path: str) -> bool:
    """Register the task's DuckDB in the shared gateway Postgres store.

    Uses the gateway store directly (same DB the MCP subprocess reads from)
    so connections are visible to MCP tools with the correct encryption key.
    Falls back to HTTP API if direct access fails.
    """
    import asyncio as _aio

    async def _register():
        from gateway.db.engine import get_session_factory
        from gateway.models import ConnectionCreate, DBType
        from gateway.store import Store

        factory = get_session_factory()
        async with factory() as session:
            store = Store(session, org_id=os.environ.get("SP_ORG_ID", "local"))
            try:
                await store.delete_connection(instance_id)
            except Exception:
                pass
            await store.create_connection(ConnectionCreate(
                name=instance_id,
                db_type=DBType.duckdb,
                database=db_path,
                description=f"Spider2-DBT benchmark: {instance_id}",
            ))
            await session.commit()

    try:
        sys.path.insert(0, str(GATEWAY_SRC))
        _aio.run(_register())
        log(f"Registered connection '{instance_id}' -> {db_path}")
        return True
    except Exception as e:
        log(f"Failed to register connection via store: {e}", "WARN")
        # Fallback: try HTTP API
        import httpx
        base = _gateway_url()
        try:
            httpx.delete(f"{base}/api/connections/{instance_id}", timeout=5)
            resp = httpx.post(f"{base}/api/connections", json={
                "name": instance_id,
                "db_type": "duckdb",
                "database": db_path,
                "description": f"Spider2-DBT benchmark: {instance_id}",
            }, timeout=5)
            resp.raise_for_status()
            log(f"Registered connection '{instance_id}' -> {db_path} (via HTTP fallback)")
            return True
        except Exception as e2:
            log(f"Failed to register connection via HTTP: {e2}", "WARN")
            return False


def delete_local_connection(instance_id: str) -> bool:
    """Delete the registered SignalPilot connection (best effort)."""
    import httpx

    try:
        httpx.delete(
            f"{_gateway_url()}/api/connections/{instance_id}",
            timeout=5,
            headers={"x-org-id": os.environ.get("SP_ORG_ID", "local")},
        )
        return True
    except Exception:
        return False


def clear_all_connections() -> int:
    """Delete ALL registered connections via gateway HTTP API.

    Returns the number of connections deleted.
    """
    import httpx

    base = _gateway_url()
    try:
        resp = httpx.get(f"{base}/api/connections", timeout=5)
        resp.raise_for_status()
        conns = resp.json()
        for conn in conns:
            name = conn.get("name", "")
            if name:
                httpx.delete(f"{base}/api/connections/{name}", timeout=5)
                log(f"Cleared stale connection '{name}'")
        return len(conns)
    except Exception as e:
        log(f"Failed to clear connections: {e}", "WARN")
        return 0


def _load_dotenv_file(path: Path) -> dict[str, str]:
    """Parse a .env file and return key/value pairs as a dict.

    Skips blank lines and lines starting with '#'. Strips surrounding quotes from values.
    Does NOT modify os.environ — returns a dict for in-memory use only.
    """
    if not path.exists():
        raise FileNotFoundError(f".env file not found: {path}")
    result: dict[str, str] = {}
    with open(path) as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            result[key] = value
    return result


def register_snowflake_connection(instance_id: str, database: str, schema: str) -> bool:
    """Register a Snowflake connection in the local SignalPilot store.

    Reads credentials from SNOWFLAKE_ENV_FILE. Deletes and re-creates to ensure freshness.
    """
    try:
        env_vars = _load_dotenv_file(SNOWFLAKE_ENV_FILE)
    except FileNotFoundError as e:
        log(f"Snowflake env file not found: {e}", "WARN")
        return False

    try:
        sys.path.insert(0, str(GATEWAY_SRC))
        from gateway.models import ConnectionCreate, DBType
        from gateway.store import create_connection, delete_connection, get_connection

        existing = get_connection(instance_id)
        if existing:
            delete_connection(instance_id)
            log(f"Deleted stale connection '{instance_id}'")

        token = env_vars.get("SNOWFLAKE_TOKEN", "")
        create_connection(
            ConnectionCreate(
                name=instance_id,
                db_type=DBType.snowflake,
                account=env_vars.get("SNOWFLAKE_ACCOUNT"),
                username=env_vars.get("SNOWFLAKE_USER"),
                password=token,
                database=database,
                warehouse=env_vars.get("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH_PARTICIPANT"),
                role=env_vars.get("SNOWFLAKE_ROLE", "PARTICIPANT"),
                schema_name=schema,
                description=f"Spider2-Snowflake benchmark: {instance_id}",
            )
        )
        # Snowflake PAT tokens work as passwords — password auth is correct.
        log(f"Registered Snowflake connection '{instance_id}' -> {database}.{schema}")
        return True
    except Exception as e:
        log(f"Failed to register Snowflake connection: {e}", "WARN")
        return False


def register_sqlite_connection(instance_id: str, db_path: str) -> bool:
    """Register a SQLite connection in the local SignalPilot store."""
    try:
        sys.path.insert(0, str(GATEWAY_SRC))
        from gateway.models import ConnectionCreate, DBType
        from gateway.store import create_connection, delete_connection, get_connection

        existing = get_connection(instance_id)
        if existing:
            delete_connection(instance_id)
            log(f"Deleted stale connection '{instance_id}'")

        create_connection(
            ConnectionCreate(
                name=instance_id,
                db_type=DBType.sqlite,
                database=db_path,
                description=f"Spider2-Lite benchmark: {instance_id}",
            )
        )
        log(f"Registered SQLite connection '{instance_id}' -> {db_path}")
        return True
    except Exception as e:
        log(f"Failed to register SQLite connection: {e}", "WARN")
        return False


def register_bigquery_connection(instance_id: str, project: str, dataset: str) -> bool:
    """Register a BigQuery connection in the local SignalPilot store."""
    try:
        if not BIGQUERY_SA_FILE.exists():
            log(f"BigQuery service account file not found: {BIGQUERY_SA_FILE}", "WARN")
            return False
        sa_json = BIGQUERY_SA_FILE.read_text()

        sys.path.insert(0, str(GATEWAY_SRC))
        from gateway.models import ConnectionCreate, DBType
        from gateway.store import create_connection, delete_connection, get_connection

        existing = get_connection(instance_id)
        if existing:
            delete_connection(instance_id)
            log(f"Deleted stale connection '{instance_id}'")

        create_connection(
            ConnectionCreate(
                name=instance_id,
                db_type=DBType.bigquery,
                project=project,
                dataset=dataset,
                credentials_json=sa_json,
                description=f"Spider2-Lite benchmark: {instance_id}",
            )
        )
        log(f"Registered BigQuery connection '{instance_id}' -> {project}.{dataset}")
        return True
    except Exception as e:
        log(f"Failed to register BigQuery connection: {e}", "WARN")
        return False
