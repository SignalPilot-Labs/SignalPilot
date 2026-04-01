"""
Persistent store for connections, sandboxes, settings, and audit log.
Uses JSON files for MVP (easy to inspect, no DB dependency).
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

import aiofiles

from .models import (
    AuditEntry,
    ConnectionCreate,
    ConnectionInfo,
    DBType,
    GatewaySettings,
    SandboxInfo,
)

DATA_DIR = Path(os.getenv("SP_DATA_DIR", str(Path.home() / ".signalpilot")))
CONNECTIONS_FILE = DATA_DIR / "connections.json"
SANDBOXES_FILE = DATA_DIR / "sandboxes.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
AUDIT_FILE = DATA_DIR / "audit.jsonl"

# In-memory vault for raw credentials (never written to disk in plain text)
_credential_vault: dict[str, str] = {}


def _ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load_json(path: Path, default: Any) -> Any:
    _ensure_data_dir()
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _save_json(path: Path, data: Any):
    _ensure_data_dir()
    path.write_text(json.dumps(data, indent=2))


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

    info = ConnectionInfo(
        id=str(uuid.uuid4()),
        name=conn.name,
        db_type=conn.db_type,
        host=conn.host,
        port=conn.port,
        database=conn.database,
        username=conn.username,
        ssl=conn.ssl,
        description=conn.description,
        created_at=time.time(),
    )

    # Store raw credential in vault (memory only for now — encrypt at rest later)
    raw_cred = conn.connection_string or _build_connection_string(conn)
    _credential_vault[conn.name] = raw_cred

    data[conn.name] = info.model_dump()
    _save_json(CONNECTIONS_FILE, data)
    return info


def delete_connection(name: str) -> bool:
    data = _load_json(CONNECTIONS_FILE, {})
    if name not in data:
        return False
    del data[name]
    _credential_vault.pop(name, None)
    _save_json(CONNECTIONS_FILE, data)
    return True


def get_connection_string(name: str) -> str | None:
    return _credential_vault.get(name)


def _build_connection_string(conn: ConnectionCreate) -> str:
    if conn.db_type == DBType.postgres:
        pw = f":{conn.password}" if conn.password else ""
        host = conn.host or "localhost"
        port = conn.port or 5432
        db = conn.database or "postgres"
        ssl_param = "?sslmode=require" if conn.ssl else ""
        return f"postgresql://{conn.username}{pw}@{host}:{port}/{db}{ssl_param}"
    elif conn.db_type == DBType.mysql:
        pw = f":{conn.password}" if conn.password else ""
        host = conn.host or "localhost"
        port = conn.port or 3306
        db = conn.database or "mysql"
        return f"mysql://{conn.username}{pw}@{host}:{port}/{db}"
    elif conn.db_type == DBType.duckdb:
        return conn.database or ":memory:"
    return ""


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

async def append_audit(entry: AuditEntry):
    _ensure_data_dir()
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
    async with aiofiles.open(AUDIT_FILE) as f:
        async for line in f:
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
