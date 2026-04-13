"""MCP config loader + SignalPilot connection registration helpers."""

from __future__ import annotations

import json
import sys

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


def _register_connection(instance_id: str, conn_create) -> bool:
    """Shared helper: delete any existing connection then create a new one.

    Accepts a fully-constructed ConnectionCreate object. All public
    register_* functions delegate to this helper after building conn_create.
    """
    try:
        sys.path.insert(0, str(GATEWAY_SRC))
        from gateway.store import create_connection, delete_connection, get_connection

        existing = get_connection(instance_id)
        if existing:
            delete_connection(instance_id)
            log(f"Deleted stale connection '{instance_id}'")

        create_connection(conn_create)
        log(f"Registered connection '{instance_id}' (type={conn_create.db_type})")
        return True
    except Exception as e:
        log(f"Failed to register connection '{instance_id}': {e}", "WARN")
        return False


def register_local_connection(instance_id: str, db_path: str) -> bool:
    """Register the task's DuckDB in the local SignalPilot store.

    Always deletes and re-creates to ensure the path matches the current workdir.
    """
    try:
        sys.path.insert(0, str(GATEWAY_SRC))
        from gateway.models import ConnectionCreate, DBType

        conn_create = ConnectionCreate(
            name=instance_id,
            db_type=DBType.duckdb,
            database=db_path,
            description=f"Spider2-DBT benchmark: {instance_id}",
        )
        return _register_connection(instance_id, conn_create)
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


def register_snowflake_connection(
    instance_id: str,
    database: str,
    schema: str,
) -> bool:
    """Register a Snowflake connection using a PAT from SNOWFLAKE_ENV_FILE.

    The SNOWFLAKE_TOKEN in .env.snowflake is a Programmatic Access Token (PAT).
    PATs are authenticated by passing them as the password field — no special
    authenticator value is needed. The token flows as password via ConnectionCreate,
    and _extract_credential_extras in store.py copies it into credential_extras
    so the Snowflake connector uses password auth automatically.
    """
    try:
        sys.path.insert(0, str(GATEWAY_SRC))
        from gateway.models import ConnectionCreate, DBType

        env_vars = _load_dotenv_file(SNOWFLAKE_ENV_FILE)
        account: str = env_vars["SNOWFLAKE_ACCOUNT"]
        user: str = env_vars["SNOWFLAKE_USER"]
        token: str = env_vars["SNOWFLAKE_TOKEN"]
        role: str | None = env_vars.get("SNOWFLAKE_ROLE")
        warehouse: str | None = env_vars.get("SNOWFLAKE_WAREHOUSE")

        conn_create = ConnectionCreate(
            name=instance_id,
            db_type=DBType.snowflake,
            account=account,
            username=user,
            password=token,
            database=database,
            warehouse=warehouse,
            role=role,
            schema_name=schema,
            description=f"Spider2-Snowflake benchmark: {instance_id}",
        )
        ok = _register_connection(instance_id, conn_create)
        if not ok:
            return False

        log(f"Registered Snowflake connection '{instance_id}' using PAT auth")
        return True

    except KeyError as e:
        log(f"Missing Snowflake credential in {SNOWFLAKE_ENV_FILE}: {e}", "ERROR")
        return False
    except Exception as e:
        log(f"Failed to register Snowflake connection '{instance_id}': {e}", "WARN")
        return False


def register_sqlite_connection(instance_id: str, db_path: str) -> bool:
    """Register a SQLite connection for a spider2-lite task."""
    try:
        sys.path.insert(0, str(GATEWAY_SRC))
        from gateway.models import ConnectionCreate, DBType

        conn_create = ConnectionCreate(
            name=instance_id,
            db_type=DBType.sqlite,
            database=db_path,
            description=f"Spider2-Lite SQLite benchmark: {instance_id}",
        )
        return _register_connection(instance_id, conn_create)
    except Exception as e:
        log(f"Failed to register SQLite connection '{instance_id}': {e}", "WARN")
        return False


def register_bigquery_connection(
    instance_id: str,
    project: str,
    dataset: str,
) -> bool:
    """Register a BigQuery connection using the service account JSON file."""
    try:
        sys.path.insert(0, str(GATEWAY_SRC))
        from gateway.models import ConnectionCreate, DBType

        if not BIGQUERY_SA_FILE.exists():
            log(f"BigQuery service account file not found: {BIGQUERY_SA_FILE}", "ERROR")
            return False

        sa_json_str: str = BIGQUERY_SA_FILE.read_text()

        conn_create = ConnectionCreate(
            name=instance_id,
            db_type=DBType.bigquery,
            project=project,
            dataset=dataset,
            credentials_json=sa_json_str,
            description=f"Spider2-Lite BigQuery benchmark: {instance_id}",
        )
        return _register_connection(instance_id, conn_create)
    except Exception as e:
        log(f"Failed to register BigQuery connection '{instance_id}': {e}", "WARN")
        return False


# ── Internal helpers ──────────────────────────────────────────────────────────

def _load_dotenv_file(path) -> dict[str, str]:
    """Parse a .env file into a dict of key/value strings.

    Does not mutate os.environ — used only to read credential files.
    """
    from pathlib import Path as _Path
    env_path = _Path(path)
    if not env_path.exists():
        raise FileNotFoundError(f"Env file not found: {env_path}")
    result: dict[str, str] = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = value.strip().strip('"').strip("'")
    return result
