"""
Persistent store for connections, sandboxes, settings, and audit log.
Uses JSON files for MVP (easy to inspect, no DB dependency).
Credentials are encrypted at rest using Fernet (AES-128-CBC + HMAC-SHA256).
"""

from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import logging
import os
import stat
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote as url_quote

import aiofiles

from .models import (
    AuditEntry,
    ConnectionCreate,
    ConnectionInfo,
    ConnectionUpdate,
    DBType,
    GatewaySettings,
    SandboxInfo,
    SSHTunnelConfig,
    SSLConfig,
)

logger = logging.getLogger(__name__)

DATA_DIR = Path(os.getenv("SP_DATA_DIR", str(Path.home() / ".signalpilot")))
CONNECTIONS_FILE = DATA_DIR / "connections.json"
CREDENTIALS_FILE = DATA_DIR / "credentials.enc"
SANDBOXES_FILE = DATA_DIR / "sandboxes.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
AUDIT_FILE = DATA_DIR / "audit.jsonl"
SCHEMA_ENDORSEMENTS_FILE = DATA_DIR / "schema_endorsements.json"

# In-memory vault for raw credentials (cache — authoritative source is encrypted file)
_credential_vault: dict[str, str] = {}
# Extra structured credential data (service account JSON, SSH keys, etc.)
_credential_extras: dict[str, dict] = {}
# Schema endorsements — controls which tables/schemas are visible to AI agents
_schema_endorsements: dict[str, dict] = {}  # connection_name -> {endorsed: [...], hidden: [...]}


def _get_encryption_key() -> bytes:
    """Derive a Fernet key from SP_ENCRYPTION_KEY env var or generate a machine-specific one."""
    from cryptography.fernet import Fernet

    key_str = os.getenv("SP_ENCRYPTION_KEY")
    if key_str:
        # User-provided key — use as-is if valid Fernet key, or derive one
        try:
            Fernet(key_str.encode())
            return key_str.encode()
        except Exception:
            # Derive a proper Fernet key from the user string
            digest = hashlib.sha256(key_str.encode()).digest()
            return base64.urlsafe_b64encode(digest)
    else:
        # Auto-generate a machine-specific key and persist it
        key_file = DATA_DIR / ".encryption_key"
        if key_file.exists():
            return key_file.read_bytes().strip()
        else:
            _ensure_data_dir()
            key = Fernet.generate_key()
            key_file.write_bytes(key)
            try:
                key_file.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600
            except OSError:
                pass
            return key


def _encrypt_credentials(data: dict) -> bytes:
    """Encrypt credential data to bytes."""
    from cryptography.fernet import Fernet
    f = Fernet(_get_encryption_key())
    return f.encrypt(json.dumps(data).encode())


def _decrypt_credentials(encrypted: bytes) -> dict:
    """Decrypt credential data from bytes."""
    from cryptography.fernet import Fernet
    f = Fernet(_get_encryption_key())
    return json.loads(f.decrypt(encrypted).decode())


def _save_credentials():
    """Persist encrypted credentials to disk."""
    _ensure_data_dir()
    data = {
        "vault": _credential_vault,
        "extras": _credential_extras,
    }
    encrypted = _encrypt_credentials(data)
    with open(CREDENTIALS_FILE, "wb") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.write(encrypted)
            f.flush()
            os.fsync(f.fileno())
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    try:
        CREDENTIALS_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600
    except OSError:
        pass


def _load_credentials():
    """Load encrypted credentials from disk into memory vault."""
    global _credential_vault, _credential_extras
    if not CREDENTIALS_FILE.exists():
        return
    try:
        with open(CREDENTIALS_FILE, "rb") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            try:
                encrypted = f.read()
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        data = _decrypt_credentials(encrypted)
        _credential_vault = data.get("vault", {})
        _credential_extras = data.get("extras", {})
        logger.info("Loaded %d encrypted credentials from disk", len(_credential_vault))
    except Exception as e:
        logger.warning("Failed to load encrypted credentials: %s", e)


