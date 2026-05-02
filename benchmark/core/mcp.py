"""MCP config loader + SignalPilot connection registration helpers.

Connection registration goes through the gateway's HTTP API
(``POST /api/connections``) instead of importing ``gateway.store`` directly,
so the runner no longer depends on the gateway's Python package being
import-compatible with the runner's interpreter.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from .logging import log
from .paths import BIGQUERY_SA_FILE, GATEWAY_URL, MCP_CONFIG, SNOWFLAKE_ENV_FILE


def _gateway_request(method: str, path: str, payload: dict | None = None, timeout: int = 10) -> tuple[int, str]:
    """Call the gateway HTTP API and return (status_code, body)."""
    url = f"{GATEWAY_URL.rstrip('/')}{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def _delete_connection_http(name: str) -> bool:
    """Delete a connection via the gateway HTTP API. 404 counts as success."""
    status, _ = _gateway_request("DELETE", f"/api/connections/{name}", timeout=5)
    return status in (200, 204, 404)


def _create_connection_http(payload: dict) -> bool:
    """Create a connection via the gateway HTTP API. Replaces any existing one with the same name."""
    name = payload.get("name", "")
    if name:
        _delete_connection_http(name)
    status, body = _gateway_request("POST", "/api/connections", payload=payload, timeout=15)
    if status not in (200, 201):
        log(f"Connection POST failed for '{name}': HTTP {status} {body[:200]}", "WARN")
        return False
    return True


def load_mcp_servers() -> dict:
    """Load MCP server configs from mcp_config.json.

    - Strips 'cwd' (not supported by SDK) and converts it to a cd+exec wrapper.
    - Injects SP_GATEWAY_URL from the process environment so the MCP subprocess
      can reach the gateway.
    """
    with open(MCP_CONFIG) as f:
        raw = json.load(f)
    servers = raw.get("mcpServers", {})
    gateway_url = os.environ.get("SP_GATEWAY_URL", GATEWAY_URL)
    result: dict = {}
    for name, config in servers.items():
        entry = dict(config)
        env = dict(entry.get("env", {}))
        env["SP_GATEWAY_URL"] = gateway_url
        entry["env"] = env
        cwd = entry.pop("cwd", None)
        if cwd and entry.get("type", "stdio") == "stdio":
            orig_cmd = entry["command"]
            orig_args = entry.get("args", [])
            entry["command"] = "bash"
            entry["args"] = ["-c", f"cd {cwd} && exec {orig_cmd} {' '.join(orig_args)}"]
        result[name] = entry
    return result


def register_local_connection(instance_id: str, db_path: str) -> bool:
    """Register the task's DuckDB connection via the gateway HTTP API."""
    ok = _create_connection_http({
        "name": instance_id,
        "db_type": "duckdb",
        "database": db_path,
        "description": f"Spider2-DBT benchmark: {instance_id}",
    })
    if ok:
        log(f"Registered DuckDB connection '{instance_id}' -> {db_path}")
    return ok


def delete_local_connection(instance_id: str) -> bool:
    """Delete the registered SignalPilot connection for this instance (best effort)."""
    return _delete_connection_http(instance_id)


def clear_all_connections() -> int:
    """Delete ALL registered connections. Call at task start to ensure a clean slate.

    Returns the number of connections deleted.
    """
    status, body = _gateway_request("GET", "/api/connections", timeout=10)
    if status != 200:
        log(f"clear_all_connections: GET /api/connections returned HTTP {status}", "WARN")
        return 0
    try:
        conns = json.loads(body)
    except json.JSONDecodeError:
        log(f"clear_all_connections: invalid JSON from gateway: {body[:200]}", "WARN")
        return 0
    if isinstance(conns, dict):
        conns = conns.get("connections") or conns.get("data") or []
    deleted = 0
    for conn in conns:
        name = conn.get("name") if isinstance(conn, dict) else None
        if not name:
            continue
        if _delete_connection_http(name):
            log(f"Cleared stale connection '{name}'")
            deleted += 1
    return deleted


def _load_dotenv_file(path: Path) -> dict[str, str]:
    """Parse a .env file and return key/value pairs as a dict."""
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
    """Register a Snowflake connection via the gateway HTTP API."""
    try:
        env_vars = _load_dotenv_file(SNOWFLAKE_ENV_FILE)
    except FileNotFoundError as e:
        log(f"Snowflake env file not found: {e}", "WARN")
        return False

    ok = _create_connection_http({
        "name": instance_id,
        "db_type": "snowflake",
        "account": env_vars.get("SNOWFLAKE_ACCOUNT"),
        "username": env_vars.get("SNOWFLAKE_USER"),
        "password": env_vars.get("SNOWFLAKE_TOKEN", ""),
        "database": database,
        "warehouse": env_vars.get("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH_PARTICIPANT"),
        "role": env_vars.get("SNOWFLAKE_ROLE", "PARTICIPANT"),
        "schema_name": schema,
        "description": f"Spider2-Snowflake benchmark: {instance_id}",
    })
    if ok:
        log(f"Registered Snowflake connection '{instance_id}' -> {database}.{schema}")
    return ok


def register_sqlite_connection(instance_id: str, db_path: str) -> bool:
    """Register a SQLite connection via the gateway HTTP API."""
    ok = _create_connection_http({
        "name": instance_id,
        "db_type": "sqlite",
        "database": db_path,
        "description": f"Spider2-Lite benchmark: {instance_id}",
    })
    if ok:
        log(f"Registered SQLite connection '{instance_id}' -> {db_path}")
    return ok


def register_bigquery_connection(instance_id: str, project: str, dataset: str) -> bool:
    """Register a BigQuery connection via the gateway HTTP API."""
    if not BIGQUERY_SA_FILE.exists():
        log(f"BigQuery service account file not found: {BIGQUERY_SA_FILE}", "WARN")
        return False
    sa_json = BIGQUERY_SA_FILE.read_text()

    ok = _create_connection_http({
        "name": instance_id,
        "db_type": "bigquery",
        "project": project,
        "dataset": dataset,
        "credentials_json": sa_json,
        "description": f"Spider2-Lite benchmark: {instance_id}",
    })
    if ok:
        log(f"Registered BigQuery connection '{instance_id}' -> {project}.{dataset}")
    return ok
