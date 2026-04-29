"""
Persistent store backed by PostgreSQL.

All operations are scoped to a user_id. In local mode user_id is always "local".
Credentials are encrypted at rest using Fernet (AES-128-CBC + HMAC-SHA256).
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote as url_quote

from sqlalchemy import delete, literal, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .byok import BYOKProvider, DEKCache, decrypt_envelope, encrypt_fields_envelope
from .governance.context import current_org_id_var
from .db.models import (
    GatewayApiKey,
    GatewayAuditLog,
    GatewayBYOKKey,
    GatewayConnection,
    GatewayCredential,
    GatewayOrg,
    GatewayProject,
    GatewaySetting,
)
from .models import (
    AuditEntry,
    ApiKeyRecord,
    ConnectionCreate,
    ConnectionInfo,
    ConnectionUpdate,
    DBType,
    GatewaySettings,
    ProjectCreate,
    ProjectInfo,
    ProjectStorage,
    ProjectUpdate,
    SandboxInfo,
    SSHTunnelConfig,
    SSLConfig,
)

logger = logging.getLogger(__name__)

DATA_DIR = Path(os.getenv("SP_DATA_DIR", str(Path.home() / ".signalpilot")))

PBKDF2_ITERATIONS = 600_000
PBKDF2_KEY_LENGTH = 32
SALT_FILE_NAME = ".encryption_salt"
KEY_FILE_NAME = ".encryption_key"

# Key version tracking for rotation support.
# Bump this constant when rotating to a new key material. When bumped, the operator
# sets the new key via SP_ENCRYPTION_KEY and the old key is kept for decryption
# of legacy rows (future multi-key read logic). Currently only version 1 exists.
# key_version is orthogonal to _decrypt_with_migration: that handles "which derivation
# method" while key_version handles "which key material".
CURRENT_KEY_VERSION = 1


class CredentialEncryptionError(Exception):
    """Raised when credential encryption or decryption fails in a non-recoverable way."""


# Module-level key cache — populated on first call, reused thereafter.
# Avoids re-running PBKDF2 (≈200 ms) on every encrypt/decrypt call.
_CACHED_KEY: bytes | None = None

# Module-level BYOK state — set by configure_byok() before any BYOK credentials
# are decrypted. Phase 2 will call configure_byok() from the application lifespan
# handler (main.py startup). Phase 1 only adds the decrypt routing; the globals
# remain None unless explicitly configured.
_byok_provider: BYOKProvider | None = None
_dek_cache: DEKCache | None = None


def configure_byok(provider: BYOKProvider, cache: DEKCache | None = None) -> None:
    """Set the module-level BYOK provider and optional DEK cache.

    Call this during application startup before any requests are served.
    Phase 2 will wire this into the FastAPI lifespan handler in main.py.
    """
    global _byok_provider, _dek_cache
    _byok_provider = provider
    _dek_cache = cache


async def _resolve_byok_key(
    session: AsyncSession,
    org_id: str,
    key_alias: str | None = None,
) -> GatewayBYOKKey | None:
    """Resolve the active BYOK key for an org.

    If key_alias is provided, looks up by org_id + key_alias + status='active'.
    If key_alias is None, looks up the org's default_byok_key_id from GatewayOrg,
    then loads that key.

    Returns the GatewayBYOKKey row or None if not found.
    """
    if key_alias is not None:
        result = await session.execute(
            select(GatewayBYOKKey).where(
                GatewayBYOKKey.org_id == org_id,
                GatewayBYOKKey.key_alias == key_alias,
                GatewayBYOKKey.status == "active",
            )
        )
        return result.scalar_one_or_none()

    # No alias: look up the org's default key
    org_result = await session.execute(
        select(GatewayOrg).where(GatewayOrg.org_id == org_id)
    )
    org_row = org_result.scalar_one_or_none()
    if org_row is None or not org_row.default_byok_key_id:
        return None

    key_result = await session.execute(
        select(GatewayBYOKKey).where(
            GatewayBYOKKey.id == org_row.default_byok_key_id,
            GatewayBYOKKey.status == "active",
        )
    )
    return key_result.scalar_one_or_none()


# ─── Atomic file helper ──────────────────────────────────────────────────────

def _atomic_create_file(path: Path, content: bytes, mode: int = 0o600) -> bytes:
    """Atomically create a file with content.

    Uses O_CREAT | O_EXCL which is POSIX-atomic: exactly one process wins the
    creation race. If the file already exists, the existing content is returned.
    """
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, mode)
        try:
            os.write(fd, content)
        finally:
            os.close(fd)
        return content
    except FileExistsError:
        return path.read_bytes()


# ─── Encryption ──────────────────────────────────────────────────────────────

def _load_or_create_salt() -> bytes:
    """Load or create the persistent PBKDF2 salt stored at SP_DATA_DIR/.encryption_salt.

    Uses atomic O_CREAT | O_EXCL to prevent TOCTOU: two simultaneous starts
    cannot each write a different salt and diverge.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    salt_file = DATA_DIR / SALT_FILE_NAME
    return _atomic_create_file(salt_file, os.urandom(16))


