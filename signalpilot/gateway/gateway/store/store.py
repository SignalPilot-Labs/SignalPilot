"""Store class — all DB-backed operations scoped by org_id."""

from __future__ import annotations

import json
import logging
import time
import uuid

from sqlalchemy import delete, literal, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import gateway.store.api_keys as api_keys
import gateway.store.audit_log as audit_log
import gateway.store.byok_state as byok_state
import gateway.store.endorsements as endorsements_mod
import gateway.store.knowledge as knowledge_mod
import gateway.store.notion as notion_mod
import gateway.store.paths as paths
import gateway.store.projects as projects
import gateway.store.settings as settings_mod
from gateway.byok import decrypt_envelope, encrypt_fields_envelope
from gateway.db.models import (
    GatewayConnection,
    GatewayCredential,
)
from gateway.governance.context import current_org_id_var
from gateway.models import (
    ApiKeyRecord,
    AuditEntry,
    ConnectionCreate,
    ConnectionInfo,
    ConnectionUpdate,
    DBType,
    GatewaySettings,
    SSHTunnelConfig,
    SSLConfig,
)
from gateway.models.knowledge import KnowledgeDoc, KnowledgeDocCreate, KnowledgeEdit, KnowledgeUsage
from gateway.runtime.mode import is_cloud_mode
from gateway.store._constants import CURRENT_KEY_VERSION
from gateway.store.connection_strings import _build_connection_string, _extract_credential_extras
from gateway.store.crypto import (
    CredentialEncryptionError,
    _decrypt_with_migration,
    _encrypt,
)

