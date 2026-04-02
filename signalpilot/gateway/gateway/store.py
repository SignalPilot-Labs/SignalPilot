"""
Persistent store for connections, sandboxes, settings, and audit log.
Uses JSON files for MVP (easy to inspect, no DB dependency).
"""

from __future__ import annotations

import fcntl
import json
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
    DBType,
    GatewaySettings,
    SandboxInfo,
    TunnelInfo,
    TunnelStatus,
)

DATA_DIR = Path(os.getenv("SP_DATA_DIR", str(Path.home() / ".signalpilot")))
CONNECTIONS_FILE = DATA_DIR / "connections.json"
SANDBOXES_FILE = DATA_DIR / "sandboxes.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
AUDIT_FILE = DATA_DIR / "audit.jsonl"
TUNNELS_FILE = DATA_DIR / "tunnels.json"

# In-memory vault for raw credentials (never written to disk in plain text)
_credential_vault: dict[str, str] = {}


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
        # URL-encode username and password to handle special chars (@, :, #, etc.)
        user = url_quote(conn.username or "", safe="")
        pw = f":{url_quote(conn.password or '', safe='')}" if conn.password else ""
        host = conn.host or "localhost"
        port = conn.port or 5432
        db = conn.database or "postgres"
        ssl_param = "?sslmode=require" if conn.ssl else ""
        return f"postgresql://{user}{pw}@{host}:{port}/{db}{ssl_param}"
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


# ─── Tunnels ────────────────────────────────────────────────────────────────

_tunnels: dict[str, TunnelInfo] = {}


def load_tunnels():
    """Load persisted tunnels from disk. All reset to stopped (no live process)."""
    global _tunnels
    data = _load_json(TUNNELS_FILE, {})
    _tunnels = {}
    for tid, raw in data.items():
        t = TunnelInfo(**raw)
        t.status = TunnelStatus.stopped
        t.pid = None
        t.public_url = None
        t.started_at = None
        t.error_message = None
        _tunnels[tid] = t


def list_tunnels() -> list[TunnelInfo]:
    return list(_tunnels.values())


def get_tunnel(tunnel_id: str) -> TunnelInfo | None:
    return _tunnels.get(tunnel_id)


def upsert_tunnel(tunnel: TunnelInfo):
    _tunnels[tunnel.id] = tunnel
    _persist_tunnels()


def delete_tunnel(tunnel_id: str) -> bool:
    if tunnel_id not in _tunnels:
        return False
    del _tunnels[tunnel_id]
    _persist_tunnels()
    return True


def _persist_tunnels():
    """Write tunnel configs to disk (runtime state like pid is included but reset on load)."""
    data = {tid: t.model_dump() for tid, t in _tunnels.items()}
    _save_json(TUNNELS_FILE, data)
