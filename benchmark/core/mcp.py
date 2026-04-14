"""MCP config loader + SignalPilot connection registration helpers."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .logging import log
from .paths import BIGQUERY_SA_FILE, GATEWAY_SRC, MCP_CONFIG, SNOWFLAKE_ENV_FILE


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