def _ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load_json(path: Path, default: Any) -> Any:
    """Load JSON file with shared (read) locking to prevent read-write races (MED-08 fix)."""
    _ensure_data_dir()
    if not path.exists():
        return default
    try:
        with open(path, "r") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            try:
                return json.load(f)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except Exception:
        return default


def _save_json(path: Path, data: Any):
    """Save JSON file with exclusive locking to prevent concurrent write races (MED-08 fix)."""
    _ensure_data_dir()
    content = json.dumps(data, indent=2)
    with open(path, "w") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    # Restrict file permissions to owner-only (0600) for sensitive data
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass  # May fail on some filesystems (Windows, Docker volumes)


# ─── Settings ────────────────────────────────────────────────────────────────

def load_settings() -> GatewaySettings:
    data = _load_json(SETTINGS_FILE, {})
    # Environment variables override stored settings
    env_overrides = {}
    if os.getenv("SP_SANDBOX_MANAGER_URL"):
        env_overrides["sandbox_manager_url"] = os.getenv("SP_SANDBOX_MANAGER_URL")
    if os.getenv("SP_GATEWAY_URL"):
        env_overrides["gateway_url"] = os.getenv("SP_GATEWAY_URL")
    return GatewaySettings(**{**data, **env_overrides})


def save_settings(settings: GatewaySettings):
    _save_json(SETTINGS_FILE, settings.model_dump())


# ─── Connections ─────────────────────────────────────────────────────────────

# Load encrypted credentials on module import
_load_credentials()


def list_connections() -> list[ConnectionInfo]:
    data = _load_json(CONNECTIONS_FILE, {})
    return [ConnectionInfo(**v) for v in data.values()]


def get_connection(name: str) -> ConnectionInfo | None:
    data = _load_json(CONNECTIONS_FILE, {})
    raw = data.get(name)
    return ConnectionInfo(**raw) if raw else None


def create_connection(conn: ConnectionCreate) -> ConnectionInfo:
    data = _load_json(CONNECTIONS_FILE, {})
    if conn.name in data:
        raise ValueError(f"Connection '{conn.name}' already exists")

    # Strip sensitive fields from SSHTunnelConfig for persistence
    ssh_tunnel_safe = None
    if conn.ssh_tunnel and conn.ssh_tunnel.enabled:
        ssh_tunnel_safe = conn.ssh_tunnel.model_copy(update={
            "password": None, "private_key": None, "private_key_passphrase": None,
        })

    # Strip sensitive fields from SSLConfig for persistence
    ssl_config_safe = None
    if conn.ssl_config and conn.ssl_config.enabled:
        ssl_config_safe = conn.ssl_config

    info = ConnectionInfo(
        id=str(uuid.uuid4()),
        name=conn.name,
        db_type=conn.db_type,
        host=conn.host,
        port=conn.port,
        database=conn.database,
        username=conn.username,
        ssl=conn.ssl,
        ssl_config=ssl_config_safe,
        ssh_tunnel=ssh_tunnel_safe,
        account=conn.account,
        warehouse=conn.warehouse,
        schema_name=conn.schema_name,
        role=conn.role,
        project=conn.project,
        dataset=conn.dataset,
        http_path=conn.http_path,
        catalog=conn.catalog,
        description=conn.description,
        created_at=time.time(),
    )

    # Store raw credential in vault and persist encrypted
    raw_cred = conn.connection_string or _build_connection_string(conn)
    _credential_vault[conn.name] = raw_cred

    # Store extra credential data for connectors that need structured params
    _credential_extras[conn.name] = _extract_credential_extras(conn)

    # Persist both connection metadata and encrypted credentials
    data[conn.name] = info.model_dump()
    _save_json(CONNECTIONS_FILE, data)
    _save_credentials()
    return info


def delete_connection(name: str) -> bool:
    data = _load_json(CONNECTIONS_FILE, {})
    if name not in data:
        return False
    del data[name]
    _credential_vault.pop(name, None)
    _credential_extras.pop(name, None)
    _save_json(CONNECTIONS_FILE, data)
    _save_credentials()
    return True