def _derive_key_pbkdf2(passphrase: str) -> bytes:
    """Derive a Fernet-compatible key from a passphrase using PBKDF2-HMAC-SHA256."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    salt = _load_or_create_salt()
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=PBKDF2_KEY_LENGTH,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    raw_key = kdf.derive(passphrase.encode())
    return base64.urlsafe_b64encode(raw_key)


def _derive_key_legacy_sha256(passphrase: str) -> bytes:
    """Legacy (insecure) key derivation via SHA-256. Used only for migration fallback."""
    digest = hashlib.sha256(passphrase.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def _get_encryption_key() -> bytes:
    """Return the cached Fernet key, deriving it on first call."""
    global _CACHED_KEY
    if _CACHED_KEY is not None:
        return _CACHED_KEY

    from cryptography.fernet import Fernet
    from .deployment import is_cloud_mode

    key_str = os.getenv("SP_ENCRYPTION_KEY")
    if key_str:
        try:
            Fernet(key_str.encode())
            # Already a valid Fernet key — use directly.
            _CACHED_KEY = key_str.encode()
            return _CACHED_KEY
        except Exception:
            if is_cloud_mode():
                deterministic_salt = hashlib.sha256(
                    b"signalpilot-cloud-salt:" + key_str.encode()
                ).digest()[:16]
                from cryptography.hazmat.primitives import hashes
                from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
                kdf = PBKDF2HMAC(
                    algorithm=hashes.SHA256(),
                    length=PBKDF2_KEY_LENGTH,
                    salt=deterministic_salt,
                    iterations=PBKDF2_ITERATIONS,
                )
                _CACHED_KEY = base64.urlsafe_b64encode(kdf.derive(key_str.encode()))
            else:
                _CACHED_KEY = _derive_key_pbkdf2(key_str)
            return _CACHED_KEY
    else:
        if is_cloud_mode():
            raise RuntimeError(
                "SP_ENCRYPTION_KEY environment variable is required in cloud mode. "
                "Cannot auto-generate encryption key from filesystem."
            )
        key_file = DATA_DIR / KEY_FILE_NAME
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        key = Fernet.generate_key()
        _CACHED_KEY = _atomic_create_file(key_file, key).strip()
        return _CACHED_KEY


def _encrypt(data: str) -> bytes:
    from cryptography.fernet import Fernet
    f = Fernet(_get_encryption_key())
    return f.encrypt(data.encode())


def _decrypt(encrypted: bytes) -> str:
    from cryptography.fernet import Fernet
    f = Fernet(_get_encryption_key())
    return f.decrypt(encrypted).decode()


def _decrypt_with_migration(encrypted: bytes) -> tuple[str, bool]:
    """Decrypt ciphertext, falling back to legacy key derivation if needed.

    Returns:
        (plaintext, needs_migration) where needs_migration is True when the
        legacy SHA-256 path was used and the caller should re-encrypt the row
        with the current PBKDF2-derived key.
    """
    from cryptography.fernet import Fernet, InvalidToken

    key_str = os.getenv("SP_ENCRYPTION_KEY")

    # Fast path: try primary (PBKDF2-derived or direct Fernet) key first.
    try:
        return _decrypt(encrypted), False
    except InvalidToken:
        pass

    # Only attempt legacy fallback when env var is a passphrase (not a raw Fernet key).
    if key_str:
        try:
            Fernet(key_str.encode())
            # key_str is a valid raw Fernet key — no legacy path makes sense.
            raise CredentialEncryptionError("Credential decryption failed; token is invalid.")
        except CredentialEncryptionError:
            raise
        except Exception:
            pass  # key_str is a passphrase; try legacy derivation.

        legacy_key = _derive_key_legacy_sha256(key_str)
        try:
            f_legacy = Fernet(legacy_key)
            plaintext = f_legacy.decrypt(encrypted).decode()
            logger.warning(
                "Credential decrypted with legacy SHA-256 key derivation. "
                "This is deprecated — row will be re-encrypted with PBKDF2 key."
            )
            return plaintext, True
        except InvalidToken:
            pass

    raise CredentialEncryptionError("Credential decryption failed; token is invalid.")


def _validate_encryption_health() -> bool:
    """Verify that the current encryption key can round-trip encrypt/decrypt.

    Returns True if healthy, False otherwise. Called at startup.
    """
    try:
        test_plaintext = "health-check-" + secrets.token_hex(8)
        ciphertext = _encrypt(test_plaintext)
        recovered = _decrypt(ciphertext)
        return recovered == test_plaintext
    except Exception as exc:
        logger.error("Encryption health check failed: %s", exc)
        return False


# ─── Local DB path validation ────────────────────────────────────────────────

def _validate_local_db_path(path: str) -> str:
    """Validate that a DuckDB/SQLite path is within DATA_DIR.

    Allowed special values:
      - ":memory:"       — in-memory database
      - paths starting with "md:" — MotherDuck cloud connection

    All other paths are resolved to an absolute canonical form and must fall
    within DATA_DIR. Using Path.resolve() canonicalizes ".." traversal and
    symlinks.

    Note: TOCTOU risk — a symlink could be created after validation but before
    DuckDB opens the file. Accepted risk: the attacker would need write access
    within DATA_DIR to exploit this.

    Raises:
        ValueError: if the resolved path is not within DATA_DIR.
    """
    if path == ":memory:" or path.startswith("md:"):
        return path

    resolved = Path(path).resolve()
    allowed_base = DATA_DIR.resolve()

    try:
        resolved.relative_to(allowed_base)
        return path
    except ValueError:
        raise ValueError(
            f"Database path not allowed: must be within the data directory ({DATA_DIR})"
        )


# ─── Connection string builder (pure function) ──────────────────────────────

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
        account = conn.account or ""
        user = url_quote(conn.username or "", safe="")
        pw = f":{url_quote(conn.password or '', safe='')}" if conn.password else ""
        db = conn.database or ""
        schema = conn.schema_name or ""
        path = f"/{db}/{schema}" if schema else f"/{db}" if db else ""
        params = []
        if conn.warehouse:
            params.append(f"warehouse={url_quote(conn.warehouse, safe='')}")
        if conn.role:
            params.append(f"role={url_quote(conn.role, safe='')}")
        query = f"?{'&'.join(params)}" if params else ""
        return f"snowflake://{user}{pw}@{account}{path}{query}"
    elif conn.db_type == DBType.bigquery:
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
        db = conn.database or "default"
        use_http = conn.protocol == "http"
        use_ssl = conn.ssl or (conn.ssl_config and conn.ssl_config.enabled)
        if use_http:
            scheme = "clickhouse+https" if use_ssl else "clickhouse+http"
            port = conn.port or (8443 if use_ssl else 8123)
        else:
            scheme = "clickhouses" if use_ssl else "clickhouse"
            port = conn.port or (9440 if use_ssl else 9000)
        return f"{scheme}://{user}{pw}@{host}:{port}/{db}"
    elif conn.db_type == DBType.databricks:
        host = conn.host or ""
        http_path = url_quote(conn.http_path or "", safe="/")
        token = url_quote(conn.access_token or "", safe="")
        params = []
        if conn.catalog:
            params.append(f"catalog={url_quote(conn.catalog, safe='')}")
        if conn.schema_name:
            params.append(f"schema={url_quote(conn.schema_name, safe='')}")
        query = f"?{'&'.join(params)}" if params else ""
        return f"databricks://{token}@{host}/{http_path}{query}"
    elif conn.db_type == DBType.mssql:
        user = url_quote(conn.username or "sa", safe="")
        pw = f":{url_quote(conn.password or '', safe='')}" if conn.password else ""
        host = conn.host or "localhost"
        port = conn.port or 1433
        db = conn.database or "master"
        return f"mssql://{user}{pw}@{host}:{port}/{db}"
    elif conn.db_type == DBType.trino:
        user = url_quote(conn.username or "trino", safe="")
        pw = f":{url_quote(conn.password or '', safe='')}" if conn.password else ""
        host = conn.host or "localhost"
        port = conn.port or 8080
        catalog = conn.catalog or ""
        schema = conn.schema_name or ""
        path = f"/{catalog}/{schema}" if schema else f"/{catalog}" if catalog else ""
        return f"trino://{user}{pw}@{host}:{port}{path}"
    return ""


def _extract_credential_extras(conn: ConnectionCreate) -> dict:
    extras: dict = {}
    if conn.ssh_tunnel and conn.ssh_tunnel.enabled:
        extras["ssh_tunnel"] = conn.ssh_tunnel.model_dump()
    if conn.ssl_config and conn.ssl_config.enabled:
        extras["ssl_config"] = conn.ssl_config.model_dump()
    if conn.credentials_json:
        extras["credentials_json"] = conn.credentials_json
    if conn.db_type == DBType.bigquery:
        for attr in ("location", "maximum_bytes_billed", "project", "dataset"):
            val = getattr(conn, attr, None)
            if val is not None:
                extras[attr] = val
    if conn.access_token:
        extras["access_token"] = conn.access_token
    if conn.password:
        extras["password"] = conn.password
    if conn.db_type == DBType.snowflake:
        for attr in ("account", "warehouse", "schema_name", "role", "username", "password"):
            extras[attr] = getattr(conn, attr, None)
        if conn.private_key:
            extras["private_key"] = conn.private_key
        if conn.private_key_passphrase:
            extras["private_key_passphrase"] = conn.private_key_passphrase
    if conn.db_type == DBType.databricks:
        for attr in ("http_path", "access_token", "catalog", "schema_name"):
            extras[attr] = getattr(conn, attr, None)
    if conn.db_type == DBType.duckdb and getattr(conn, "motherduck_token", None):
        extras["motherduck_token"] = conn.motherduck_token
    for attr in ("connection_timeout", "query_timeout", "keepalive_interval"):
        val = getattr(conn, attr, None)
        if val is not None and (attr != "keepalive_interval" or val > 0):
            extras[attr] = val
    return extras


# ─── dbt project templates (pure) ───────────────────────────────────────────

_DBT_PROJECT_YML_TEMPLATE = """\
name: '{name}'
version: '1.0.0'
config-version: 2
profile: '{name}'