logger = logging.getLogger(__name__)


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

    def _require_org_id(self) -> str:
        """Return org_id, raising ValueError in cloud mode if unset."""
        if self.org_id:
            return self.org_id
        if is_cloud_mode() and not self._allow_unscoped:
            raise ValueError(
                "org_id is required in cloud mode but was not set. Ensure resolve_org_id ran before constructing Store."
            )
        return "local"

    # ─── Settings ────────────────────────────────────────────────────────

    async def load_settings(self) -> GatewaySettings:
        oid = self._require_org_id()
        return await settings_mod.load_settings(self.session, org_id=oid)

    async def save_settings(self, settings: GatewaySettings):
        oid = self._require_org_id()
        await settings_mod.save_settings(self.session, org_id=oid, user_id=self.user_id, settings=settings)

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
        result = await self.session.execute(select(GatewayConnection).where(self._conn_filter()))
        return [ConnectionInfo(**row.to_info_dict()) for row in result.scalars()]

    async def get_connection(self, name: str) -> ConnectionInfo | None:
        result = await self.session.execute(
            select(GatewayConnection).where(self._conn_filter(), GatewayConnection.name == name)
        )
        row = result.scalar_one_or_none()
        return ConnectionInfo(**row.to_info_dict()) if row else None

    async def create_connection(self, conn: ConnectionCreate) -> ConnectionInfo:
        oid = self._require_org_id()
        uid = self.user_id
        # Check uniqueness
        existing = await self.get_connection(conn.name)
        if existing:
            raise ValueError(f"Connection '{conn.name}' already exists")

        # When connection_string is provided without individual fields, parse
        # host/port/database/username from the URL so they're stored as metadata
        # for display and editing.
        if conn.connection_string and not conn.host:
            from gateway.network import parse_connection_url

            try:
                db_type_str = conn.db_type.value if hasattr(conn.db_type, "value") else conn.db_type
                parsed = parse_connection_url(conn.connection_string, db_type=db_type_str)
                conn = conn.model_copy(
                    update={
                        k: v
                        for k, v in parsed.items()
                        if k
                        in (
                            "host",
                            "port",
                            "database",
                            "username",
                            "ssl",
                            "account",
                            "warehouse",
                            "schema_name",
                            "role",
                            "catalog",
                            "http_path",
                        )
                        and v  # only backfill non-empty values
                    }
                )
            except Exception:
                pass  # URL parsing failed — keep original fields

        # Strip sensitive fields from SSH/SSL for metadata storage
        ssh_tunnel_safe = None
        if conn.ssh_tunnel and conn.ssh_tunnel.enabled:
            ssh_tunnel_safe = conn.ssh_tunnel.model_copy(
                update={
                    "password": None,
                    "private_key": None,
                    "private_key_passphrase": None,
                }
            ).model_dump()

        ssl_config_safe = None
        if conn.ssl_config and conn.ssl_config.enabled:
            ssl_config_safe = conn.ssl_config.model_dump()

        conn_id = str(uuid.uuid4())
        db_conn = GatewayConnection(
            id=conn_id,
            org_id=oid,
            user_id=uid,
            name=conn.name,
            db_type=conn.db_type.value if hasattr(conn.db_type, "value") else conn.db_type,
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
                paths._validate_local_db_path(raw_cred)
        extras = _extract_credential_extras(conn)

        # BYOK encrypt path: use envelope encryption when org has BYOK configured
        byok_key = None
        if oid and byok_state._byok_provider is not None:
            byok_key = await byok_state._resolve_byok_key(self.session, oid, conn.byok_key_alias)

        if byok_key is not None and byok_state._byok_provider is not None:
            ciphertexts, wrapped_dek = await encrypt_fields_envelope(
                byok_state._byok_provider,
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
        oid = self._require_org_id()
        result = await self.session.execute(
            select(GatewayConnection).where(GatewayConnection.org_id == oid, GatewayConnection.name == name)
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
        oid = self._require_org_id()
        result = await self.session.execute(
            select(GatewayConnection).where(GatewayConnection.org_id == oid, GatewayConnection.name == name)
        )
        row = result.scalar_one_or_none()
        if not row:
            return None

        update_fields = update_data.model_dump(exclude_none=True)
        credential_fields = {
            "password",
            "connection_string",
            "credentials_json",
            "access_token",
            "private_key",
            "private_key_passphrase",
            "motherduck_token",
        }

        # Update metadata fields
        for key, value in update_fields.items():
            if key in credential_fields:
                continue
            if key == "ssh_tunnel" and value:
                ssh_config = SSHTunnelConfig(**value) if isinstance(value, dict) else value
                value = ssh_config.model_copy(
                    update={
                        "password": None,
                        "private_key": None,
                        "private_key_passphrase": None,
                    }
                ).model_dump()
            if key == "ssl_config" and value:
                if isinstance(value, dict):
                    value = SSLConfig(**value).model_dump()
            if hasattr(row, key):
                setattr(row, key, value)

        # Rebuild credentials if needed
        needs_cred_rebuild = any(
            k in update_fields
            for k in (
                "host",
                "port",
                "database",
                "username",
                "password",
                "connection_string",
                "account",
                "warehouse",
                "schema_name",
                "role",
                "project",
                "credentials_json",
                "http_path",
                "access_token",
                "catalog",
                "ssl",
                "ssl_config",
                # Xata-specific fields stored only in encrypted extras
                "workspace",
                "region",
                "branch",
                "xata_api_url",
                "xata_org",
                "xata_token_url",
                "xata_client_id",
                "xata_client_secret",
                "xata_username",
                "xata_password",
            )
        )
        if needs_cred_rebuild:
            existing_extras = await self.get_credential_extras(name)
            # Back-translate stored extras keys into ConnectionCreate kwarg names.
            # Four Xata fields are stored prefixed; the rest are stored identically.
            _extras_key_map = {
                "xata_workspace": "workspace",
                "xata_region": "region",
                "xata_database": "database",
                "xata_branch": "branch",
            }
            from_extras: dict = {}
            for stored_key, val in existing_extras.items():
                kwarg_name = _extras_key_map.get(stored_key, stored_key)
                from_extras[kwarg_name] = val
            # Precedence: existing extras (lowest) < column snapshot < user patch (highest)
            merged = {**from_extras, **row.to_info_dict(), **update_fields, "name": name}
            for rm_key in (
                "id",
                "created_at",
                "last_used",
                "status",
                "last_schema_refresh",
                "endorsements",
                "location",
            ):
                merged.pop(rm_key, None)
            try:
                create_obj = ConnectionCreate(**merged)
                raw_cred = create_obj.connection_string or _build_connection_string(create_obj)
                if create_obj.db_type in ("duckdb", "sqlite"):
                    is_sandboxed = raw_cred not in (":memory:",) and not raw_cred.startswith("md:")
                    if not is_sandboxed:
                        paths._validate_local_db_path(raw_cred)
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
                    if org_id and byok_state._byok_provider is not None:
                        byok_key = await byok_state._resolve_byok_key(self.session, org_id, key_alias)

                    if byok_key is not None and byok_state._byok_provider is not None:
                        ciphertexts, wrapped_dek = await encrypt_fields_envelope(
                            byok_state._byok_provider,
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
                logger.error("Credential encryption failed for connection %s: %s", name, e)
                raise CredentialEncryptionError(f"Failed to encrypt credentials for connection '{name}'") from e

        await self.session.commit()
        await self.session.refresh(row)
        return ConnectionInfo(**row.to_info_dict())

    async def get_connection_string(self, name: str) -> str | None:
        oid = self._require_org_id()
        result = await self.session.execute(
            select(GatewayCredential, GatewayConnection)
            .join(
                GatewayConnection,
                (GatewayConnection.org_id == GatewayCredential.org_id)
                & (GatewayConnection.name == GatewayCredential.connection_name),
                isouter=True,
            )
            .where(
                GatewayCredential.org_id == oid,
                GatewayCredential.connection_name == name,
            )
        )
        row_pair = result.first()
        if not row_pair:
            return None
        cred_row, conn_row = row_pair

        if cred_row.encryption_mode == "byok":
            if byok_state._byok_provider is None:
                raise CredentialEncryptionError("BYOK provider not configured")
            if cred_row.wrapped_dek is None:
                raise CredentialEncryptionError("Credential is in BYOK mode but has no wrapped DEK")
            org_id = conn_row.org_id if conn_row else None
            key_alias = conn_row.byok_key_alias if conn_row else None
            if not org_id or not key_alias:
                raise CredentialEncryptionError("Connection is missing BYOK configuration for decryption")
            return await decrypt_envelope(
                provider=byok_state._byok_provider,
                org_id=org_id,
                key_alias=key_alias,
                wrapped_dek=cred_row.wrapped_dek,
                ciphertext=cred_row.connection_string_enc,
                cache=byok_state._dek_cache,
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
        oid = self._require_org_id()
        result = await self.session.execute(
            select(GatewayCredential, GatewayConnection)
            .join(
                GatewayConnection,
                (GatewayConnection.org_id == GatewayCredential.org_id)
                & (GatewayConnection.name == GatewayCredential.connection_name),
                isouter=True,
            )
            .where(
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
            if byok_state._byok_provider is None:
                raise CredentialEncryptionError("BYOK provider not configured")
            if cred_row.wrapped_dek is None:
                raise CredentialEncryptionError("Credential is in BYOK mode but has no wrapped DEK")
            org_id = conn_row.org_id if conn_row else None
            key_alias = conn_row.byok_key_alias if conn_row else None
            if not org_id or not key_alias:
                raise CredentialEncryptionError("Connection is missing BYOK configuration for decryption")
            extras_json = await decrypt_envelope(
                provider=byok_state._byok_provider,
                org_id=org_id,
                key_alias=key_alias,
                wrapped_dek=cred_row.wrapped_dek,
                ciphertext=cred_row.extras_enc,
                cache=byok_state._dek_cache,
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

    async def list_projects(self) -> list[projects.ProjectInfo]:
        oid = self._require_org_id()
        return await projects.list_projects(self.session, org_id=oid)

    async def get_project(self, name: str) -> projects.ProjectInfo | None:
        oid = self._require_org_id()
        return await projects.get_project(self.session, org_id=oid, name=name)

    async def create_project(self, proj: projects.ProjectCreate) -> projects.ProjectInfo:
        oid = self._require_org_id()
        return await projects.create_project(
            self.session,
            org_id=oid,
            user_id=self.user_id,
            proj=proj,
            get_connection=self.get_connection,
            get_existing_project=self.get_project,
        )

    def _create_new_project(self, proj: projects.ProjectCreate, connection: ConnectionInfo) -> projects.ProjectInfo:
        return projects.create_new_project(proj, connection, org_id=self._require_org_id())

    def _create_local_project(self, proj: projects.ProjectCreate, connection: ConnectionInfo) -> projects.ProjectInfo:
        return projects.create_local_project(proj, connection, org_id=self._require_org_id())

    def _generate_profiles_yml(self, project_name: str, connection: ConnectionInfo) -> str:
        return projects.generate_profiles_yml(project_name, connection)

    async def update_project(self, name: str, update_data: projects.ProjectUpdate) -> projects.ProjectInfo | None:
        oid = self._require_org_id()
        return await projects.update_project(self.session, org_id=oid, name=name, update_data=update_data)

    async def delete_project(self, name: str) -> bool:
        oid = self._require_org_id()
        return await projects.delete_project(self.session, org_id=oid, name=name)

    # ─── Audit ───────────────────────────────────────────────────────────

    async def append_audit(self, entry: AuditEntry) -> None:
        oid = self._require_org_id()
        await audit_log.append_audit(self.session, org_id=oid, user_id=self.user_id, entry=entry)

    async def read_audit(
        self,
        limit: int = 200,
        offset: int = 0,
        connection_name: str | None = None,
        event_type: str | None = None,
        return_total: bool = False,
    ) -> list[AuditEntry] | tuple[list[AuditEntry], int]:
        oid = self._require_org_id()
        return await audit_log.read_audit(
            self.session,
            org_id=oid,
            limit=limit,
            offset=offset,
            connection_name=connection_name,
            event_type=event_type,
            return_total=return_total,
        )

    # ─── Schema Endorsements ─────────────────────────────────────────────

    async def get_schema_endorsements(self, name: str) -> dict:
        oid = self._require_org_id()
        return await endorsements_mod.get_schema_endorsements(self.session, org_id=oid, name=name)

    async def set_schema_endorsements(self, name: str, endorsements: dict) -> dict:
        oid = self._require_org_id()
        return await endorsements_mod.set_schema_endorsements(
            self.session, org_id=oid, name=name, endorsements=endorsements
        )

    # ─── PII Redaction Config ──────────────────────────────────────────────

    async def get_pii_config(self, name: str) -> dict:
        oid = self._require_org_id()
        return await endorsements_mod.get_pii_config(self.session, org_id=oid, name=name)

    async def set_pii_config(self, name: str, enabled: bool, rules: dict[str, str]) -> dict:
        oid = self._require_org_id()
        return await endorsements_mod.set_pii_config(self.session, org_id=oid, name=name, enabled=enabled, rules=rules)

    async def delete_schema_endorsements(self, name: str):
        oid = self._require_org_id()
        return await endorsements_mod.delete_schema_endorsements(self.session, org_id=oid, name=name)

    async def apply_endorsement_filter(self, name: str, schema: dict) -> dict:
        oid = self._require_org_id()
        return await endorsements_mod.apply_endorsement_filter(self.session, org_id=oid, name=name, schema=schema)

    # ─── Notion Integrations ─────────────────────────────────────────────

    async def list_notion_integrations(self) -> list[notion_mod.NotionIntegrationInfo]:
        """List all Notion integrations for this org."""
        oid = self._require_org_id()
        return await notion_mod.list_integrations(self.session, org_id=oid)

    async def get_notion_integration(self, name: str) -> notion_mod.NotionIntegrationInfo | None:
        """Get a Notion integration by name."""
        oid = self._require_org_id()
        return await notion_mod.get_integration(self.session, org_id=oid, name=name)

    async def create_notion_integration(
        self, integration: notion_mod.NotionIntegrationCreate,
    ) -> notion_mod.NotionIntegrationInfo:
        """Create a Notion integration with encrypted API key."""
        oid = self._require_org_id()
        return await notion_mod.create_integration(self.session, org_id=oid, integration=integration)

    async def update_notion_integration(
        self, name: str, update: notion_mod.NotionIntegrationUpdate,
    ) -> notion_mod.NotionIntegrationInfo | None:
        """Update a Notion integration."""
        oid = self._require_org_id()
        return await notion_mod.update_integration(self.session, org_id=oid, name=name, update=update)

    async def delete_notion_integration(self, name: str) -> bool:
        """Delete a Notion integration."""
        oid = self._require_org_id()
        return await notion_mod.delete_integration(self.session, org_id=oid, name=name)

    async def get_notion_api_key(self, name: str) -> str | None:
        """Get the decrypted API key for a Notion integration."""
        oid = self._require_org_id()
        return await notion_mod.get_api_key(self.session, org_id=oid, name=name)

    async def create_notion_oauth_state(self, redirect_after: str | None, ttl_seconds: int = 600) -> str:
        """Create a short-lived Notion OAuth state value."""
        oid = self._require_org_id()
        return await notion_mod.create_oauth_state(
            self.session,
            org_id=oid,
            user_id=self.user_id,
            redirect_after=redirect_after,
            ttl_seconds=ttl_seconds,
        )

    async def list_notion_oauth_installations(self) -> list[notion_mod.NotionOAuthInstallationInfo]:
        """List Notion OAuth installations for this org."""
        oid = self._require_org_id()
        return await notion_mod.list_oauth_installations(self.session, org_id=oid)

    async def get_notion_oauth_installation(
        self, installation_id: str,
    ) -> notion_mod.NotionOAuthInstallationInfo | None:
        """Get a Notion OAuth installation for this org."""
        oid = self._require_org_id()
        return await notion_mod.get_oauth_installation(self.session, org_id=oid, installation_id=installation_id)

    async def get_notion_oauth_installation_token(self, installation_id: str) -> str | None:
        """Get the decrypted Notion OAuth access token for this org."""
        oid = self._require_org_id()
        return await notion_mod.get_oauth_installation_token(
            self.session,
            org_id=oid,
            installation_id=installation_id,
        )

    async def get_notion_oauth_installation_tokens(self, installation_id: str) -> tuple[str, str | None] | None:
        """Get the decrypted Notion OAuth access and refresh tokens for this org."""
        oid = self._require_org_id()
        return await notion_mod.get_oauth_installation_tokens(
            self.session,
            org_id=oid,
            installation_id=installation_id,
        )

    async def update_notion_oauth_installation_tokens(
        self,
        installation_id: str,
        access_token: str,
        refresh_token: str | None,
    ) -> None:
        """Update encrypted Notion OAuth tokens after refresh."""
        oid = self._require_org_id()
        await notion_mod.update_oauth_installation_tokens(
            self.session,
            org_id=oid,
            installation_id=installation_id,
            access_token=access_token,
            refresh_token=refresh_token,
        )

    async def save_notion_oauth_installation_config(
        self,
        installation_id: str,
        parent_page_id: str | None,
        trigger_page_id: str,
        requests_data_source_id: str,
        requests_database_page_id: str,
        enabled: bool = True,
    ) -> notion_mod.NotionOAuthInstallationInfo | None:
        """Save provisioned Notion resources for an OAuth installation."""
        oid = self._require_org_id()
        return await notion_mod.save_oauth_installation_config(
            self.session,
            org_id=oid,
            installation_id=installation_id,
            parent_page_id=parent_page_id,
            trigger_page_id=trigger_page_id,
            requests_data_source_id=requests_data_source_id,
            requests_database_page_id=requests_database_page_id,
            enabled=enabled,
        )

    async def disable_notion_oauth_installation(self, installation_id: str) -> bool:
        """Disable a Notion OAuth installation for this org."""
        oid = self._require_org_id()
        return await notion_mod.disable_oauth_installation(
            self.session,
            org_id=oid,
            installation_id=installation_id,
        )

    # ─── API Keys ───────────────────────────────────────────────────────
    async def list_api_keys(self) -> list[ApiKeyRecord]:
        return await api_keys.list_api_keys(self.session, org_id=self.org_id, allow_unscoped=self._allow_unscoped)

    async def create_api_key(
        self, name: str, scopes: list[str], expires_at: str | None = None
    ) -> tuple[ApiKeyRecord, str]:
        oid = self._require_org_id()
        return await api_keys.create_api_key(
            self.session,
            org_id=oid,
            user_id=self.user_id,
            name=name,
            scopes=scopes,
            expires_at=expires_at,
        )

    async def delete_api_key(self, key_id: str) -> bool:
        oid = self._require_org_id()
        return await api_keys.delete_api_key(self.session, org_id=oid, key_id=key_id)

    async def validate_stored_api_key(self, raw_key: str) -> ApiKeyRecord | None:
        return await api_keys.validate_stored_api_key(self.session, raw_key)

    # ─── Key Rotation ────────────────────────────────────────────────────

    async def get_credentials_needing_rotation(self, org_scoped: bool = True) -> int:
        """Return count of credentials encrypted with a key version below CURRENT_KEY_VERSION.

        ORG-SCOPED by default (org_scoped=True): filters to the current org via
        _require_org_id(). Cross-org count is opt-in (org_scoped=False) and
        intended only for future operator-only callers — no production caller
        currently passes org_scoped=False.
        """
        org_id = self._require_org_id() if org_scoped else None
        return await settings_mod.get_credentials_needing_rotation(self.session, org_id=org_id)

    # ─── Knowledge Base ──────────────────────────────────────────────────

    async def _knowledge_limits(self):
        """Resolve the org's plan limits for knowledge enforcement."""
        from gateway.governance.plan_limits import get_org_limits

        return await get_org_limits(self._require_org_id())

    async def list_knowledge_docs(
        self,
        *,
        scope: str | None = None,
        scope_ref: str | None = None,
        category: str | None = None,
        status: str = "active",
        include_body: bool = False,
        limit: int = 200,
        offset: int = 0,
    ) -> list[KnowledgeDoc]:
        oid = self._require_org_id()
        return await knowledge_mod.list_knowledge_docs(
            self.session,
            org_id=oid,
            scope=scope,
            scope_ref=scope_ref,
            category=category,
            status=status,
            include_body=include_body,
            limit=limit,
            offset=offset,
        )

    async def get_knowledge_doc(
        self, doc_id: str, *, include_body: bool = True, bump_view: bool = False
    ) -> KnowledgeDoc | None:
        import asyncio

        oid = self._require_org_id()
        row = await knowledge_mod.get_knowledge_doc(
            self.session, org_id=oid, doc_id=doc_id, include_body=include_body
        )
        if row is None:
            return None
        doc = knowledge_mod._row_to_doc(row, include_body=include_body)
        if bump_view:
            asyncio.create_task(self.increment_knowledge_view(doc_id))
        return doc

    async def get_knowledge_doc_by_key(
        self,
        *,
        scope: str,
        scope_ref: str | None,
        category: str,
        title: str,
        bump_view: bool = False,
    ) -> KnowledgeDoc | None:
        import asyncio

        oid = self._require_org_id()
        row = await knowledge_mod.get_knowledge_doc_by_key(
            self.session,
            org_id=oid,
            scope=scope,
            scope_ref=scope_ref,
            category=category,
            title=title,
        )
        if row is None:
            return None
        doc = knowledge_mod._row_to_doc(row, include_body=True)
        if bump_view:
            asyncio.create_task(self.increment_knowledge_view(doc.id))
        return doc

    async def insert_knowledge_doc(
        self, payload: KnowledgeDocCreate, *, user_id: str | None, agent: str | None = None
    ) -> KnowledgeDoc:
        oid = self._require_org_id()
        limits = await self._knowledge_limits()
        settings = await self.load_settings()
        return await knowledge_mod.insert_knowledge_doc(
            self.session,
            org_id=oid,
            payload=payload,
            user_id=user_id,
            agent=agent,
            limits=limits,
            settings=settings,
        )

    async def upsert_knowledge_doc(
        self, payload: KnowledgeDocCreate, *, user_id: str | None, agent: str | None = None
    ) -> KnowledgeDoc:
        oid = self._require_org_id()
        limits = await self._knowledge_limits()
        settings = await self.load_settings()
        return await knowledge_mod.upsert_knowledge_doc(
            self.session,
            org_id=oid,
            payload=payload,
            user_id=user_id,
            agent=agent,
            limits=limits,
            settings=settings,
        )

    async def update_knowledge_body(
        self,
        doc_id: str,
        *,
        body: str,
        user_id: str | None,
        agent: str | None = None,
    ) -> KnowledgeDoc:
        oid = self._require_org_id()
        limits = await self._knowledge_limits()
        settings = await self.load_settings()
        return await knowledge_mod.update_knowledge_body(
            self.session,
            org_id=oid,
            doc_id=doc_id,
            body=body,
            user_id=user_id,
            agent=agent,
            limits=limits,
            settings=settings,
        )

    async def archive_knowledge_doc(self, doc_id: str) -> bool:
        oid = self._require_org_id()
        return await knowledge_mod.archive_knowledge_doc(self.session, org_id=oid, doc_id=doc_id)

    async def approve_knowledge_doc(self, doc_id: str, *, user_id: str | None) -> KnowledgeDoc:
        oid = self._require_org_id()
        return await knowledge_mod.approve_knowledge_doc(
            self.session, org_id=oid, doc_id=doc_id, user_id=user_id
        )

    async def list_knowledge_edits(self, doc_id: str, *, limit: int = 20) -> list[KnowledgeEdit]:
        oid = self._require_org_id()
        return await knowledge_mod.list_knowledge_edits(
            self.session, org_id=oid, doc_id=doc_id, limit=limit
        )

    async def search_knowledge(
        self,
        *,
        query: str,
        scope: str | None = None,
        scope_ref: str | None = None,
        category: str | None = None,
        limit: int = 20,
        bump_view: bool = True,
    ) -> list[KnowledgeDoc]:
        import asyncio

        oid = self._require_org_id()
        docs = await knowledge_mod.search_knowledge(
            self.session,
            org_id=oid,
            query=query,
            scope=scope,
            scope_ref=scope_ref,
            category=category,
            limit=limit,
        )
        if bump_view:
            for doc in docs:
                asyncio.create_task(self.increment_knowledge_view(doc.id))
        return docs

    async def get_knowledge_usage(self) -> KnowledgeUsage:
        oid = self._require_org_id()
        limits = await self._knowledge_limits()
        return await knowledge_mod.get_knowledge_usage(self.session, org_id=oid, limits=limits)

    async def increment_knowledge_view(self, doc_id: str) -> None:
        """Best-effort fire-and-forget view counter increment."""
        oid = self._require_org_id()
        from gateway.db.engine import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            await knowledge_mod.increment_knowledge_view(session, org_id=oid, doc_id=doc_id)

    # ─── Workspace Projects ─────────────────────────────────────────────────

    async def create_workspace_project(self, **kwargs):
        from . import workspace_projects as wp

        oid = self._require_org_id()
        return await wp.create_project(self.session, org_id=oid, user_id=self.user_id, **kwargs)

    async def list_workspace_projects(self, **kwargs):
        from . import workspace_projects as wp

        oid = self._require_org_id()
        return await wp.list_projects(self.session, org_id=oid, **kwargs)

    async def get_workspace_project(self, project_id: str):
        from . import workspace_projects as wp

        oid = self._require_org_id()
        return await wp.get_project(self.session, org_id=oid, project_id=project_id)

    async def update_workspace_project(self, project_id: str, updates: dict):
        from . import workspace_projects as wp

        oid = self._require_org_id()
        return await wp.update_project(self.session, org_id=oid, project_id=project_id, updates=updates)

    async def delete_workspace_project(self, project_id: str):
        from . import workspace_projects as wp

        oid = self._require_org_id()
        return await wp.delete_project(self.session, org_id=oid, project_id=project_id)

    # ─── Chat ────────────────────────────────────────────────────────────────

    async def create_conversation(self, **kwargs):
        from . import chat

        oid = self._require_org_id()
        return await chat.create_conversation(self.session, org_id=oid, user_id=self.user_id or "local", **kwargs)

    async def list_conversations(self, **kwargs):
        from . import chat

        oid = self._require_org_id()
        return await chat.list_conversations(self.session, org_id=oid, user_id=self.user_id or "local", **kwargs)

    async def get_conversation(self, conversation_id: str):
        from . import chat

        oid = self._require_org_id()
        return await chat.get_conversation(
            self.session, org_id=oid, user_id=self.user_id or "local", conversation_id=conversation_id
        )

    async def delete_conversation(self, conversation_id: str):
        from . import chat

        oid = self._require_org_id()
        return await chat.delete_conversation(
            self.session, org_id=oid, user_id=self.user_id or "local", conversation_id=conversation_id
        )

    async def append_message(self, conversation_id: str, **kwargs):
        from . import chat

        oid = self._require_org_id()
        return await chat.append_message(
            self.session, org_id=oid, user_id=self.user_id or "local", conversation_id=conversation_id, **kwargs
        )

    async def list_messages(self, conversation_id: str, **kwargs):
        from . import chat

        oid = self._require_org_id()
        return await chat.list_messages(
            self.session, org_id=oid, user_id=self.user_id or "local", conversation_id=conversation_id, **kwargs
        )

    # ─── Chat Traces ─────────────────────────────────────────────────────────

    async def upsert_chat_trace_thread(self, thread):
        from . import chat_traces

        oid = self._require_org_id()
        return await chat_traces.upsert_thread(
            self.session, org_id=oid, user_id=self.user_id or "local", thread=thread
        )

    async def clear_chat_trace_events(self, thread_id: str):
        from . import chat_traces

        oid = self._require_org_id()
        return await chat_traces.clear_events(
            self.session, org_id=oid, user_id=self.user_id or "local", thread_id=thread_id
        )

    async def append_chat_trace_event(self, thread_id: str, event):
        from . import chat_traces

        oid = self._require_org_id()
        return await chat_traces.append_event(
            self.session, org_id=oid, user_id=self.user_id or "local", thread_id=thread_id, event=event
        )

    async def list_chat_trace_threads(self, **kwargs):
        from . import chat_traces

        oid = self._require_org_id()
        return await chat_traces.list_threads(
            self.session, org_id=oid, user_id=self.user_id or "local", **kwargs
        )

    async def get_chat_trace_thread(self, thread_id: str):
        from . import chat_traces

        oid = self._require_org_id()
        return await chat_traces.get_thread(
            self.session, org_id=oid, user_id=self.user_id or "local", thread_id=thread_id
        )

    async def get_chat_trace_events(self, thread_id: str, **kwargs):
        from . import chat_traces

        oid = self._require_org_id()
        return await chat_traces.get_events(
            self.session, org_id=oid, user_id=self.user_id or "local", thread_id=thread_id, **kwargs
        )

    # ─── Agent Runs ──────────────────────────────────────────────────────────

    async def create_agent_run(self, **kwargs):
        from . import agent_runs

        oid = self._require_org_id()
        return await agent_runs.create_run(self.session, org_id=oid, user_id=self.user_id, **kwargs)

    async def list_agent_runs(self, **kwargs):
        from . import agent_runs

        oid = self._require_org_id()
        return await agent_runs.list_runs(self.session, org_id=oid, **kwargs)

    async def get_agent_run(self, run_id: str):
        from . import agent_runs

        oid = self._require_org_id()
        return await agent_runs.get_run(self.session, org_id=oid, run_id=run_id)

    async def update_agent_run(self, run_id: str, updates: dict):
        from . import agent_runs

        oid = self._require_org_id()
        return await agent_runs.update_run(self.session, org_id=oid, run_id=run_id, updates=updates)

    # ─── Branches ────────────────────────────────────────────────────────────

    # Branch methods removed — branches are git refs now. Use git CLI directly.