def update_connection(name: str, update: ConnectionUpdate) -> ConnectionInfo | None:
    """Update an existing connection with partial data. Only provided fields are changed."""
    data = _load_json(CONNECTIONS_FILE, {})
    if name not in data:
        return None

    existing = data[name]
    update_fields = update.model_dump(exclude_none=True)

    # Separate credential fields from metadata fields
    credential_fields = {"password", "connection_string", "credentials_json", "access_token"}
    meta_updates = {k: v for k, v in update_fields.items() if k not in credential_fields}

    # Update metadata fields in connection info
    for key, value in meta_updates.items():
        if key == "ssh_tunnel" and value:
            # Strip sensitive SSH fields for persistence
            ssh_config = SSHTunnelConfig(**value) if isinstance(value, dict) else value
            value = ssh_config.model_copy(update={
                "password": None, "private_key": None, "private_key_passphrase": None,
            }).model_dump()
        if key == "ssl_config" and value:
            if isinstance(value, dict):
                value = SSLConfig(**value).model_dump()
        existing[key] = value

    # Rebuild connection string if credential-related fields changed
    needs_cred_rebuild = any(k in update_fields for k in (
        "host", "port", "database", "username", "password", "connection_string",
        "account", "warehouse", "schema_name", "role", "project",
        "credentials_json", "http_path", "access_token", "catalog",
        "ssl", "ssl_config",
    ))

    if needs_cred_rebuild:
        # Build a synthetic ConnectionCreate from merged data for string building
        db_type = update_fields.get("db_type", existing.get("db_type"))
        merged = {**existing, **update_fields, "name": name, "db_type": db_type}
        # Remove fields not in ConnectionCreate
        for rm_key in ("id", "created_at", "last_used", "status"):
            merged.pop(rm_key, None)
        try:
            create_obj = ConnectionCreate(**merged)
            raw_cred = create_obj.connection_string or _build_connection_string(create_obj)
            _credential_vault[name] = raw_cred
            _credential_extras[name] = _extract_credential_extras(create_obj)
        except Exception:
            pass  # Keep existing credentials if rebuild fails

    data[name] = existing
    _save_json(CONNECTIONS_FILE, data)
    _save_credentials()
    return ConnectionInfo(**existing)


def get_connection_string(name: str) -> str | None:
    return _credential_vault.get(name)


def _build_connection_string(conn: ConnectionCreate) -> str:
    if conn.db_type == DBType.postgres:
        user = url_quote(conn.username or "", safe="")
        pw = f":{url_quote(conn.password or '', safe='')}" if conn.password else ""
        host = conn.host or "localhost"
        port = conn.port or 5432
        db = conn.database or "postgres"
        ssl_mode = conn.ssl_config.mode if conn.ssl_config and conn.ssl_config.enabled else ("require" if conn.ssl else "")
        ssl_param = f"?sslmode={ssl_mode}" if ssl_mode else ""
        return f"postgresql://{user}{pw}@{host}:{port}/{db}{ssl_param}"

    elif conn.db_type == DBType.mysql:
        user = url_quote(conn.username or "", safe="")
        pw = f":{url_quote(conn.password or '', safe='')}" if conn.password else ""
        host = conn.host or "localhost"
        port = conn.port or 3306
        db = conn.database or ""
        return f"mysql+pymysql://{user}{pw}@{host}:{port}/{db}"

    elif conn.db_type == DBType.duckdb:
        return conn.database or ":memory:"

    elif conn.db_type == DBType.sqlite:
        return conn.database or ":memory:"

    elif conn.db_type == DBType.snowflake:
        # Snowflake uses account identifier, not host:port
        account = conn.account or ""
        user = conn.username or ""
        pw = conn.password or ""
        db = conn.database or ""
        wh = conn.warehouse or ""
        schema = conn.schema_name or ""
        role = conn.role or ""
        return f"snowflake://{account}|{user}|{pw}|{db}|{wh}|{schema}|{role}"

    elif conn.db_type == DBType.bigquery:
        # BigQuery uses project + credentials JSON — connection_string holds the project ID
        return conn.project or ""

    elif conn.db_type == DBType.redshift:
        user = url_quote(conn.username or "", safe="")
        pw = f":{url_quote(conn.password or '', safe='')}" if conn.password else ""
        host = conn.host or "localhost"
        port = conn.port or 5439
        db = conn.database or "dev"
        ssl_param = "?sslmode=require" if conn.ssl else ""
        return f"redshift://{user}{pw}@{host}:{port}/{db}{ssl_param}"

    elif conn.db_type == DBType.clickhouse:
        user = url_quote(conn.username or "default", safe="")
        pw = f":{url_quote(conn.password or '', safe='')}" if conn.password else ""
        host = conn.host or "localhost"
        port = conn.port or 9000
        db = conn.database or "default"
        return f"clickhouse://{user}{pw}@{host}:{port}/{db}"

    elif conn.db_type == DBType.databricks:
        # Databricks uses server_hostname + http_path + access_token
        host = conn.host or ""
        http_path = conn.http_path or ""
        token = conn.access_token or ""
        return f"databricks://{host}|{http_path}|{token}"

    return ""