model-paths: ["models"]
analysis-paths: ["analyses"]
test-paths: ["tests"]
seed-paths: ["seeds"]
macro-paths: ["macros"]
snapshot-paths: ["snapshots"]

clean-targets:
  - "target"
  - "dbt_packages"
"""

_PACKAGES_YML_TEMPLATE = """\
packages: []
"""

_PROFILES_DUCKDB = """\
{name}:
  target: dev
  outputs:
    dev:
      type: duckdb
      path: '{database}'
"""

_PROFILES_POSTGRES = """\
{name}:
  target: dev
  outputs:
    dev:
      type: postgres
      host: '{host}'
      port: {port}
      user: '{username}'
      dbname: '{database}'
      schema: public
"""

_PROFILES_SNOWFLAKE = """\
{name}:
  target: dev
  outputs:
    dev:
      type: snowflake
      account: '{account}'
      user: '{username}'
      database: '{database}'
      warehouse: '{warehouse}'
      schema: public
      role: '{role}'
"""

_PROFILES_BIGQUERY = """\
{name}:
  target: dev
  outputs:
    dev:
      type: bigquery
      method: service-account
      project: '{project}'
      dataset: '{dataset}'
      location: '{location}'
"""

_PROFILES_PLACEHOLDER = """\
# TODO: Configure profile for {db_type}
# See https://docs.getdbt.com/docs/core/connect-data-platform
{name}:
  target: dev
  outputs:
    dev:
      type: '{db_type}'
