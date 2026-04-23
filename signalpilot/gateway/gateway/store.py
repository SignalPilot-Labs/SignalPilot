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
from typing import Any
from urllib.parse import quote as url_quote

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .db.models import (
    GatewayApiKey,
    GatewayAuditLog,
    GatewayConnection,
    GatewayCredential,
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


# ─── Encryption ──────────────────────────────────────────────────────────────

def _get_encryption_key() -> bytes:
    from cryptography.fernet import Fernet

    key_str = os.getenv("SP_ENCRYPTION_KEY")
    if key_str:
        try:
            Fernet(key_str.encode())
            return key_str.encode()
        except Exception:
            digest = hashlib.sha256(key_str.encode()).digest()
            return base64.urlsafe_b64encode(digest)
    else:
        key_file = DATA_DIR / ".encryption_key"
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if key_file.exists():
            return key_file.read_bytes().strip()
        key = Fernet.generate_key()
        key_file.write_bytes(key)
        return key


def _encrypt(data: str) -> bytes:
    from cryptography.fernet import Fernet
    f = Fernet(_get_encryption_key())
    return f.encrypt(data.encode())


def _decrypt(encrypted: bytes) -> str:
    from cryptography.fernet import Fernet
    f = Fernet(_get_encryption_key())
    return f.decrypt(encrypted).decode()


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

def get_local_api_key() -> str:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    key_file = DATA_DIR / "local_api_key"
    if key_file.exists():
        key = key_file.read_text().strip()
        if key:
            return key
    key = "sp_local_" + secrets.token_hex(16)
    key_file.write_text(key)
    logger.info("Generated local API key: %s...", key[:12])
    return key


# ═══════════════════════════════════════════════════════════════════════════════
# Store class — all DB-backed operations scoped by user_id
# ═══════════════════════════════════════════════════════════════════════════════

class Store:
    """Database-backed store scoped by user_id.

    If user_id is None, operations apply globally (for background tasks).
    """

    def __init__(self, session: AsyncSession, user_id: str | None = None):
        self.session = session
        self.user_id = user_id

    # ─── Settings ────────────────────────────────────────────────────────

    async def load_settings(self) -> GatewaySettings:
        uid = self.user_id or "local"
        result = await self.session.execute(
            select(GatewaySetting).where(GatewaySetting.user_id == uid)
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
        uid = self.user_id or "local"
        result = await self.session.execute(
            select(GatewaySetting).where(GatewaySetting.user_id == uid)
        )
        row = result.scalar_one_or_none()
        if row:
            row.settings_json = settings.model_dump()
        else:
            self.session.add(GatewaySetting(
                user_id=uid,
                settings_json=settings.model_dump(),
            ))
        await self.session.commit()

    # ─── Connections ─────────────────────────────────────────────────────

    def _conn_filter(self):
        if self.user_id is not None:
            return GatewayConnection.user_id == self.user_id
        return True

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
        uid = self.user_id or "local"
        # Check uniqueness
        existing = await self.get_connection(conn.name)
        if existing:
            raise ValueError(f"Connection '{conn.name}' already exists")

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
        )
        self.session.add(db_conn)

        # Store encrypted credentials
        raw_cred = conn.connection_string or _build_connection_string(conn)
        extras = _extract_credential_extras(conn)
        cred = GatewayCredential(
            user_id=uid,
            connection_name=conn.name,
            connection_string_enc=_encrypt(raw_cred),
            extras_enc=_encrypt(json.dumps(extras)),
        )
        self.session.add(cred)
        await self.session.commit()
        await self.session.refresh(db_conn)
        return ConnectionInfo(**db_conn.to_info_dict())

    async def delete_connection(self, name: str) -> bool:
        uid = self.user_id or "local"
        result = await self.session.execute(
            select(GatewayConnection).where(
                GatewayConnection.user_id == uid, GatewayConnection.name == name
            )
        )
        row = result.scalar_one_or_none()
        if not row:
            return False
        await self.session.delete(row)
        await self.session.execute(
            delete(GatewayCredential).where(
                GatewayCredential.user_id == uid,
                GatewayCredential.connection_name == name,
            )
        )
        await self.session.commit()
        return True

    async def update_connection(self, name: str, update_data: ConnectionUpdate) -> ConnectionInfo | None:
        uid = self.user_id or "local"
        result = await self.session.execute(
            select(GatewayConnection).where(
                GatewayConnection.user_id == uid, GatewayConnection.name == name
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
                extras = _extract_credential_extras(create_obj)
                # Update credential row
                cred_result = await self.session.execute(
                    select(GatewayCredential).where(
                        GatewayCredential.user_id == uid,
                        GatewayCredential.connection_name == name,
                    )
                )
                cred_row = cred_result.scalar_one_or_none()
                if cred_row:
                    cred_row.connection_string_enc = _encrypt(raw_cred)
                    cred_row.extras_enc = _encrypt(json.dumps(extras))
            except Exception:
                pass

        await self.session.commit()
        await self.session.refresh(row)
        return ConnectionInfo(**row.to_info_dict())

    async def get_connection_string(self, name: str) -> str | None:
        uid = self.user_id or "local"
        result = await self.session.execute(
            select(GatewayCredential).where(
                GatewayCredential.user_id == uid,
                GatewayCredential.connection_name == name,
            )
        )
        row = result.scalar_one_or_none()
        if not row:
            return None
        return _decrypt(row.connection_string_enc)

    async def get_credential_extras(self, name: str) -> dict:
        uid = self.user_id or "local"
        result = await self.session.execute(
            select(GatewayCredential).where(
                GatewayCredential.user_id == uid,
                GatewayCredential.connection_name == name,
            )
        )
        row = result.scalar_one_or_none()
        if not row or not row.extras_enc:
            return {}
        return json.loads(_decrypt(row.extras_enc))

    # ─── Projects ────────────────────────────────────────────────────────

    async def list_projects(self) -> list[ProjectInfo]:
        uid = self.user_id or "local"
        result = await self.session.execute(
            select(GatewayProject).where(GatewayProject.user_id == uid)
        )
        rows = result.scalars().all()
        return [ProjectInfo(**{c.key: getattr(r, c.key) for c in GatewayProject.__table__.columns}) for r in rows]

    async def get_project(self, name: str) -> ProjectInfo | None:
        uid = self.user_id or "local"
        result = await self.session.execute(
            select(GatewayProject).where(
                GatewayProject.user_id == uid, GatewayProject.name == name
            )
        )
        row = result.scalar_one_or_none()
        if not row:
            return None
        return ProjectInfo(**{c.key: getattr(row, c.key) for c in GatewayProject.__table__.columns})

    async def create_project(self, proj: ProjectCreate) -> ProjectInfo:
        uid = self.user_id or "local"
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
            user_id=uid,
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
        await self.session.commit()
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
        (project_dir / "profiles.yml").write_text(
            self._generate_profiles_yml(proj.name, connection))
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
        uid = self.user_id or "local"
        result = await self.session.execute(
            select(GatewayProject).where(
                GatewayProject.user_id == uid, GatewayProject.name == name
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
        uid = self.user_id or "local"
        result = await self.session.execute(
            select(GatewayProject).where(
                GatewayProject.user_id == uid, GatewayProject.name == name
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
        uid = self.user_id or "local"
        self.session.add(GatewayAuditLog(
            id=entry.id or str(uuid.uuid4()),
            user_id=uid,
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
            metadata_json=entry.metadata,
        ))
        await self.session.commit()

    async def read_audit(
        self,
        limit: int = 200,
        offset: int = 0,
        connection_name: str | None = None,
        event_type: str | None = None,
    ) -> list[AuditEntry]:
        uid = self.user_id or "local"
        q = select(GatewayAuditLog).where(GatewayAuditLog.user_id == uid)
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
                tables=row.tables,
                rows_returned=row.rows_returned,
                cost_usd=row.cost_usd,
                blocked=row.blocked,
                block_reason=row.block_reason,
                duration_ms=row.duration_ms,
                agent_id=row.agent_id,
                metadata=row.metadata_json,
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
        uid = self.user_id or "local"
        result = await self.session.execute(
            select(GatewayConnection).where(
                GatewayConnection.user_id == uid, GatewayConnection.name == name
            )
        )
        return result.scalar_one_or_none()

    # ─── API Keys ────────────────────────────────────────────────────────

    async def list_api_keys(self) -> list[ApiKeyRecord]:
        uid = self.user_id or "local"
        result = await self.session.execute(
            select(GatewayApiKey).where(GatewayApiKey.user_id == uid)
        )
        return [ApiKeyRecord(
            id=r.id, name=r.name, prefix=r.prefix, key_hash=r.key_hash,
            scopes=r.scopes, created_at=r.created_at, last_used_at=r.last_used_at,
        ) for r in result.scalars()]

    async def create_api_key(self, name: str, scopes: list[str]) -> tuple[ApiKeyRecord, str]:
        uid = self.user_id or "local"
        raw_key = "sp_" + secrets.token_hex(16)
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        key_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        db_key = GatewayApiKey(
            id=key_id, user_id=uid, name=name, prefix=raw_key[:7],
            key_hash=key_hash, scopes=scopes, created_at=now,
        )
        self.session.add(db_key)
        await self.session.commit()

        record = ApiKeyRecord(
            id=key_id, name=name, prefix=raw_key[:7], key_hash=key_hash,
            scopes=scopes, created_at=now, last_used_at=None,
        )
        return record, raw_key

    async def delete_api_key(self, key_id: str) -> bool:
        uid = self.user_id or "local"
        result = await self.session.execute(
            select(GatewayApiKey).where(
                GatewayApiKey.user_id == uid, GatewayApiKey.id == key_id
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
        # Search all keys (not user-scoped — validation doesn't know user yet)
        result = await self.session.execute(
            select(GatewayApiKey).where(GatewayApiKey.key_hash == key_hash)
        )
        row = result.scalar_one_or_none()
        if not row:
            return None
        if not _hmac.compare_digest(row.key_hash, key_hash):
            return None
        row.last_used_at = datetime.now(timezone.utc).isoformat()
        await self.session.commit()
        return ApiKeyRecord(
            id=row.id, name=row.name, prefix=row.prefix, key_hash=row.key_hash,
            scopes=row.scopes, created_at=row.created_at, last_used_at=row.last_used_at,
        )