def _extract_credential_extras(conn: ConnectionCreate) -> dict:
    """Extract structured credential data that can't fit in a connection string."""
    extras: dict = {}
    if conn.ssh_tunnel and conn.ssh_tunnel.enabled:
        extras["ssh_tunnel"] = conn.ssh_tunnel.model_dump()
    if conn.ssl_config and conn.ssl_config.enabled:
        extras["ssl_config"] = conn.ssl_config.model_dump()
    if conn.credentials_json:
        extras["credentials_json"] = conn.credentials_json
    if conn.access_token:
        extras["access_token"] = conn.access_token
    if conn.password:
        extras["password"] = conn.password
    # Snowflake structured params
    if conn.db_type == DBType.snowflake:
        extras["account"] = conn.account
        extras["warehouse"] = conn.warehouse
        extras["schema_name"] = conn.schema_name
        extras["role"] = conn.role
        extras["username"] = conn.username
        extras["password"] = conn.password
    # Databricks structured params
    if conn.db_type == DBType.databricks:
        extras["http_path"] = conn.http_path
        extras["access_token"] = conn.access_token
        extras["catalog"] = conn.catalog
        extras["schema_name"] = conn.schema_name
    return extras


def get_credential_extras(name: str) -> dict:
    """Get extra credential data for a connection."""
    return _credential_extras.get(name, {})


# ─── Sandboxes ───────────────────────────────────────────────────────────────

_active_sandboxes: dict[str, SandboxInfo] = {}


def list_sandboxes() -> list[SandboxInfo]:
    return list(_active_sandboxes.values())


def get_sandbox(sandbox_id: str) -> SandboxInfo | None:
    return _active_sandboxes.get(sandbox_id)


def upsert_sandbox(sandbox: SandboxInfo):
    _active_sandboxes[sandbox.id] = sandbox


def delete_sandbox(sandbox_id: str) -> bool:
    if sandbox_id not in _active_sandboxes:
        return False
    del _active_sandboxes[sandbox_id]
    return True


# ─── Audit Log ───────────────────────────────────────────────────────────────

# Max audit file size before rotation (10MB)
_AUDIT_MAX_BYTES = int(os.getenv("SP_AUDIT_MAX_BYTES", str(10 * 1024 * 1024)))
# Max entries to read into memory for a single query (prevents OOM on large files)
_AUDIT_MAX_SCAN = int(os.getenv("SP_AUDIT_MAX_SCAN", "50000"))