"""

_SCAFFOLD_DIRS = [
    "models/staging", "models/marts", "analyses", "tests", "seeds", "macros", "snapshots",
]


# ─── Sandboxes (in-memory, not user-scoped — ephemeral) ─────────────────────

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


# ─── Local API Key (file-based, only for local mode) ────────────────────────

def get_local_api_key() -> str | None:
    from .deployment import is_cloud_mode
    if is_cloud_mode():
        return None
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    key_file = DATA_DIR / "local_api_key"
    new_key = "sp_local_" + secrets.token_hex(16)
    result = _atomic_create_file(key_file, new_key.encode()).decode().strip()
    if result:
        return result
    # File existed but was empty (should not occur with O_EXCL writes, but guard anyway).
    key_file.unlink(missing_ok=True)
    new_key2 = "sp_local_" + secrets.token_hex(16)
    logger.info("Generated new local API key (stored in %s)", key_file)
    return _atomic_create_file(key_file, new_key2.encode()).decode().strip()


# ═══════════════════════════════════════════════════════════════════════════════
# Store class — all DB-backed operations scoped by user_id
# ═══════════════════════════════════════════════════════════════════════════════

class Store:
    """Database-backed store scoped by org_id.

    Pass allow_unscoped=True for background tasks that legitimately need
    access across all orgs.  Callers that omit org_id without allow_unscoped=True
    will get a ValueError from _conn_filter to prevent accidental data leaks.
    """

    def __init__(
        self,
        session: AsyncSession,
        org_id: str | None = None,
        user_id: str | None = None,
        allow_unscoped: bool = False,
    ):
        self.session = session
        self.org_id = org_id
        self.user_id = user_id
        self._allow_unscoped = allow_unscoped
        # Intentional: we do not store the token for reset. FastAPI runs each request in a
        # dedicated asyncio task whose contextvars copy is isolated; the var dies with the task.
        # Background task usage must set the var explicitly and reset (see main.py schema refresh loop).
        if self.org_id:
            current_org_id_var.set(self.org_id)

    # ─── Settings ────────────────────────────────────────────────────────

    async def load_settings(self) -> GatewaySettings:
        oid = self.org_id or "local"
        result = await self.session.execute(
            select(GatewaySetting).where(GatewaySetting.org_id == oid)
        )
        row = result.scalar_one_or_none()
        data = row.settings_json if row else {}
        # Environment variables provide defaults — user-saved settings take priority
        if os.getenv("SP_SANDBOX_MANAGER_URL") and "sandbox_manager_url" not in data:
            data["sandbox_manager_url"] = os.getenv("SP_SANDBOX_MANAGER_URL")
        if os.getenv("SP_GATEWAY_URL") and "gateway_url" not in data:
            data["gateway_url"] = os.getenv("SP_GATEWAY_URL")
        return GatewaySettings(**data)

    async def save_settings(self, settings: GatewaySettings):
        oid = self.org_id or "local"
        result = await self.session.execute(
            select(GatewaySetting).where(GatewaySetting.org_id == oid)
        )
        row = result.scalar_one_or_none()
        if row:
            row.settings_json = settings.model_dump()
        else:
            self.session.add(GatewaySetting(
                org_id=oid,
                user_id=self.user_id,
                settings_json=settings.model_dump(),
            ))
        await self.session.commit()

    # ─── Connections ─────────────────────────────────────────────────────

    def _conn_filter(self):
        if self.org_id is not None:
            return GatewayConnection.org_id == self.org_id
        if self._allow_unscoped:
            return literal(True)
        raise ValueError(
            "Store requires org_id for connection queries. "
            "Use allow_unscoped=True for background tasks that need cross-org access."
        )

    async def list_connections(self) -> list[ConnectionInfo]:
        result = await self.session.execute(
            select(GatewayConnection).where(self._conn_filter())
        )
        return [ConnectionInfo(**row.to_info_dict()) for row in result.scalars()]

    async def get_connection(self, name: str) -> ConnectionInfo | None:
        result = await self.session.execute(
            select(GatewayConnection).where(
                self._conn_filter(), GatewayConnection.name == name
            )
        )
        row = result.scalar_one_or_none()
        return ConnectionInfo(**row.to_info_dict()) if row else None

    async def create_connection(self, conn: ConnectionCreate) -> ConnectionInfo:
        oid = self.org_id or "local"
        uid = self.user_id
        # Check uniqueness
        existing = await self.get_connection(conn.name)
        if existing:
            raise ValueError(f"Connection '{conn.name}' already exists")

        # When connection_string is provided without individual fields, parse
        # host/port/database/username from the URL so they're stored as metadata
        # for display and editing.
        if conn.connection_string and not conn.host:
            from .url_parser import parse_connection_url
            try:
                db_type_str = conn.db_type.value if hasattr(conn.db_type, 'value') else conn.db_type
                parsed = parse_connection_url(conn.connection_string, db_type=db_type_str)
                conn = conn.model_copy(update={
                    k: v for k, v in parsed.items()
                    if k in ("host", "port", "database", "username", "ssl", "account",
                             "warehouse", "schema_name", "role", "catalog", "http_path")
                    and v  # only backfill non-empty values
                })
            except Exception:
                pass  # URL parsing failed — keep original fields

        # Strip sensitive fields from SSH/SSL for metadata storage
        ssh_tunnel_safe = None
        if conn.ssh_tunnel and conn.ssh_tunnel.enabled:
            ssh_tunnel_safe = conn.ssh_tunnel.model_copy(update={
                "password": None, "private_key": None, "private_key_passphrase": None,
            }).model_dump()

        ssl_config_safe = None
        if conn.ssl_config and conn.ssl_config.enabled:
            ssl_config_safe = conn.ssl_config.model_dump()

        conn_id = str(uuid.uuid4())
        db_conn = GatewayConnection(
            id=conn_id,
            org_id=oid,
            user_id=uid,
            name=conn.name,
            db_type=conn.db_type.value if hasattr(conn.db_type, 'value') else conn.db_type,
            host=conn.host,
            port=conn.port,
            database=conn.database,
            username=conn.username,
            ssl=conn.ssl or False,
            ssl_config=ssl_config_safe,
            ssh_tunnel=ssh_tunnel_safe,
            account=conn.account,
            warehouse=conn.warehouse,
            schema_name=conn.schema_name,
            role=conn.role,
            project=conn.project,
            dataset=conn.dataset,
            location=getattr(conn, "location", None),
            http_path=conn.http_path,
            catalog=conn.catalog,
            description=conn.description,
            tags=conn.tags,
            schema_filter_include=conn.schema_filter_include,
            schema_filter_exclude=conn.schema_filter_exclude,
            schema_refresh_interval=conn.schema_refresh_interval,
            connection_timeout=conn.connection_timeout,
            query_timeout=conn.query_timeout,
            keepalive_interval=conn.keepalive_interval,
            created_at=time.time(),
            byok_key_alias=conn.byok_key_alias,
        )
        self.session.add(db_conn)

        # Store encrypted credentials
        raw_cred = conn.connection_string or _build_connection_string(conn)
        # Validate DuckDB/SQLite paths — but only for non-sandboxed modes.
        # Local file paths (host paths like C:\Users\...) are executed via the
        # gVisor sandbox which provides its own isolation. Only in-DATA_DIR
        # paths (direct connector) need the traversal check.
        if conn.db_type in (DBType.duckdb, DBType.sqlite):
            is_sandboxed = raw_cred not in (":memory:",) and not raw_cred.startswith("md:")
            if not is_sandboxed:
                _validate_local_db_path(raw_cred)
        extras = _extract_credential_extras(conn)

        # BYOK encrypt path: use envelope encryption when org has BYOK configured
        byok_key = None
        if oid and _byok_provider is not None:
            byok_key = await _resolve_byok_key(
                self.session, oid, conn.byok_key_alias
            )

        if byok_key is not None and _byok_provider is not None:
            ciphertexts, wrapped_dek = await encrypt_fields_envelope(
                _byok_provider,
                oid,
                byok_key.key_alias,
                [raw_cred, json.dumps(extras)],
            )
            db_conn.byok_key_alias = byok_key.key_alias
            cred = GatewayCredential(
                org_id=oid,
                user_id=uid,
                connection_name=conn.name,
                connection_string_enc=ciphertexts[0],
                extras_enc=ciphertexts[1],
                key_version=CURRENT_KEY_VERSION,
                encryption_mode="byok",
                wrapped_dek=wrapped_dek,
                byok_key_id=byok_key.id,
            )
        else:
            cred = GatewayCredential(
                org_id=oid,
                user_id=uid,
                connection_name=conn.name,
                connection_string_enc=_encrypt(raw_cred),
                extras_enc=_encrypt(json.dumps(extras)),
                key_version=CURRENT_KEY_VERSION,
            )
        self.session.add(cred)
        try:
            await self.session.commit()
        except IntegrityError as e:
            await self.session.rollback()
            orig = str(e.orig) if e.orig is not None else str(e)
            if "uq_gw_conn_org_name" in orig or "uq_gw_cred_org_conn" in orig:
                raise ValueError(f"Connection '{conn.name}' already exists") from e
            raise
        await self.session.refresh(db_conn)
        return ConnectionInfo(**db_conn.to_info_dict())

    async def delete_connection(self, name: str) -> bool:
        oid = self.org_id or "local"
        result = await self.session.execute(
            select(GatewayConnection).where(
                GatewayConnection.org_id == oid, GatewayConnection.name == name
            )
        )
        row = result.scalar_one_or_none()
        if not row:
            return False
        await self.session.delete(row)
        await self.session.execute(
            delete(GatewayCredential).where(
                GatewayCredential.org_id == oid,
                GatewayCredential.connection_name == name,
            )
        )
        await self.session.commit()
        return True

    async def update_connection(self, name: str, update_data: ConnectionUpdate) -> ConnectionInfo | None:
        oid = self.org_id or "local"
        result = await self.session.execute(
            select(GatewayConnection).where(
                GatewayConnection.org_id == oid, GatewayConnection.name == name
            )
        )
        row = result.scalar_one_or_none()
        if not row:
            return None

        update_fields = update_data.model_dump(exclude_none=True)
        credential_fields = {"password", "connection_string", "credentials_json",
                             "access_token", "private_key", "private_key_passphrase", "motherduck_token"}

        # Update metadata fields
        for key, value in update_fields.items():
            if key in credential_fields:
                continue
            if key == "ssh_tunnel" and value:
                ssh_config = SSHTunnelConfig(**value) if isinstance(value, dict) else value
                value = ssh_config.model_copy(update={
                    "password": None, "private_key": None, "private_key_passphrase": None,
                }).model_dump()
            if key == "ssl_config" and value:
                if isinstance(value, dict):
                    value = SSLConfig(**value).model_dump()
            if hasattr(row, key):
                setattr(row, key, value)

        # Rebuild credentials if needed
        needs_cred_rebuild = any(k in update_fields for k in (
            "host", "port", "database", "username", "password", "connection_string",
            "account", "warehouse", "schema_name", "role", "project",
            "credentials_json", "http_path", "access_token", "catalog", "ssl", "ssl_config",
        ))
        if needs_cred_rebuild:
            merged = {**row.to_info_dict(), **update_fields, "name": name}
            for rm_key in ("id", "created_at", "last_used", "status", "last_schema_refresh",
                           "endorsements", "location"):
                merged.pop(rm_key, None)
            try:
                create_obj = ConnectionCreate(**merged)
                raw_cred = create_obj.connection_string or _build_connection_string(create_obj)
                if create_obj.db_type in ("duckdb", "sqlite"):
                    is_sandboxed = raw_cred not in (":memory:",) and not raw_cred.startswith("md:")
                    if not is_sandboxed:
                        _validate_local_db_path(raw_cred)
                extras = _extract_credential_extras(create_obj)
                # Update credential row
                cred_result = await self.session.execute(
                    select(GatewayCredential).where(
                        GatewayCredential.org_id == oid,
                        GatewayCredential.connection_name == name,
                    )
                )
                cred_row = cred_result.scalar_one_or_none()
                if cred_row:
                    # BYOK encrypt path: use envelope encryption if org has BYOK configured
                    org_id = row.org_id
                    key_alias = row.byok_key_alias
                    byok_key = None
                    if org_id and _byok_provider is not None:
                        byok_key = await _resolve_byok_key(self.session, org_id, key_alias)

                    if byok_key is not None and _byok_provider is not None:
                        ciphertexts, wrapped_dek = await encrypt_fields_envelope(
                            _byok_provider,
                            org_id,  # type: ignore[arg-type]
                            byok_key.key_alias,
                            [raw_cred, json.dumps(extras)],
                        )
                        cred_row.connection_string_enc = ciphertexts[0]
                        cred_row.extras_enc = ciphertexts[1]
                        cred_row.key_version = CURRENT_KEY_VERSION
                        cred_row.encryption_mode = "byok"
                        cred_row.wrapped_dek = wrapped_dek
                        cred_row.byok_key_id = byok_key.id
                        row.byok_key_alias = byok_key.key_alias
                    else:
                        cred_row.connection_string_enc = _encrypt(raw_cred)
                        cred_row.extras_enc = _encrypt(json.dumps(extras))
                        cred_row.key_version = CURRENT_KEY_VERSION
            except Exception as e:
                logger.error(
                    "Credential encryption failed for connection %s: %s", name, e
                )
                raise CredentialEncryptionError(
                    f"Failed to encrypt credentials for connection '{name}'"
                ) from e

        await self.session.commit()
        await self.session.refresh(row)
        return ConnectionInfo(**row.to_info_dict())

    async def get_connection_string(self, name: str) -> str | None:
        oid = self.org_id or "local"
        result = await self.session.execute(
            select(GatewayCredential, GatewayConnection).join(
                GatewayConnection,
                (GatewayConnection.org_id == GatewayCredential.org_id)
                & (GatewayConnection.name == GatewayCredential.connection_name),
                isouter=True,
            ).where(
                GatewayCredential.org_id == oid,
                GatewayCredential.connection_name == name,
            )
        )
        row_pair = result.first()
        if not row_pair:
            return None
        cred_row, conn_row = row_pair

        if cred_row.encryption_mode == "byok":
            if _byok_provider is None:
                raise CredentialEncryptionError("BYOK provider not configured")
            if cred_row.wrapped_dek is None:
                raise CredentialEncryptionError(
                    "Credential is in BYOK mode but has no wrapped DEK"
                )
            org_id = conn_row.org_id if conn_row else None
            key_alias = conn_row.byok_key_alias if conn_row else None
            if not org_id or not key_alias:
                raise CredentialEncryptionError(
                    "Connection is missing BYOK configuration for decryption"
                )
            return await decrypt_envelope(
                provider=_byok_provider,
                org_id=org_id,
                key_alias=key_alias,
                wrapped_dek=cred_row.wrapped_dek,
                ciphertext=cred_row.connection_string_enc,
                cache=_dek_cache,
                credential_id=cred_row.id,
            )

        # Managed (default) path — existing Fernet-based decryption
        plaintext, needs_migration = _decrypt_with_migration(cred_row.connection_string_enc)
        # Re-encrypt if using legacy key derivation OR if key_version is behind current.
        # Concurrent reads may both re-encrypt — this is safe because re-encryption
        # with the same key is idempotent (same plaintext, same key version result).
        needs_version_upgrade = cred_row.key_version != CURRENT_KEY_VERSION
        if needs_migration or needs_version_upgrade:
            cred_row.connection_string_enc = _encrypt(plaintext)
            # Re-encrypt extras_enc too so key_version covers both fields
            if cred_row.extras_enc:
                extras_plain, _ = _decrypt_with_migration(cred_row.extras_enc)
                cred_row.extras_enc = _encrypt(extras_plain)
            cred_row.key_version = CURRENT_KEY_VERSION
            await self.session.commit()
        return plaintext

    async def get_credential_extras(self, name: str) -> dict:
        oid = self.org_id or "local"
        result = await self.session.execute(
            select(GatewayCredential, GatewayConnection).join(
                GatewayConnection,
                (GatewayConnection.org_id == GatewayCredential.org_id)
                & (GatewayConnection.name == GatewayCredential.connection_name),
                isouter=True,
            ).where(
                GatewayCredential.org_id == oid,
                GatewayCredential.connection_name == name,
            )
        )
        row_pair = result.first()
        if not row_pair:
            return {}
        cred_row, conn_row = row_pair
        if not cred_row.extras_enc:
            return {}

        if cred_row.encryption_mode == "byok":
            if _byok_provider is None:
                raise CredentialEncryptionError("BYOK provider not configured")
            if cred_row.wrapped_dek is None:
                raise CredentialEncryptionError(
                    "Credential is in BYOK mode but has no wrapped DEK"
                )
            org_id = conn_row.org_id if conn_row else None
            key_alias = conn_row.byok_key_alias if conn_row else None
            if not org_id or not key_alias:
                raise CredentialEncryptionError(
                    "Connection is missing BYOK configuration for decryption"
                )
            extras_json = await decrypt_envelope(
                provider=_byok_provider,
                org_id=org_id,
                key_alias=key_alias,
                wrapped_dek=cred_row.wrapped_dek,
                ciphertext=cred_row.extras_enc,
                cache=_dek_cache,
                credential_id=cred_row.id,
            )
            return json.loads(extras_json)

        # Managed (default) path — existing Fernet-based decryption
        plaintext, needs_migration = _decrypt_with_migration(cred_row.extras_enc)
        # Re-encrypt if using legacy key derivation OR if key_version is behind current.
        # Concurrent reads may both re-encrypt — this is safe because re-encryption
        # with the same key is idempotent (same plaintext, same key version result).
        needs_version_upgrade = cred_row.key_version != CURRENT_KEY_VERSION
        if needs_migration or needs_version_upgrade:
            cred_row.extras_enc = _encrypt(plaintext)
            # Re-encrypt connection_string_enc too so key_version covers both fields
            if cred_row.connection_string_enc:
                cs_plain, _ = _decrypt_with_migration(cred_row.connection_string_enc)
                cred_row.connection_string_enc = _encrypt(cs_plain)
            cred_row.key_version = CURRENT_KEY_VERSION
            await self.session.commit()
        return json.loads(plaintext)

    # ─── Projects ────────────────────────────────────────────────────────

    async def list_projects(self) -> list[ProjectInfo]:
        oid = self.org_id or "local"
        result = await self.session.execute(
            select(GatewayProject).where(GatewayProject.org_id == oid)
        )
        rows = result.scalars().all()
        return [ProjectInfo(**{c.key: getattr(r, c.key) for c in GatewayProject.__table__.columns}) for r in rows]

    async def get_project(self, name: str) -> ProjectInfo | None:
        oid = self.org_id or "local"
        result = await self.session.execute(
            select(GatewayProject).where(
                GatewayProject.org_id == oid, GatewayProject.name == name
            )
        )
        row = result.scalar_one_or_none()
        if not row:
            return None
        return ProjectInfo(**{c.key: getattr(row, c.key) for c in GatewayProject.__table__.columns})

    async def create_project(self, proj: ProjectCreate) -> ProjectInfo:
        oid = self.org_id or "local"
        existing = await self.get_project(proj.name)
        if existing:
            raise ValueError(f"Project '{proj.name}' already exists")

        connection = await self.get_connection(proj.connection_name)
        if connection is None:
            raise ValueError(f"Connection '{proj.connection_name}' not found")

        if proj.source.value == "local":
            info = self._create_local_project(proj, connection)
        else:
            info = self._create_new_project(proj, connection)

        db_proj = GatewayProject(
            id=info.id,
            org_id=oid,
            user_id=self.user_id,
            name=info.name,
            connection_name=info.connection_name,
            project_dir=info.project_dir,
            storage=info.storage.value if hasattr(info.storage, 'value') else info.storage,
            source=info.source.value if hasattr(info.source, 'value') else info.source,
            db_type=info.db_type,
            description=info.description,
            tags=info.tags,
        )
        self.session.add(db_proj)
        try:
            await self.session.commit()
        except IntegrityError as e:
            await self.session.rollback()
            orig = str(e.orig) if e.orig is not None else str(e)
            if "uq_gw_proj_org_name" in orig:
                raise ValueError(f"Project '{proj.name}' already exists") from e
            raise
        return info

    def _create_new_project(self, proj: ProjectCreate, connection: ConnectionInfo) -> ProjectInfo:
        project_dir = DATA_DIR / "projects" / proj.name
        project_dir.mkdir(parents=True, exist_ok=True)
        for d in _SCAFFOLD_DIRS:
            (project_dir / d).mkdir(parents=True, exist_ok=True)
        for d in ("models/staging", "models/marts"):
            (project_dir / d / ".gitkeep").touch()
        (project_dir / "dbt_project.yml").write_text(
            _DBT_PROJECT_YML_TEMPLATE.format(name=proj.name))
        profiles_path = project_dir / "profiles.yml"
        profiles_path.write_text(self._generate_profiles_yml(proj.name, connection))
        os.chmod(str(profiles_path), 0o600)
        os.chmod(str(project_dir), 0o700)
        (project_dir / "packages.yml").write_text(_PACKAGES_YML_TEMPLATE)
        return ProjectInfo(
            id=str(uuid.uuid4()), name=proj.name,
            connection_name=proj.connection_name, project_dir=str(project_dir),
            storage=ProjectStorage.managed, source=proj.source,
            db_type=connection.db_type, description=proj.description, tags=proj.tags,
        )

    def _create_local_project(self, proj: ProjectCreate, connection: ConnectionInfo) -> ProjectInfo:
        local = Path(proj.local_path or "")
        if not local.exists() or not (local / "dbt_project.yml").exists():
            raise ValueError(f"Path '{local}' does not exist or lacks dbt_project.yml")
        if proj.link_mode == "copy":
            project_dir = DATA_DIR / "projects" / proj.name
            shutil.copytree(str(local), str(project_dir), dirs_exist_ok=True)
            storage = ProjectStorage.managed
        else:
            project_dir = local
            storage = ProjectStorage.linked
        return ProjectInfo(
            id=str(uuid.uuid4()), name=proj.name,
            connection_name=proj.connection_name, project_dir=str(project_dir),
            storage=storage, source=proj.source,
            db_type=connection.db_type, description=proj.description, tags=proj.tags,
        )

    def _generate_profiles_yml(self, project_name: str, connection: ConnectionInfo) -> str:
        db = connection.db_type
        if db == "duckdb":
            return _PROFILES_DUCKDB.format(name=project_name, database=connection.database or ":memory:")
        if db == "postgres":
            return _PROFILES_POSTGRES.format(
                name=project_name, host=connection.host or "localhost",
                port=connection.port or 5432, username=connection.username or "",
                database=connection.database or "")
        if db == "snowflake":
            return _PROFILES_SNOWFLAKE.format(
                name=project_name, account=connection.account or "",
                username=connection.username or "", database=connection.database or "",
                warehouse=connection.warehouse or "", role=connection.role or "")
        if db == "bigquery":
            return _PROFILES_BIGQUERY.format(
                name=project_name, project=connection.project or "",
                dataset=connection.dataset or "", location=getattr(connection, "location", "US") or "US")
        return _PROFILES_PLACEHOLDER.format(name=project_name, db_type=db)

    async def update_project(self, name: str, update_data: ProjectUpdate) -> ProjectInfo | None:
        oid = self.org_id or "local"
        result = await self.session.execute(
            select(GatewayProject).where(
                GatewayProject.org_id == oid, GatewayProject.name == name
            )
        )
        row = result.scalar_one_or_none()
        if not row:
            return None
        for key, value in update_data.model_dump(exclude_none=True).items():
            if hasattr(row, key):
                setattr(row, key, value)
        await self.session.commit()
        await self.session.refresh(row)
        return ProjectInfo(**{c.key: getattr(row, c.key) for c in GatewayProject.__table__.columns})

    async def delete_project(self, name: str) -> bool:
        oid = self.org_id or "local"
        result = await self.session.execute(
            select(GatewayProject).where(
                GatewayProject.org_id == oid, GatewayProject.name == name
            )
        )
        row = result.scalar_one_or_none()
        if not row:
            return False
        if row.storage == "managed" and row.project_dir:
            project_dir = Path(row.project_dir)
            if project_dir.exists():
                shutil.rmtree(project_dir)
        await self.session.delete(row)
        await self.session.commit()
        return True

    # ─── Audit ───────────────────────────────────────────────────────────

    async def append_audit(self, entry: AuditEntry):
        oid = self.org_id or "local"
        self.session.add(GatewayAuditLog(
            id=entry.id or str(uuid.uuid4()),
            org_id=oid,
            user_id=self.user_id,
            timestamp=entry.timestamp,
            event_type=entry.event_type,
            connection_name=entry.connection_name,
            sandbox_id=entry.sandbox_id,
            sql_text=entry.sql,
            tables=entry.tables,
            rows_returned=entry.rows_returned,
            cost_usd=entry.cost_usd,
            blocked=entry.blocked or False,
            block_reason=entry.block_reason,
            duration_ms=entry.duration_ms,
            agent_id=entry.agent_id,
            parent_id=entry.parent_id,
            metadata_json=entry.metadata,
            client_ip=entry.client_ip,
            user_agent=entry.user_agent,
        ))
        await self.session.commit()

    async def read_audit(
        self,
        limit: int = 200,
        offset: int = 0,
        connection_name: str | None = None,
        event_type: str | None = None,
    ) -> list[AuditEntry]:
        oid = self.org_id or "local"
        q = select(GatewayAuditLog).where(GatewayAuditLog.org_id == oid)
        if connection_name:
            q = q.where(GatewayAuditLog.connection_name == connection_name)
        if event_type:
            q = q.where(GatewayAuditLog.event_type == event_type)
        q = q.order_by(GatewayAuditLog.timestamp.desc()).offset(offset).limit(limit)
        result = await self.session.execute(q)
        entries = []
        for row in result.scalars():
            entries.append(AuditEntry(
                id=row.id,
                timestamp=row.timestamp,
                event_type=row.event_type,
                connection_name=row.connection_name,
                sandbox_id=row.sandbox_id,
                sql=row.sql_text,
                tables=row.tables or [],
                rows_returned=row.rows_returned,
                cost_usd=row.cost_usd,
                blocked=row.blocked,
                block_reason=row.block_reason,
                duration_ms=row.duration_ms,
                agent_id=row.agent_id,
                parent_id=getattr(row, "parent_id", None),
                metadata=row.metadata_json or {},
                client_ip=getattr(row, "client_ip", None),
                user_agent=getattr(row, "user_agent", None),
            ))
        return entries

    # ─── Schema Endorsements ─────────────────────────────────────────────

    async def get_schema_endorsements(self, name: str) -> dict:
        conn = await self._get_conn_row(name)
        if not conn or not conn.endorsements:
            return {"endorsed": [], "hidden": [], "mode": "all"}
        return conn.endorsements

    async def set_schema_endorsements(self, name: str, endorsements: dict) -> dict:
        conn = await self._get_conn_row(name)
        if not conn:
            return {"endorsed": [], "hidden": [], "mode": "all"}
        conn.endorsements = {
            "endorsed": endorsements.get("endorsed", []),
            "hidden": endorsements.get("hidden", []),
            "mode": endorsements.get("mode", "all"),
        }
        await self.session.commit()
        return conn.endorsements

    # ─── PII Redaction Config ──────────────────────────────────────────────

    async def get_pii_config(self, name: str) -> dict:
        conn = await self._get_conn_row(name)
        if not conn:
            return {"enabled": False, "rules": {}}
        return {
            "enabled": conn.pii_enabled or False,
            "rules": conn.pii_rules or {},
        }

    async def set_pii_config(self, name: str, enabled: bool, rules: dict[str, str]) -> dict:
        conn = await self._get_conn_row(name)
        if not conn:
            raise ValueError(f"Connection '{name}' not found")
        conn.pii_enabled = enabled
        conn.pii_rules = rules
        await self.session.commit()
        return {"enabled": conn.pii_enabled, "rules": conn.pii_rules}

    async def delete_schema_endorsements(self, name: str):
        conn = await self._get_conn_row(name)
        if conn:
            conn.endorsements = None
            await self.session.commit()

    async def apply_endorsement_filter(self, name: str, schema: dict) -> dict:
        config = await self.get_schema_endorsements(name)
        mode = config.get("mode", "all")
        endorsed = set(config.get("endorsed", []))
        hidden = set(config.get("hidden", []))
        if mode == "endorsed_only" and endorsed:
            return {k: v for k, v in schema.items() if k in endorsed}
        elif hidden:
            return {k: v for k, v in schema.items() if k not in hidden}
        return schema

    async def _get_conn_row(self, name: str) -> GatewayConnection | None:
        oid = self.org_id or "local"
        result = await self.session.execute(
            select(GatewayConnection).where(
                GatewayConnection.org_id == oid, GatewayConnection.name == name
            )
        )
        return result.scalar_one_or_none()

    # ─── API Keys ────────────────────────────────────────────────────────

    async def list_api_keys(self) -> list[ApiKeyRecord]:
        if self._allow_unscoped:
            result = await self.session.execute(select(GatewayApiKey))
        else:
            oid = self.org_id or "local"
            result = await self.session.execute(
                select(GatewayApiKey).where(GatewayApiKey.org_id == oid)
            )
        return [ApiKeyRecord(
            id=r.id, name=r.name, prefix=r.prefix, key_hash=r.key_hash,
            scopes=r.scopes, created_at=r.created_at, last_used_at=r.last_used_at,
            expires_at=r.expires_at, user_id=r.user_id, org_id=r.org_id,
        ) for r in result.scalars()]

    async def create_api_key(
        self, name: str, scopes: list[str], expires_at: str | None = None
    ) -> tuple[ApiKeyRecord, str]:
        oid = self.org_id or "local"
        raw_key = "sp_" + secrets.token_hex(16)
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        key_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        db_key = GatewayApiKey(
            id=key_id, org_id=oid, user_id=self.user_id, name=name, prefix=raw_key[:7],
            key_hash=key_hash, scopes=scopes, created_at=now, expires_at=expires_at,
        )
        self.session.add(db_key)
        await self.session.commit()

        record = ApiKeyRecord(
            id=key_id, name=name, prefix=raw_key[:7], key_hash=key_hash,
            scopes=scopes, created_at=now, last_used_at=None,
            expires_at=expires_at, user_id=self.user_id, org_id=oid,
        )
        return record, raw_key

    async def delete_api_key(self, key_id: str) -> bool:
        oid = self.org_id or "local"
        result = await self.session.execute(
            select(GatewayApiKey).where(
                GatewayApiKey.org_id == oid, GatewayApiKey.id == key_id
            )
        )
        row = result.scalar_one_or_none()
        if not row:
            return False
        await self.session.delete(row)
        await self.session.commit()
        return True

    async def validate_stored_api_key(self, raw_key: str) -> ApiKeyRecord | None:
        import hmac as _hmac
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        # Search all keys (not org-scoped — validation doesn't know org yet)
        result = await self.session.execute(
            select(GatewayApiKey).where(GatewayApiKey.key_hash == key_hash)
        )
        row = result.scalar_one_or_none()
        if not row:
            return None
        if not _hmac.compare_digest(row.key_hash, key_hash):
            return None
        # Check expiry before allowing access
        if row.expires_at is not None:
            try:
                expiry = datetime.fromisoformat(row.expires_at)
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=timezone.utc)
                if expiry <= datetime.now(timezone.utc):
                    return None
            except (ValueError, TypeError):
                return None  # Corrupt expiry data → treat as expired (fail closed)
        row.last_used_at = datetime.now(timezone.utc).isoformat()
        await self.session.commit()
        return ApiKeyRecord(
            id=row.id, name=row.name, prefix=row.prefix, key_hash=row.key_hash,
            scopes=row.scopes, created_at=row.created_at, last_used_at=row.last_used_at,
            expires_at=row.expires_at, user_id=row.user_id, org_id=row.org_id,
        )

    # ─── Key Rotation ────────────────────────────────────────────────────

    async def get_credentials_needing_rotation(self) -> int:
        """Return count of credentials encrypted with a key version below CURRENT_KEY_VERSION.

        This is a global (non-user-scoped) query, intentionally, because it is
        called from the admin-only security_status endpoint which needs a system-wide count.
        """
        from sqlalchemy import func as sa_func
        result = await self.session.execute(
            select(sa_func.count()).select_from(GatewayCredential).where(
                GatewayCredential.key_version < CURRENT_KEY_VERSION
            )
        )
        return result.scalar_one()