def _rotate_audit_if_needed():
    """Rotate audit log if it exceeds max size (MED-04 fix)."""
    if not AUDIT_FILE.exists():
        return
    try:
        size = AUDIT_FILE.stat().st_size
        if size > _AUDIT_MAX_BYTES:
            # Rotate: rename current to .1, delete older rotations
            rotated = AUDIT_FILE.with_suffix(".jsonl.1")
            old_rotated = AUDIT_FILE.with_suffix(".jsonl.2")
            if old_rotated.exists():
                old_rotated.unlink()
            if rotated.exists():
                rotated.rename(old_rotated)
            AUDIT_FILE.rename(rotated)
    except OSError:
        pass  # Best-effort rotation


async def append_audit(entry: AuditEntry):
    _ensure_data_dir()
    _rotate_audit_if_needed()
    line = entry.model_dump_json() + "\n"
    async with aiofiles.open(AUDIT_FILE, "a") as f:
        await f.write(line)


async def read_audit(
    limit: int = 200,
    offset: int = 0,
    connection_name: str | None = None,
    event_type: str | None = None,
) -> list[AuditEntry]:
    _ensure_data_dir()
    if not AUDIT_FILE.exists():
        return []

    entries = []
    lines_scanned = 0
    async with aiofiles.open(AUDIT_FILE) as f:
        async for line in f:
            lines_scanned += 1
            if lines_scanned > _AUDIT_MAX_SCAN:
                break  # Prevent OOM on very large audit files (MED-04)
            line = line.strip()
            if not line:
                continue
            try:
                entry = AuditEntry(**json.loads(line))
                if connection_name and entry.connection_name != connection_name:
                    continue
                if event_type and entry.event_type != event_type:
                    continue
                entries.append(entry)
            except Exception:
                pass

    # Most recent first
    entries.sort(key=lambda e: e.timestamp, reverse=True)
    return entries[offset : offset + limit]


# ── Schema Endorsements (HEX Data Browser pattern) ─────────────────────────

def _load_endorsements():
    """Load endorsements from disk on startup."""
    global _schema_endorsements
    _schema_endorsements = _load_json(SCHEMA_ENDORSEMENTS_FILE, {})


def _save_endorsements():
    """Persist endorsements to disk."""
    _save_json(SCHEMA_ENDORSEMENTS_FILE, _schema_endorsements)


def get_schema_endorsements(name: str) -> dict:
    """Get endorsement config for a connection.

    Returns: {"endorsed": ["schema.table", ...], "hidden": ["schema.table", ...], "mode": "all|endorsed_only"}
    """
    return _schema_endorsements.get(name, {"endorsed": [], "hidden": [], "mode": "all"})


def set_schema_endorsements(name: str, endorsements: dict) -> dict:
    """Set endorsement config for a connection.

    Args:
        endorsements: {"endorsed": [...], "hidden": [...], "mode": "all|endorsed_only"}
            - mode="all": show all tables except hidden ones (default)
            - mode="endorsed_only": show only endorsed tables
    """
    _schema_endorsements[name] = {
        "endorsed": endorsements.get("endorsed", []),
        "hidden": endorsements.get("hidden", []),
        "mode": endorsements.get("mode", "all"),
    }
    _save_endorsements()
    return _schema_endorsements[name]


def delete_schema_endorsements(name: str):
    """Remove all endorsements for a connection."""
    _schema_endorsements.pop(name, None)
    _save_endorsements()


def apply_endorsement_filter(name: str, schema: dict) -> dict:
    """Filter schema tables based on endorsement settings.

    This is the key feature that improved HEX's AI SQL accuracy from 82% to 96%:
    by curating which tables the AI agent sees, you eliminate noise and improve
    schema linking accuracy.
    """
    config = get_schema_endorsements(name)
    mode = config.get("mode", "all")
    endorsed = set(config.get("endorsed", []))
    hidden = set(config.get("hidden", []))

    if mode == "endorsed_only" and endorsed:
        # Only show endorsed tables
        return {k: v for k, v in schema.items() if k in endorsed}
    elif hidden:
        # Show all except hidden
        return {k: v for k, v in schema.items() if k not in hidden}

    return schema


# Load endorsements on module import
try:
    _load_endorsements()
except Exception:
    pass
